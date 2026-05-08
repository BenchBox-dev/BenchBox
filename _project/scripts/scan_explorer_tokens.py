#!/usr/bin/env python3
"""Fail when raw Tailwind palette literals appear under results-explorer/src.

The Results Explorer retheme moves every public surface to CSS-variable
tokens defined in results-explorer/src/index.css. This scan keeps the
contract durable: a PR that reintroduces a raw text-/bg-/border-/...-
gray-700 (or any palette/stop combination) breaks CI rather than ships
silently.

Allowlist mechanism: an inline marker on the same line as the literal,
e.g. `// allow-explorer-token-literal: <reason>` for JS/TS/TSX or
`/* allow-explorer-token-literal: <reason> */` for CSS. Without a
reason, the marker does not exempt the line.

Exit status:
  0 — no unallowlisted literals found
  1 — one or more literals found (printed to stderr)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

UTILITIES = (
    "text",
    "bg",
    "border",
    "divide",
    "ring",
    "placeholder",
    "fill",
    "stroke",
    "outline",
    "shadow",
)

PALETTES = (
    "slate",
    "gray",
    "zinc",
    "neutral",
    "stone",
    "red",
    "orange",
    "amber",
    "yellow",
    "lime",
    "green",
    "emerald",
    "teal",
    "cyan",
    "sky",
    "blue",
    "indigo",
    "violet",
    "purple",
    "fuchsia",
    "pink",
    "rose",
)

STOPS = ("50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950")

LITERAL_RE = re.compile(
    r"\b(?:" + "|".join(UTILITIES) + r")"
    r"-(?:" + "|".join(PALETTES) + r")"
    r"-(?:" + "|".join(STOPS) + r")\b"
)

ALLOW_MARKER_RE = re.compile(r"allow-explorer-token-literal:\s*\S")

DEFAULT_EXTENSIONS = (".tsx", ".ts", ".jsx", ".js", ".css", ".html")


def iter_files(roots: Iterable[Path], extensions: tuple[str, ...]) -> Iterable[Path]:
    for root in roots:
        if root.is_file():
            if root.suffix in extensions:
                yield root
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in extensions:
                yield path


def scan_file(path: Path) -> list[tuple[int, str, list[str]]]:
    hits: list[tuple[int, str, list[str]]] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        matches = LITERAL_RE.findall(line)
        if not matches:
            continue
        if ALLOW_MARKER_RE.search(line):
            continue
        hits.append((lineno, line.rstrip(), matches))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path("results-explorer/src")],
        help="Files or directories to scan (default: results-explorer/src)",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=None,
        help="Override the default extension list (repeatable, e.g. --ext .tsx --ext .css)",
    )
    args = parser.parse_args()

    roots = [path.resolve() for path in args.paths]
    missing = [path for path in roots if not path.exists()]
    if missing:
        print(
            "scan_explorer_tokens: missing path(s): "
            + ", ".join(str(path) for path in missing),
            file=sys.stderr,
        )
        return 2

    extensions = tuple(args.ext) if args.ext else DEFAULT_EXTENSIONS

    total_hits = 0
    for path in iter_files(roots, extensions):
        hits = scan_file(path)
        for lineno, line, matches in hits:
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
            f"\nscan_explorer_tokens: {total_hits} literal(s) found. "
            "Use a CSS variable token (var(--bb-...)) or, if intentional, append "
            "`// allow-explorer-token-literal: <reason>` (or the /* ... */ form for CSS).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
