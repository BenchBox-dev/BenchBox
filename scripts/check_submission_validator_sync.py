#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

CLI_DESCRIPTION = (
    "Detect drift between the two copies of the submission validator workflow.\n"
    "\n"
    "`validate-submission.yml` lives on both `develop` (the maintained source of\n"
    "truth) and `published-results` (the branch copy that actually runs for\n"
    "contributor PRs). The corpus sync bot cannot mirror workflow files\n"
    "(`GITHUB_TOKEN` lacks `workflows: write`), so the published-results copy is\n"
    "kept in sync by a hand-opened PR. That manual step is easy to forget, and a\n"
    "drifted copy silently runs stale validation logic (this is exactly how the\n"
    "§2.6/§2.7/§2.1 hardening and the Defect #1 fork gate came to lag behind).\n"
    "\n"
    "The two copies are intended to be byte-identical **except** for the uv\n"
    "invocation: `develop` runs inside the project (`uv run -- python ...`), while\n"
    "`published-results` is a slim branch with no `pyproject.toml`/`uv.lock` and\n"
    "must run `uv run --no-project --python 3.11 -- python ...`. This tool\n"
    "normalizes that one sanctioned difference away and reports any remaining\n"
    "divergence as drift.\n"
    "\n"
    "Usage:\n"
    "    uv run -- python scripts/check_submission_validator_sync.py         --develop .github/workflows/validate-submission.yml         --published /tmp/published-results-validate-submission.yml\n"
    "\n"
    "Exit code 0 when the copies match (after normalization), 1 on drift, 2 on a\n"
    "usage/IO error. The scheduled `submission-validator-drift-check.yml` workflow\n"
    "wires the two real branch copies into this script.\n"
)

_SLIM_INVOCATION = re.compile(r"uv run --no-project --python 3\.11 -- python")
_PROJECT_INVOCATION = re.compile(r"uv run -- python")
_CANONICAL = "uv run <INVOCATION> python"


def normalize(text: str) -> str:
    text = _SLIM_INVOCATION.sub(_CANONICAL, text)
    text = _PROJECT_INVOCATION.sub(_CANONICAL, text)
    return text


def diff(develop_text: str, published_text: str) -> list[str]:
    dev = normalize(develop_text).splitlines(keepends=True)
    pub = normalize(published_text).splitlines(keepends=True)
    if dev == pub:
        return []
    return list(
        difflib.unified_diff(
            dev,
            pub,
            fromfile="develop:validate-submission.yml (normalized)",
            tofile="published-results:validate-submission.yml (normalized)",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument(
        "--develop",
        required=True,
        type=Path,
        help="Path to develop's copy of validate-submission.yml.",
    )
    parser.add_argument(
        "--published",
        required=True,
        type=Path,
        help="Path to published-results' copy of validate-submission.yml.",
    )
    args = parser.parse_args(argv)

    for label, path in (("develop", args.develop), ("published-results", args.published)):
        if not path.is_file():
            print(f"::error::{label} copy not found at {path}", file=sys.stderr)
            return 2

    drift = diff(
        args.develop.read_text(encoding="utf-8"),
        args.published.read_text(encoding="utf-8"),
    )
    if not drift:
        print("Submission validator copies are in sync (after invocation normalization).")
        return 0

    print(
        "::error::validate-submission.yml has drifted between develop and "
        "published-results. Open a sync PR against published-results, preserving "
        "the slim-branch `uv run --no-project --python 3.11` invocation (see "
        "docs/development/adr/adr-published-results-slim-corpus-branch.md). "
        "Normalized diff:",
        file=sys.stderr,
    )
    sys.stderr.writelines(drift)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
