"""Front clearance from the depth image: the agent's band above the horizon against a 3D corridor.

The agent measures the free space ahead as the 12th percentile of the depth in a band above the
horizon (x 0.4-0.6, y 0.25-0.5): objects lower than the camera (0.385 m) are not seen, and in
closed loop the robot got stuck against a bin, a coffee table and a dumbbell. The corridor keeps
the pixels whose 3D point lies in front of the body (|lateral| <= half width) between a few cm
above the floor and 1 m, from the planar depth of a level camera, and takes the k-th nearest.

Truth: walking distance along the heading until the robot's width touches an obstacle of the
occupancy map (glass excluded, the simulated depth sees through it), from the camera position.
Frames, depth and poses: data/frames and data/extra_frames (capture.py, local only).

Usage: python corridor_eval.py [frame_glob ...]
"""
import glob
import json
import math
import os
import sys

import numpy as np

import topo_eval as T

HERE = os.path.dirname(os.path.abspath(__file__))
CAM_HEIGHT_M = 0.385
CAM_FORWARD_M = 0.116  # camera ahead of the base centre
HFOV_DEG = 110.0
HALF_WIDTH_M = 0.25
MIN_HEIGHT_M = 0.05
MAX_HEIGHT_M = 1.0
K_NEAREST = 25
MAX_RANGE_M = 6.0
# The front legs are in the bottom of the image, 0.10-0.15 m from the camera; the nearest floor
# the camera sees is 0.48 m away.
MIN_DEPTH_M = 0.3


def band_clearance(d):
    """The agent's current measure: 12th percentile in x 0.4-0.6, y 0.25-0.5."""
    h, w = d.shape
    roi = d[int(0.25 * h):int(0.5 * h), int(0.4 * w):int(0.6 * w)]
    v = roi[np.isfinite(roi) & (roi > 0) & (roi <= 40)]
    if v.size == 0:
        return None
    v = np.sort(v)
    return float(v[min(v.size - 1, int(0.12 * v.size))])


def corridor_clearance(d):
    """k-th nearest depth among the pixels inside the 3D corridor in front of the body; None if clear."""
    h, w = d.shape
    tan_h = math.tan(math.radians(HFOV_DEG / 2))
    tan_v = tan_h * h / w
    xs = (np.arange(w) + 0.5) / w
    ys = (np.arange(h) + 0.5) / h
    tx = (xs - 0.5) * 2 * tan_h  # lateral offset per metre of depth
    ty = (ys - 0.5) * 2 * tan_v  # downward offset per metre of depth
    valid = np.isfinite(d) & (d >= MIN_DEPTH_M) & (d <= 40)
    z = np.where(valid, d, np.nan)
    lateral = z * tx[None, :]
    height = CAM_HEIGHT_M - z * ty[:, None]
    inside = valid & (np.abs(lateral) <= HALF_WIDTH_M) & (height >= MIN_HEIGHT_M) & (height <= MAX_HEIGHT_M)
    v = np.sort(z[inside])
    if v.size < K_NEAREST:
        return None
    return float(v[K_NEAREST - 1])


def truth_clearance(pose):
    """Distance from the camera along the heading until a map obstacle (glass excluded) is within the body's width."""
    yaw = math.radians(pose["yaw_deg"])
    c, s = math.cos(yaw), math.sin(yaw)
    cx, cy = pose["x"] + CAM_FORWARD_M * c, pose["y"] + CAM_FORWARD_M * s
    step = 0.05
    for i in range(1, int(MAX_RANGE_M / step) + 1):
        dist = i * step
        for k in np.linspace(-HALF_WIDTH_M, HALF_WIDTH_M, 11):
            x, y = cx + dist * c - k * s, cy + dist * s + k * c
            if T.occupied(x, y):
                return dist
    return None


def main():
    patterns = sys.argv[1:] or [os.path.join(HERE, "data", "frames", "*.json"), os.path.join(HERE, "data", "extra_frames", "*.json")]
    # ldc* frames are from the other world: the house map is not their truth.
    files = sorted(f for p in patterns for f in glob.glob(p) if not os.path.basename(f).startswith("ldc"))
    rows = []
    for f in files:
        meta = json.load(open(f))
        depth_path = f[: -len(".json")] + ".depth.npy"
        if "pose" not in meta or not os.path.exists(depth_path):
            continue
        d = np.load(depth_path)
        rows.append((meta["name"], truth_clearance(meta["pose"]), band_clearance(d), corridor_clearance(d)))
    cap = lambda v: MAX_RANGE_M if v is None else min(v, MAX_RANGE_M)
    print(f"{'frame':24s} truth  band  corridor  min(band, corridor)")
    near = []
    for name, truth, band, corr in rows:
        both = min(cap(band), cap(corr))
        if truth is not None and truth <= 2.0:
            near.append((truth, cap(band), both))
        flag = "  <-- band misses" if truth is not None and truth <= 1.5 and cap(band) > truth + 0.5 else ""
        print(f"{name:24s} {cap(truth):5.2f} {cap(band):5.2f} {cap(corr):8.2f} {both:8.2f}{flag}")
    a = np.array(near)
    if len(a):
        print(f"\n{len(rows)} frames; {len(a)} with a map obstacle within 2 m of the camera (body width):")
        for label, col in [("band above the horizon", 1), ("min(band, corridor)", 2)]:
            err = a[:, col] - a[:, 0]
            print(f"  {label:24s} median error {np.median(err):+.2f} m, overestimates > 0.5 m: {(err > 0.5).sum()}, "
                  f"underestimates > 0.5 m: {(err < -0.5).sum()}")


if __name__ == "__main__":
    main()
