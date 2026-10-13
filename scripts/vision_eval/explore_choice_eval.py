"""Which way to explore after a full search turn without the target?

For each capture location (4 views ~90 deg apart, as in the robot's search turn) and each
target category that lies only in other zones, the correct view is the one facing the first
passage of the route to the target (house_topology.json, evaluation only). Compared:
  - llm: the reasoning model picks a view from the scene summaries and open exits of the views;
  - exits: a view with an open exit (the most open one), else the most open view;
  - open: the most open view (front clearance from depth), the rule without doorways;
  - chance: 1 / number of views.

Usage: python explore_choice_eval.py [<vlm cfg with openings>]   (default kimi26_exits_1024)
Writes results/explore_choice_<cfg>.jsonl.
"""
import json
import math
import os
import re
import sys
from collections import deque

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

import topo_eval as T

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, "..", "..", ".env"))
client = OpenAI(base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
                api_key=os.environ["NEBIUS_API_KEY"], timeout=60.0, max_retries=2)
MODEL = os.getenv("NEBIUS_REASONING_MODEL", "nvidia/Nemotron-3_5-Lightning")
CFG = sys.argv[1] if len(sys.argv) > 1 else "kimi26_exits_1024"
SCAN_VIEWS = T.SCAN_VIEWS
FRONT_ROI = (0.4, 0.25, 0.6, 0.5)
TARGETS = ["bed", "wardrobe", "desk", "nightstand", "refrigerator", "dining table", "front door", "shoe rack",
           "sofa", "television", "fitness machine", "barbell", "coffee table", "chair", "trash can"]


def in_poly(x, y, poly):
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def zone_of(x, y):
    return next((z for z, poly in T.TOPO["zones"].items() if in_poly(x, y, poly)), None)


def object_zones():
    """category -> set of zones holding an instance, from house.world poses and gt.json categories."""
    world = open(os.path.join(T.WS, "src", "go2_sim_worlds", "worlds", "house.world")).read()
    pos = {}
    for m in re.finditer(r"<include>(.*?)</include>", world, re.S):
        n, p = re.search(r"<name>(.*?)</name>", m.group(1)), re.search(r"<pose>(.*?)</pose>", m.group(1))
        if n and p:
            pos[n.group(1)] = [float(v) for v in p.group(1).split()[:2]]
    cats = {}
    for fr in T.GT.values():
        for o in fr["objects"]:
            cats[o["name"]] = o["category"]
    out = {}
    for name, cat in cats.items():
        if name in pos and zone_of(*pos[name]):
            out.setdefault(cat, set()).add(zone_of(*pos[name]))
    return out


def zone_routes(start):
    """BFS over passages: zone -> list of passage elements along the shortest route."""
    edges = [e for e in T.TOPO["elements"] if e["type"] == "passage"]
    routes, q = {start: []}, deque([start])
    while q:
        z = q.popleft()
        for e in edges:
            a, b = e["connects"]
            for u, v in ((a, b), (b, a)):
                if u == z and v not in routes:
                    routes[v] = routes[z] + [e]
                    q.append(v)
    return routes


def seg_dist(px, py, e):
    (ax, ay), (bx, by) = e["a"], e["b"]
    t = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / max(1e-9, (bx - ax) ** 2 + (by - ay) ** 2)))
    return math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))


def front_clearance(frame):
    v = T.np.load(os.path.join(HERE, "data", "frames", f"{frame}.depth.npy"))
    h, w = v.shape
    r = v[int(FRONT_ROI[1] * h):int(FRONT_ROI[3] * h), int(FRONT_ROI[0] * w):int(FRONT_ROI[2] * w)]
    r = r[np.isfinite(r) & (r > 0)]
    return float(np.percentile(r, 12)) if r.size else None


def parse_json(text):
    text = re.sub(r"<think>[\s\S]*?</think>", "", text or "")
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


EXPLORE_TOOL = [{"type": "function", "function": {
    "name": "explore",
    "description": "Walk toward the chosen view direction to look for the target from there.",
    "parameters": {"type": "object", "properties": {"view": {"type": "integer", "description": "view number"},
                                                    "reason": {"type": "string"}}, "required": ["view"]}}}]
SYSTEM = ("You choose where a quadruped robot explores next to find an object in a house it has no map of. Use common sense "
          "about homes: beds, wardrobes and nightstands are in bedrooms, usually behind a doorway or corridor; refrigerators "
          "in kitchens; dining tables in dining areas. Prefer a view showing an open doorway or passage toward a room that "
          "likely holds the target, or the target's room itself. Glass doors and windows cannot be walked through. "
          "Call explore with the chosen view.")


def ask_llm(target, views):
    payload = {
        "target": target,
        "note": "A full turn in place did not show the target. heading_deg is relative to the first view (positive = left).",
        "views": views,
    }
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}]
    r = client.chat.completions.create(model=MODEL, temperature=0, messages=msgs, tools=EXPLORE_TOOL,
                                       tool_choice="auto", parallel_tool_calls=False)
    msg = r.choices[0].message
    call = next((c for c in (msg.tool_calls or []) if c.type == "function"), None)
    if call is None:
        return None, (msg.content or "")[-200:]
    try:
        args = json.loads(call.function.arguments or "{}")
        return int(args["view"]), str(args.get("reason", ""))
    except (ValueError, KeyError, TypeError):
        return None, call.function.arguments[:200]


VISION_MODEL = os.getenv("NEBIUS_VISION_MODEL", "moonshotai/Kimi-K2.6")


def mosaic(frames, headings):
    """The views of the turn in a 2x2 image, each labelled with its number and relative heading."""
    from PIL import Image, ImageDraw, ImageFont
    import base64
    import io
    w, h = 768, 432
    im = Image.new("RGB", (2 * w, 2 * h))
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    for k, (f, hd) in enumerate(zip(frames, headings)):
        v = Image.open(os.path.join(HERE, "data", "frames", f"{f}.png")).convert("RGB").resize((w, h), Image.LANCZOS)
        d = ImageDraw.Draw(v)
        d.rectangle([0, 0, 250, 50], fill=(0, 0, 0))
        d.text((10, 6), f"view {k}: {hd:+d} deg", fill=(255, 255, 0), font=font)
        im.paste(v, ((k % 2) * w, (k // 2) * h))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


HINTS = {
    "base": "",
    "glass": ("A room seen through framed glass panels (glass doors or glass walls, with metal or wooden frames) is not "
              "reachable that way; an open passage shows the floor continuing into the next area. "),
    "frontier": ("A room seen through framed glass panels (glass doors or glass walls, with metal or wooden frames) is not "
                 "reachable that way; an open passage shows the floor continuing into the next area. Areas fully in view "
                 "that show no target are unlikely to hold it: prefer an open passage toward an area you cannot see from here. "),
}
HINT = os.getenv("EXPLORE_HINT", "base")


def ask_vlm(target, frames, headings, n_views):
    text = (f"The image shows the {n_views} views of a full turn in place of a quadruped robot inside a house; each view is "
            "labelled with its number and its heading relative to view 0 (positive = left). The robot is looking for: "
            f'"{target}". It is not visible in any view. Which view should the robot walk toward to find it? Think about which '
            "room each view shows and where doorways, corridors or passages lead: e.g. a bed is in a bedroom, usually reached "
            "through a doorway or corridor; a refrigerator is in the kitchen. Glass doors and windows cannot be walked through. "
            + HINTS[HINT] +
            'Return JSON: {"reason": string (one or two sentences), "view": <view number>, "x": number (horizontal position '
            "in the chosen view of the doorway, passage or free floor to walk toward, as a fraction of that view's width: "
            '0.0 = its left edge, 1.0 = its right edge)}')
    schema = {"type": "object", "properties": {"reason": {"type": "string"}, "view": {"type": "integer"}, "x": {"type": "number"}},
              "required": ["reason", "view", "x"], "additionalProperties": False}
    r = client.chat.completions.create(
        model=VISION_MODEL, temperature=0, max_tokens=500,
        response_format={"type": "json_schema", "json_schema": {"name": "choice", "schema": schema, "strict": True}},
        messages=[{"role": "user", "content": [{"type": "text", "text": text},
                                               {"type": "image_url", "image_url": {"url": mosaic(frames, headings)}}]}],
        extra_body={"chat_template_kwargs": {"thinking": False}})
    parsed = parse_json(r.choices[0].message.content or "")
    try:
        x = float(parsed["x"])
        return int(parsed["view"]), str(parsed.get("reason", "")), min(1.0, max(0.0, x))
    except (TypeError, KeyError, ValueError):
        return None, (r.choices[0].message.content or "")[:200], None


def ask_vlm2(target, frames, headings, n_views):
    """Same mosaic, but the model first lists, per view, the room and the openings with their kind, then chooses."""
    text = (f"The image shows the {n_views} views of a full turn in place of a quadruped robot inside a house; each view is "
            "labelled with its number and its heading relative to view 0 (positive = left). The robot is looking for: "
            f'"{target}". It is not visible in any view. First describe each view: the room or area it shows and every '
            "doorway, passage, corridor or glass door in it, with its horizontal position x in that view (0.0 = left edge, "
            "1.0 = right edge) and its kind: open = the robot could walk through it now, glass = glass door or glass wall "
            "(framed glass panels, even with wooden frames, are glass doors), closed = closed door. Then choose the view to walk "
            "toward to find the target, and x: an open passage or free floor in that view. Think about which room likely holds "
            "the target (e.g. a bed is in a bedroom, a refrigerator in the kitchen) and which open passage leads there. "
            "Glass doors, closed doors and windows cannot be walked through.")
    opening = {"type": "object", "properties": {"x": {"type": "number"}, "kind": {"type": "string", "enum": ["open", "glass", "closed"]}},
               "required": ["x", "kind"], "additionalProperties": False}
    schema = {"type": "object", "properties": {
        "views": {"type": "array", "items": {"type": "object", "properties": {
            "view": {"type": "integer"}, "area": {"type": "string"}, "openings": {"type": "array", "items": opening}},
            "required": ["view", "area", "openings"], "additionalProperties": False}},
        "reason": {"type": "string"}, "view": {"type": "integer"}, "x": {"type": "number"}},
        "required": ["views", "reason", "view", "x"], "additionalProperties": False}
    r = client.chat.completions.create(
        model=VISION_MODEL, temperature=0, max_tokens=900,
        response_format={"type": "json_schema", "json_schema": {"name": "choice", "schema": schema, "strict": True}},
        messages=[{"role": "user", "content": [{"type": "text", "text": text},
                                               {"type": "image_url", "image_url": {"url": mosaic(frames, headings)}}]}],
        extra_body={"chat_template_kwargs": {"thinking": False}})
    parsed = parse_json(r.choices[0].message.content or "")
    try:
        return int(parsed["view"]), str(parsed.get("reason", "")), min(1.0, max(0.0, float(parsed["x"]))), parsed.get("views")
    except (TypeError, KeyError, ValueError):
        return None, (r.choices[0].message.content or "")[:200], None, None


def occupied_walk(x, y):
    """Map obstacle for walking: walls, furniture outlines and glass doors."""
    r = T.MAP.shape[0] - 1 - int((y - T.ORIGIN[1]) / T.RES)
    c = int((x - T.ORIGIN[0]) / T.RES)
    return not (0 <= r < T.MAP.shape[0] and 0 <= c < T.MAP.shape[1]) or T.MAP[r, c] == 0


def walk_reaches(px, py, heading_deg, element, max_m=9.0):
    """True if walking straight along the heading crosses the passage before any obstacle."""
    a = math.radians(heading_deg)
    s = 0.3
    while s < max_m:
        x, y = px + s * math.cos(a), py + s * math.sin(a)
        if seg_dist(x, y, element) < 0.08:
            return True
        if occupied_walk(x, y):
            return False
        s += 0.04
    return False


INFLATE_CELLS = 4  # 0.2 m: half the robot's width
WALK_M = 2.5
MARGIN_M = 0.45
_free = None
_geo = {}


def free_grid():
    """Walkable cells: free in the map, at least INFLATE_CELLS from walls, furniture and glass."""
    global _free
    if _free is None:
        from scipy.ndimage import binary_dilation
        blocked = T.MAP != 254
        _free = ~binary_dilation(blocked, iterations=INFLATE_CELLS)
    return _free


def cell(x, y):
    return T.MAP.shape[0] - 1 - int((y - T.ORIGIN[1]) / T.RES), int((x - T.ORIGIN[0]) / T.RES)


def geodesic_to(zones):
    """Grid of walking distance (m) to the nearest walkable cell inside the zones."""
    key = tuple(sorted(zones))
    if key in _geo:
        return _geo[key]
    import heapq
    free = free_grid()
    h, w = free.shape
    dist = np.full((h, w), np.inf)
    heap = []
    for r in range(h):
        for c in range(w):
            if free[r, c]:
                x, y = T.ORIGIN[0] + (c + 0.5) * T.RES, T.ORIGIN[1] + (h - 1 - r + 0.5) * T.RES
                if any(in_poly(x, y, T.TOPO["zones"][z]) for z in zones):
                    dist[r, c] = 0
                    heap.append((0.0, r, c))
    heapq.heapify(heap)
    steps = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    while heap:
        d, r, c = heapq.heappop(heap)
        if d > dist[r, c]:
            continue
        for dr, dc, k in steps:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and free[rr, cc] and d + k * T.RES < dist[rr, cc]:
                dist[rr, cc] = d + k * T.RES
                heapq.heappush(heap, (dist[rr, cc], rr, cc))
    _geo[key] = dist
    return dist


def geo_at(dist, x, y):
    r, c = cell(x, y)
    window = dist[max(0, r - 6):r + 7, max(0, c - 6):c + 7]
    return float(window.min()) if np.isfinite(window).any() else math.inf


def walk_end(px, py, heading_deg):
    """Where a straight walk of WALK_M stops, MARGIN_M before the first obstacle (glass included)."""
    a = math.radians(heading_deg)
    s = 0.0
    while s < WALK_M + MARGIN_M:
        x, y = px + (s + 0.05) * math.cos(a), py + (s + 0.05) * math.sin(a)
        if occupied_walk(x, y):
            break
        s += 0.05
    s = max(0.0, min(WALK_M, s - MARGIN_M))
    return px + s * math.cos(a), py + s * math.sin(a)


def progress(dist, px, py, heading_deg):
    """Geodesic metres gained by the walk; an end point off the walkable grid counts as no move."""
    ex, ey = walk_end(px, py, heading_deg)
    start, end = geo_at(dist, px, py), geo_at(dist, ex, ey)
    return 0.0 if not (math.isfinite(start) and math.isfinite(end)) else start - end


def main():
    recs = {}
    for line in open(os.path.join(HERE, "results", "vlm", f"{CFG}.jsonl")):
        r = json.loads(line)
        recs.setdefault(r["frame"], r)
    zones_of = object_zones()
    out_path = os.path.join(HERE, "results", f"explore_choice_{CFG}.jsonl")
    rows = []
    for loc, zone in sorted(T.TOPO["capture_zones"].items()):
        frames = [f"{loc}_{i:02d}" for i in SCAN_VIEWS]
        pose = T.GT[frames[0]]["pose"]
        px, py, yaw0 = pose["x"], pose["y"], pose["yaw_deg"]
        routes = zone_routes(zone)
        views, clearance, exits = [], [], []
        for k, f in enumerate(frames):
            yaw = T.GT[f]["pose"]["yaw_deg"]
            r = recs[f]
            open_b = [round(T.bearing_of_x((b[0] + b[2]) / 2)) for b, kind, _ in T.detections(r) if kind == "open"]
            c = front_clearance(f)
            clearance.append(c or 0)
            exits.append(open_b)
            m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', r.get("raw", ""))
            views.append({"view": k, "heading_deg": round(T.wrap(yaw - yaw0)), "scene": m.group(1) if m else "",
                          "open_exits_bearing_deg": open_b, "front_clearance_m": round(c, 1) if c else None})
        for target in TARGETS:
            tz = zones_of.get(target)
            if not tz or zone in tz:
                continue
            dest = min((z for z in tz if z in routes), key=lambda z: len(routes[z]), default=None)
            if dest is None:
                continue
            route = routes[dest]
            first = next((e for e in route if seg_dist(px, py, e) >= 1.5), route[-1])
            mx, my = (first["a"][0] + first["b"][0]) / 2, (first["a"][1] + first["b"][1]) / 2
            heading = math.degrees(math.atan2(my - py, mx - px))
            yaws = [T.GT[f]["pose"]["yaw_deg"] for f in frames]
            correct = [k for k, y in enumerate(yaws) if abs(T.wrap(heading - y)) <= 55]
            if not correct:
                continue
            pick_open = int(np.argmax(clearance))
            with_exit = [k for k in range(len(frames)) if exits[k]]
            pick_exits = max(with_exit, key=lambda k: clearance[k]) if with_exit else pick_open
            pick_llm, reason = ask_llm(target, views)
            pick_vlm, vreason, pick_x = ask_vlm(target, frames, [v["heading_deg"] for v in views], len(frames))
            via_ok = [e for e in T.TOPO["elements"] if e["type"] == "passage" and e["id"] == first["id"]]
            walk_vlm = walk_view = walk_open = False
            if pick_vlm is not None and 0 <= pick_vlm < len(frames):
                yv = T.GT[frames[pick_vlm]]["pose"]["yaw_deg"]
                walk_vlm = any(walk_reaches(px, py, yv + T.bearing_of_x(pick_x), e) for e in via_ok)
                walk_view = any(walk_reaches(px, py, yv, e) for e in via_ok)
            walk_open = any(walk_reaches(px, py, T.GT[frames[pick_open]]["pose"]["yaw_deg"], e) for e in via_ok)
            pick_v2, v2reason, pick_x2, v2views = ask_vlm2(target, frames, [v["heading_deg"] for v in views], len(frames))
            dist = geodesic_to(tz)
            yaws_all = [T.GT[f]["pose"]["yaw_deg"] for f in frames]
            gain = {
                "vlm2_point": progress(dist, px, py, yaws_all[pick_v2] + T.bearing_of_x(pick_x2)) if pick_v2 is not None and 0 <= pick_v2 < len(frames) else 0.0,
                "vlm_point": progress(dist, px, py, yaws_all[pick_vlm] + T.bearing_of_x(pick_x)) if pick_vlm is not None and 0 <= pick_vlm < len(frames) else 0.0,
                "vlm_view": progress(dist, px, py, yaws_all[pick_vlm]) if pick_vlm is not None and 0 <= pick_vlm < len(frames) else 0.0,
                "llm_view": progress(dist, px, py, yaws_all[pick_llm]) if pick_llm is not None and 0 <= pick_llm < len(frames) else 0.0,
                "exits_view": progress(dist, px, py, yaws_all[pick_exits]),
                "open_view": progress(dist, px, py, yaws_all[pick_open]),
                "chance": float(np.mean([progress(dist, px, py, y) for y in yaws_all])),
            }
            row = {"loc": loc, "zone": zone, "target": target, "target_zones": sorted(tz), "via": first["id"],
                   "correct": correct, "llm": pick_llm, "vlm": pick_vlm, "x": pick_x, "walk_vlm": walk_vlm,
                   "walk_vlm_view_centre": walk_view, "walk_open": walk_open, "exits": pick_exits, "open": pick_open,
                   "reason": reason, "vlm_reason": vreason, "gain": gain, "vlm2": pick_v2, "x2": pick_x2,
                   "vlm2_reason": v2reason, "vlm2_views": v2views}
            rows.append(row)
            print(f"{loc:8s} {target:15s} via {first['id']:22s} correct {correct} vlm {pick_vlm} x {pick_x} walk {walk_vlm} "
                  f"(centre {walk_view}, open {walk_open}) | {vreason[:80]}", flush=True)
    with open(out_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    n = len(rows)
    for method in ("vlm2", "vlm", "llm", "exits", "open"):
        ok = sum(1 for r in rows if r[method] in r["correct"])
        print(f"{method:6s} correct {ok}/{n} ({ok / max(1, n):.0%})")
    for key in ("walk_vlm", "walk_vlm_view_centre", "walk_open"):
        ok = sum(1 for r in rows if r[key])
        print(f"{key:21s} walks through the right passage {ok}/{n} ({ok / max(1, n):.0%})")
    print(f"progress toward the target zone after one {WALK_M} m walk (geodesic m; mean, share > 0.5 m):")
    for key in ("vlm2_point", "vlm_point", "vlm_view", "llm_view", "exits_view", "open_view", "chance"):
        g = [r["gain"][key] for r in rows]
        print(f"  {key:11s} mean {np.mean(g):+.2f} m   >0.5 m: {np.mean([x > 0.5 for x in g]):.0%}   <-0.5 m: {np.mean([x < -0.5 for x in g]):.0%}")
    chance = np.mean([len(r["correct"]) / len(SCAN_VIEWS) for r in rows]) if rows else 0
    print(f"chance  {chance:.0%}")


if __name__ == "__main__":
    main()
