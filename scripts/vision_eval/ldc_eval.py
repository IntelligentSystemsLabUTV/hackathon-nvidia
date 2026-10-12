"""LDC25 check: small/far COCO targets (fire hydrant, traffic light) for VLM-only localization.

Reference boxes come from tiled YOLO (YOLO26s, conf >= 0.5) on the same frames.
Usage: python ldc_eval.py yolo           -> writes data/ldc_ref.json (system python3 with onnxruntime)
       python ldc_eval.py vlm <cfg...>   -> writes results/vlm_ldc25/<cfg>.jsonl (.venv python)
       python ldc_eval.py score <cfg...>
"""
import glob
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(HERE, "data", "frames", "ldc*.png")) if "ldcspawn" not in p)
DW, DH = 672, 376


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def yolo_ref():
    import onnxruntime as ort
    from PIL import Image
    ye = load("ye", os.path.join(HERE, "yolo_eval.py"))
    ye.CLASSES = {"fire hydrant": 10, "traffic light": 9, "stop sign": 11}
    model = os.environ.get("YOLO26S_ONNX", os.path.expanduser("~/.agenticros/models/yolo26s.onnx"))
    sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    ref = {}
    for f in FRAMES:
        img = Image.open(os.path.join(HERE, "data", "frames", f + ".png")).convert("RGB")
        r, _ = ye.tiled(sess, img)
        ref[f] = {c: [d for d in ds if d[4] >= 0.5] for c, ds in r.items()}
        print(f, {c: [round(d[4], 2) for d in ds] for c, ds in ref[f].items()})
    json.dump(ref, open(os.path.join(HERE, "data", "ldc_ref.json"), "w"), indent=1)


QUERIES = [("red fire hydrant", "fire hydrant"), ("traffic light", "traffic light"), ("refrigerator", None)]


def vlm(cfgs):
    ev = load("ev", os.path.join(HERE, "eval_vlm.py"))
    ref = json.load(open(os.path.join(HERE, "data", "ldc_ref.json")))
    os.makedirs(os.path.join(HERE, "results", "vlm_ldc25"), exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    for cfg in cfgs:
        qs = []
        for f in FRAMES:
            for target, cls in QUERIES:
                positive = bool(cls and ref[f].get(cls))
                if cls and not positive and cls == "traffic light":
                    continue  # traffic light not visible or not confidently detected: skip as ambiguous
                qs.append((f, target, positive))
        with ThreadPoolExecutor(max_workers=4) as ex, open(os.path.join(HERE, "results", "vlm_ldc25", f"{cfg}.jsonl"), "w") as out:
            for rec in ex.map(lambda q: ev.run_one(cfg, q), qs):
                out.write(json.dumps(rec) + "\n")
        print(cfg, "done", len(qs), flush=True)


def bearing(xn):
    return -math.degrees(math.atan((xn - 0.5) * 2 * math.tan(math.radians(55))))


def depth_at(frame, box, pct=12):
    d = np.load(os.path.join(HERE, "data", "frames", f"{frame}.depth.npy"))
    x0, y0 = int(max(0, box[0]) * DW), int(max(0, box[1]) * DH)
    x1, y1 = max(x0 + 1, int(math.ceil(min(1, box[2]) * DW))), max(y0 + 1, int(math.ceil(min(1, box[3]) * DH)))
    v = d[y0:y1, x0:x1]
    v = np.sort(v[np.isfinite(v) & (v > 0)])
    return float(v[int(pct / 100 * len(v))]) if v.size else None


def inner(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return [b[0] + w * 0.25, b[1] + h * 0.15, b[2] - w * 0.25, b[3] - h * 0.15]


def score(cfgs):
    ref = json.load(open(os.path.join(HERE, "data", "ldc_ref.json")))
    for cfg in cfgs:
        recs = [json.loads(l) for l in open(os.path.join(HERE, "results", "vlm_ldc25", f"{cfg}.jsonl"))]
        tp = fn = fp = tn = 0
        rows = []
        for r in recs:
            cls = {"red fire hydrant": "fire hydrant", "traffic light": "traffic light"}.get(r["target"])
            if r["positive"]:
                if r["visible"] and r.get("cx") is not None:
                    tp += 1
                    g = max(ref[r["frame"]][cls], key=lambda d: d[4])
                    gb = bearing((g[0] + g[2]) / 2)
                    pb = bearing(r["cx"])
                    roi = r["box"] if cfg.split("_")[1] == "cols9" else inner(r["box"])
                    d = depth_at(r["frame"], roi)
                    gd = depth_at(r["frame"], inner(g[:4]))
                    rows.append((r["frame"], r["target"], round(pb - gb, 1), d and round(d, 2), gd and round(gd, 2)))
                else:
                    fn += 1
                    rows.append((r["frame"], r["target"], "MISS", None, None))
            else:
                fp += r["visible"]
                tn += not r["visible"]
        errs = [abs(x[2]) for x in rows if x[2] != "MISS"]
        derr = [abs(x[3] - x[4]) for x in rows if x[2] != "MISS" and x[3] and x[4]]
        lat = np.median([r["latency"] for r in recs])
        print(f"{cfg:22s} TP={tp} FN={fn} FP={fp} TN={tn} | bearing err med={np.median(errs) if errs else float('nan'):.1f} max={max(errs) if errs else float('nan'):.1f} | dist err med={np.median(derr) if derr else float('nan'):.2f} max={max(derr) if derr else float('nan'):.2f} | lat {lat:.2f}s")
        for x in rows:
            print("   ", x)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "yolo":
        yolo_ref()
    elif mode == "vlm":
        vlm(sys.argv[2:])
    else:
        score(sys.argv[2:])
