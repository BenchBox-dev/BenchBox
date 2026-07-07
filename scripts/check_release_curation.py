#!/usr/bin/env python3
"""Curation-drift CI guard.

Verifies that every top-level tracked path on develop is accounted for as
either main-only (will land on the released main tree) or curated (will be
git-rm'd from the release branch by `make release-cut`).

Sources of truth:
  - A3 main-only allowlist: _project/decisions/single-repo-migration.md
    (the bullet under "**main only**" in the A3 row).
  - Curation list: the `git rm -rf` / `git rm -f` lines inside the
    `release-cut:` target in Makefile.
  - Required deferred release paths: explicit release-cut removals for
    v0.3.0 surfaces that remain on develop but must not ship on main.

Fails (exit 1) on any top-level path that appears in neither list, naming
the offending paths and recommending which list to update.

Run locally:
    uv run -- python scripts/check_release_curation.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISION_DOC = REPO_ROOT / "_project" / "decisions" / "single-repo-migration.md"
MAKEFILE = REPO_ROOT / "Makefile"
REQUIRED_CURATED_PATHS = frozenset(
    {
        "results-data",
        "results-explorer",
        ".github/workflows/results-explorer-browser.yml",
        ".github/workflows/seed-corpus.yml",
        ".github/workflows/sync-results-data-to-published.yml",
        ".github/workflows/validate-submission.yml",
    }
)


def parse_main_only_allowlist(doc: Path) -> set[str]:
    """Extract backtick-quoted top-level paths from every "main only" bullet.

    Picks up both the original A3 bullet and any later amendments that
    extend the main-only list (matched by the same `**`main` only**:` marker).
    """
    text = doc.read_text(encoding="utf-8")
    # Allow optional descriptive text after "main only" before the colon,
    # e.g. "**`main` only** (extension to A3):" so amendments can extend
    # the allowlist without changing the original A3 row.
    matches = re.findall(
        r"\*\*`main` only\*\*[^:\n]*:(.*?)(?=\n\s*-\s*\*\*|\n\n)",
        text,
        re.DOTALL,
    )
    if not matches:
        sys.exit(f"ERROR: could not find any 'main only' bullet in {doc}")
    paths: set[str] = set()
    for body in matches:
        paths.update(re.findall(r"`([^`]+)`", body))
    # Strip trailing slashes; we compare against top-level tree entries.
    return {p.rstrip("/") for p in paths}


def parse_curation_list(makefile: Path) -> set[str]:
    """Extract `git rm` paths from the `release-cut:` target body."""
    text = makefile.read_text(encoding="utf-8")
    match = re.search(
        r"^release-cut:\s*\n((?:[ \t].*\n|\n)+)",
        text,
        re.MULTILINE,
    )
    if not match:
        sys.exit(f"ERROR: could not find release-cut: target in {makefile}")
    body = match.group(1)
    paths: set[str] = set()
    for line in body.splitlines():
        # Match `git rm -rf <paths>` and `git rm -f <paths>`, with or without
        # `--ignore-unmatch` and with or without a leading `-` (the Make
        # "ignore exit code" prefix used before --ignore-unmatch was added).
        rm_match = re.search(r"git rm (?:-rf|-f)(?: --ignore-unmatch)? (.+?)$", line.strip())
        if not rm_match:
            continue
        paths.update(rm_match.group(1).split())
    return paths


def list_tracked_top_level() -> set[str]:
    """Return the set of top-level tracked paths from `git ls-tree HEAD`."""
    result = subprocess.run(
        ["git", "ls-tree", "HEAD", "--name-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def main() -> int:
    main_only = parse_main_only_allowlist(DECISION_DOC)
    curated = parse_curation_list(MAKEFILE)
    tracked = list_tracked_top_level()

    missing_required = sorted(REQUIRED_CURATED_PATHS - curated)
    if missing_required:
        print("ERROR: release-cut is missing required deferred-path curation:")
        for path in missing_required:
            print(f"  - {path}")
        print()
        print("These paths stay on develop but must be git-rm'd from v0.3.0 release branches.")
        return 1

    accounted = main_only | curated
    unaccounted = sorted(tracked - accounted)

    if not unaccounted:
        print(
            f"OK: all {len(tracked)} top-level tracked paths are accounted for "
            f"({len(main_only)} main-only, {len(curated)} curated)."
        )
        return 0

    print("ERROR: the following top-level paths are not accounted for:")
    for path in unaccounted:
        print(f"  - {path}")
    print()
    print("Each unaccounted-for path must be added to ONE of:")
    print("  (a) the A3 'main only' allowlist in _project/decisions/single-repo-migration.md (if it ships to main), OR")
    print(
        "  (b) the curation list in the release-cut: target in Makefile "
        "(if it is dev-only and should be git-rm'd from the release branch)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
