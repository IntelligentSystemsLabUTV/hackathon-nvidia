"""Evaluate VLM-only target localization on the captured frames.

Usage: python eval_vlm.py <config> [<config> ...]   (configs defined in CONFIGS)
Writes results/vlm/<config>.jsonl (one line per query) and prints a summary.
"""
import base64
import io
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
client = OpenAI(
    base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
    api_key=os.environ["NEBIUS_API_KEY"],
    timeout=120.0,
    max_retries=2,
)

HFOV = 110.0
DW, DH = 672, 376
GT = json.load(open(os.path.join(HERE, "data", "gt.json")))

TARGETS = ["refrigerator", "bed", "sofa", "television", "dining table", "chair", "wardrobe", "fitness machine",
           "barbell", "trash can", "nightstand", "desk", "front door", "shoe rack", "coffee table"]
POS_MIN_PX = 120  # depth-image pixels (672x376) for a target to count as visible

SYSTEM = ("You are the visual perception component of an indoor quadruped robot. Describe only visible evidence. "
          "Do not issue commands or invent distances. Return JSON only.")
SIMILAR = "Report visible=true only for that object itself, not for a similar one (a sofa is not a bed, a cabinet is not a refrigerator). "
SUMMARY = '"summary": string (one or two sentences: layout, obstacles, free space, openings)'

NO_THINK = {
    "moonshotai/Kimi-K2.6": {"chat_template_kwargs": {"thinking": False}},
    "moonshotai/Kimi-K3": {"reasoning_effort": "none"},
    "deepseek-ai/DeepSeek-V4.1-Flash": {"reasoning_effort": "none"},
    "Qwen/Qwen3.8-27B": {"chat_template_kwargs": {"enable_thinking": False}},
}

AREAS = ["bedroom", "living room", "kitchen", "dining room", "gym", "hallway", "office", "bathroom", "other"]

GRID_COLS = 9
GRID_ROWS_LETTERS = "ABCDE"


def bearing(xn):
    half = math.tan(math.radians(HFOV / 2))
    return -math.degrees(math.atan((xn - 0.5) * 2 * half))


def font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def encode(img, quality=80):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def frame_image(name, width, overlay):
    im = Image.open(os.path.join(HERE, "data", "frames", f"{name}.png")).convert("RGB")
    h = round(width * im.height / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    w = width
    d = ImageDraw.Draw(im)
    if overlay == "cols9":
        # replica of perception.ts toVisionJpeg(grid=true), scaled to the width
        s = w / 768
        f = font(round(22 * s))
        for i in range(GRID_COLUMNS_9):
            x = i * w / GRID_COLUMNS_9
            if i > 0:
                d.line([(x, 0), (x, h)], fill=(0, 160, 255), width=max(2, round(2 * s)))
            d.text((x + w / GRID_COLUMNS_9 / 2, round(26 * s)), str(i + 1), fill=(0, 80, 255), font=f, anchor="ms")
    elif overlay == "grid":
        s = w / 768
        f = font(round(18 * s))
        rows = len(GRID_ROWS_LETTERS)
        for i in range(1, GRID_COLS):
            x = i * w / GRID_COLS
            d.line([(x, 0), (x, h)], fill=(0, 160, 255), width=max(2, round(2 * s)))
        for j in range(1, rows):
            y = j * h / rows
            d.line([(0, y), (w, y)], fill=(0, 160, 255), width=max(2, round(2 * s)))
        for j in range(rows):
            for i in range(GRID_COLS):
                d.text((i * w / GRID_COLS + 4 * s, j * h / rows + 3 * s), f"{GRID_ROWS_LETTERS[j]}{i + 1}", fill=(0, 80, 255), font=f)
    return im, encode(im)


GRID_COLUMNS_9 = 9


def build_prompt(variant, target, goal, size=(0, 0)):
    if variant == "cols9":
        text = (f"Robot goal: {goal}. The image is split by blue lines into {GRID_COLUMNS_9} numbered columns (1 = far left, {GRID_COLUMNS_9} = far right). "
                f'Look for: "{target}". Report the column containing its centre, or visible=false if it is not in view. ' + SIMILAR +
                "Schema: {" + SUMMARY + f', "target": {{"visible": boolean, "column": integer 1-{GRID_COLUMNS_9} or null, "apparent_size": "tiny"|"small"|"medium"|"large"|"very_large"|null}}}}')
    elif variant == "grid":
        text = (f"Robot goal: {goal}. The image is split by blue lines into a grid: columns 1-{GRID_COLS} from left to right and rows "
                f"{GRID_ROWS_LETTERS[0]}-{GRID_ROWS_LETTERS[-1]} from top to bottom; each cell is labelled (e.g. B3 = row B, column 3). "
                f'Look for: "{target}". If it is visible, report the cells it covers as the first and last column and the first and last row. ' + SIMILAR +
                "Schema: {" + SUMMARY + f', "target": {{"visible": boolean, "columns": [first, last] or null, "rows": [first_letter, last_letter] or null}}}}')
    elif variant == "bbox":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR +
                "If it is visible, give its bounding box [x1, y1, x2, y2] in coordinates normalized to 0-1000 "
                "(0,0 = top-left corner of the image, 1000,1000 = bottom-right corner). If several are visible, give the nearest one. "
                "Schema: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}}')
    elif variant == "point":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR +
                "If it is visible, give one point [x, y] on the object itself, at the centre of its visible part, in coordinates "
                "normalized to 0-1000 (0,0 = top-left corner of the image, 1000,1000 = bottom-right corner). If several are visible, give the nearest one. "
                "Schema: {" + SUMMARY + ', "target": {"visible": boolean, "point": [x, y] or null}}')
    elif variant == "bboxpx":
        w, h = size
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR +
                f"If it is visible, give its bounding box [x1, y1, x2, y2] in pixel coordinates of this {w}x{h} image "
                f"(x from 0 at the left edge to {w} at the right edge, y from 0 at the top edge to {h} at the bottom edge). "
                "If several are visible, give the nearest one. "
                "Schema: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}}')
    elif variant == "bboxunit":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR +
                "If it is visible, give its bounding box [x1, y1, x2, y2] as fractions of the image width and height "
                "(0.0 = left/top edge, 1.0 = right/bottom edge), e.g. [0.12, 0.40, 0.25, 0.61]. If several are visible, give the nearest one. "
                "Schema: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}}')
    elif variant == "final":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR + "If several are visible, give the nearest one. "
                "Coordinates are fractions of the image width and height: 0.0 = left/top edge, 1.0 = right/bottom edge "
                "(e.g. [0.12, 0.40, 0.25, 0.61]). "
                "Return JSON: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}, '
                '"doorways": [[x1, y1, x2, y2], ...] (interior doorways, open doors or corridors leading to another room of the house; '
                "not windows, glass walls or doors to the outside; [] if none)}")
    elif variant == "finalocc":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR + "If several are visible, give the nearest one. "
                "Coordinates are fractions of the image width and height: 0.0 = left/top edge, 1.0 = right/bottom edge "
                "(e.g. [0.12, 0.40, 0.25, 0.61]). "
                "Return JSON: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null, '
                '"occluded": boolean (true if a closer object hides part of the target or stands between the robot and the target)}, '
                '"doorways": [[x1, y1, x2, y2], ...] (interior doorways, open doors or corridors leading to another room of the house; '
                "not windows, glass walls or doors to the outside; [] if none)}")
    elif variant == "graph":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR + "If several are visible, give the nearest one. "
                "Coordinates are fractions of the image width and height: 0.0 = left/top edge, 1.0 = right/bottom edge "
                "(e.g. [0.12, 0.40, 0.25, 0.61]). "
                "Return JSON: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}, '
                f'"area": the kind of room or area the robot is in ({", ".join(AREAS)}), '
                '"openings": [{"bbox": [x1, y1, x2, y2], "kind": "open"|"glass"|"closed"|"window"|"outside", "leads_to": string}, ...] '
                "(every doorway, passage, corridor, glass door, glass wall and window in view. kind: open = the robot could walk "
                "through it now (open doorway, corridor, passage to another area); glass = glass door or glass wall, even if you see "
                "a room through it; closed = closed door; window = window; outside = door to the outside. leads_to: the room or area "
                "beyond it, in a few words. [] if none)}")
    elif variant == "exits":
        text = (f"Robot goal: {goal}. " f'Look for: "{target}". ' + SIMILAR + "If several are visible, give the nearest one. "
                "Coordinates are fractions of the image width and height: 0.0 = left/top edge, 1.0 = right/bottom edge "
                "(e.g. [0.12, 0.40, 0.25, 0.61]). "
                "Return JSON: {" + SUMMARY + ', "target": {"visible": boolean, "bbox": [x1, y1, x2, y2] or null}, '
                '"openings": [{"bbox": [x1, y1, x2, y2], "kind": "open"|"glass"|"closed"}, ...] '
                "(doorways, passages and corridors to another room or area, and glass doors or glass walls. kind: open = the robot "
                "could walk through it now; glass = glass door or glass wall, even if a room shows through it; closed = closed door. "
                "Ignore windows and doors to the outside. [] if none)}")
    elif variant == "cols9s":
        return build_prompt("cols9", target, goal, size)
    else:
        raise ValueError(variant)
    return text


CONFIGS = {
    # name: (model, variant, width)
    "minicpm_cols9_768": ("openbmb/MiniCPM-V-4_5", "cols9", 768),
    "minicpm_grid_768": ("openbmb/MiniCPM-V-4_5", "grid", 768),
    "minicpm_grid_1344": ("openbmb/MiniCPM-V-4_5", "grid", 1344),
    "minicpm_bbox_768": ("openbmb/MiniCPM-V-4_5", "bbox", 768),
    "minicpm_bbox_1344": ("openbmb/MiniCPM-V-4_5", "bbox", 1344),
    "minicpm_point_1344": ("openbmb/MiniCPM-V-4_5", "point", 1344),
    "minicpm_cols9_1344": ("openbmb/MiniCPM-V-4_5", "cols9", 1344),
    "kimi26_bbox_768": ("moonshotai/Kimi-K2.6", "bbox", 768),
    "kimi26_bbox_1280": ("moonshotai/Kimi-K2.6", "bbox", 1280),
    "kimi26_point_1280": ("moonshotai/Kimi-K2.6", "point", 1280),
    "kimi26_cols9_768": ("moonshotai/Kimi-K2.6", "cols9", 768),
    "kimi3_bbox_1280": ("moonshotai/Kimi-K3", "bbox", 1280),
    "dsv41_bbox_768": ("deepseek-ai/DeepSeek-V4.1-Flash", "bbox", 768),
    "dsv41_bbox_1280": ("deepseek-ai/DeepSeek-V4.1-Flash", "bbox", 1280),
    "gemma3_bbox_1280": ("google/gemma-3-27b-it", "bbox", 1280),
    "kimi26_bboxpx_1280": ("moonshotai/Kimi-K2.6", "bboxpx", 1280),
    "kimi26_bboxunit_1280": ("moonshotai/Kimi-K2.6", "bboxunit", 1280),
    "dsv41_bboxpx_1280": ("deepseek-ai/DeepSeek-V4.1-Flash", "bboxpx", 1280),
    "kimi26_bboxpx_1920": ("moonshotai/Kimi-K2.6", "bboxpx", 1920),
    "kimi26_bboxunit_768": ("moonshotai/Kimi-K2.6", "bboxunit", 768),
    "kimi26_bboxunit_1024": ("moonshotai/Kimi-K2.6", "bboxunit", 1024),
    "kimi26_bboxunit_1920": ("moonshotai/Kimi-K2.6", "bboxunit", 1920),
    "dsv41_bboxunit_1280": ("deepseek-ai/DeepSeek-V4.1-Flash", "bboxunit", 1280),
    "kimi26_final_1024": ("moonshotai/Kimi-K2.6", "final", 1024),
    "minicpm_cols9s_768": ("openbmb/MiniCPM-V-4_5", "cols9s", 768),
    "kimi26_finalocc_1024": ("moonshotai/Kimi-K2.6", "finalocc", 1024),
    "kimi26_graph_1024": ("moonshotai/Kimi-K2.6", "graph", 1024),
    "kimi26_exits_1024": ("moonshotai/Kimi-K2.6", "exits", 1024),
    "dsv41_bbox_1920": ("deepseek-ai/DeepSeek-V4.1-Flash", "bbox", 1920),
    "minicpm_bboxpx_1344": ("openbmb/MiniCPM-V-4_5", "bboxpx", 1344),
}


def queries():
    """Deterministic list of (frame, target, is_positive)."""
    out = []
    names = sorted(GT)
    for k, name in enumerate(names):
        objs = GT[name]["objects"]
        px = {}
        for o in objs:
            if o["category"] in TARGETS:
                px[o["category"]] = max(px.get(o["category"], 0), o.get("visible_px", 0) if o.get("visible_box") else 0)
        pos = sorted([c for c, p in px.items() if p >= POS_MIN_PX], key=lambda c: -px[c])
        chosen = []
        if pos:
            chosen.append(pos[0])  # most visible
            if len(pos) > 1:
                chosen.append(pos[-1])  # least visible (small / far) above threshold
            if len(pos) > 2:
                chosen.append(pos[len(pos) // 2])
        for c in chosen:
            out.append((name, c, True))
        absent = [c for c in TARGETS if px.get(c, 0) == 0]
        if absent:
            out.append((name, absent[(k * 7) % len(absent)], False))
    return out


def parse_json(text):
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.I)
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.I).strip()
    end = cleaned.rfind("}")
    start = cleaned.find("{")
    while start >= 0 and start < end:
        try:
            v = json.loads(cleaned[start:end + 1])
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            pass
        start = cleaned.find("{", start + 1)
    return None


def to_norm(vals, w, h):
    """0-1000 normalized -> 0-1; values above 1000 are taken as pixels of the sent image."""
    vals = [float(v) for v in vals]
    if any(v > 1000.5 for v in vals):
        if len(vals) == 4:
            return [vals[0] / w, vals[1] / h, vals[2] / w, vals[3] / h], "px"
        return [vals[0] / w, vals[1] / h], "px"
    if all(0 <= v <= 1.0 for v in vals) and any(v > 0 for v in vals) and max(vals) <= 1.0:
        return vals, "unit"
    return [v / 1000 for v in vals], "k"


FINAL_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "target": {"type": "object", "properties": {"visible": {"type": "boolean"},
               "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "null"}]}},
               "required": ["visible", "bbox"], "additionalProperties": False},
    "doorways": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}}},
    "required": ["summary", "target", "doorways"], "additionalProperties": False}
COLS_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "target": {"type": "object", "properties": {"visible": {"type": "boolean"},
               "column": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 9}, {"type": "null"}]},
               "apparent_size": {"anyOf": [{"type": "string", "enum": ["tiny", "small", "medium", "large", "very_large"]}, {"type": "null"}]}},
               "required": ["visible", "column", "apparent_size"], "additionalProperties": False}},
    "required": ["summary", "target"], "additionalProperties": False}
import copy as _copy
FINALOCC_SCHEMA = _copy.deepcopy(FINAL_SCHEMA)
FINALOCC_SCHEMA["properties"]["target"]["properties"]["occluded"] = {"type": "boolean"}
FINALOCC_SCHEMA["properties"]["target"]["required"] = ["visible", "bbox", "occluded"]
GRAPH_SCHEMA = _copy.deepcopy(FINAL_SCHEMA)
del GRAPH_SCHEMA["properties"]["doorways"]
GRAPH_SCHEMA["properties"]["area"] = {"type": "string", "enum": AREAS}
GRAPH_SCHEMA["properties"]["openings"] = {"type": "array", "items": {"type": "object", "properties": {
    "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
    "kind": {"type": "string", "enum": ["open", "glass", "closed", "window", "outside"]},
    "leads_to": {"type": "string"}}, "required": ["bbox", "kind", "leads_to"], "additionalProperties": False}}
GRAPH_SCHEMA["required"] = ["summary", "target", "area", "openings"]
EXITS_SCHEMA = _copy.deepcopy(GRAPH_SCHEMA)
del EXITS_SCHEMA["properties"]["area"]
EXITS_SCHEMA["properties"]["openings"]["items"]["properties"] = {
    "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
    "kind": {"type": "string", "enum": ["open", "glass", "closed"]}}
EXITS_SCHEMA["properties"]["openings"]["items"]["required"] = ["bbox", "kind"]
EXITS_SCHEMA["required"] = ["summary", "target", "openings"]
STRUCTURED = {"final": FINAL_SCHEMA, "cols9s": COLS_SCHEMA, "finalocc": FINALOCC_SCHEMA, "graph": GRAPH_SCHEMA, "exits": EXITS_SCHEMA}


def run_one(cfg, q):
    model, variant, width = CONFIGS[cfg]
    name, target, positive = q
    im, url = frame_image(name, width, "cols9" if variant in ("cols9", "cols9s") else ("grid" if variant == "grid" else None))
    goal = f"find the {target} and go near it"
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": build_prompt(variant, target, goal, (im.width, im.height))},
                                         {"type": "image_url", "image_url": {"url": url}}]}]
    t0 = time.monotonic()
    err = None
    content = ""
    usage = None
    try:
        kw = {}
        if variant in STRUCTURED:
            kw["response_format"] = {"type": "json_schema", "json_schema": {"name": "observation", "schema": STRUCTURED[variant], "strict": True}}
        r = client.chat.completions.create(model=model, temperature=0, max_tokens=800 if variant == "graph" else 500, messages=msgs,
                                           extra_body=NO_THINK.get(model, {}), **kw)
        content = r.choices[0].message.content or ""
        usage = [r.usage.prompt_tokens, r.usage.completion_tokens] if r.usage else None
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    dt = time.monotonic() - t0
    parsed = parse_json(content)
    t = (parsed or {}).get("target") or {}
    if parsed and variant in ("final", "finalocc"):
        dw = parsed.get("doorways")
        content_doors = dw if isinstance(dw, list) else None
    else:
        content_doors = None
    openings = parsed.get("openings") if parsed and variant in ("graph", "exits") and isinstance(parsed.get("openings"), list) else None
    rec = {"doorways": content_doors, "cfg": cfg, "frame": name, "target": target, "positive": positive, "latency": round(dt, 2), "usage": usage,
           "error": err, "raw": content[-600:], "visible": t.get("visible") is True, "parse_ok": parsed is not None,
           "size": [im.width, im.height], "occluded": t.get("occluded"),
           "area": (parsed or {}).get("area") if variant == "graph" else None, "openings": openings}
    w, h = im.width, im.height
    if rec["visible"]:
        try:
            if variant in ("cols9", "cols9s"):
                c = int(t.get("column"))
                if 1 <= c <= GRID_COLUMNS_9:
                    rec["box"] = [(c - 1) / GRID_COLUMNS_9, 0.3, c / GRID_COLUMNS_9, 0.55]
                    rec["cx"] = (c - 0.5) / GRID_COLUMNS_9
                    rec["cy"] = None
                    rec["apparent_size"] = t.get("apparent_size")
            elif variant == "grid":
                cols = t.get("columns")
                rows = t.get("rows")
                c0, c1 = int(cols[0]), int(cols[-1])
                r0 = GRID_ROWS_LETTERS.index(str(rows[0]).strip().upper()[0])
                r1 = GRID_ROWS_LETTERS.index(str(rows[-1]).strip().upper()[0])
                c0, c1 = min(c0, c1), max(c0, c1)
                r0, r1 = min(r0, r1), max(r0, r1)
                nr = len(GRID_ROWS_LETTERS)
                rec["box"] = [(c0 - 1) / GRID_COLS, r0 / nr, c1 / GRID_COLS, (r1 + 1) / nr]
            elif variant == "bboxpx":
                b = [float(v) for v in t.get("bbox")]
                b = [b[0] / w, b[1] / h, b[2] / w, b[3] / h]
                conv = "px"
                x0, y0, x1, y1 = b
                rec["box"] = [max(0, min(x0, x1)), max(0, min(y0, y1)), min(1, max(x0, x1)), min(1, max(y0, y1))]
                rec["conv"] = conv
            elif variant in ("bboxunit", "final", "finalocc", "graph", "exits"):
                b = [float(v) for v in t.get("bbox")]
                conv = "unit" if max(b) <= 1.0 else "k"
                if conv == "k":
                    b = [v / 1000 for v in b]
                x0, y0, x1, y1 = b
                rec["box"] = [max(0, min(x0, x1)), max(0, min(y0, y1)), min(1, max(x0, x1)), min(1, max(y0, y1))]
                rec["conv"] = conv
            elif variant == "bbox":
                b, conv = to_norm(t.get("bbox"), w, h)
                x0, y0, x1, y1 = b
                rec["box"] = [max(0, min(x0, x1)), max(0, min(y0, y1)), min(1, max(x0, x1)), min(1, max(y0, y1))]
                rec["conv"] = conv
            elif variant == "point":
                p, conv = to_norm(t.get("point"), w, h)
                rec["point"] = [min(1, max(0, p[0])), min(1, max(0, p[1]))]
                rec["cx"], rec["cy"] = rec["point"]
                rec["conv"] = conv
            if "box" in rec and "cx" not in rec:
                rec["cx"] = (rec["box"][0] + rec["box"][2]) / 2
                rec["cy"] = (rec["box"][1] + rec["box"][3]) / 2
        except Exception as e:  # noqa: BLE001
            rec["loc_error"] = str(e)[:120]
    return rec


def main():
    cfgs = sys.argv[1:]
    os.makedirs(os.path.join(HERE, "results", "vlm"), exist_ok=True)
    qs = queries()
    print(f"{len(qs)} queries ({sum(1 for q in qs if q[2])} positive)", flush=True)
    for cfg in cfgs:
        path = os.path.join(HERE, "results", "vlm", f"{cfg}.jsonl")
        done = set()
        if os.path.exists(path):
            for line in open(path):
                r = json.loads(line)
                if not r.get("error"):
                    done.add((r["frame"], r["target"]))
        todo = [q for q in qs if (q[0], q[1]) not in done]
        workers = 4
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as ex, open(path, "a") as f:
            for rec in ex.map(lambda q: run_one(cfg, q), todo):
                f.write(json.dumps(rec) + "\n")
                f.flush()
        print(f"{cfg}: {len(todo)} queries in {time.monotonic() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
