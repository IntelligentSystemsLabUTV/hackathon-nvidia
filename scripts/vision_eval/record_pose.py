"""Records the ground-truth pose of the robot for closed-loop evaluation: "epoch x y yaw_deg" lines, at most 1 Hz.
Evaluation only: the agent never sees this topic. Started by closed_loop_matrix.sh.
Usage (ROS sourced): python3 record_pose.py <out.txt> [topic]
"""
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

out = open(sys.argv[1], "a", buffering=1)
topic = sys.argv[2] if len(sys.argv) > 2 else "/gz/dottorcane/pose"
last = 0.0


def on_pose(msg):
    global last
    now = time.time()
    if now - last < 1.0:
        return
    last = now
    p, q = msg.pose.position, msg.pose.orientation
    yaw = math.degrees(math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z)))
    out.write(f"{now:.1f} {p.x:.3f} {p.y:.3f} {yaw:.1f}\n")


rclpy.init()
node = Node("closed_loop_pose_recorder")
node.create_subscription(PoseStamped, topic, on_pose, qos_profile_sensor_data)
try:
    rclpy.spin(node)
except (KeyboardInterrupt, ExternalShutdownException):
    pass  # stopped by closed_loop_matrix.sh at the end of the series
