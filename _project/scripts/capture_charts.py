#!/usr/bin/env python3
"""Backward-compatible wrapper for ``scripts/capture_chart_images.py``."""

from __future__ import annotations

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_chart_images.py"


if __name__ == "__main__":
    runpy.run_path(str(SCRIPT), run_name="__main__")
