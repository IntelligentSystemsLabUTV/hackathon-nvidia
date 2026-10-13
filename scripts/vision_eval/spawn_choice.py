"""Repeated exploration choice from the spawn views (agent tile order and labels), with geodesic progress."""
import json, math, sys
import numpy as np
sys.path.insert(0, "/home/neo/workspace/scripts/vision_eval")
import explore_choice_eval as E
T = E.T
D = "/home/neo/workspace/scripts/vision_eval/data/frames"
frames = [f"spawn_{i:02d}" for i in range(4)]
yaw = {f: json.load(open(f"{D}/{f}.json"))["pose"]["yaw_deg"] for f in frames}
px, py = 0.0, 1.5
robot = -90.0  # dead-reckoned heading at the end of the turn (0, -90, 180, 90, 0, -90)
nominal = {"spawn_00": 0, "spawn_01": -90, "spawn_02": 180, "spawn_03": 90}
order = sorted(frames, key=lambda f: -T.wrap(nominal[f] - robot))
rel = [round(T.wrap(nominal[f] - robot)) for f in order]
zones = E.object_zones()
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
for target in ["bed", "wardrobe", "desk", "refrigerator"]:
    dist = E.geodesic_to(zones[target])
    gains, picks = [], []
    for _ in range(N):
        v, reason, x = E.ask_vlm(target, order, rel, 4)
        if v is None or not 0 <= v < 4:
            gains.append(0.0); picks.append(None); continue
        h = yaw[order[v]] + T.bearing_of_x(x)
        gains.append(E.progress(dist, px, py, h)); picks.append((rel[v], round(x, 2)))
    best = max(E.progress(dist, px, py, yaw[f] + b) for f in frames for b in range(-50, 51, 10))
    print(f"{target:12s} progress >0.5 m in {np.mean([g > 0.5 for g in gains]):.0%} of {N}, mean {np.mean(gains):+.2f} m "
          f"(best possible {best:+.2f}) picks {picks}", flush=True)
