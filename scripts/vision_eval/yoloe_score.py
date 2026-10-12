import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
GT = json.load(open(os.path.join(HERE, "data", "gt.json")))
MAP = {c: c for c in ["refrigerator", "bed", "sofa", "television", "dining table", "chair", "wardrobe", "fitness machine", "barbell", "trash can", "nightstand", "desk", "shoe rack", "coffee table"]}
MAP["front door"] = "door"
def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0); u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / u if u > 0 else 0
def match(d, o):
    b = o["visible_box"]; cx, cy = (d["box"][0]+d["box"][2])/2, (d["box"][1]+d["box"][3])/2
    return iou(d["box"], b) >= 0.3 or (b[0] <= cx <= b[2] and b[1] <= cy <= b[3])
for label in sys.argv[1:]:
    data = json.load(open(os.path.join(HERE, "results", "yolo", f"{label}.json")))
    dets = {}
    for d in data["detections"]: dets.setdefault((d["frame"], d["cls"]), []).append(d)
    for thr in (0.35, 0.25):
        tp = tot = fp = 0; per = {}
        for frame, g in GT.items():
            for cat, cls in MAP.items():
                inst = [o for o in g["objects"] if o["category"] == cat and o.get("visible_box")]
                pos = [o for o in inst if o["visible_px"] >= 120]
                ds = [d for d in dets.get((frame, cls), []) if d["conf"] >= thr]
                for o in pos:
                    hit = any(match(d, o) for d in ds); tp += hit; tot += 1
                    per.setdefault(cat, [0, 0]); per[cat][0] += hit; per[cat][1] += 1
                fp += sum(1 for d in ds if not any(match(d, o) for o in inst))
        print(f"{label} thr={thr} recall={tp/tot:.2f} ({tp}/{tot}) FP={fp} | " + " ".join(f"{c[:8]}={v[0]}/{v[1]}" for c, v in per.items()) + f" | {data['sec_per_frame_tiled']:.2f}s/frame")
