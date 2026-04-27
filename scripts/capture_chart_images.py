#!/usr/bin/env python3
"""Capture visualization screenshots and sync shared docs/blog image copies.

Pipeline: ``benchbox visualize`` -> ANSI text -> ansi2html -> headless Chrome -> PNG.

This script is the supported entrypoint for the historical blog/chart screenshot
automation. Fresh renders are written to ``_blog/building-benchbox/images`` and
then synced into ``docs/blog/images`` so the published docs do not drift from
the blog source tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmark_runs" / "results"
OX_RESULTS = Path("/Users/joe/Developer/Oxbow/benchmark_runs/results")
PRIMARY_OUT = ROOT / "_blog" / "building-benchbox" / "images"
SYNC_OUT_DIRS = (ROOT / "docs" / "blog" / "images",)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# DuckDB 1.2.2 / 1.3.2 / 1.4.4 at SF=1 (Oxbow project)
OX_A = OX_RESULTS / "tpch_sf1_duckdb_sql_20260223_140745_f1e6f02e.json"  # 1.2.2
OX_B = OX_RESULTS / "tpch_sf1_duckdb_sql_20260223_141239_0e852969.json"  # 1.3.2
OX_C = OX_RESULTS / "tpch_sf1_duckdb_sql_20260223_141527_a41ee940.json"  # 1.4.4

# (output_name, [result_files], chart_type, no_color)
CHARTS: list[tuple[str, list[Path], str, bool]] = [
    ("percentile_ladder", [OX_A, OX_B, OX_C], "percentile_ladder", False),
    ("cdf_chart", [OX_A, OX_B, OX_C], "cdf_chart", False),
    ("sparkline_table", [OX_A, OX_B, OX_C], "sparkline_table", False),
    ("rank_table", [OX_A, OX_B, OX_C], "rank_table", False),
    ("normalized_speedup", [OX_A, OX_B, OX_C], "normalized_speedup", False),
    ("comparison_bar_color", [OX_A, OX_C], "comparison_bar", False),
    ("comparison_bar_nocolor", [OX_A, OX_C], "comparison_bar", True),
    ("post_run_chart_v013", [OX_C], "query_histogram", False),
]

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


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Copy existing generated screenshots from _blog/... into docs/blog/images without re-rendering.",
    )
    return parser.parse_args()


def sync_existing_images(
    source_dir: Path = PRIMARY_OUT,
    target_dirs: Sequence[Path] = SYNC_OUT_DIRS,
    names: Iterable[str] | None = None,
) -> int:
    """Copy existing PNG screenshots into the synced docs/blog destinations."""
    copied = 0
    selected_names = list(names) if names is not None else sorted(path.stem for path in source_dir.glob("*.png"))

    for name in selected_names:
        source_path = source_dir / f"{name}.png"
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source screenshot: {source_path}")

        for target_dir in target_dirs:
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / source_path.name
            shutil.copy2(source_path, target_path)
            copied += 1

    return copied


def _require_capture_dependencies() -> None:
    """Validate optional screenshot capture dependencies before rendering."""
    missing: list[str] = []
    try:
        import ansi2html  # noqa: F401
    except ImportError:
        missing.append("ansi2html")

    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")

    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing capture dependencies: {joined}. Install them before running screenshot capture.")

    if not CHROME.exists():
        raise SystemExit(f"Chrome binary not found: {CHROME}")

    missing_results = sorted(
        {
            str(result_path)
            for _name, result_files, _chart_type, _no_color in CHARTS
            for result_path in result_files
            if not result_path.exists()
        }
    )
    if missing_results:
        formatted = "\n".join(f"  - {path}" for path in missing_results)
        raise SystemExit(f"Missing input result files for screenshot capture:\n{formatted}")


def run_chart(result_files: Sequence[Path], chart_type: str, no_color: bool) -> str:
    """Run ``benchbox visualize`` and return raw chart output."""
    paths = [str(path if path.is_absolute() else RESULTS / path) for path in result_files]
    cmd = ["uv", "run", "benchbox", "visualize", *paths, "--chart-type", chart_type]
    if no_color:
        cmd.append("--no-color")
    env = {**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"}
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env, check=False)
    output = result.stdout.strip()
    if not output:
        print(f"  WARNING: no output for {chart_type}", file=sys.stderr)
    return output


def ansi_to_html(ansi_text: str) -> str:
    """Convert ANSI escape sequences to HTML spans via ``ansi2html``."""
    from ansi2html import Ansi2HTMLConverter  # type: ignore[import]

    converter = Ansi2HTMLConverter(inline=True, scheme="ansi2html", dark_bg=True)
    return converter.convert(ansi_text, full=False)


def estimate_height(text: str, pad: int = 80) -> int:
    """Estimate viewport height from line count."""
    lines = text.count("\n") + 1
    return min(max(lines * 22 + pad * 2, 200), 2400)


def save_png(html_content: str, out_path: Path, text: str, width: int = 960) -> None:
    """Render HTML to PNG via headless Chrome."""
    height = estimate_height(text)
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False, encoding="utf-8") as handle:
        handle.write(html_content)
        tmp_html = handle.name

    try:
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
                f"file://{tmp_html}",
            ],
            capture_output=True,
            check=True,
        )
    finally:
        os.unlink(tmp_html)


def crop_to_content(png_path: Path) -> None:
    """Crop blank bottom rows using Pillow."""
    from PIL import Image  # type: ignore[import]

    img = Image.open(png_path).convert("RGB")
    pixels = img.load()
    width, height = img.size

    def is_bg(r: int, g: int, b: int) -> bool:
        return abs(r - 26) <= 4 and abs(g - 30) <= 4 and abs(b - 36) <= 4

    last_row = height - 1
    for y in range(height - 1, 0, -1):
        if not all(is_bg(*pixels[x, y]) for x in range(0, width, 4)):
            last_row = y + 32
            break

    if last_row < height:
        img = img.crop((0, 0, width, min(last_row, height)))
        img.save(png_path)


def render_images() -> None:
    """Render the configured screenshots and sync them into docs/blog."""
    _require_capture_dependencies()
    PRIMARY_OUT.mkdir(parents=True, exist_ok=True)

    for name, result_files, chart_type, no_color in CHARTS:
        out_path = PRIMARY_OUT / f"{name}.png"
        suffix = " [no-color]" if no_color else ""
        print(f"→ {out_path.name}  ({chart_type}{suffix})")

        ansi_text = run_chart(result_files, chart_type, no_color)
        if not ansi_text:
            print("  SKIP: empty output")
            continue

        if no_color:
            html_body = ansi_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        else:
            html_body = ansi_to_html(ansi_text)

        html = HTML_TEMPLATE.format(content=html_body)
        save_png(html, out_path, ansi_text)
        crop_to_content(out_path)

        sync_existing_images(names=[name])
        size_kb = out_path.stat().st_size // 1024
        print(f"  saved {out_path.name} ({size_kb} KB)")


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()

    if args.sync_only:
        copied = sync_existing_images()
        print(f"Synced {copied} screenshot copy/copies into docs/blog/images.")
        return 0

    render_images()
    print("\nDone. Images written to:")
    print(f"  - {PRIMARY_OUT}")
    for target_dir in SYNC_OUT_DIRS:
        print(f"  - {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
