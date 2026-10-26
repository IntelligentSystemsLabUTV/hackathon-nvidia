#!/usr/bin/env python3
"""Obstacle LaserScan for Nav2 from the Livox Mid-360 of the real Go2 (DottorCane).

Nav2 runs on a workstation over Wi-Fi: streaming the whole point cloud (~200k
points/s) there is too heavy, so this node runs on the Jetson and sends a 360 deg
LaserScan instead. It keeps the last `window` seconds of points in the odom frame
(the robot moves while Nav2 drives), drops the robot's own body, keeps the points
between min_height and max_height above the floor and publishes, per direction,
the nearest one in the body frame.

Heights above the floor are body z + base_height (the standing base height, from
the measured camera height minus its 4 cm above the base). The real lidar has a
few cm of noise and the body pitches slightly, so min_height stays well above the
floor (10 cm).

The Mid-360 is tilted 30 deg forward: behind the robot its rays point upward and
never see the floor band. A direction without obstacles reads +inf (Nav2 clears
it) only within +/- clear_half_angle_deg of the front; behind it reads NaN, so
the costmaps keep what they marked there before.

Drop-offs (stairs going down, a step) have no points in the obstacle band: with
cliff_check:=true the floor patch ahead of the robot (cliff_near..cliff_far,
within cliff_half_width) is checked as well, and when the lidar finds too few
floor points there, or points well below the floor, the front reads as an
obstacle at cliff_near. Off by default here: the costmaps of Nav2 take the scan,
and a false drop-off (a black glossy floor that returns little) would block it.
"""

import math

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import LaserScan, PointCloud2
from sensor_msgs_py import point_cloud2
from tf2_ros import Buffer, TransformException, TransformListener


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


class LidarObstacleScan(Node):

    def __init__(self):
        super().__init__('lidar_obstacle_scan')
        p = self.declare_parameter
        self.body_frame = p('body_frame', 'dottorcane/base_link').value
        self.odom_frame = p('odom_frame', 'map').value
        # Standing base height above the floor (camera at 0.38 m, 4 cm above the base).
        self.base_height = p('base_height', 0.34).value
        self.min_height = p('min_height', 0.10).value
        self.max_height = p('max_height', 0.70).value
        self.range_max = p('range_max', 8.0).value
        self.window = p('window', 0.3).value
        self.angle_increment = p('angle_increment', math.radians(0.5)).value
        self.clear_half_angle = math.radians(p('clear_half_angle_deg', 100.0).value)
        # Box around the robot in the body frame: points inside are the robot itself.
        self.body_box_min = np.array(p('body_box_min', [-0.45, -0.22, -0.45]).value)
        self.body_box_max = np.array(p('body_box_max', [0.45, 0.22, 0.25]).value)
        # Drop-off check of the floor patch ahead (body frame, m). The tilted Mid-360 sees the
        # floor from ~0.75 m ahead of the base: ~300 points per cloud there in simulation.
        self.cliff_check = p('cliff_check', False).value
        self.cliff_near = p('cliff_near', 0.6).value
        self.cliff_far = p('cliff_far', 1.2).value
        self.cliff_half_width = p('cliff_half_width', 0.3).value
        self.cliff_min_points = int(p('cliff_min_points', 20).value)
        # Floor points are within this of the floor; points this far below it are a drop.
        self.floor_tolerance = p('floor_tolerance', 0.06).value
        self.drop_height = p('drop_height', 0.12).value
        self.floor_counts = []  # (stamp seconds, floor points, points below the floor) in the patch

        self.n_beams = int(round(2 * math.pi / self.angle_increment))
        angles = -math.pi + (np.arange(self.n_beams) + 0.5) * self.angle_increment
        self.clearable = np.abs(angles) <= self.clear_half_angle

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.clouds = []  # (stamp seconds, Nx3 obstacle points in the odom frame)
        self.warned = set()
        self.pub = self.create_publisher(LaserScan, 'scan', qos_profile_sensor_data)
        self.create_subscription(PointCloud2, 'points', self.on_cloud, qos_profile_sensor_data)

    def warn_once(self, key, text):
        if key not in self.warned:
            self.warned.add(key)
            self.get_logger().warn(text)

    def lookup(self, target, source, stamp):
        # No waiting: the TF listener runs on this node's single-threaded executor, so
        # a blocking lookup would stall the /tf callbacks it waits for (measured in
        # simulation: one scan every few seconds instead of 10 Hz). A transform that is
        # not there yet at the cloud stamp falls back to the latest one, at most one
        # EKF period older (millimetres at the agent's speeds).
        for when in (stamp, Time()):
            try:
                return transform_matrix(self.tf_buffer.lookup_transform(target, source, when))
            except TransformException as e:
                error = e
        self.warn_once(f'tf-{target}-{source}', f'waiting for TF {source} -> {target}: {error}')
        return None

    def on_cloud(self, msg: PointCloud2):
        stamp = Time.from_msg(msg.header.stamp)
        body_from_lidar = self.lookup(self.body_frame, msg.header.frame_id, stamp)
        odom_from_body = self.lookup(self.odom_frame, self.body_frame, stamp)
        if body_from_lidar is None or odom_from_body is None:
            return
        xyz = point_cloud2.read_points_numpy(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        # Rays without a return are +inf in Gazebo (gpu_lidar); the Livox driver drops them.
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        body = xyz @ body_from_lidar[:3, :3].T + body_from_lidar[:3, 3]
        on_robot = np.all((body >= self.body_box_min) & (body <= self.body_box_max), axis=1)
        above = body[:, 2] + self.base_height
        if self.cliff_check:
            patch = (~on_robot & (body[:, 0] >= self.cliff_near) & (body[:, 0] <= self.cliff_far)
                     & (np.abs(body[:, 1]) <= self.cliff_half_width))
            floor = int(np.sum(patch & (np.abs(above) <= self.floor_tolerance)))
            below = int(np.sum(patch & (above <= -self.drop_height)))
            self.floor_counts.append((stamp.nanoseconds * 1e-9, floor, below))
        body = body[~on_robot & (above >= self.min_height) & (above <= self.max_height)]
        odom = body @ odom_from_body[:3, :3].T + odom_from_body[:3, 3]

        now = stamp.nanoseconds * 1e-9
        self.clouds.append((now, odom))
        self.clouds = [(s, c) for s, c in self.clouds if now - s <= self.window]
        body_from_odom = np.linalg.inv(odom_from_body)
        pts = np.concatenate([c for _, c in self.clouds])
        pts = pts @ body_from_odom[:3, :3].T + body_from_odom[:3, 3]
        if self.cliff_check:
            self.floor_counts = [c for c in self.floor_counts if now - c[0] <= self.window]
            floor = sum(c[1] for c in self.floor_counts)
            below = sum(c[2] for c in self.floor_counts)
            if floor < self.cliff_min_points or below >= self.cliff_min_points:
                self.get_logger().warning(
                    f'no floor ahead ({floor} floor points, {below} below it, {self.cliff_near}-{self.cliff_far} m): '
                    'drop-off, the front reads as an obstacle', throttle_duration_sec=5.0)
                ys = np.linspace(-self.cliff_half_width, self.cliff_half_width, 13)
                wall = np.stack([np.full_like(ys, self.cliff_near), ys, np.zeros_like(ys)], axis=1)
                pts = np.concatenate([pts, wall])
        self.publish(msg.header.stamp, pts)

    def publish(self, stamp, pts):
        ranges = np.full(self.n_beams, np.inf, dtype=np.float32)
        if len(pts):
            r = np.hypot(pts[:, 0], pts[:, 1])
            beam = ((np.arctan2(pts[:, 1], pts[:, 0]) + math.pi) / self.angle_increment).astype(np.int64)
            keep = (r <= self.range_max) & (beam >= 0) & (beam < self.n_beams)
            np.minimum.at(ranges, beam[keep], r[keep].astype(np.float32))
        ranges[np.isinf(ranges) & ~self.clearable] = np.nan

        scan = LaserScan()
        scan.header.stamp = stamp
        scan.header.frame_id = self.body_frame
        scan.angle_min = -math.pi + 0.5 * self.angle_increment
        scan.angle_max = scan.angle_min + (self.n_beams - 1) * self.angle_increment
        scan.angle_increment = self.angle_increment
        scan.range_min = 0.0
        scan.range_max = self.range_max
        scan.ranges = ranges.tolist()
        self.pub.publish(scan)


def main():
    rclpy.init()
    node = LidarObstacleScan()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
