#!/usr/bin/env python3
"""Odometry for Nav2 from the Gazebo ground-truth pose of the Go2.

Subscribes to the model pose bridged from Gazebo (world frame, ~10 Hz) and
publishes nav_msgs/Odometry plus the odom -> base_link transform. The odom
frame coincides with the Gazebo world frame, which is also the frame of the
house map, so AMCL starts from the spawn pose with map -> odom close to the
identity. Twist is estimated by differencing consecutive poses (body frame,
low-pass filtered): Nav2 uses it only for velocity feedback.

It also publishes odom -> base_ground: the robot position projected on the
floor, yaw only. Height filters on the camera point cloud (obstacle scan for
Nav2) use it, so "5 cm above the floor" stays right while the body pitches.

On the real robot this role belongs to the state estimator (leg odometry +
IMU); in simulation the ground truth stands in for it.
"""

import math

import rclpy
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from tf2_ros import TransformBroadcaster


def yaw_of(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class GroundTruthOdom(Node):

    def __init__(self):
        super().__init__('ground_truth_odom')
        self.odom_frame = self.declare_parameter('odom_frame', 'dottorcane/odom').value
        self.base_frame = self.declare_parameter('base_frame', 'dottorcane/base_link').value
        self.ground_frame = self.declare_parameter('ground_frame', 'dottorcane/base_ground').value
        # Weight of the newest finite-difference velocity (1.0 = no filtering).
        self.alpha = self.declare_parameter('velocity_filter_alpha', 0.5).value
        self.publish_tf = self.declare_parameter('publish_tf', True).value
        self.odom_pub = self.create_publisher(Odometry, 'odom', 10)
        self.tf_pub = TransformBroadcaster(self)
        self.create_subscription(PoseStamped, 'pose', self.on_pose, qos_profile_sensor_data)
        self.last = None
        self.twist = (0.0, 0.0, 0.0)

    def on_pose(self, msg: PoseStamped):
        p, q = msg.pose.position, msg.pose.orientation
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        yaw = yaw_of(q)
        if self.last is not None:
            lt, lx, ly, lyaw = self.last
            dt = t - lt
            if dt <= 0.0:
                return  # duplicate or out-of-order sample
            dx, dy = p.x - lx, p.y - ly
            # World displacement expressed in the body frame of the previous sample.
            vx = (math.cos(lyaw) * dx + math.sin(lyaw) * dy) / dt
            vy = (-math.sin(lyaw) * dx + math.cos(lyaw) * dy) / dt
            wz = math.atan2(math.sin(yaw - lyaw), math.cos(yaw - lyaw)) / dt
            a = self.alpha
            self.twist = tuple(a * new + (1.0 - a) * old for new, old in zip((vx, vy, wz), self.twist))
        self.last = (t, p.x, p.y, yaw)

        odom = Odometry()
        odom.header.stamp = msg.header.stamp
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose = msg.pose
        odom.twist.twist.linear.x, odom.twist.twist.linear.y, odom.twist.twist.angular.z = self.twist
        # Ground truth: tiny but non-zero covariances keep consumers numerically happy.
        for i in (0, 7, 14, 21, 28, 35):
            odom.pose.covariance[i] = 1e-4
            odom.twist.covariance[i] = 1e-3
        self.odom_pub.publish(odom)

        if self.publish_tf:
            tf = TransformStamped()
            tf.header = odom.header
            tf.child_frame_id = self.base_frame
            tf.transform.translation.x, tf.transform.translation.y, tf.transform.translation.z = p.x, p.y, p.z
            tf.transform.rotation = q
            ground = TransformStamped()
            ground.header = odom.header
            ground.child_frame_id = self.ground_frame
            ground.transform.translation.x, ground.transform.translation.y = p.x, p.y
            ground.transform.rotation.z, ground.transform.rotation.w = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
            self.tf_pub.sendTransform([tf, ground])


def main():
    rclpy.init()
    node = GroundTruthOdom()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
