#!/usr/bin/env python3
"""Render scale-factor-harmonization blog images via textcharts CLI.

Pipeline: textcharts CLI -> ANSI text -> ansi2html -> headless Chrome -> PNG
Reuses the capture infrastructure from capture_chart_images.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "scripts" / "_chart_data"
sys.path.insert(0, str(ROOT / "scripts"))

from capture_chart_images import (  # noqa: E402
    HTML_TEMPLATE,
    PRIMARY_OUT,
    ansi_to_html,
    crop_to_content,
    save_png,
    sync_existing_images,
)

CHARTS: list[tuple[str, list[str]]] = [
    (
        "sf1_before_after",
        [
            "textcharts",
            "comparison",
            "-f",
            str(DATA / "sf1_before_after.json"),
            "--title",
            "SF=1 data size before and after harmonization",
            "--subtitle",
            "Target: ~1 GB uncompressed CSV  |  7 adjustable benchmarks  |  BenchBox v0.2.1",
            "--metric-label",
            "GB (uncompressed CSV)",
            "--theme",
            "dark",
            "--width",
            "96",
        ],
    ),
    (
        "tsbs_quadratic",
        [
            "textcharts",
            "comparison",
            "-f",
            str(DATA / "tsbs_comparison.json"),
            "--title",
            "TSBS DevOps: output size by scale factor",
            "--subtitle",
            "BenchBox (fixed duration) vs. naive scaling (hosts x duration)  |  GB",
            "--metric-label",
            "GB",
            "--theme",
            "dark",
            "--width",
            "96",
        ],
    ),
    (
        "v021_release_scope",
        [
            "textcharts",
            "bar",
            "-f",
            str(DATA / "v021_release_scope.json"),
            "--title",
            "BenchBox v0.2.1 by the numbers",
            "--subtitle",
            "Net-new additions in this release  |  shipped 2026-04-26",
            "--metric-label",
            "count",
            "--theme",
            "dark",
            "--width",
            "96",
            "--sort-by",
            "value",
        ],
    ),
]


def run_chart(cmd: list[str]) -> str:
    env = {**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"}
    result = subprocess.run(
        ["uv", "run", "--project", str(ROOT), *cmd],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        print(f"  WARNING: no output — stderr: {result.stderr[:200]}", file=sys.stderr)
    return output


def main() -> int:
    PRIMARY_OUT.mkdir(parents=True, exist_ok=True)

    for name, cmd in CHARTS:
        out_path = PRIMARY_OUT / f"{name}.png"
        print(f"→ {out_path.name}")

        ansi_text = run_chart(cmd)
        if not ansi_text:
            print("  SKIP: empty output")
            continue

        html_body = ansi_to_html(ansi_text)
        html = HTML_TEMPLATE.format(content=html_body)
        save_png(html, out_path, ansi_text, width=1050)
        crop_to_content(out_path)

        sync_existing_images(names=[name])
        size_kb = out_path.stat().st_size // 1024
        print(f"  saved {out_path.name} ({size_kb} KB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
