#!/usr/bin/env python3
"""Smoke-test image understanding through Nebius Token Factory."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "openbmb/MiniCPM-V-4_5"

SYSTEM_PROMPT = """You inspect images from an indoor mobile robot.
Describe only what is visibly supported by the image. Do not invent objects,
room identities, doors, or navigability. Return one JSON object with exactly
these fields:
{
  "scene_type": "short label or unknown",
  "objects": ["visible object"],
  "transitions": [
    {"type": "doorway or opening", "image_region": "left|center|right", "confidence": "low|medium|high"}
  ],
  "needs_more_evidence": true,
  "suggested_observation": "brief description of what to inspect next"
}
Return JSON only, without Markdown fences.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one local image to an NVIDIA vision model on Nebius Token Factory."
    )
    parser.add_argument("image", nargs="?", type=Path, help="JPEG, PNG or WebP image")
    parser.add_argument(
        "--model",
        default=None,
        help="Override NEBIUS_VISION_MODEL (default: openbmb/MiniCPM-V-4_5)",
    )
    parser.add_argument(
        "--prompt",
        default="Inspect this robot-camera image and describe the environment.",
        help="Question sent with the image",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List every model ID visible to the API key and exit",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="With --list-models, show only IDs containing this text",
    )
    return parser.parse_args()


def make_client() -> OpenAI:
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            f"NEBIUS_API_KEY is empty. Insert the key in {REPO_ROOT / '.env'}."
        )
    return OpenAI(
        base_url=os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
        timeout=60.0,
        max_retries=1,
    )


def image_data_url(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Image does not exist: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Supported formats: JPEG, PNG and WebP")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def list_models(client: OpenAI, needle: str | None = None) -> None:
    model_ids = sorted(model.id for model in client.models.list().data)
    for model_id in model_ids:
        if needle is None or needle.lower() in model_id.lower():
            print(model_id)


def inspect_image(client: OpenAI, image: Path, model: str, prompt: str) -> None:
    started = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url(image)},
                    },
                ],
            },
        ],
        temperature=0,
        max_tokens=600,
    )
    elapsed = time.monotonic() - started
    content = response.choices[0].message.content or ""

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        print(content)
        raise RuntimeError("The model response was not valid JSON") from None

    print(json.dumps(parsed, indent=2, ensure_ascii=False))
    print(
        f"\nmodel={model} latency_seconds={elapsed:.2f} request_id={response.id}",
        file=sys.stderr,
    )


def main() -> int:
    args = parse_args()
    try:
        client = make_client()
        if args.list_models:
            list_models(client, args.filter)
            return 0
        if args.image is None:
            raise ValueError("Pass an image path, or use --list-models")
        model = args.model or os.getenv("NEBIUS_VISION_MODEL", DEFAULT_MODEL)
        inspect_image(client, args.image, model, args.prompt)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
