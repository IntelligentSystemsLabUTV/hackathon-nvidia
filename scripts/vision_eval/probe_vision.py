"""Probe which Nebius models accept image input, with a tiny synthetic grounding test.

Loads NEBIUS_API_KEY from the workspace .env without printing it.
"""
import base64
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
client = OpenAI(
    base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
    api_key=os.environ["NEBIUS_API_KEY"],
    timeout=90.0,
    max_retries=0,
)

# 1280x720 grey canvas: red disc centred at (960, 250) r=60, blue square at (200..320, 420..540)
img = Image.new("RGB", (1280, 720), (200, 200, 200))
d = ImageDraw.Draw(img)
d.ellipse((900, 190, 1020, 310), fill=(220, 20, 20))
d.rectangle((200, 420, 320, 540), fill=(20, 40, 220))
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=90)
url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

PROMPT = (
    "There is a red disc in this image. Return JSON only: "
    '{"bbox_1000": [x1, y1, x2, y2]} with coordinates normalized to 0-1000 '
    "(0,0 = top-left, 1000,1000 = bottom-right)."
)

models = sys.argv[1:]


def probe(model: str):
    t0 = time.monotonic()
    try:
        r = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ]}],
        )
        txt = (r.choices[0].message.content or "").strip().replace("\n", " ")
        reasoning = getattr(r.choices[0].message, "reasoning_content", None)
        u = r.usage
        return model, f"{time.monotonic()-t0:.1f}s in={u.prompt_tokens if u else '?'} out={u.completion_tokens if u else '?'} -> {txt[-300:]}" + (" [has reasoning]" if reasoning else "")
    except Exception as e:  # noqa: BLE001
        return model, f"{time.monotonic()-t0:.1f}s ERROR {type(e).__name__}: {str(e)[:200]}"


with ThreadPoolExecutor(max_workers=6) as ex:
    for model, res in ex.map(probe, models):
        print(f"{model}: {res}", flush=True)
print("truth bbox_1000 = [703, 264, 797, 431]")
