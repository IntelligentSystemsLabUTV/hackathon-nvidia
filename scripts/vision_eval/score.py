"""Score VLM localization results against the rasterized ground truth.

Usage: python score.py [cfg ...]   (default: every results/*.jsonl)
"""
import glob
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GT = json.load(open(os.path.join(HERE, "data", "gt.json")))
DW, DH = 672, 376
HFOV = 110.0
POS_MIN_PX = 120
_depth_cache = {}


def bearing(xn):
    half = math.tan(math.radians(HFOV / 2))
    return -math.degrees(math.atan((xn - 0.5) * 2 * half))


def depth(frame):
    if frame not in _depth_cache:
        _depth_cache[frame] = np.load(os.path.join(HERE, "data", "frames", f"{frame}.depth.npy"))
    return _depth_cache[frame]


def roi_depth(frame, box, pct=12):
    d = depth(frame)
    x0, y0 = int(max(0, box[0]) * DW), int(max(0, box[1]) * DH)
    x1, y1 = max(x0 + 1, int(math.ceil(min(1, box[2]) * DW))), max(y0 + 1, int(math.ceil(min(1, box[3]) * DH)))
    r = d[y0:y1, x0:x1]
    v = r[np.isfinite(r) & (r > 0) & (r <= 40)]
    if v.size == 0:
        return None
    v = np.sort(v)
    return float(v[min(len(v) - 1, int(pct / 100 * len(v)))])


def inner(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return [b[0] + w * 0.25, b[1] + h * 0.15, b[2] - w * 0.25, b[3] - h * 0.15]


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def mask(frame, obj):
    p = os.path.join(HERE, "data", "masks", f"{frame}__{obj}.npy")
    if not os.path.exists(p):
        return None
    return np.unpackbits(np.load(p))[: DW * DH].reshape(DH, DW).astype(bool)


def score_record(r):
    inst = [o for o in GT[r["frame"]]["objects"] if o["category"] == r["target"] and o.get("visible_box")]
    out = {"tp": r["positive"] and r["visible"], "fn": r["positive"] and not r["visible"],
           "fp": (not r["positive"]) and r["visible"], "tn": (not r["positive"]) and not r["visible"]}
    if not out["tp"] or r.get("cx") is None or not inst:
        return out
    pb = bearing(r["cx"])
    errs = [abs(pb - o["bearing_deg"]) for o in inst]
    k = int(np.argmin(errs))
    o = inst[k]
    out["bearing_err"] = errs[k]
    b = o["visible_box"]
    cy = r.get("cy")
    in_x = any(oo["visible_box"][0] - 0.02 <= r["cx"] <= oo["visible_box"][2] + 0.02 for oo in inst)
    in_xy = any(oo["visible_box"][0] - 0.02 <= r["cx"] <= oo["visible_box"][2] + 0.02 and
                (cy is None or oo["visible_box"][1] - 0.03 <= cy <= oo["visible_box"][3] + 0.03) for oo in inst)
    out["hit_x"] = in_x
    out["hit_xy"] = in_xy
    if "box" in r:
        out["iou"] = max(iou(r["box"], oo["visible_box"]) for oo in inst)
    if "point" in r:
        px, py = r["point"]
        on = False
        for oo in inst:
            m = mask(r["frame"], oo["name"])
            if m is None:
                continue
            u, v = min(DW - 1, int(px * DW)), min(DH - 1, int(py * DH))
            # allow 3 depth pixels of slack
            if m[max(0, v - 3):v + 4, max(0, u - 3):u + 4].any():
                on = True
        out["on_object"] = on
    # distance with the ROI the agent would use
    if "point" in r:
        px, py = r["point"]
        roi = [px - 0.03, py - 0.05, px + 0.03, py + 0.05]
    elif r["cfg"].split("_")[1] == "cols9":
        roi = r["box"]
    else:
        roi = inner(r["box"])
    d = roi_depth(r["frame"], roi)
    gd = o.get("distance_m")
    # nearest instance by distance may be the right reference when several are in the ROI
    gds = [oo.get("distance_m") for oo in inst if oo.get("distance_m") is not None]
    if d is not None and gd is not None:
        out["dist_err"] = abs(d - gd)
        out["dist_rel"] = abs(d - gd) / gd
        out["dist_err_best"] = min(abs(d - g) for g in gds)
        out["gt_dist"] = gd
    return out


def summarize(cfg, recs):
    if not recs or all(r.get("error") for r in recs):
        return f"{cfg:22s} n={len(recs)} (no successful calls yet)"
    s = [score_record(r) for r in recs]
    tp = sum(x["tp"] for x in s)
    fn = sum(x["fn"] for x in s)
    fp = sum(x["fp"] for x in s)
    tn = sum(x["tn"] for x in s)
    be = np.array([x["bearing_err"] for x in s if "bearing_err" in x])
    de = np.array([x["dist_err_best"] for x in s if "dist_err_best" in x])
    drel = np.array([x["dist_err_best"] / max(0.3, x["gt_dist"]) for x in s if "dist_err_best" in x])
    near = np.array([x["dist_err_best"] for x in s if "dist_err_best" in x and x["gt_dist"] <= 2.5])
    lat = np.array([r["latency"] for r in recs if not r.get("error")])
    ious = np.array([x["iou"] for x in s if "iou" in x])
    hx = [x["hit_x"] for x in s if "hit_x" in x]
    hxy = [x["hit_xy"] for x in s if "hit_xy" in x]
    on = [x["on_object"] for x in s if "on_object" in x]
    parse_fail = sum(1 for r in recs if not r["parse_ok"])
    errors = sum(1 for r in recs if r.get("error"))
    convs = {}
    for r in recs:
        if r.get("conv"):
            convs[r["conv"]] = convs.get(r["conv"], 0) + 1
    toks = [r["usage"][0] for r in recs if r.get("usage")]
    line = (f"{cfg:22s} n={len(recs):3d} TPR={tp / max(1, tp + fn):.2f} FPR={fp / max(1, fp + tn):.2f} "
            f"| bearing med={np.median(be) if be.size else float('nan'):5.1f}° p80={np.percentile(be, 80) if be.size else float('nan'):5.1f}° "
            f"<=6°:{(be <= 6).mean() if be.size else 0:.2f} <=12°:{(be <= 12).mean() if be.size else 0:.2f} "
            f"| hit_x={np.mean(hx) if hx else float('nan'):.2f} hit_xy={np.mean(hxy) if hxy else float('nan'):.2f}"
            + (f" on_obj={np.mean(on):.2f}" if on else "")
            + (f" IoU med={np.median(ious):.2f} >=0.5:{(ious >= 0.5).mean():.2f}" if ious.size else "")
            + f" | dist med={np.median(de) if de.size else float('nan'):.2f}m ok(<=20%|0.3m)={((drel <= 0.2) | (de <= 0.3)).mean() if de.size else 0:.2f}"
            + f" near<=2.5m med={np.median(near) if near.size else float('nan'):.2f}m(n={near.size})"
            + f" | lat med={np.median(lat):.2f}s p90={np.percentile(lat, 90):.2f}s tok_in={int(np.median(toks)) if toks else 0}"
            + f" | parse_fail={parse_fail} err={errors}" + (f" conv={convs}" if convs else ""))
    return line


def balanced_json(text):
    """First complete top-level JSON object found by brace matching (strings respected)."""
    import re as _re
    t = _re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=_re.I)
    t = _re.sub(r"```(?:json)?", "", t, flags=_re.I)
    for start in [i for i, ch in enumerate(t) if ch == "{"]:
        depth_, in_str, esc = 0, False, False
        for j in range(start, len(t)):
            ch = t[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth_ += 1
            elif ch == "}":
                depth_ -= 1
                if depth_ == 0:
                    try:
                        v = json.loads(t[start:j + 1])
                        if isinstance(v, dict):
                            return v
                    except Exception:
                        pass
                    break
    return None


def reparse(r):
    """Re-run localization extraction on the raw reply with the robust parser."""
    if r["parse_ok"]:
        return r
    import importlib.util
    global _ev
    if "_ev" not in globals():
        spec = importlib.util.spec_from_file_location("ev", os.path.join(HERE, "eval_vlm.py"))
        _ev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ev)
    parsed = balanced_json(r["raw"])
    if parsed is None:
        return r
    r = dict(r)
    r["parse_ok"] = True
    r["reparsed"] = True
    t = parsed.get("target") or {}
    r["visible"] = t.get("visible") is True
    if r["visible"]:
        model, variant, width = _ev.CONFIGS[r["cfg"]]
        w, h = r["size"]
        try:
            if variant == "cols9":
                c = int(t.get("column"))
                if 1 <= c <= 9:
                    r["box"] = [(c - 1) / 9, 0.3, c / 9, 0.55]
                    r["cx"] = (c - 0.5) / 9
                    r["cy"] = None
            elif variant == "grid":
                cols, rows = t.get("columns"), t.get("rows")
                c0, c1 = sorted([int(cols[0]), int(cols[-1])])
                L = _ev.GRID_ROWS_LETTERS
                r0, r1 = sorted([L.index(str(rows[0]).strip().upper()[0]), L.index(str(rows[-1]).strip().upper()[0])])
                r["box"] = [(c0 - 1) / _ev.GRID_COLS, r0 / len(L), c1 / _ev.GRID_COLS, (r1 + 1) / len(L)]
            elif variant == "bbox":
                b, conv = _ev.to_norm(t.get("bbox"), w, h)
                r["box"] = [max(0, min(b[0], b[2])), max(0, min(b[1], b[3])), min(1, max(b[0], b[2])), min(1, max(b[1], b[3]))]
            elif variant == "point":
                pt, conv = _ev.to_norm(t.get("point"), w, h)
                r["point"] = [min(1, max(0, pt[0])), min(1, max(0, pt[1]))]
                r["cx"], r["cy"] = r["point"]
            if "box" in r and "cx" not in r:
                r["cx"] = (r["box"][0] + r["box"][2]) / 2
                r["cy"] = (r["box"][1] + r["box"][3]) / 2
        except Exception:
            pass
    return r


def main():
    robust = "--robust" in sys.argv
    sys.argv = [a for a in sys.argv if a != "--robust"]
    cfgs = sys.argv[1:] or sorted(os.path.basename(p)[:-6] for p in glob.glob(os.path.join(HERE, "results", "vlm", "*.jsonl")))
    for cfg in cfgs:
        recs = {}
        for line in open(os.path.join(HERE, "results", "vlm", f"{cfg}.jsonl")):
            r = json.loads(line)
            recs[(r["frame"], r["target"])] = r  # last wins
        values = [reparse(r) for r in recs.values()] if robust else list(recs.values())
        print(summarize(cfg + ("+R" if robust else ""), values))


if __name__ == "__main__":
    main()
