#!/usr/bin/env python3
"""Lighter copy of the Mid-360 cloud for the DUA Nav2 on a workstation (DottorCane).

The costmaps of dua_nav2 (config/dottorcane.yaml) take the deskewed Mid-360 cloud:
~200k points/s of 32 bytes (x, y, z, intensity, tag, ring, timestamp), ~6.4 MB/s.
Nav2 on the PC is a zenoh client of the router on the Jetson, and the local and
global costmaps live in two processes, so over Wi-Fi the cloud would cross twice
(~100 Mbit/s), on the same link as the cmd_vel of Nav2 (go2_control stops after a
500 ms watchdog).

This node runs on the Jetson and republishes only what the costmaps use:
  - the points within the obstacle band of the costmaps (min_height..max_height,
    z in the odom frame, as Nav2 filters them: in the global frame `map`);
  - one point per voxel (voxel m), the original point, not a centroid;
  - x, y, z only (12 bytes per point).
The points stay in the frame of the input cloud with its stamp, so Nav2 still
waits for that transform and raytraces from the same sensor origin.
"""

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import PointCloud2
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


class LidarNavCloud(Node):

    def __init__(self):
        super().__init__('lidar_nav_cloud')
        p = self.declare_parameter
        self.odom_frame = p('odom_frame', 'map').value
        # Obstacle band of the dua_nav2 costmaps (min/max_obstacle_height, global frame).
        self.min_height = p('min_height', 0.1).value
        self.max_height = p('max_height', 1.0).value
        # Resolution of the local costmap: one point per cell is enough to mark it.
        self.voxel = p('voxel', 0.05).value

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.warned = set()
        self.stats = [0, 0, 0]  # clouds, points in, points out (for the periodic log)
        self.pub = self.create_publisher(PointCloud2, 'cloud', qos_profile_sensor_data)
        self.create_subscription(PointCloud2, 'points', self.on_cloud, qos_profile_sensor_data)
        self.create_timer(30.0, self.log_stats)

    def warn_once(self, key, text):
        if key not in self.warned:
            self.warned.add(key)
            self.get_logger().warn(text)

    def lookup(self, target, source, stamp):
        # No waiting, as in lidar_obstacle_scan: a blocking lookup on this single-threaded
        # executor stalls the /tf callbacks. Without the transform at the cloud stamp the
        # latest one only decides which points are in the band.
        for when in (stamp, Time()):
            try:
                return transform_matrix(self.tf_buffer.lookup_transform(target, source, when))
            except TransformException as e:
                error = e
        self.warn_once(f'tf-{target}-{source}', f'waiting for TF {source} -> {target}: {error}')
        return None

    def on_cloud(self, msg: PointCloud2):
        odom_from_lidar = self.lookup(self.odom_frame, msg.header.frame_id, Time.from_msg(msg.header.stamp))
        if odom_from_lidar is None:
            return
        xyz = point_cloud2.read_points_numpy(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        xyz = np.asarray(xyz, dtype=np.float32).reshape(-1, 3)
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        odom = xyz.astype(np.float64) @ odom_from_lidar[:3, :3].T + odom_from_lidar[:3, 3]
        band = (odom[:, 2] >= self.min_height) & (odom[:, 2] <= self.max_height)
        xyz, odom = xyz[band], odom[band]
        if len(xyz):
            _, first = np.unique(np.floor(odom / self.voxel).astype(np.int64), axis=0, return_index=True)
            xyz = xyz[np.sort(first)]
        self.stats[0] += 1
        self.stats[1] += msg.width * msg.height
        self.stats[2] += len(xyz)
        self.pub.publish(point_cloud2.create_cloud_xyz32(msg.header, xyz))

    def log_stats(self):
        clouds, points_in, points_out = self.stats
        if clouds:
            self.get_logger().info(
                f'{clouds / 30.0:.1f} clouds/s, {points_in // clouds} -> {points_out // clouds} points '
                f'({points_out * 12 / 30.0 / 1e3:.0f} kB/s out)')
        else:
            self.warn_once('no-cloud', 'no input cloud yet')
        self.stats = [0, 0, 0]


def main():
    rclpy.init()
    node = LidarNavCloud()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
