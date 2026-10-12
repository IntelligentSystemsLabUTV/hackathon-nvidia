"""Sequential (no concurrency) latency on real frames for the final candidates, with/without json_schema."""
import importlib.util, json, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ev", os.path.join(HERE, "eval_vlm.py")); ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
qs = ev.queries()[::9][:20]
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}, "target": {"type": "object", "properties": {
    "visible": {"type": "boolean"}, "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "null"}]}},
    "required": ["visible", "bbox"]}}, "required": ["summary", "target"]}
def run(cfg, structured):
    model, variant, width = ev.CONFIGS[cfg]
    lat, ok = [], 0
    for (name, target, pos) in qs:
        im, url = ev.frame_image(name, width, variant if variant in ("cols9", "grid") else None)
        msgs = [{"role": "system", "content": ev.SYSTEM}, {"role": "user", "content": [
            {"type": "text", "text": ev.build_prompt(variant, target, f"find the {target} and go near it", (im.width, im.height))},
            {"type": "image_url", "image_url": {"url": url}}]}]
        kw = dict(model=model, temperature=0, max_tokens=400, messages=msgs, extra_body=ev.NO_THINK.get(model, {}))
        if structured:
            kw["response_format"] = {"type": "json_schema", "json_schema": {"name": "observation", "schema": SCHEMA, "strict": True}}
        t0 = time.monotonic()
        r = ev.client.chat.completions.create(**kw)
        lat.append(time.monotonic() - t0)
        ok += ev.parse_json(r.choices[0].message.content or "") is not None
    print(f"{cfg:22s} structured={structured!s:5s} n={len(lat)} median={np.median(lat):.2f}s p90={np.percentile(lat,90):.2f}s max={max(lat):.2f}s parse_ok={ok}/{len(lat)}", flush=True)
for cfg, st in [("minicpm_cols9_768", False), ("kimi26_bboxunit_768", False), ("kimi26_bboxunit_1024", False), ("kimi26_bboxunit_1024", True), ("kimi26_bboxunit_1280", False)]:
    run(cfg, st)
