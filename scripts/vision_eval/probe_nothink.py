"""Try to disable reasoning on the vision-capable models and measure latency/accuracy."""
import base64
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor

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

VARIANTS = {
    "ctk_enable_thinking_false": {"chat_template_kwargs": {"enable_thinking": False}},
    "ctk_thinking_false": {"chat_template_kwargs": {"thinking": False}},
    "thinking_disabled": {"thinking": {"type": "disabled"}},
    "reasoning_effort_none": {"reasoning_effort": "none"},
    "reasoning_effort_low": {"reasoning_effort": "low"},
}

MODELS = [
    "Qwen/Qwen3.8-27B",
    "moonshotai/Kimi-K3",
    "moonshotai/Kimi-K2.6",
    "zai-org/GLM-5.3-Flash",
    "deepseek-ai/DeepSeek-V4.1-Flash",
]


def run(args):
    model, vname = args
    extra = VARIANTS[vname]
    t0 = time.monotonic()
    try:
        r = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=1500,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ]}],
            extra_body=extra,
        )
        m = r.choices[0].message
        txt = (m.content or "").strip().replace("\n", " ")
        reasoning = getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None)
        u = r.usage
        return f"{model} [{vname}] {time.monotonic()-t0:.1f}s in={u.prompt_tokens} out={u.completion_tokens} reasoning={'yes' if reasoning else 'no'} -> {txt[-160:]}"
    except Exception as e:  # noqa: BLE001
        return f"{model} [{vname}] {time.monotonic()-t0:.1f}s ERROR {str(e)[:160]}"


jobs = [(m, v) for m in MODELS for v in VARIANTS]
with ThreadPoolExecutor(max_workers=8) as ex:
    for line in ex.map(run, jobs):
        print(line, flush=True)
print("truth bbox_1000 = [703, 264, 797, 431]")
