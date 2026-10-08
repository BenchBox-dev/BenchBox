#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
PRIMARY_DIR = ROOT / "_blog" / "building-benchbox" / "images"
DOCS_DIR = ROOT / "docs" / "blog" / "images"


def expected_png_names(source_dir: Path = PRIMARY_DIR) -> list[str]:
    return sorted(path.name for path in source_dir.glob("*.png"))


def find_mismatches(
    source_dir: Path = PRIMARY_DIR,
    target_dir: Path = DOCS_DIR,
    names: Iterable[str] | None = None,
) -> list[str]:
    if names is not None:
        selected_names = sorted(set(names))
    else:
        selected_names = sorted(
            {path.name for path in source_dir.glob("*.png")} | {path.name for path in target_dir.glob("*.png")}
        )
    mismatches: list[str] = []

    for name in selected_names:
        source_path = source_dir / name
        target_path = target_dir / name

        if not source_path.exists():
            mismatches.append(f"Missing source image: {source_path}")
            continue
        if not target_path.exists():
            mismatches.append(f"Missing docs image: {target_path}")
            continue
        if source_path.read_bytes() != target_path.read_bytes():
            mismatches.append(f"Image differs: {target_path} (expected byte-identical copy of {source_path})")

    return mismatches


def main() -> int:
    if not PRIMARY_DIR.exists():
        print(f"Source directory {PRIMARY_DIR} not found, skipping sync check.")
        return 0

    mismatches = find_mismatches()
    if mismatches:
        print("Visualization screenshot sync check failed:")
        for mismatch in mismatches:
            print(f"  - {mismatch}")
        print("\nRun `uv run -- python scripts/capture_chart_images.py --sync-only` to resync copies.")
        return 1

    print("Visualization screenshots are in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
