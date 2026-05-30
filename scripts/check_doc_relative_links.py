#!/usr/bin/env python3
"""Check repo-local relative links in Markdown docs resolve to real files.

Closes the detection gap that let a broken source-relative link
(`docs/contributing-results.md` -> `getting-started.rst`) ship undetected.
That class of link evades the existing docs gates three ways:

  1. The Sphinx ``linkcheck`` builder only validates *external* (http/https)
     URLs -- it never checks local source-relative file links.
  2. The HTML build runs ``sphinx-build -b html --keep-going`` without
     ``-W``, so warnings never fail CI.
  3. ``docs/conf.py`` sets ``suppress_warnings = ["myst.xref_missing",
     "ref.myst"]``, suppressing the very warning a missing local target
     would otherwise raise.

This check scans ``docs/**/*.md`` (excluding the generated ``_build/``
tree), extracts inline Markdown links ``[text](target)``, and asserts that
every *repo-local relative* target exists on disk. External URLs, ``mailto:``
and other schemes, bare ``#anchors``, and server-absolute ``/paths`` are left
to the external linkcheck / site routing and are not inspected here.

Pre-existing broken links are recorded in a baseline file so this gate blocks
*new* breakage immediately without forcing a repo-wide cleanup. The baseline
cannot rot: an entry whose target now resolves is reported as stale and must
be removed (regenerate with ``--update-baseline``).

Usage:
    python scripts/check_doc_relative_links.py            # check (CI mode)
    python scripts/check_doc_relative_links.py --update-baseline

Exit codes:
    0 - No new broken relative links; baseline is current
    1 - New broken relative link(s) found, or baseline contains stale entries

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
BASELINE_PATH = REPO_ROOT / "scripts" / "doc_relative_link_baseline.txt"

# Inline link [text](target ["title"]) but not images (![...]); target stops
# at whitespace or the closing paren.
_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def iter_doc_files() -> list[Path]:
    """Markdown files under docs/, excluding the generated _build/ tree."""
    return sorted(p for p in DOCS_DIR.rglob("*.md") if "_build" not in p.parts)


def extract_relative_links(content: str) -> list[tuple[int, str]]:
    """Return (line_number, target) for repo-local relative inline links.

    Skips fenced and inline code spans, external URLs, other URI schemes,
    bare ``#anchors``, and server-absolute ``/paths``.
    """
    results: list[tuple[int, str]] = []
    in_fence = False
    for line_num, line in enumerate(content.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = _INLINE_CODE_RE.sub("", line)
        for match in _LINK_RE.finditer(stripped):
            target = match.group(1).strip()
            if target.startswith(("#", "/")):
                continue
            if _SCHEME_RE.match(target):  # http:, https:, mailto:, etc.
                continue
            results.append((line_num, target))
    return results


def target_resolves(doc_file: Path, target: str) -> bool:
    """Whether the relative target (fragment/query stripped) exists on disk."""
    core = target.split("#", 1)[0].split("?", 1)[0]
    if not core:  # same-document anchor written as (path#frag) with empty path
        return True
    return (doc_file.parent / core).exists()


def collect_broken() -> list[tuple[str, int, str]]:
    """All broken repo-local relative links as (rel_source, line, target)."""
    broken: list[tuple[str, int, str]] = []
    for doc_file in iter_doc_files():
        rel_source = doc_file.relative_to(REPO_ROOT).as_posix()
        for line_num, target in extract_relative_links(doc_file.read_text(encoding="utf-8")):
            if not target_resolves(doc_file, target):
                broken.append((rel_source, line_num, target))
    return broken


def load_baseline() -> set[tuple[str, str]]:
    """Known pre-existing broken links as a set of (rel_source, target)."""
    if not BASELINE_PATH.exists():
        return set()
    pairs: set[tuple[str, str]] = set()
    for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        source, _, target = line.partition("\t")
        if target:
            pairs.add((source, target))
    return pairs


def write_baseline(broken: list[tuple[str, int, str]]) -> int:
    """Regenerate the baseline file from the current broken set."""
    pairs = sorted({(source, target) for source, _, target in broken})
    lines = [
        "# Pre-existing broken repo-local relative links in docs/.",
        "# Format: <source-path-from-repo-root><TAB><link-target>",
        "# Regenerate: uv run -- python scripts/check_doc_relative_links.py --update-baseline",
        "# Burn this list down; do NOT add new entries to silence regressions.",
    ]
    lines += [f"{source}\t{target}" for source, target in pairs]
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ Wrote {len(pairs)} baseline entries to {BASELINE_PATH.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite the baseline file from the current broken-link set.",
    )
    args = parser.parse_args()

    if not DOCS_DIR.exists():
        print(f"❌ Documentation directory not found: {DOCS_DIR}")
        return 1

    broken = collect_broken()

    if args.update_baseline:
        return write_baseline(broken)

    baseline = load_baseline()
    broken_pairs = {(source, target) for source, _, target in broken}

    new_breaks = [(source, line, target) for source, line, target in broken if (source, target) not in baseline]
    stale_baseline = sorted(baseline - broken_pairs)

    print("Checking repo-local relative links in docs/ ...")
    print(f"  scanned files : {len(iter_doc_files())}")
    print(f"  baseline size : {len(baseline)}")
    print(f"  broken total  : {len(broken_pairs)}")

    if new_breaks:
        print(f"\n❌ {len(new_breaks)} NEW broken relative link(s):")
        for source, line, target in new_breaks:
            print(f"   {source}:{line} -> {target}")
        print(
            "\nFix the link, or (only for an intentional pre-existing case)"
            " regenerate the baseline with --update-baseline."
        )

    if stale_baseline:
        print(f"\n❌ {len(stale_baseline)} baseline entr(y/ies) now resolve and must be removed:")
        for source, target in stale_baseline:
            print(f"   {source} -> {target}")
        print("\nRegenerate with --update-baseline to drop fixed entries.")

    if new_breaks or stale_baseline:
        print("\n❌ DOC RELATIVE-LINK CHECK FAILED")
        return 1

    print("\n✅ No new broken relative links; baseline is current.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Check interrupted")
        sys.exit(1)
