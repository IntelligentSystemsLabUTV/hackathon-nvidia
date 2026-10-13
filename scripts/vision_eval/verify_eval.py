"""Crop check of a sighting ("is this the target?"): the agent's prompt against a name-first one.

In closed loop the crop check confirmed a sofa as a bed (twice) and a coffee table as a desk.
The agent's prompt asks for {"match", "reason"}: the model answers before reasoning. The
name-first prompt makes it name the object first (JSON schema: object, reason, match).

Crops are cut like perception.ts verifyCandidate (box padded by 30%, at least 48 px, 384 px JPEG)
from the house frames, around ground-truth boxes (data/gt.json). Each target is asked on crops of
the target itself and of objects that look alike.

Usage: python verify_eval.py [variant ...]   (variants: current, name_first, name_part; default all)
"""
import base64
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, "..", "..", ".env"))
client = OpenAI(base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
                api_key=os.environ["NEBIUS_API_KEY"])
MODEL = os.getenv("NEBIUS_VISION_MODEL", "moonshotai/Kimi-K2.6")

# target -> (category of the target, categories that look alike)
CASES = {
    "bed": ("bed", ["sofa"]),
    "sofa": ("sofa", ["bed"]),
    "desk": ("desk", ["coffee table", "dining table", "small round table", "TV cabinet"]),
    "refrigerator": ("refrigerator", ["kitchen cabinet"]),
    "wardrobe": ("wardrobe", ["kitchen cabinet", "TV cabinet", "front door"]),
}
MIN_VISIBLE_FRAC = 0.3
MIN_BOX_FRAC = 0.03  # width or height of the box, fraction of the image


def crop_b64(frame, box):
    img = Image.open(os.path.join(HERE, "data", "frames", f"{frame}.png")).convert("RGB")
    w, h = img.size
    x0, y0, x1, y1 = box
    pad_x = max(48, (x1 - x0) * w * 0.3)
    pad_y = max(48, (y1 - y0) * h * 0.3)
    left, top = max(0, int(x0 * w - pad_x)), max(0, int(y0 * h - pad_y))
    right, bottom = min(w, int(x1 * w + pad_x + 0.999)), min(h, int(y1 * h + pad_y + 0.999))
    c = img.crop((left, top, right, bottom))
    c.thumbnail((384, 384))
    buf = io.BytesIO()
    c.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def ask(variant, target, b64):
    if variant == "current":
        text = (f"Is the main object in this crop a {target}? A similar object is not a match "
                '(a sofa is not a bed, a cabinet is not a refrigerator). Return JSON only: {"match": boolean, "reason": string}')
        extra = {}
    else:
        part = f" or a part of one (a mattress is part of a bed)" if variant == "name_part" else ""
        text = (f"Name the main object in this crop with its most specific common name, then say whether it is a {target}{part}. "
                "A similar object is not a match (a sofa is not a bed, a coffee table is not a desk, a cabinet is not a refrigerator). "
                'Return JSON: {"object": string, "reason": string, "match": boolean}')
        schema = {"type": "object", "additionalProperties": False, "required": ["object", "reason", "match"],
                  "properties": {"object": {"type": "string"}, "reason": {"type": "string"}, "match": {"type": "boolean"}}}
        extra = {"response_format": {"type": "json_schema", "json_schema": {"name": "verify", "schema": schema, "strict": True}}}
    r = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=200,
        messages=[{"role": "user", "content": [{"type": "text", "text": text},
                                               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        extra_body={"chat_template_kwargs": {"thinking": False}}, **extra)
    content = r.choices[0].message.content or ""
    try:
        s = content[content.index("{"):content.rindex("}") + 1]
        return json.loads(s)
    except ValueError:
        return {}


def main():
    variants = sys.argv[1:] or ["current", "name_first", "name_part"]
    gt = json.load(open(os.path.join(HERE, "data", "gt.json")))
    items = []
    for target, (pos, negs) in CASES.items():
        for frame, rec in gt.items():
            for o in rec.get("objects", []):
                box = o.get("visible_box")
                if not box or o.get("visible_frac", 0) < MIN_VISIBLE_FRAC or o["category"] not in [pos, *negs]:
                    continue
                if max(box[2] - box[0], box[3] - box[1]) < MIN_BOX_FRAC:
                    continue
                items.append((target, o["category"] == pos, o["category"], frame, box))
    crops = {}
    for _t, _p, _c, frame, box in items:
        crops.setdefault((frame, tuple(box)), crop_b64(frame, box))
    out_path = os.path.join(HERE, "results", "verify_eval.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "a") as out:
        for variant in variants:
            def run(item):
                target, positive, cat, frame, box = item
                return item, ask(variant, target, crops[(frame, tuple(box))])
            with ThreadPoolExecutor(6) as ex:
                results = list(ex.map(run, items))
            stats = {}
            for (target, positive, cat, frame, box), ans in results:
                out.write(json.dumps({"variant": variant, "target": target, "category": cat, "frame": frame,
                                      "positive": positive, "answer": ans}) + "\n")
                s = stats.setdefault(target, {"tp": 0, "pos": 0, "fp": 0, "neg": 0})
                match = ans.get("match") is True
                if positive:
                    s["pos"] += 1
                    s["tp"] += match
                else:
                    s["neg"] += 1
                    s["fp"] += match
            tot = {k: sum(s[k] for s in stats.values()) for k in ("tp", "pos", "fp", "neg")}
            print(f"\n{variant}: target confirmed {tot['tp']}/{tot['pos']}, look-alike confirmed {tot['fp']}/{tot['neg']}")
            for target, s in stats.items():
                print(f"  {target:13s} target {s['tp']:2d}/{s['pos']:2d}   look-alike {s['fp']:2d}/{s['neg']:2d}")


if __name__ == "__main__":
    main()
