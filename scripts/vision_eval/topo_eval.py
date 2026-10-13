"""Score the openings (exits) and the area label reported by the vision model.

Ground truth: house_topology.json (passages, glass folding doors, front door, windows)
projected into each captured frame with the ground-truth pose and the occupancy map
(glass doors are transparent for line of sight, as they are for the camera).

Usage: python topo_eval.py <cfg> [<cfg> ...]   (results/vlm/<cfg>.jsonl)
Records from the "final" prompt carry "doorways" (boxes only, all taken as open);
records from the "graph" prompt carry "openings" (box, kind, leads_to) and "area".
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.abspath(os.path.join(HERE, "..", ".."))
HFOV = 110.0
GT = json.load(open(os.path.join(HERE, "data", "gt.json")))
TOPO = json.load(open(os.path.join(HERE, "house_topology.json")))
MAP = np.array(Image.open(os.path.join(WS, "src", "go2_sim_worlds", "maps", "house_world_map.pgm")))
RES, ORIGIN = 0.05, (-12.5, -12.5)
MIN_VISIBLE_DEG = 10.0  # a passage narrower than this in the image is not expected to be reported
MAX_PASSAGE_DIST_M = 6.0  # farther passages are not expected either
MAX_PASSAGE_BEARING_DEG = 45.0  # nor ones whose visible centre is at the image edge
SCAN_VIEWS = (0, 2, 4, 6)  # frames ~90 deg apart, as in the robot's search turn
CLUSTER_DEG = 20.0
BEARING_TOL_DEG = 3.0
PASSABLE_KINDS = {"open"}


def bearing_of_x(xn):
    half = math.tan(math.radians(HFOV / 2))
    return -math.degrees(math.atan((xn - 0.5) * 2 * half))


def wrap(d):
    return (d + 180) % 360 - 180


def glass_boxes():
    out = []
    for e in TOPO["elements"]:
        if e["type"] == "glass":
            xs, ys = (e["a"][0], e["b"][0]), (e["a"][1], e["b"][1])
            out.append((min(xs) - 0.12, max(xs) + 0.12, min(ys) - 0.12, max(ys) + 0.12))
    return out


GLASS = glass_boxes()


def occupied(x, y):
    r = MAP.shape[0] - 1 - int((y - ORIGIN[1]) / RES)
    c = int((x - ORIGIN[0]) / RES)
    if not (0 <= r < MAP.shape[0] and 0 <= c < MAP.shape[1]):
        return True
    if MAP[r, c] != 0:
        return False
    return not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in GLASS)


def line_of_sight(px, py, qx, qy, stop_before=0.15):
    d = math.hypot(qx - px, qy - py)
    s = 0.3
    while s < d - stop_before:
        if occupied(px + (qx - px) * s / d, py + (qy - py) * s / d):
            return False
        s += 0.025
    return True


_visible_cache = {}


def visible_elements(frame):
    """{element id: {"type", "bmin", "bmax", "dist"}} for elements in the field of view and in line of sight."""
    if frame in _visible_cache:
        return _visible_cache[frame]
    pose = GT[frame]["pose"]
    px, py, yaw = pose["x"], pose["y"], pose["yaw_deg"]
    out = {}
    for e in TOPO["elements"]:
        (ax, ay), (bx, by) = e["a"], e["b"]
        n = max(2, int(math.hypot(bx - ax, by - ay) / 0.05))
        bs, ds = [], []
        for i in range(n + 1):
            x, y = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
            b = wrap(math.degrees(math.atan2(y - py, x - px)) - yaw)
            if abs(b) > HFOV / 2 or math.hypot(x - px, y - py) > 12:
                continue
            if line_of_sight(px, py, x, y):
                bs.append(b)
                ds.append(math.hypot(x - px, y - py))
        if bs:
            out[e["id"]] = {"type": e["type"], "bmin": min(bs), "bmax": max(bs), "dist": float(np.median(ds))}
    _visible_cache[frame] = out
    return out


def norm_box(raw):
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        v = [float(x) for x in raw]
    except (TypeError, ValueError):
        return None
    if any(x < 0 for x in v):
        return None
    scale = 1 if max(v) <= 1 else 1000 if max(v) <= 1000 else None
    if scale is None:
        return None
    a, b, c, d = [min(1, x / scale) for x in v]
    box = [min(a, c), min(b, d), max(a, c), max(b, d)]
    if box[2] - box[0] < 0.004 or box[3] - box[1] < 0.004:
        return None
    return box


def detections(rec):
    """[(box, kind, leads_to)] from either prompt format."""
    if rec.get("openings") is not None:
        out = []
        for o in rec["openings"]:
            if isinstance(o, dict):
                b = norm_box(o.get("bbox"))
                if b:
                    out.append((b, str(o.get("kind", "")), str(o.get("leads_to", ""))))
        return out
    return [(b, "open", "") for b in (norm_box(x) for x in (rec.get("doorways") or [])) if b]


def match(frame, box):
    """Element id the detection points at (nearest element under its centre), or None."""
    vis = visible_elements(frame)
    bl, br = bearing_of_x(box[0]), bearing_of_x(box[2])
    bc = bearing_of_x((box[0] + box[2]) / 2)
    under = [(v["dist"], k) for k, v in vis.items() if v["bmin"] - BEARING_TOL_DEG <= bc <= v["bmax"] + BEARING_TOL_DEG]
    if under:
        return min(under)[1]
    best, best_ov = None, 0.0
    for k, v in vis.items():
        ov = max(0.0, min(bl, v["bmax"]) - max(br, v["bmin"]))
        if ov > best_ov:
            best, best_ov = k, ov
    return best if best is not None and best_ov >= 0.5 * max(1e-6, bl - br) else None


def relevant_passage(eid, v):
    """A passage between rooms the robot is expected to report from this frame."""
    return (v["type"] == "passage" and eid != "east_opening" and v["bmax"] - v["bmin"] >= MIN_VISIBLE_DEG
            and v["dist"] <= MAX_PASSAGE_DIST_M and abs((v["bmax"] + v["bmin"]) / 2) <= MAX_PASSAGE_BEARING_DEG)


def element_type(eid):
    return next(e["type"] for e in TOPO["elements"] if e["id"] == eid) if eid else "none"


BED_WORDS = re.compile(r"bed|sleep", re.I)


def score(cfg):
    path = os.path.join(HERE, "results", "vlm", f"{cfg}.jsonl")
    recs = [json.loads(line) for line in open(path)]
    recs = [r for r in recs if not r.get("error") and r.get("parse_ok")]
    by_kind = defaultdict(Counter)  # reported kind -> matched element type
    passage_seen = Counter()
    passage_found = Counter()
    open_total = 0
    open_ok = 0
    leads = []
    areas = defaultdict(Counter)
    per_frame_open = []
    for r in recs:
        frame = r["frame"]
        vis = visible_elements(frame)
        dets = detections(r)
        found = set()
        n_open = 0
        for box, kind, lead in dets:
            eid = match(frame, box)
            et = element_type(eid)
            by_kind[kind][et] += 1
            if kind in PASSABLE_KINDS:
                n_open += 1
                open_total += 1
                if et == "passage":
                    open_ok += 1
                    found.add(eid)
                    leads.append((frame, eid, lead))
        per_frame_open.append(n_open)
        for k, v in vis.items():
            if relevant_passage(k, v):
                passage_seen[k] += 1
                if k in found:
                    passage_found[k] += 1
        loc = frame.rsplit("_", 1)[0]
        if r.get("area"):
            areas[loc][r["area"]] += 1
    print(f"== {cfg}: {len(recs)} replies")
    print(f"openings reported as passable: {open_total}, on a real passage: {open_ok} "
          f"(precision {open_ok / max(1, open_total):.0%}); per reply: mean {np.mean(per_frame_open):.2f}")
    for kind, cnt in sorted(by_kind.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  reported kind={kind or '-':8s} -> " + ", ".join(f"{t} {n}" for t, n in cnt.most_common()))
    tot_seen, tot_found = sum(passage_seen.values()), sum(passage_found.values())
    print(f"passages between rooms in view (>= {MIN_VISIBLE_DEG:.0f} deg, <= {MAX_PASSAGE_DIST_M:.0f} m, centre within "
          f"{MAX_PASSAGE_BEARING_DEG:.0f} deg): {tot_seen}, reported as passable: {tot_found} (recall {tot_found / max(1, tot_seen):.0%})")
    for k in sorted(passage_seen):
        print(f"  {k:22s} {passage_found[k]}/{passage_seen[k]}")
    west = [(f, e, lead) for f, e, lead in leads if e.startswith("west_passage") and f.rsplit("_", 1)[0] in ("hall", "gym", "living")]
    if west and any(lead for _, _, lead in west):
        bed = sum(1 for _, e, lead in west if e == "west_passage_bedroom" and BED_WORDS.search(lead))
        nb = sum(1 for _, e, _ in west if e == "west_passage_bedroom")
        print(f"west passage seen from the centre: {len(west)} reports; toward the bedroom with bed/bedroom in leads_to: {bed}/{nb}")
        for f, e, lead in west[:12]:
            print(f"    {f:10s} {e:22s} {lead}")
    lat = [r["latency"] for r in recs if r.get("latency")]
    print(f"latency: median {np.median(lat):.2f}s, p90 {np.percentile(lat, 90):.2f}s")
    scan_level(recs)
    if areas:
        print("area label by capture location:")
        for loc in sorted(areas):
            print(f"  {loc:8s} " + ", ".join(f"{a} {n}" for a, n in areas[loc].most_common()))


def scan_level(recs):
    """Per capture location, the search turn of the robot: union of the views ~90 deg apart."""
    first = {}
    for r in recs:
        first.setdefault(r["frame"], r)
    expected_total = found_total = false_total = 0
    lines = []
    for loc in sorted({f.rsplit("_", 1)[0] for f in first}):
        frames = [f"{loc}_{i:02d}" for i in SCAN_VIEWS if f"{loc}_{i:02d}" in first]
        expected, found, false_heads = set(), set(), []
        for f in frames:
            yaw = GT[f]["pose"]["yaw_deg"]
            for k, v in visible_elements(f).items():
                if relevant_passage(k, v):
                    expected.add(k)
            for box, kind, _ in detections(first[f]):
                if kind not in PASSABLE_KINDS:
                    continue
                eid = match(f, box)
                if element_type(eid) == "passage":
                    found.add(eid)
                else:
                    heading = wrap(yaw + bearing_of_x((box[0] + box[2]) / 2))
                    if not any(abs(wrap(heading - h)) <= CLUSTER_DEG for h in false_heads):
                        false_heads.append(heading)
        relevant_found = found & expected
        expected_total += len(expected)
        found_total += len(relevant_found)
        false_total += len(false_heads)
        lines.append(f"  {loc:8s} passages {len(relevant_found)}/{len(expected)} {sorted(relevant_found) or ''} "
                     f"other found {sorted(found - expected) or '-'}; false open exits {len(false_heads)}")
    print(f"search turn ({len(SCAN_VIEWS)} views ~90 deg apart): passages found {found_total}/{expected_total}, false open exits {false_total}")
    print("\n".join(lines))


def show_truth():
    for frame in sorted(GT):
        vis = visible_elements(frame)
        items = [f"{k}({v['bmin']:+.0f}..{v['bmax']:+.0f} @{v['dist']:.1f}m)" for k, v in vis.items() if v["type"] in ("passage", "glass")]
        if items:
            print(f"{frame:11s} " + "  ".join(items))


if __name__ == "__main__":
    if sys.argv[1:] == ["--truth"]:
        show_truth()
    for cfg in sys.argv[1:]:
        if cfg != "--truth":
            score(cfg)
