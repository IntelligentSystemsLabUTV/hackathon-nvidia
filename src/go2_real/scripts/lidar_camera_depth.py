#!/usr/bin/env python3
"""Depth image for AgenticROS from the Livox Mid-360, aligned with the Go2 front camera.

The real DottorCane has no depth camera: the agent's ros2_depth_distance (distance
inside the target box) and ros2_depth_corridor (nearest obstacle in front of the
body) read a 32FC1 image instead. This node projects the last `window` seconds of
lidar points into the rectified front camera and publishes, per pixel, the nearest
z-depth (metres, NaN where no point fell).

The output is aligned with the camera image by image fractions, which is how the
agent maps a bounding box onto the depth image: pixel (u, v) of the camera lands on
(u / W_cam * width, v / H_cam * height). The height is chosen so that the depth
image has square pixels (fx = fy), as ros2_depth_corridor assumes: the rectified
Go2 camera has fx != fy, so the image is not 16:9.

The floor is removed before the projection: a point less than floor_height above
the floor (heights in odom_frame, gravity-aligned by the EKF, from the standing
base height) is not an obstacle. ros2_depth_corridor rejects the floor on its own
from an assumed camera height for a level camera; a few centimetres of error in
either turned the whole floor near the robot into an obstacle at ~0.35 m.

Points are kept for `window` seconds in odom_frame and reprojected from the camera
pose of the latest cloud. In sensor coordinates the points of the last 0.5 s, taken
while the body turned and rocked, read the floor as an obstacle for about half a
second after every motion (measured in simulation: corridor 0.37 m instead of 4 m).
Without the odom_frame transform (or with odom_frame empty: no localization, branch
mapless) the node falls back to the sensor frame, with the floor estimated for a
level body; keep `window` short then, since the points are not compensated. Points on the robot's own body (front legs, head)
are dropped with a box in the body frame.

The camera must be in the TF tree (URDF or a static transform). Without a
calibrated camera_info, hfov_deg + image_width/height describe an ideal pinhole.
"""

import math

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image, PointCloud2
from sensor_msgs_py import point_cloud2
from tf2_ros import Buffer, TransformException, TransformListener

# Optical frame (x right, y down, z forward) from a body-convention camera frame
# (x forward, y left, z up).
BODY_TO_OPTICAL = np.array([
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
    [1.0, 0.0, 0.0],
])


def transform_matrix(transform):
    t, q = transform.transform.translation, transform.transform.rotation
    x, y, z, w = q.x, q.y, q.z, q.w
    m = np.eye(4)
    m[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    m[:3, 3] = [t.x, t.y, t.z]
    return m


class LidarCameraDepth(Node):

    def __init__(self):
        super().__init__('lidar_camera_depth')
        p = self.declare_parameter
        self.body_frame = p('body_frame', 'dottorcane/base_link').value
        # Empty: the frame_id of camera_info.
        self.camera_frame = p('camera_frame', '').value
        # optical (z forward), body (x forward) or auto (from the transform to the body).
        self.convention = p('camera_convention', 'auto').value
        self.width = int(p('width', 320).value)
        self.window = p('window', 0.5).value
        self.min_depth = p('min_depth', 0.1).value
        self.max_depth = p('max_depth', 20.0).value
        # Fill empty pixels with the nearest depth within this many pixels (0: off).
        self.fill_radius = int(p('fill_radius', 1).value)
        # Box around the robot in the body frame: points inside are the robot itself.
        self.body_box_min = np.array(p('body_box_min', [-0.45, -0.22, -0.45]).value)
        self.body_box_max = np.array(p('body_box_max', [0.45, 0.22, 0.25]).value)
        # Gravity-aligned frame of the localization (EKF), for motion compensation and floor removal.
        self.odom_frame = p('odom_frame', 'map').value
        # Standing base height above the floor (0.34 m on the real Go2, 0.22 m with CHAMP).
        self.base_height = p('base_height', 0.34).value
        # Points lower than this above the floor are floor (0: keep them).
        self.floor_height = p('floor_height', 0.06).value
        # Camera without a calibration (no camera_info): ideal pinhole with this
        # horizontal field of view, centred, square pixels, frame camera_frame.
        hfov = p('hfov_deg', 0.0).value
        image_width = int(p('image_width', 1280).value)
        image_height = int(p('image_height', 720).value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.info = None
        self.out_info = None
        self.lidar_to_optical = {}  # lidar frame -> 4x4, transform is static
        self.lidar_to_body = {}
        self.clouds = []  # (stamp seconds, Nx3 points in odom_frame, or in the lidar frame without it)
        self.warned = set()

        self.pub = self.create_publisher(Image, 'depth', 5)
        self.info_pub = self.create_publisher(CameraInfo, 'depth/camera_info', 5)
        if hfov > 0:
            if not self.camera_frame:
                raise ValueError('hfov_deg needs camera_frame')
            f = image_width / (2 * math.tan(math.radians(hfov) / 2))
            info = CameraInfo()
            info.header.frame_id = self.camera_frame
            info.width, info.height = image_width, image_height
            info.k = [f, 0.0, image_width / 2, 0.0, f, image_height / 2, 0.0, 0.0, 1.0]
            info.p = [f, 0.0, image_width / 2, 0.0, 0.0, f, image_height / 2, 0.0, 0.0, 0.0, 1.0, 0.0]
            self.on_info(info)
        else:
            self.create_subscription(CameraInfo, 'camera_info', self.on_info, qos_profile_sensor_data)
        self.create_subscription(PointCloud2, 'points', self.on_cloud, qos_profile_sensor_data)

    def warn_once(self, key, text):
        if key not in self.warned:
            self.warned.add(key)
            self.get_logger().warning(text)

    def on_info(self, info: CameraInfo):
        if self.info is not None:
            return
        fx, fy = info.p[0], info.p[5]
        if fx <= 0 or fy <= 0:
            fx, fy = info.k[0], info.k[4]
        if fx <= 0 or fy <= 0 or info.width == 0 or info.height == 0:
            self.warn_once('info', 'camera_info without intrinsics, waiting for a valid one')
            return
        self.info = info
        scale = self.width / info.width
        self.f = fx * scale
        # Square pixels: the vertical image fraction of a ray matches the camera's.
        self.height = max(1, int(round(self.f * info.height / fy)))
        self.cx = (info.p[2] if info.p[0] > 0 else info.k[2]) * scale
        self.cy = (info.p[6] if info.p[0] > 0 else info.k[5]) * self.height / info.height
        self.frame = self.camera_frame or info.header.frame_id
        hfov = math.degrees(2 * math.atan(info.width / (2 * fx)))
        self.get_logger().info(
            f'camera {info.width}x{info.height} fx={fx:.1f} fy={fy:.1f} '
            f'(HFOV {hfov:.1f} deg) -> depth {self.width}x{self.height} in {self.frame}')

        out = CameraInfo()
        out.header.frame_id = self.frame
        out.width, out.height = self.width, self.height
        out.distortion_model = 'plumb_bob'
        out.d = [0.0] * 5
        out.k = [self.f, 0.0, self.cx, 0.0, self.f, self.cy, 0.0, 0.0, 1.0]
        out.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        out.p = [self.f, 0.0, self.cx, 0.0, 0.0, self.f, self.cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.out_info = out

    def static_transforms(self, lidar_frame):
        if lidar_frame in self.lidar_to_optical:
            return self.lidar_to_optical[lidar_frame], self.lidar_to_body[lidar_frame]
        try:
            cam_from_lidar = transform_matrix(
                self.tf_buffer.lookup_transform(self.frame, lidar_frame, Time()))
            body_from_lidar = transform_matrix(
                self.tf_buffer.lookup_transform(self.body_frame, lidar_frame, Time()))
            body_from_cam = transform_matrix(
                self.tf_buffer.lookup_transform(self.body_frame, self.frame, Time()))
        except TransformException as e:
            self.warn_once(f'tf-{lidar_frame}', f'waiting for TF {lidar_frame} -> {self.frame}: {e}')
            return None, None

        convention = self.convention
        if convention == 'auto':
            # Which camera axis looks along the body's forward axis.
            forward = body_from_cam[:3, :3].T @ np.array([1.0, 0.0, 0.0])
            convention = 'optical' if abs(forward[2]) >= abs(forward[0]) else 'body'
            self.get_logger().info(f'camera frame {self.frame}: {convention} convention')
        optical_from_cam = np.eye(4)
        if convention == 'body':
            optical_from_cam[:3, :3] = BODY_TO_OPTICAL
        self.lidar_to_optical[lidar_frame] = optical_from_cam @ cam_from_lidar
        self.lidar_to_body[lidar_frame] = body_from_lidar
        return self.lidar_to_optical[lidar_frame], body_from_lidar

    def on_cloud(self, msg: PointCloud2):
        if self.out_info is None:
            self.warn_once('noinfo', 'waiting for camera_info')
            return
        to_optical, to_body = self.static_transforms(msg.header.frame_id)
        if to_optical is None:
            return
        xyz = point_cloud2.read_points_numpy(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        # Rays without a return are +inf in Gazebo (gpu_lidar); the Livox driver drops them.
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        odom_from_body = self.odom_pose(msg.header.stamp) if self.odom_frame else None
        if xyz.size:
            body = xyz @ to_body[:3, :3].T + to_body[:3, 3]
            on_robot = np.all((body >= self.body_box_min) & (body <= self.body_box_max), axis=1)
            body = body[~on_robot]
            if odom_from_body is not None:
                pts = body @ odom_from_body[:3, :3].T + odom_from_body[:3, 3]
                # Height above the floor below the robot: odom_frame is gravity-aligned.
                above = pts[:, 2] - odom_from_body[2, 3] + self.base_height
            else:
                pts = xyz[~on_robot]
                above = body[:, 2] + self.base_height
            if self.floor_height > 0:
                pts = pts[above >= self.floor_height]
        else:
            pts = xyz

        stamp = Time.from_msg(msg.header.stamp).nanoseconds * 1e-9
        moving = odom_from_body is not None
        if self.clouds and self.clouds[-1][2] != moving:
            self.clouds = []  # frame of the stored points changed
        self.clouds.append((stamp, pts, moving))
        self.clouds = [c for c in self.clouds if stamp - c[0] <= self.window]
        stored = np.concatenate([c[1] for c in self.clouds])
        if moving:
            # odom_frame -> lidar at the latest pose, then -> camera.
            lidar_from_odom = np.linalg.inv(odom_from_body @ to_body)
            stored = stored @ lidar_from_odom[:3, :3].T + lidar_from_odom[:3, 3]
        cam = stored @ to_optical[:3, :3].T + to_optical[:3, 3]
        cam = cam[(cam[:, 2] >= self.min_depth) & (cam[:, 2] <= self.max_depth)]
        self.publish(msg.header.stamp, cam)

    def odom_pose(self, stamp_msg):
        """odom_frame <- body at the cloud stamp, else the latest one (no waiting: the TF
        listener shares this single-threaded executor); None without the transform."""
        for when in (Time.from_msg(stamp_msg), Time()):
            try:
                return transform_matrix(self.tf_buffer.lookup_transform(self.odom_frame, self.body_frame, when))
            except TransformException as e:
                error = e
        self.warn_once('tf-odom', f'no TF {self.body_frame} -> {self.odom_frame} ({error}): '
                                  'no motion compensation, floor for a level body')
        return None

    def publish(self, stamp, pts):
        depth = np.full(self.height * self.width, np.inf, dtype=np.float32)
        if len(pts):
            z = pts[:, 2]
            u = np.floor(self.f * pts[:, 0] / z + self.cx).astype(np.int64)
            v = np.floor(self.f * pts[:, 1] / z + self.cy).astype(np.int64)
            inside = (u >= 0) & (u < self.width) & (v >= 0) & (v < self.height)
            np.minimum.at(depth, v[inside] * self.width + u[inside], z[inside].astype(np.float32))
        depth = depth.reshape(self.height, self.width)

        if self.fill_radius > 0:
            r = self.fill_radius
            padded = np.pad(depth, r, constant_values=np.inf)
            nearest = depth.copy()
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    nearest = np.minimum(
                        nearest, padded[r + dy:r + dy + self.height, r + dx:r + dx + self.width])
            empty = np.isinf(depth)
            depth[empty] = nearest[empty]
        depth[np.isinf(depth)] = np.nan

        img = Image()
        img.header.stamp = stamp
        img.header.frame_id = self.frame
        img.height, img.width = self.height, self.width
        img.encoding = '32FC1'
        img.is_bigendian = 0
        img.step = self.width * 4
        img.data = depth.tobytes()
        self.pub.publish(img)
        self.out_info.header.stamp = stamp
        self.info_pub.publish(self.out_info)


def main():
    rclpy.init()
    node = LidarCameraDepth()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
