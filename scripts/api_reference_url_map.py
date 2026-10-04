#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import Counter
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOLS = REPO_ROOT / "_project" / "design" / "site-inventory" / "api-public-symbols.json"
DEFAULT_OUT = REPO_ROOT / "_project" / "design" / "site-inventory" / "api-reference-url-map.json"
NOTE_ANCHOR = "not-part-of-public-contract"
AUTODOC_LINE = re.compile(r"^\.\. (?:auto\w*|method|function|class|attribute)::", re.MULTILINE)
ARTICLE = re.compile(r"<article\b.*?</article>", re.DOTALL)
HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
POLICY = (
    "Every page URL is kept: the authored contract page replaces the .rst at the same path stem. Every id and name "
    "attribute in the built article body stays resolvable on the same page, as the id of a heading (disposition "
    "heading), as an alias id element next to the content that replaced it (alias), or as an alias that lands on an "
    "anchored not-part-of-public-contract note on the same page (alias-to-note) when the symbol is outside the public "
    "contract."
)


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for attribute, value in attrs:
            if attribute in {"id", "name"} and value:
                self.found.append((tag, attribute, value))


def discover_sources(docs: Path) -> list[Path]:
    candidates = [docs / "api.rst", *sorted((docs / "reference" / "python-api").rglob("*.rst"))]
    return [path for path in candidates if path.is_file() and AUTODOC_LINE.search(path.read_text(encoding="utf-8"))]


def page_path(docs: Path, source: Path) -> str:
    return source.relative_to(docs).with_suffix(".html").as_posix()


def collect_ids(html: str) -> list[tuple[str, str, str]]:
    match = ARTICLE.search(html)
    if match is None:
        raise ValueError("no <article> element in built page")
    collector = IdCollector()
    collector.feed(match.group(0))
    return collector.found


def classify(tag: str) -> str:
    if tag == "dt":
        return "object"
    if tag == "section" or tag in HEADINGS:
        return "section"
    return "other"


def covered(identifier: str, names: frozenset[str]) -> bool:
    return any(identifier == name or identifier.startswith(name + ".") for name in names)


def bare_owner(identifier: str, ordered: list[str]) -> str | None:
    for candidate in reversed(ordered):
        if candidate.rsplit(".", 1)[-1] == identifier:
            return candidate
    return None


def build_page(
    found: list[tuple[str, str, str]],
    public: frozenset[str],
    dropped: frozenset[str],
    heading_ids: frozenset[str],
) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    qualified: list[str] = []
    for tag, attribute, value in found:
        entry = entries.setdefault(value, {"class": classify(tag), "via": set()})
        entry["via"].add(attribute)
        if tag == "dt" and value.startswith("benchbox."):
            qualified.append(value)
    for value, entry in entries.items():
        subject: str | None = None
        if entry["class"] == "object":
            subject = value if value.startswith("benchbox.") else bare_owner(value, qualified)
        if subject is not None and covered(subject, dropped):
            entry["disposition"] = "alias-to-note"
            entry["target"] = "#" + NOTE_ANCHOR
        elif entry["class"] == "section" or value in heading_ids:
            entry["disposition"] = "heading"
        else:
            entry["disposition"] = "alias"
        entry["via"] = sorted(entry["via"])
    ids = {key: entries[key] for key in sorted(entries)}
    return {"ids": ids, "has_note": any(e["disposition"] == "alias-to-note" for e in ids.values())}


def build_map(docs: Path, html_root: Path, symbols_path: Path, source_sha: str, command: str) -> dict[str, Any]:
    inventory = json.loads(symbols_path.read_text(encoding="utf-8"))
    heading_ids = frozenset(entry["symbol"] for entry in inventory["symbols"])
    public = frozenset(
        {entry["symbol"] for entry in inventory["symbols"]}
        | {alias for entry in inventory["symbols"] for alias in entry.get("aliases", [])}
    )
    dropped = frozenset(inventory.get("dropped", []))
    pages: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    bare = 0
    unexpected: set[str] = set()
    for source in discover_sources(docs):
        rel = page_path(docs, source)
        built = html_root / rel
        if not built.is_file():
            raise FileNotFoundError(f"built page missing: {built}")
        page = build_page(collect_ids(built.read_text(encoding="utf-8")), public, dropped, heading_ids)
        counts = Counter(f"{e['class']}:{e['disposition']}" for e in page["ids"].values())
        totals.update(counts)
        totals.update(f"class:{e['class']}" for e in page["ids"].values())
        totals.update(f"disposition:{e['disposition']}" for e in page["ids"].values())
        bare += sum(1 for k, e in page["ids"].items() if e["class"] == "object" and not k.startswith("benchbox."))
        unexpected.update(
            k
            for k, e in page["ids"].items()
            if e["class"] == "object"
            and k.startswith("benchbox.")
            and e["disposition"] != "alias-to-note"
            and not covered(k, public)
        )
        pages.append(
            {
                "url": "/docs/" + rel,
                "source": source.relative_to(docs.parent).as_posix(),
                "note_anchor": NOTE_ANCHOR if page["has_note"] else None,
                "counts": dict(sorted(counts.items())),
                "ids": page["ids"],
            }
        )
    totals["ids"] = sum(len(p["ids"]) for p in pages)
    totals["bare_object_anchors"] = bare
    return {
        "source_sha": source_sha,
        "command": command,
        "policy": POLICY,
        "totals": dict(sorted(totals.items())),
        "documented_but_not_in_inventory": sorted(unexpected),
        "pages": sorted(pages, key=lambda p: p["url"]),
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the API reference URL map from a built Sphinx HTML tree.")
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--docs", type=Path, default=REPO_ROOT / "docs")
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arguments)
    portable = ["<built docs html dir>" if a == str(args.html) else a for a in arguments]
    command = shlex.join(["uv", "run", "--", "python", "scripts/api_reference_url_map.py", *portable])
    try:
        data = build_map(args.docs, args.html, args.symbols, args.source_sha, command)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.out.write_text(render(data), encoding="utf-8")
    print(f"wrote {args.out} ({data['totals']['ids']} ids across {len(data['pages'])} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
