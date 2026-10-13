#!/usr/bin/env bash
# Runs imu_check.mjs while record_pose.py records the ground truth, then prints IMU against truth.
# Evaluation only. Usage (in the container, sim running, robot with ~1 m free around it): bash -ic './imu_check.sh'
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${here}/results/imu_check"
mkdir -p "$out"
: > "$out/truth.txt"
python3 "${here}/record_pose.py" "$out/truth.txt" &
recorder=$!
sleep 3
node "${here}/imu_check.mjs" > "$out/imu.txt"
kill "$recorder" 2>/dev/null
python3 - "$out/truth.txt" "$out/imu.txt" <<'PY'
import sys
gt = [tuple(map(float, l.split())) for l in open(sys.argv[1]) if l.strip()]
unwrapped, acc, prev = [], 0.0, None
for t, _x, _y, yaw in gt:
    if prev is not None:
        acc += (yaw - prev + 180) % 360 - 180
    prev = yaw
    unwrapped.append((t, acc))
truth = lambda t: min(unwrapped, key=lambda r: abs(r[0] - t))[1]
rows = [l.split() for l in open(sys.argv[2]) if l.strip()][1:]
t0, i0 = float(rows[0][0]), float(rows[0][2])
g0 = truth(t0)
for t, label, yaw, gaps in rows:
    i, g = float(yaw) - i0, truth(float(t)) - g0
    print(f"{label:16s} IMU {i:8.1f}  truth {g:8.1f}  difference {i - g:+6.1f}  gaps {gaps}")
PY
