#!/usr/bin/env python3
"""
Capture ASCII chart terminal output as PNG images for blog posts.
Pipeline: benchbox visualize → ANSI text → ansi2html → Chrome headless → PNG
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
RESULTS = ROOT / "benchmark_runs" / "results"
OUT = ROOT / "_blog" / "building-benchbox" / "images"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SF10_A = "tpch_sf10_duckdb_sql_20260220_082306_7ce17eb6.json"
SF10_B = "tpch_sf10_duckdb_sql_20260220_082331_1dea1e5a.json"
SF10_C = "tpch_sf10_duckdb_sql_20260220_082357_98034fae.json"
SF001_DUCK = "tpch_sf001_duckdb_sql_20260223_211334_mcp_b5ff1412.json"
SF001_FRESH = "tpch_sf001_duckdb_sql_20260223_211442_mcp_daa85cef.json"

CHARTS = [
    # (output_name, [result_files], chart_type, no_color)
    ("percentile_ladder",   [SF10_C],                  "percentile_ladder",  False),
    ("cdf_chart",           [SF10_C],                  "cdf_chart",          False),
    ("sparkline_table",     [SF10_A, SF10_B, SF10_C],  "sparkline_table",    False),
    ("rank_table",          [SF10_A, SF10_C],          "rank_table",         False),
    ("normalized_speedup",  [SF10_B, SF10_C],          "normalized_speedup", False),
    # No-color comparison pair using comparison_bar
    ("comparison_bar_color",   [SF10_B, SF10_C],       "comparison_bar",     False),
    ("comparison_bar_nocolor", [SF10_B, SF10_C],       "comparison_bar",     True),
    # Post-run header image: query_histogram from fresh run
    ("post_run_chart_v013", [SF001_FRESH],             "query_histogram",    False),
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
    font-family: "Menlo", "JetBrains Mono", "SF Mono", "Consolas", monospace;
    font-size: 13.5px;
    line-height: 1.55;
    color: #d4d4d4;
    white-space: pre;
  }}
  /* ansi2html colour overrides – match iTerm2 dark profile */
  .ansi1  {{ font-weight: bold; }}
  .ansi32 {{ color: #4ec9b0; }}   /* green → teal (best queries) */
  .ansi33 {{ color: #e6ab02; }}   /* yellow */
  .ansi34 {{ color: #569cd6; }}   /* blue */
  .ansi35 {{ color: #c586c0; }}   /* magenta */
  .ansi36 {{ color: #4ec9b0; }}   /* cyan → teal */
  .ansi37 {{ color: #d4d4d4; }}   /* white */
  .ansi38-5-36  {{ color: #4ec9b0; }}   /* xterm 36 – main bar colour */
  .ansi38-5-60  {{ color: #5a6478; }}   /* xterm 60 – dim/mean line */
  .ansi38-5-70  {{ color: #6aaf6a; }}   /* xterm 70 – best label */
  .ansi38-5-166 {{ color: #d7875f; }}   /* xterm 166 – worst/orange */
  .ansi38-5-242 {{ color: #6b7075; }}   /* xterm 242 – secondary text */
</style>
</head>
<body>
<pre>{content}</pre>
</body>
</html>
"""


def run_chart(result_files: list[str], chart_type: str, no_color: bool) -> str:
    """Run benchbox visualize and return raw output (with ANSI if not no_color)."""
    paths = [str(RESULTS / f) for f in result_files]
    cmd = ["uv", "run", "benchbox", "visualize", *paths, "--chart-type", chart_type]
    if no_color:
        cmd.append("--no-color")
    env = {**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"}
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(ROOT), env=env
    )
    output = result.stdout.strip()
    if not output:
        print(f"  WARNING: no output for {chart_type}", file=sys.stderr)
    return output


def ansi_to_html(ansi_text: str) -> str:
    """Convert ANSI escape sequences to HTML spans via ansi2html."""
    from ansi2html import Ansi2HTMLConverter  # type: ignore[import]
    conv = Ansi2HTMLConverter(inline=True, scheme="ansi2html", dark_bg=True)
    full_html = conv.convert(ansi_text, full=False)
    return full_html


def estimate_height(text: str, pad: int = 80) -> int:
    """Estimate viewport height from line count."""
    lines = text.count("\n") + 1
    return min(max(lines * 22 + pad * 2, 200), 2400)


def save_png(html_content: str, out_path: Path, text: str, width: int = 960) -> None:
    """Render HTML to PNG via Chrome headless."""
    height = estimate_height(text)
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
        f.write(html_content)
        tmp_html = f.name

    try:
        subprocess.run(
            [
                CHROME,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-web-security",
                f"--window-size={width},{height}",
                "--screenshot=" + str(out_path),
                "--hide-scrollbars",
                "file://" + tmp_html,
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
    w, h = img.size
    # Background colour: #1a1e24 = (26, 30, 36) – allow ±4 tolerance
    def is_bg(r: int, g: int, b: int) -> bool:
        return abs(r - 26) <= 4 and abs(g - 30) <= 4 and abs(b - 36) <= 4
    last_row = h - 1
    for y in range(h - 1, 0, -1):
        if not all(is_bg(*pixels[x, y]) for x in range(0, w, 4)):
            last_row = y + 32  # 32px bottom pad
            break
    if last_row < h:
        img = img.crop((0, 0, w, min(last_row, h)))
        img.save(png_path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for name, result_files, chart_type, no_color in CHARTS:
        label = f"{name}.png"
        out_path = OUT / label
        suffix = " [no-color]" if no_color else ""
        print(f"→ {label}  ({chart_type}{suffix})")

        ansi_text = run_chart(result_files, chart_type, no_color)
        if not ansi_text:
            print(f"  SKIP: empty output")
            continue

        if no_color:
            # Plain text – wrap directly, no ansi2html needed
            html_body = ansi_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        else:
            html_body = ansi_to_html(ansi_text)

        html = HTML_TEMPLATE.format(content=html_body)
        save_png(html, out_path, ansi_text)
        crop_to_content(out_path)

        size_kb = out_path.stat().st_size // 1024
        print(f"  saved {out_path.name} ({size_kb} KB)")

    print("\nDone. Images in:", OUT)


if __name__ == "__main__":
    main()
