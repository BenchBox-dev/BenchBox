#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from soundness_paths import any_soundness_path  # noqa: E402

_REVIEW_HEADER = re.compile(r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?Soundness review:[ \t]*$")
_NEXT_HEADING = re.compile(r"(?im)^[ \t]*#{1,6}[ \t]+\S")
_REVIEWER = re.compile(r"(?im)^[ \t]*(?:[-*+][ \t]+)?(?:external[ \t]+)?reviewer[ \t]*:[ \t]*(codex|muse|agy)\b")
_COMMENT_LINK = re.compile(r"https://github\.com/[^/\s)]+/[^/\s)]+/pull/\d+#issuecomment-\d+\b", re.IGNORECASE)
_RESOLUTION = re.compile(
    r"(?im)^[ \t]*(?:[-*+][ \t]+)?all\s+(?:critical/high|critical\s+and\s+high)\s+findings\s+(?:are\s+)?resolved[.!]?[ \t]*$",
    re.IGNORECASE,
)


CLI_DESCRIPTION = "Require an external adversarial review section for soundness-path PRs."


def _plain_markdown(body: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        stripped = line.lstrip()
        fence_match = re.match(r"^(?P<fence>`{3,}|~{3,})", stripped)
        if fence_match:
            marker = fence_match.group("fence")[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None and not stripped.startswith(">"):
            lines.append(line)
    return "\n".join(lines)


def _review_section(body: str) -> str | None:
    plain_body = _plain_markdown(body)
    match = _REVIEW_HEADER.search(plain_body)
    if match is None:
        return None
    section = plain_body[match.end() :]
    next_heading = _NEXT_HEADING.search(section)
    if next_heading is not None:
        section = section[: next_heading.start()]
    return section.strip()


def soundness_review_errors(body: str) -> list[str]:
    section = _review_section(body)
    if section is None:
        return ["PR body must contain a 'Soundness review:' section"]

    errors: list[str] = []
    if _REVIEWER.search(section) is None:
        errors.append("Soundness review must name codex, muse, or agy as the external reviewer")
    if _COMMENT_LINK.search(section) is None:
        errors.append("Soundness review must link the external review PR comment")
    if _RESOLUTION.search(section) is None:
        errors.append("Soundness review must state that all Critical/High findings are resolved")
    return errors


def check_soundness_review(paths: list[str], body: str) -> list[str]:
    if not any_soundness_path(paths):
        return []
    return soundness_review_errors(body)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("--paths-file", type=Path, required=True, help="Newline-delimited changed git paths")
    parser.add_argument("--body-file", type=Path, required=True, help="Pull request body markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    paths = args.paths_file.read_text(encoding="utf-8").splitlines()
    body = args.body_file.read_text(encoding="utf-8")
    errors = check_soundness_review(paths, body)
    if errors:
        for error in errors:
            print(f"soundness-flag: {error}", file=sys.stderr)
        return 1
    print("soundness-flag: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
