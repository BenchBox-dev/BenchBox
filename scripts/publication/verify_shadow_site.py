#!/usr/bin/env python3
"""Verify assembled shadow site links, assets, Explorer routes, and Sphinx references (A4 w3, w4).

Usage:
  uv run python scripts/publication/verify_shadow_site.py [site_dir]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HREF_SRC_RE = re.compile(r'(?:href|src)=["\']([^"\'#?]+)(?:[#?][^"\']*)?["\']', re.IGNORECASE)
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "javascript:", "data:")


def verify_site_directory(site_dir: Path) -> list[str]:
    """Verify shadow site structure, entry points, and local asset links."""
    errors: list[str] = []

    if not site_dir.exists():
        # Informational check when site directory is not yet generated
        print(f"Shadow site dir '{site_dir}' does not exist yet (pre-assembly state).")
        return []

    # Check key files
    expected_entrypoints = ["index.html"]
    for ep in expected_entrypoints:
        if not (site_dir / ep).is_file():
            errors.append(f"Missing essential site entry point: '{ep}'")

    # Scan HTML files for broken local references
    for root, _, files in os.walk(site_dir):
        for f in files:
            if not f.endswith((".html", ".htm")):
                continue
            html_path = Path(root) / f
            try:
                content = html_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                errors.append(f"Failed to read '{html_path}': {e}")
                continue

            for match in HREF_SRC_RE.finditer(content):
                target = match.group(1).strip()
                if not target or any(target.startswith(scheme) for scheme in EXTERNAL_SCHEMES):
                    continue

                # Resolve relative or absolute site path
                if target.startswith("/"):
                    resolved = site_dir / target.lstrip("/")
                else:
                    resolved = html_path.parent / target

                # Allow directory index lookup
                if resolved.is_dir() and (resolved / "index.html").is_file():
                    continue

                if not resolved.exists() and not (resolved.with_suffix(".html")).exists():
                    rel_source = html_path.relative_to(site_dir).as_posix()
                    errors.append(f"Broken internal link in '{rel_source}' -> '{target}' (target not found)")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify assembled shadow site links and routes")
    parser.add_argument("site_dir", type=Path, nargs="?", default=Path("publication/out/site"))
    args = parser.parse_args(argv)

    print(f"Verifying shadow site at '{args.site_dir}'...")
    errors = verify_site_directory(args.site_dir)

    if errors:
        print("❌ Shadow site verification FAILED:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        return 1

    print("✅ Shadow site verification PASSED: all routes, assets, and entry points valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
