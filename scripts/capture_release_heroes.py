#!/usr/bin/env python3
"""Render hero PNGs for v0.3.0 release blog posts.

Two render modes:
  --ansi-file <path>  ANSI text → ansi2html → headless Chrome → PNG
  --url <url>         headless Chrome → PNG (for the /prompts/ landing page)

Outputs land in ``_blog/building-benchbox/images`` and are synced into
``docs/blog/images``, matching ``scripts/capture_chart_images.py`` conventions.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIMARY_OUT = ROOT / "_blog" / "building-benchbox" / "images"
SYNC_OUT_DIRS = (ROOT / "docs" / "blog" / "images",)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ background: #1a1e24; }}
  body {{
    background: #1a1e24;
    padding: 28px 32px;
    display: inline-block;
    min-width: 860px;
  }}
  pre {{
    font-family: "Fira Code", "Menlo", "JetBrains Mono", "SF Mono", "Consolas", monospace;
    font-size: 13.5px;
    line-height: 1.0;
    color: #d4d4d4;
    white-space: pre;
  }}
  .ansi1  {{ font-weight: bold; }}
  .ansi32 {{ color: #4ec9b0; }}
  .ansi33 {{ color: #e6ab02; }}
  .ansi34 {{ color: #569cd6; }}
  .ansi35 {{ color: #c586c0; }}
  .ansi36 {{ color: #4ec9b0; }}
  .ansi37 {{ color: #d4d4d4; }}
  .ansi38-5-36  {{ color: #4ec9b0; }}
  .ansi38-5-60  {{ color: #5a6478; }}
  .ansi38-5-70  {{ color: #6aaf6a; }}
  .ansi38-5-166 {{ color: #d7875f; }}
  .ansi38-5-242 {{ color: #6b7075; }}
</style>
</head>
<body>
<pre>{content}</pre>
</body>
</html>
"""


def ansi_to_html(ansi_text: str) -> str:
    from ansi2html import Ansi2HTMLConverter  # type: ignore[import]

    converter = Ansi2HTMLConverter(inline=True, scheme="ansi2html", dark_bg=True)
    return converter.convert(ansi_text, full=False)


def estimate_height(text: str, pad: int = 80) -> int:
    lines = text.count("\n") + 1
    return min(max(lines * 22 + pad * 2, 200), 2400)


def chrome_screenshot(target: str, out_path: Path, width: int, height: int) -> None:
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-web-security",
            f"--window-size={width},{height}",
            f"--screenshot={out_path}",
            "--hide-scrollbars",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=8000",
            target,
        ],
        capture_output=True,
        check=True,
    )


def render_ansi_to_png(ansi_text: str, out_path: Path, width: int = 960) -> None:
    html_body = ansi_to_html(ansi_text)
    html = HTML_TEMPLATE.format(content=html_body)
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False, encoding="utf-8") as h:
        h.write(html)
        tmp_html = h.name
    try:
        chrome_screenshot(f"file://{tmp_html}", out_path, width, estimate_height(ansi_text))
    finally:
        os.unlink(tmp_html)
    crop_to_content(out_path)


def render_url_to_png(url: str, out_path: Path, width: int = 1280, height: int = 1400) -> None:
    chrome_screenshot(url, out_path, width, height)


def crop_to_content(png_path: Path, bg=(26, 30, 36), tolerance: int = 4, pad: int = 32) -> None:
    from PIL import Image  # type: ignore[import]

    img = Image.open(png_path).convert("RGB")
    pixels = img.load()
    width, height = img.size

    def is_bg(r, g, b) -> bool:
        return abs(r - bg[0]) <= tolerance and abs(g - bg[1]) <= tolerance and abs(b - bg[2]) <= tolerance

    last_row = height - 1
    for y in range(height - 1, 0, -1):
        if not all(is_bg(*pixels[x, y]) for x in range(0, width, 4)):
            last_row = y + pad
            break

    if last_row < height:
        img = img.crop((0, 0, width, min(last_row, height)))
        img.save(png_path)


def sync(name: str) -> int:
    src = PRIMARY_OUT / f"{name}.png"
    if not src.exists():
        raise FileNotFoundError(src)
    copied = 0
    for d in SYNC_OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, d / src.name)
        copied += 1
    return copied


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, help="Output basename (no extension)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--ansi-file", help="Path to an ANSI text fixture")
    src.add_argument("--url", help="URL to render (file:// allowed)")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    args = p.parse_args()

    PRIMARY_OUT.mkdir(parents=True, exist_ok=True)
    out = PRIMARY_OUT / f"{args.name}.png"

    if args.ansi_file:
        text = Path(args.ansi_file).read_text(encoding="utf-8")
        render_ansi_to_png(text, out, width=args.width or 960)
    else:
        render_url_to_png(args.url, out, width=args.width or 1280, height=args.height or 1400)
        crop_to_content(out)

    size_kb = out.stat().st_size // 1024
    sync(args.name)
    print(f"saved {out.name} ({size_kb} KB) + synced to docs/blog/images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
