#!/usr/bin/env python3
"""Render one sticker prompt with xAI grok-imagine-image.

Usage:
    python scripts/render_prompt.py "die-cut sticker of a cat" -o sticker.png

Reads XAI_API_KEY. Optional XAI_IMAGE_MODEL overrides grok-imagine-image.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from merchandise_discovery.infrastructure.providers.image_provider import (
    ImageGenerationRequest,
    XAIImageProvider,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one prompt with xAI.")
    parser.add_argument("prompt", help="The full image prompt.")
    parser.add_argument("-o", "--output", default="sticker.png", help="PNG path to write.")
    args = parser.parse_args()
    key = (os.getenv("XAI_API_KEY") or "").strip()
    if not key:
        print("XAI_API_KEY is not set.", file=sys.stderr)
        return 1
    model = (os.getenv("XAI_IMAGE_MODEL") or "grok-imagine-image").strip()
    image = XAIImageProvider(key, model).generate(
        ImageGenerationRequest(
            concept_id="render-prompt",
            brief_id="render-prompt",
            prompt=args.prompt,
            variant_number=1,
        )
    )
    request = Request(image.source_url, headers={"User-Agent": "render-prompt/1"})
    with urlopen(request, timeout=120) as response:
        payload = response.read()
    path = Path(args.output)
    path.write_bytes(payload)
    print(f"Wrote {path} ({len(payload)} bytes) with {model}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
