#!/usr/bin/env bash
timeout 8 ros2 topic echo --once /gz/dottorcane/pose 2>/dev/null | python3 -c "
import sys, math, re
t = sys.stdin.read()
v = {k: float(x) for k, x in re.findall(r'(\bx|\by|\bz|\bw): (-?[0-9.e-]+)', t)} if False else None
nums = re.findall(r'(-?\d+\.\d+(?:e-?\d+)?)', t)
px, py, pz, qx, qy, qz, qw = map(float, nums[-7:])
yaw = math.degrees(math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz)))
print(f'pose x={px:.2f} y={py:.2f} yaw={yaw:.0f}')
fx, fy = 8.70, -1.03
print(f'dist to fridge centre={math.hypot(fx-px, fy-py):.2f} m; fridge front face x=8.29 -> camera-to-face approx {8.29 - (px + 0.124*math.cos(math.radians(yaw))):.2f} m (if facing +x)')
"
