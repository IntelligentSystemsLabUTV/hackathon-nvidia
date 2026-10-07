#!/usr/bin/env python3
"""Obstacle LaserScan for Nav2 from the ZED depth image.

The single-plane scan (depthimage_to_laserscan, camera height ~0.39 m) misses
low or thin obstacles such as bed frames, chair legs or a barbell rack. This
node back-projects the whole depth image, keeps the points between min_height
and max_height above the floor and publishes, for each direction, the nearest
one as a LaserScan in a floor-level frame (dottorcane/base_ground, yaw only,
from ground_truth_odom): the costmaps and the collision monitor see every
obstacle the camera sees, at its real distance.

It works on the depth image (32FC1, z-depth in metres) instead of the bridged
point cloud: converting the 250k-point cloud in the bridge dropped it below
1 Hz, while the image already arrives at the sensor rate.
"""

import math

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image, LaserScan
from tf2_ros import Buffer, TransformException, TransformListener


def quaternion_matrix(q):
    x, y, z, w = q.x, q.y, q.z, q.w
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


class DepthObstacleScan(Node):

    def __init__(self):
        super().__init__('depth_obstacle_scan')
        p = self.declare_parameter
        self.target_frame = p('target_frame', 'dottorcane/base_ground').value
        self.min_height = p('min_height', 0.06).value
        self.max_height = p('max_height', 0.7).value
        self.range_min = p('range_min', 0.4).value
        self.range_max = p('range_max', 4.0).value
        self.angle_min = p('angle_min', -0.96).value
        self.angle_max = p('angle_max', 0.96).value
        self.angle_increment = p('angle_increment', 0.0087).value
        # Use every n-th row and column: 2 keeps ~0.33 deg between columns.
        self.decimation = int(p('decimation', 2).value)
        self.n_beams = int(round((self.angle_max - self.angle_min) / self.angle_increment)) + 1

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.rays = None  # unit-depth rays in the camera link frame, per pixel
        self.pub = self.create_publisher(LaserScan, 'scan', qos_profile_sensor_data)
        self.create_subscription(CameraInfo, 'depth_camera_info', self.on_info, qos_profile_sensor_data)
        self.create_subscription(Image, 'depth', self.on_depth, qos_profile_sensor_data)

    def on_info(self, info: CameraInfo):
        if self.rays is not None and self.rays.shape[:2] == self.shape_for(info):
            return
        fx, fy, cx, cy = info.k[0], info.k[4], info.k[2], info.k[5]
        d = self.decimation
        u = np.arange(0, info.width, d, dtype=np.float32)
        v = np.arange(0, info.height, d, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)
        # Gazebo camera link: x forward, y left, z up; image u right, v down.
        self.rays = np.stack([np.ones_like(uu), -(uu - cx) / fx, -(vv - cy) / fy], axis=-1)

    def shape_for(self, info):
        d = self.decimation
        return (len(range(0, info.height, d)), len(range(0, info.width, d)))

    def lookup(self, frame, stamp):
        try:
            return self.tf_buffer.lookup_transform(
                self.target_frame, frame, Time.from_msg(stamp), timeout=Duration(seconds=0.05))
        except TransformException:
            try:
                return self.tf_buffer.lookup_transform(self.target_frame, frame, Time())
            except TransformException as error:
                self.get_logger().warn(f'no transform {frame} -> {self.target_frame}: {error}',
                                       throttle_duration_sec=5.0)
                return None

    def on_depth(self, msg: Image):
        if self.rays is None or msg.encoding != '32FC1':
            return
        tf = self.lookup(msg.header.frame_id, msg.header.stamp)
        if tf is None:
            return
        d = self.decimation
        depth = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)[::d, ::d]
        if depth.shape != self.rays.shape[:2]:
            return
        valid = np.isfinite(depth) & (depth > 0.0)
        points = self.rays[valid] * depth[valid][:, None]
        t = tf.transform.translation
        points = points @ quaternion_matrix(tf.transform.rotation).T + np.array([t.x, t.y, t.z])

        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        r = np.hypot(x, y)
        keep = (z >= self.min_height) & (z <= self.max_height) & (r >= self.range_min) & (r <= self.range_max)
        angle = np.arctan2(y[keep], x[keep])
        idx = np.round((angle - self.angle_min) / self.angle_increment).astype(np.int64)
        inside = (idx >= 0) & (idx < self.n_beams)
        ranges = np.full(self.n_beams, np.inf, dtype=np.float32)
        np.minimum.at(ranges, idx[inside], r[keep][inside].astype(np.float32))

        scan = LaserScan()
        scan.header.stamp = msg.header.stamp
        scan.header.frame_id = self.target_frame
        scan.angle_min = self.angle_min
        scan.angle_max = self.angle_min + (self.n_beams - 1) * self.angle_increment
        scan.angle_increment = self.angle_increment
        scan.scan_time = 0.2
        scan.range_min = self.range_min
        scan.range_max = self.range_max
        scan.ranges = ranges.tolist()
        self.pub.publish(scan)


def main():
    rclpy.init()
    node = DepthObstacleScan()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
