"""Python replica of @agenticros/object-detection detectClassTiled for any
YOLO ONNX with [1, 4+nc, N] output, evaluated on all classes in one pass.

Usage: python3 yolo_eval.py <label> <model.onnx> [providers=cpu]
Writes results/yolo/<label>.json with every detection >= 0.05.
"""
import glob
import json
import os
import sys
import time

import numpy as np
import onnxruntime as ort
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT = 640
CLASSES = {"refrigerator": 72, "bed": 59, "couch": 57, "tv": 62, "dining table": 60, "chair": 56,
           "toilet": 61, "potted plant": 58, "sports ball": 32, "oven": 69, "sink": 71, "bench": 13}
SCORE_MIN = 0.05


def letterbox(img):
    w, h = img.size
    scale = min(INPUT / w, INPUT / h)
    nw, nh = round(w * scale), round(h * scale)
    padx, pady = (INPUT - nw) // 2, (INPUT - nh) // 2
    canvas = Image.new("RGB", (INPUT, INPUT), (114, 114, 114))
    canvas.paste(img.resize((nw, nh), Image.BILINEAR), (padx, pady))
    x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return x, scale, padx, pady


def nms(boxes, scores, thr):
    order = np.argsort(-scores)
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx0 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy0 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx1 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy1 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx1 - xx0, 0, None) * np.clip(yy1 - yy0, 0, None)
        a = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        b = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / np.maximum(1e-9, a + b - inter)
        order = order[1:][iou < thr]
    return keep


def detect(sess, img):
    """All CLASSES on one image: dict cls -> list of (x0,y0,x1,y1,score) in image pixels."""
    w, h = img.size
    x, scale, padx, pady = letterbox(img)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    if out.shape[1] < out.shape[2]:
        out = out[0]  # (4+nc, N)
    else:
        out = out[0].T
    res = {}
    for cls, cid in CLASSES.items():
        sc = out[4 + cid]
        m = sc >= SCORE_MIN
        if not m.any():
            res[cls] = []
            continue
        cx, cy, bw, bh = out[0, m], out[1, m], out[2, m], out[3, m]
        x0 = np.clip((cx - bw / 2 - padx) / scale, 0, w)
        y0 = np.clip((cy - bh / 2 - pady) / scale, 0, h)
        x1 = np.clip((cx + bw / 2 - padx) / scale, 0, w)
        y1 = np.clip((cy + bh / 2 - pady) / scale, 0, h)
        boxes = np.stack([x0, y0, x1, y1], 1)
        ok = (x1 > x0) & (y1 > y0)
        boxes, s = boxes[ok], sc[m][ok]
        keep = nms(boxes, s, 0.5)
        res[cls] = [(*boxes[i], float(s[i])) for i in keep]
    return res


def tiled(sess, img):
    w, h = img.size
    allr = {c: list(v) for c, v in detect(sess, img).items()}
    tile = min(h, w, max(320, round(w * 0.25)))
    stride = max(1, tile * 0.75)
    top = round(max(0, min(h - tile, 0.5 * h - tile / 2)))
    origins = []
    o = 0.0
    while o + tile < w:
        origins.append(round(o))
        o += stride
    origins.append(w - tile)
    for left in origins:
        crop = img.crop((left, top, left + tile, top + tile))
        r = detect(sess, crop)
        for c, dets in r.items():
            for (x0, y0, x1, y1, s) in dets:
                if (left > 0 and x0 <= 2) or (left + tile < w and x1 >= tile - 2) or (top > 0 and y0 <= 2) or (top + tile < h and y1 >= tile - 2):
                    continue
                allr[c].append((x0 + left, y0 + top, x1 + left, y1 + top, s))
    final = {}
    for c, dets in allr.items():
        if not dets:
            final[c] = []
            continue
        arr = np.array([d[:4] for d in dets])
        sc = np.array([d[4] for d in dets])
        keep = nms(arr, sc, 0.4)
        final[c] = [[float(arr[i, 0] / w), float(arr[i, 1] / h), float(arr[i, 2] / w), float(arr[i, 3] / h), float(sc[i])] for i in keep]
    return final, len(origins) + 1


def main():
    label, model = sys.argv[1], sys.argv[2]
    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"] if (len(sys.argv) > 3 and sys.argv[3] == "cuda") else ["CPUExecutionProvider"]
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(model, so, providers=prov)
    print(label, "output", sess.get_outputs()[0].shape, "providers", sess.get_providers(), flush=True)
    dets = []
    times = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "frames", "*.png"))):
        img = Image.open(f).convert("RGB")
        t0 = time.monotonic()
        r, n = tiled(sess, img)
        times.append(time.monotonic() - t0)
        name = os.path.basename(f)[:-4]
        for c, ds in r.items():
            for d in ds:
                dets.append({"frame": name, "cls": c, "box": [round(v, 4) for v in d[:4]], "conf": round(d[4], 3)})
    os.makedirs(os.path.join(HERE, "results", "yolo"), exist_ok=True)
    json.dump({"label": label, "sec_per_frame_tiled": float(np.median(times)), "detections": dets},
              open(os.path.join(HERE, "results", "yolo", f"{label}.json"), "w"))
    print(f"{label}: {len(dets)} detections, {np.median(times):.2f}s per frame (tiled, all classes, {n} inferences)", flush=True)


if __name__ == "__main__":
    main()
