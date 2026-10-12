"""Sequential latency of the vision candidates with reasoning disabled (3 runs each)."""
import base64
import io
import os
import time

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
client = OpenAI(
    base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
    api_key=os.environ["NEBIUS_API_KEY"],
    timeout=120.0,
    max_retries=0,
)

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

CANDIDATES = [
    ("openbmb/MiniCPM-V-4_5", {}),
    ("google/gemma-3-27b-it", {}),
    ("moonshotai/Kimi-K3", {"reasoning_effort": "none"}),
    ("moonshotai/Kimi-K2.6", {"chat_template_kwargs": {"thinking": False}}),
    ("Qwen/Qwen3.8-27B", {"chat_template_kwargs": {"enable_thinking": False}}),
    ("deepseek-ai/DeepSeek-V4.1-Flash", {"reasoning_effort": "none"}),
]

for model, extra in CANDIDATES:
    times = []
    outs = []
    for _ in range(3):
        t0 = time.monotonic()
        try:
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=300,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": url}},
                ]}],
                extra_body=extra,
            )
            times.append(time.monotonic() - t0)
            outs.append((r.choices[0].message.content or "").strip().replace("\n", " ")[-70:])
        except Exception as e:  # noqa: BLE001
            times.append(float("nan"))
            outs.append(f"ERR {str(e)[:80]}")
    print(f"{model}: {' '.join(f'{t:.2f}s' for t in times)} | {outs[-1]}", flush=True)
