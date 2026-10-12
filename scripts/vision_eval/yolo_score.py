"""Score tiled YOLO detections against the rasterized ground truth.

Usage: python yolo_score.py [label ...]
"""
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GT = json.load(open(os.path.join(HERE, "data", "gt.json")))
MAP = {"refrigerator": "refrigerator", "bed": "bed", "sofa": "couch", "television": "tv", "dining table": "dining table", "chair": "chair"}
POS_MIN_PX = 120


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def match(d, o):
    b = o["visible_box"]
    cx, cy = (d["box"][0] + d["box"][2]) / 2, (d["box"][1] + d["box"][3]) / 2
    return iou(d["box"], b) >= 0.3 or (b[0] <= cx <= b[2] and b[1] <= cy <= b[3])


def score(label, thr):
    data = json.load(open(os.path.join(HERE, "results", "yolo", f"{label}.json")))
    dets = {}
    for d in data["detections"]:
        dets.setdefault((d["frame"], d["cls"]), []).append(d)
    per_cls = {c: [0, 0] for c in MAP}
    fp = {c: 0 for c in MAP}
    best_conf = {c: [] for c in MAP}
    for frame, g in GT.items():
        for cat, coco in MAP.items():
            inst = [o for o in g["objects"] if o["category"] == cat and o.get("visible_box")]
            pos = [o for o in inst if o["visible_px"] >= POS_MIN_PX]
            ds = dets.get((frame, coco), [])
            for o in pos:
                confs = [d["conf"] for d in ds if match(d, o)]
                c = max(confs) if confs else 0.0
                best_conf[cat].append(c)
                per_cls[cat][1] += 1
                if c >= thr:
                    per_cls[cat][0] += 1
            for d in ds:
                if d["conf"] >= thr and not any(match(d, o) for o in inst):
                    fp[cat] += 1
    tot_tp = sum(v[0] for v in per_cls.values())
    tot = sum(v[1] for v in per_cls.values())
    parts = " ".join(f"{c[:6]}={v[0]}/{v[1]}" for c, v in per_cls.items())
    med = {c: (round(float(np.median(v)), 2) if v else None) for c, v in best_conf.items()}
    return (f"{label:16s} thr={thr:.2f} recall={tot_tp / max(1, tot):.2f} ({tot_tp}/{tot}) FP={sum(fp.values()):3d} "
            f"| {parts} | FP by class {fp} | median best conf {med} | {data['sec_per_frame_tiled']:.2f}s/frame")


def main():
    labels = sys.argv[1:] or sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(HERE, "results", "yolo", "*.json")))
    for thr in (0.35, 0.25):
        for label in labels:
            print(score(label, thr))
        print()


if __name__ == "__main__":
    main()
