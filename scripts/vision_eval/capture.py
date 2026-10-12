"""Capture RGB + depth + ground-truth pose at several headings by rotating in place.

Usage: python3 capture.py <run_name> <n_headings> [step_deg]
Saves frames/<run>_<i>.png, .depth.npy, .json in data/frames/.
Ground-truth pose is only used offline to evaluate perception.
"""
import json
import math
import os
import sys
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from PIL import Image as PILImage
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "frames")
os.makedirs(OUT, exist_ok=True)

RGB = "/dottorcane/slam/zed_x_driver/left/image_rect_color"
DEPTH = "/dottorcane/slam/zed_x_driver/depth_distances"
POSE = "/gz/dottorcane/pose"
CMD = "/dottorcane/go2_control/cmd_vel"


class Cap(Node):
    def __init__(self):
        super().__init__("perception_capture")
        self.rgb = None
        self.depth = None
        self.pose = None
        self.create_subscription(Image, RGB, self.on_rgb, qos_profile_sensor_data)
        self.create_subscription(Image, DEPTH, self.on_depth, qos_profile_sensor_data)
        self.create_subscription(PoseStamped, POSE, self.on_pose, 10)
        self.pub = self.create_publisher(Twist, CMD, 10)

    def on_rgb(self, m):
        self.rgb = (time.monotonic(), m)

    def on_depth(self, m):
        self.depth = (time.monotonic(), m)

    def on_pose(self, m):
        self.pose = (time.monotonic(), m)

    def spin_for(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)

    def fresh(self, after):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if all(x is not None and x[0] > after for x in (self.rgb, self.depth, self.pose)):
                return True
        return False

    def rotate(self, degrees, eff=0.65, w=0.5):
        seconds = abs(math.radians(degrees)) / (w * eff)
        t = Twist()
        t.angular.z = math.copysign(w, degrees)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pub.publish(t)
            self.spin_for(0.1)
        self.pub.publish(Twist())
        for _ in range(5):
            self.pub.publish(Twist())
            self.spin_for(0.1)


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def save(node, name):
    _, rgb = node.rgb
    _, dep = node.depth
    _, pose = node.pose
    arr = np.frombuffer(bytes(rgb.data), dtype=np.uint8).reshape(rgb.height, rgb.step)
    ch = 3 if rgb.encoding in ("rgb8", "bgr8") else 4
    arr = arr[:, : rgb.width * ch].reshape(rgb.height, rgb.width, ch)[:, :, :3]
    if rgb.encoding.startswith("bgr"):
        arr = arr[:, :, ::-1]
    PILImage.fromarray(arr).save(os.path.join(OUT, f"{name}.png"))
    d = np.frombuffer(bytes(dep.data), dtype=np.float32).reshape(dep.height, dep.step // 4)[:, : dep.width]
    np.save(os.path.join(OUT, f"{name}.depth.npy"), d.astype(np.float32))
    p, q = pose.pose.position, pose.pose.orientation
    meta = {
        "name": name,
        "rgb_encoding": rgb.encoding,
        "rgb_size": [rgb.width, rgb.height],
        "depth_size": [dep.width, dep.height],
        "depth_encoding": dep.encoding,
        "pose": {"x": p.x, "y": p.y, "z": p.z, "qx": q.x, "qy": q.y, "qz": q.z, "qw": q.w, "yaw_deg": math.degrees(yaw_of(q))},
    }
    with open(os.path.join(OUT, f"{name}.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"saved {name}: pose x={p.x:.2f} y={p.y:.2f} z={p.z:.3f} yaw={meta['pose']['yaw_deg']:.1f}", flush=True)


def main():
    run = sys.argv[1]
    n = int(sys.argv[2])
    step = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0
    rclpy.init()
    node = Cap()
    for i in range(n):
        node.spin_for(1.5)  # settle after motion
        t0 = time.monotonic()
        if not node.fresh(t0):
            print("timeout waiting for fresh frames", flush=True)
            break
        save(node, f"{run}_{i:02d}")
        if i < n - 1:
            node.rotate(step)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
