#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

STALE_PATTERNS = (
    re.compile(r"dark BenchBox shell \+ light analytical data panels"),
    re.compile(r"mixed dark/light"),
    re.compile(r"light data surface contract"),
    re.compile(r"light analytical data"),
)

ALLOW_MARKER_RE = re.compile(r"allow-stale-theme:\s*\S")
SUPERSESSION_RE = re.compile(r"\b(?:superseded|supersedes|supersede|supersession)\b", re.IGNORECASE)

DEFAULT_PATHS = (
    Path("results-explorer/src"),
    Path("results-explorer/e2e"),
    Path("_project/analysis"),
)
DEFAULT_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js", ".css", ".md", ".html")
SUPERSESSION_HEADER_LINES = 40


CLI_DESCRIPTION = (
    "Fail when active source revives the retired mixed-theme Results Explorer contract.\n"
    "\n"
    "The current product contract is the shared BenchBox `system` / `light` / `dark`\n"
    'theme. Earlier planning evidence described a retired "dark BenchBox shell +\n'
    'light analytical data panels" contract; if those phrases re-enter active source\n'
    "or active test/spec names, future implementers can silently restore the wrong\n"
    "contract.\n"
    "\n"
    "This scan looks for the retired phrases in:\n"
    "  * results-explorer/src (production source and unit tests)\n"
    "  * results-explorer/e2e (route specs)\n"
    "  * _project/analysis  (planning evidence)\n"
    "\n"
    "It allows two escape hatches:\n"
    "  * Inline marker `allow-stale-theme: <reason>` on the same line.\n"
    "  * For `_project/analysis/*` files, an early supersession note within the\n"
    "    first 40 lines that mentions one of: superseded, supersedes, supersede,\n"
    "    supersession.\n"
    "\n"
    "Historical evidence under `_project/DONE/` is intentionally excluded - the\n"
    "project rule is to add supersession notes to active analysis, not to rewrite\n"
    "completed work.\n"
    "\n"
    "Exit status:\n"
    "  0 - no unallowlisted references found\n"
    "  1 - one or more references found (printed to stderr)\n"
)


def has_supersession_header(path: Path) -> bool:
    if "_project" not in path.parts or "analysis" not in path.parts:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    head = "\n".join(text.splitlines()[:SUPERSESSION_HEADER_LINES])
    return bool(SUPERSESSION_RE.search(head))


def iter_files(roots: Iterable[Path], extensions: tuple[str, ...]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in extensions:
                yield root
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in extensions:
                yield path


def scan_file(path: Path) -> list[tuple[int, str, list[str]]]:
    text = path.read_text(encoding="utf-8")
    allow_file = has_supersession_header(path)
    hits: list[tuple[int, str, list[str]]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        matches: list[str] = []
        for pattern in STALE_PATTERNS:
            matches.extend(pattern.findall(line))
        if not matches:
            continue
        if ALLOW_MARKER_RE.search(line):
            continue
        if allow_file:
            continue
        hits.append((lineno, line.rstrip(), matches))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=list(DEFAULT_PATHS),
        help="Files or directories to scan (default: results-explorer/src, results-explorer/e2e, _project/analysis)",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=None,
        help="Override the default extension list (repeatable)",
    )
    args = parser.parse_args()

    roots = [path.resolve() for path in args.paths]
    extensions = tuple(args.ext) if args.ext else DEFAULT_EXTENSIONS

    total_hits = 0
    for path in iter_files(roots, extensions):
        for lineno, line, matches in scan_file(path):
            total_hits += 1
            display = path
            try:
                display = path.relative_to(Path.cwd())
            except ValueError:
                pass
            print(
                f"{display}:{lineno}: {', '.join(sorted(set(matches)))}: {line}",
                file=sys.stderr,
            )

    if total_hits:
        print(
            f"\nscan_explorer_stale_theme: {total_hits} stale-theme reference(s) found.\n"
            "Rewrite the language to describe the current light/dark theme contract,\n"
            "add a supersession header (e.g. `Superseded on ...`) to the analysis file,\n"
            "or append `allow-stale-theme: <reason>` to the line.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
