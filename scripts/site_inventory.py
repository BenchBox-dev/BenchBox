#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

SCHEMA_VERSION = 1
INDEX_NAME = "index.json"
SHARD_BUDGET = 800_000
SHARD_LIMIT = 900_000
SHARDED_LISTS = ("paths", "chrome_links")
SITE_HOSTS = frozenset({"benchbox.dev", "www.benchbox.dev"})
SITE_ORIGIN = "https://benchbox.dev"
SPA_PREFIX = "/results/"
CHROME_SOURCE = "(site chrome)"
NOT_FOUND_PATH = "/404.html"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
HASHED_ASSET_RE = re.compile(r"^(/results/assets/.+?)-[A-Za-z0-9_-]{6,}(\.[A-Za-z0-9]+)$")
CAPTURE_SPEC = Path(__file__).resolve().parents[1] / "results-explorer/e2e/captures/public-site-pages.spec.ts"
CAPTURE_ROUTE_RE = re.compile(r'\bpath:\s*"(/[^"]*)"')
FAILING_KINDS = (
    "missing path",
    "missing fragment",
    "broken internal link",
    "missing image",
    "feed regression",
    "canonical loss",
    "404 fallback change",
)
INFO_KINDS = ("changed heading", "changed metadata", "unreferenced image", "stale allowance")
REPORT_KINDS = FAILING_KINDS + INFO_KINDS
HEADING_TAGS = frozenset({"h1", "h2", "h3"})
CHROME_TAGS = frozenset({"aside", "nav", "header", "footer"})
CONTENT_ASIDE_CLASS = "starlight-aside"
SKIPPED_HEADING_TEXT = "¶"
WHITESPACE_RE = re.compile(r"\s+")


def capture_routes(spec: Path = CAPTURE_SPEC) -> list[str]:
    routes = CAPTURE_ROUTE_RE.findall(spec.read_text(encoding="utf-8"))
    if not routes:
        raise ValueError(f"{spec}: no capture routes found")
    return routes


def _clean(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.replace(SKIPPED_HEADING_TEXT, "")).strip()


def internal_target(raw: str, page_path: str) -> tuple[str, str] | None:
    value = raw.strip()
    if not value:
        return None
    joined = urlsplit(urljoin(SITE_ORIGIN + page_path, value))
    if joined.scheme not in ("http", "https"):
        return None
    if joined.netloc.lower() not in SITE_HOSTS:
        return None
    return unquote(joined.path) or "/", unquote(joined.fragment)


def _target_key(target: tuple[str, str]) -> str:
    path, fragment = target
    return f"{path}#{fragment}" if fragment else path


class _PageParser(HTMLParser):
    def __init__(self, page_path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_path = page_path
        self.title_parts: list[str] = []
        self.description = ""
        self.canonical = ""
        self.h1: list[str] = []
        self.headings: list[list[str]] = []
        self.links: set[str] = set()
        self.chrome_links: set[str] = set()
        self._chrome_depth = 0
        self._chrome_stack: list[bool] = []
        self.images: set[str] = set()
        self.assets: set[str] = set()
        self.ids: set[str] = set()
        self._in_title = False
        self._title_seen = False
        self._svg_depth = 0
        self._body_seen = False
        self._heading: str | None = None
        self._heading_parts: list[str] = []

    def _add(self, bucket: set[str], raw: str | None) -> None:
        if raw is None:
            return
        target = internal_target(raw, self.page_path)
        if target is not None:
            bucket.add(_target_key(target))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"] or "")
        if tag in CHROME_TAGS:
            is_chrome = not (tag == "aside" and CONTENT_ASIDE_CLASS in (values.get("class") or "").split())
            self._chrome_stack.append(is_chrome)
            self._chrome_depth += is_chrome
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "body":
            self._body_seen = True
        if tag == "title":
            if not (self._svg_depth or self._body_seen or self._title_seen):
                self._in_title = True
                self._title_seen = True
        elif tag == "meta" and (values.get("name") or "").lower() == "description":
            self.description = _clean(values.get("content") or "")
        elif tag == "link":
            rels = (values.get("rel") or "").lower().split()
            if "canonical" in rels:
                self.canonical = (values.get("href") or "").strip()
            elif "stylesheet" in rels:
                self._add(self.assets, values.get("href"))
        elif tag == "script":
            self._add(self.assets, values.get("src"))
        elif tag == "a":
            self._add(self.chrome_links if self._chrome_depth else self.links, values.get("href"))
        elif tag == "img":
            self._add(self.images, values.get("src"))
        elif tag in HEADING_TAGS:
            self._heading = tag
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in CHROME_TAGS and self._chrome_stack:
            self._chrome_depth -= self._chrome_stack.pop()
        if tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        if tag == "title":
            self._in_title = False
        elif tag == self._heading:
            text = _clean("".join(self._heading_parts))
            if tag == "h1":
                self.h1.append(text)
            else:
                self.headings.append([tag, text])
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._heading is not None:
            self._heading_parts.append(data)

    def page(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "description": self.description,
            "h1": self.h1,
            "headings": self.headings,
            "ids": sorted(self.ids),
            "images": sorted(self.images),
            "links": sorted(self.links),
            "title": _clean("".join(self.title_parts)),
        }


def parse_page(page_path: str, markup: str) -> tuple[dict[str, Any], set[str], set[str]]:
    parser = _PageParser(page_path)
    parser.feed(markup)
    parser.close()
    return parser.page(), parser.chrome_links, parser.assets


def _link_hrefs(entry: ET.Element, page_path: str) -> list[str]:
    hrefs = []
    for link in entry.findall(f"{ATOM_NS}link"):
        href = link.get("href") or ""
        target = internal_target(href, page_path)
        hrefs.append(_target_key(target) if target else href)
    return sorted(hrefs)


def parse_feed(feed_path: str, text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    entries = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        entries.append(
            {
                "id": _clean(entry.findtext(f"{ATOM_NS}id") or ""),
                "links": _link_hrefs(entry, feed_path),
                "title": _clean(entry.findtext(f"{ATOM_NS}title") or ""),
            }
        )
    return sorted(entries, key=lambda item: (str(item["id"]), str(item["title"])))


def parse_not_found(markup: str) -> dict[str, Any]:
    return {
        "redirect_targets": sorted(set(re.findall(r"location\.replace\(\s*['\"]([^'\"]+)['\"]", markup))),
        "session_storage_keys": sorted(set(re.findall(r"['\"](benchbox\.[A-Za-z0-9_.-]+)['\"]", markup))),
        "spa_prefixes": sorted(set(re.findall(r"pathname\.startsWith\(\s*['\"]([^'\"]+)['\"]", markup))),
        "uses_session_storage": "sessionStorage" in markup,
    }


def resolve_path(path: str, served: frozenset[str]) -> str | None:
    candidates = [path]
    if path.endswith("/"):
        candidates.append(path + "index.html")
    else:
        candidates.extend([path + ".html", path + "/index.html"])
    for candidate in candidates:
        if candidate in served:
            return candidate
    return None


def _route_status(route: str, served: frozenset[str], spa: bool) -> str:
    resolved = resolve_path(route, served)
    if resolved is not None:
        return resolved
    return "spa-fallback" if spa and route.startswith(SPA_PREFIX) else ""


def build_inventory(site_dir: Path, source_sha: str | None = None) -> dict[str, Any]:
    root = site_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"site directory is missing: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    paths = sorted("/" + path.relative_to(root).as_posix() for path in files)
    served = frozenset(paths)
    pages: dict[str, Any] = {}
    chrome_links: set[str] = set()
    assets: set[str] = set()
    feeds: dict[str, Any] = {}
    for path in paths:
        if path.endswith(".html"):
            markup = (root / path.lstrip("/")).read_text(encoding="utf-8", errors="replace")
            pages[path], page_chrome, page_assets = parse_page(path, markup)
            chrome_links |= page_chrome
            assets |= page_assets
        elif path.endswith("/atom.xml") or path == "/atom.xml":
            feeds[path] = parse_feed(path, (root / path.lstrip("/")).read_text(encoding="utf-8"))
    not_found: dict[str, Any] = {"present": NOT_FOUND_PATH in served}
    if NOT_FOUND_PATH in served:
        not_found.update(parse_not_found((root / NOT_FOUND_PATH.lstrip("/")).read_text(encoding="utf-8")))
    spa = bool(not_found.get("session_storage_keys"))
    return {
        "assets": sorted(assets),
        "chrome_links": sorted(chrome_links),
        "feeds": feeds,
        "not_found": not_found,
        "page_count": len(pages),
        "pages": pages,
        "path_count": len(paths),
        "paths": paths,
        "routes": {route: _route_status(route, served, spa) for route in capture_routes()},
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
    }


def dump_inventory(inventory: Any) -> str:
    return json.dumps(inventory, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _encoded(value: Any) -> bytes:
    return dump_inventory(value).encode("utf-8")


def _chunks(items: list[tuple[str, Any]]) -> list[list[tuple[str, Any]]]:
    chunks: list[list[tuple[str, Any]]] = [[]]
    used = 0
    for key, value in items:
        size = len(_encoded({key: value}))
        if size > SHARD_BUDGET:
            raise ValueError(f"{key}: a single entry exceeds the shard budget ({size} bytes)")
        if chunks[-1] and used + size > SHARD_BUDGET:
            chunks.append([])
            used = 0
        chunks[-1].append((key, value))
        used += size
    return chunks


def _page_group(path: str) -> str:
    parts = path.strip("/").split("/")
    return parts[0] if len(parts) > 1 else "root"


def write_sharded(inventory: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.json"):
        stale.unlink()
    index = {key: value for key, value in inventory.items() if key not in ("pages", *SHARDED_LISTS)}
    shards: dict[str, list[str]] = {"pages": []}
    written: list[Path] = []

    def emit(name: str, payload: Any) -> None:
        target = output_dir / name
        target.write_text(dump_inventory(payload), encoding="utf-8")
        written.append(target)

    groups: dict[str, list[tuple[str, Any]]] = {}
    for path, page in sorted(inventory["pages"].items()):
        groups.setdefault(_page_group(path), []).append((path, page))
    for group, items in sorted(groups.items()):
        for number, chunk in enumerate(_chunks(items), start=1):
            name = f"pages-{group}-{number:03d}.json"
            emit(name, dict(chunk))
            shards["pages"].append(name)
    for field in SHARDED_LISTS:
        shards[field] = []
        for number, chunk in enumerate(_chunks([(value, None) for value in inventory[field]]), start=1):
            name = f"{field}-{number:03d}.json"
            emit(name, [key for key, _ in chunk])
            shards[field].append(name)
    index["shards"] = shards
    emit(INDEX_NAME, index)
    for target in written:
        if target.stat().st_size >= SHARD_LIMIT:
            raise ValueError(f"{target}: exceeds the {SHARD_LIMIT} byte shard limit")
    return sorted(written)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_inventory(path: Path) -> dict[str, Any]:
    if path.is_dir():
        data = _read_json(path / INDEX_NAME)
        shards = data.pop("shards")
        data["pages"] = {}
        for name in shards["pages"]:
            data["pages"].update(_read_json(path / name))
        for field in SHARDED_LISTS:
            data[field] = [item for name in shards[field] for item in _read_json(path / name)]
    else:
        data = _read_json(path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: unsupported inventory schema {data.get('schema_version')!r}")
    return data


def _split_key(key: str) -> tuple[str, str]:
    path, _, fragment = key.partition("#")
    return path, fragment


def _spa_enabled(inventory: dict[str, Any]) -> bool:
    return bool(inventory["not_found"].get("session_storage_keys"))


def broken_links(inventory: dict[str, Any]) -> set[tuple[str, str, str]]:
    served = frozenset(inventory["paths"])
    pages: dict[str, dict[str, Any]] = inventory["pages"]
    spa = _spa_enabled(inventory)
    sources = [(page_path, page["links"]) for page_path, page in pages.items()]
    sources.append((CHROME_SOURCE, inventory["chrome_links"]))
    for feed_path, entries in inventory.get("feeds", {}).items():
        feed_keys = {key for entry in entries for key in entry["links"] if internal_target(key, feed_path)}
        sources.append((feed_path, sorted(feed_keys)))
    found: set[tuple[str, str, str]] = set()
    for source, keys in sources:
        for key in keys:
            path, fragment = _split_key(key)
            resolved = resolve_path(path, served)
            if resolved is None:
                if not (spa and path.startswith(SPA_PREFIX)):
                    found.add((source, key, "missing path"))
                continue
            target_page = pages.get(resolved)
            if fragment and fragment != "top" and target_page is not None and fragment not in target_page["ids"]:
                found.add((source, key, "missing fragment"))
    return found


def missing_images(inventory: dict[str, Any]) -> set[tuple[str, str]]:
    served = frozenset(inventory["paths"])
    pages: dict[str, dict[str, Any]] = inventory["pages"]
    found: set[tuple[str, str]] = set()
    for page_path, page in pages.items():
        for key in page["images"]:
            if resolve_path(_split_key(key)[0], served) is None:
                found.add((page_path, key))
    return found


def _path_key(path: str) -> str:
    match = HASHED_ASSET_RE.match(path)
    return match.group(1) + match.group(2) if match else path


def load_expected_removals(path: Path) -> list[dict[str, str]]:
    entries = _read_json(path)
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a JSON list of removal entries")
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: entry {position} must be an object")
        target, reason = entry.get("path"), entry.get("reason")
        if not isinstance(target, str) or not target.startswith("/"):
            raise ValueError(f"{path}: entry {position} needs a 'path' starting with '/'")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path}: entry {position} ({target}) needs a nonempty 'reason'")
    return entries


def _entry_matches(pattern: str, key: str) -> bool:
    if "#" in pattern:
        return key == pattern
    if pattern.endswith(("/", "*")):
        return key.startswith(pattern.rstrip("*"))
    return _split_key(key)[0] == pattern


class _Allowances:
    def __init__(self, entries: list[dict[str, str]]) -> None:
        self.patterns = [entry["path"] for entry in entries]
        self.used: set[str] = set()

    def allows(self, key: str) -> bool:
        hit = False
        for pattern in self.patterns:
            if _entry_matches(pattern, key):
                self.used.add(pattern)
                hit = True
        return hit

    def stale(self) -> list[str]:
        return sorted(set(self.patterns) - self.used)


def _heading_changes(page_path: str, before: list[list[str]], after: list[list[str]]) -> list[str]:
    old = [tuple(heading) for heading in before]
    new = [tuple(heading) for heading in after]
    changes = []
    for operation, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if operation == "equal":
            continue
        changes.extend(
            f"{page_path} [headings]: removed {json.dumps(list(heading), ensure_ascii=False)}"
            for heading in old[old_start:old_end]
        )
        changes.extend(
            f"{page_path} [headings]: added {json.dumps(list(heading), ensure_ascii=False)}"
            for heading in new[new_start:new_end]
        )
    return changes


def _compare_pages(baseline: dict[str, Any], candidate: dict[str, Any], allow: _Allowances) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {kind: [] for kind in REPORT_KINDS}
    base_pages: dict[str, dict[str, Any]] = baseline["pages"]
    cand_pages: dict[str, dict[str, Any]] = candidate["pages"]
    for page_path in sorted(base_pages.keys() & cand_pages.keys()):
        before, after = base_pages[page_path], cand_pages[page_path]
        for field in ("title", "h1"):
            if before[field] != after[field]:
                found["changed heading"].append(
                    f"{page_path} [{field}]: {json.dumps(before[field], ensure_ascii=False)}"
                    f" -> {json.dumps(after[field], ensure_ascii=False)}"
                )
        found["changed heading"].extend(_heading_changes(page_path, before["headings"], after["headings"]))
        if before["description"] != after["description"]:
            found["changed metadata"].append(
                f"{page_path} [description]: {json.dumps(before['description'], ensure_ascii=False)}"
                f" -> {json.dumps(after['description'], ensure_ascii=False)}"
            )
        if before["canonical"] != after["canonical"]:
            kind = "canonical loss" if before["canonical"] and not after["canonical"] else "changed metadata"
            found[kind].append(f"{page_path} [canonical]: {before['canonical']!r} -> {after['canonical']!r}")
        for key in sorted(set(before["images"]) - set(after["images"])):
            found["unreferenced image"].append(f"{page_path}: {key} (no longer referenced)")
        for fragment in sorted(set(before["ids"]) - set(after["ids"])):
            if not allow.allows(f"{page_path}#{fragment}"):
                found["missing fragment"].append(f"{page_path}#{fragment}")
    return found


def _compare_feeds(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {kind: [] for kind in REPORT_KINDS}
    cand_feeds: dict[str, list[dict[str, Any]]] = candidate.get("feeds", {})
    for feed_path, base_entries in sorted(baseline.get("feeds", {}).items()):
        if feed_path not in cand_feeds:
            continue
        cand_entries = {entry["id"]: entry for entry in cand_feeds[feed_path]}
        for entry in base_entries:
            now = cand_entries.get(entry["id"])
            if now is None:
                found["feed regression"].append(f"{feed_path}: entry {entry['id']} removed")
                continue
            for link in sorted(set(entry["links"]) - set(now["links"])):
                found["feed regression"].append(f"{feed_path}: entry {entry['id']} lost link {link}")
            if entry["title"] != now["title"]:
                found["changed metadata"].append(
                    f"{feed_path}: entry {entry['id']} [title]: {entry['title']!r} -> {now['title']!r}"
                )
    return found


def _compare_not_found(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    before, after = baseline["not_found"], candidate["not_found"]
    if not before.get("present"):
        return []
    changes = []
    for field in ("redirect_targets", "session_storage_keys"):
        if before.get(field) != after.get(field):
            changes.append(f"{NOT_FOUND_PATH} [{field}]: {before.get(field)!r} -> {after.get(field)!r}")
    return changes


def diff_inventories(
    baseline: dict[str, Any], candidate: dict[str, Any], expected_removals: list[dict[str, str]] | None = None
) -> dict[str, list[str]]:
    allow = _Allowances(expected_removals or [])
    base_paths = {_path_key(path): path for path in baseline["paths"]}
    cand_keys = {_path_key(path) for path in candidate["paths"]}
    missing_paths = [path for key, path in base_paths.items() if key not in cand_keys and not allow.allows(path)]
    cand_routes: dict[str, str] = candidate["routes"]
    for route, status in baseline["routes"].items():
        if status and not cand_routes.get(route) and not allow.allows(route):
            missing_paths.append(f"{route} (capture route)")

    report = _compare_pages(baseline, candidate, allow)
    for kind, items in _compare_feeds(baseline, candidate).items():
        report[kind].extend(items)
    report["404 fallback change"] = _compare_not_found(baseline, candidate)
    new_broken = sorted(item for item in broken_links(candidate) - broken_links(baseline) if not allow.allows(item[1]))
    new_missing_images = sorted(missing_images(candidate) - missing_images(baseline))
    report["missing path"] = sorted(missing_paths)
    report["broken internal link"] = [f"{page}: {target} ({reason})" for page, target, reason in new_broken]
    report["missing image"] = [f"{page}: {key} (not served)" for page, key in new_missing_images]
    report["stale allowance"] = [f"{pattern} (matched nothing)" for pattern in allow.stale()]
    return {kind: sorted(report[kind]) if kind != "broken internal link" else report[kind] for kind in REPORT_KINDS}


APPROVAL_STATES = ("pending", "approved")


def load_allowed_differences(path: Path) -> list[dict[str, str]]:
    return validate_allowed_differences(_read_json(path), str(path))


def validate_allowed_differences(rules: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(rules, list):
        raise ValueError(f"{path}: expected a JSON list of allowed differences")
    seen: set[str] = set()
    for position, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"{path}: rule {position} must be an object")
        label = f"{path}: rule {position}"
        for field in ("id", "kind", "match", "reason"):
            if not isinstance(rule.get(field), str) or not rule[field].strip():
                raise ValueError(f"{label} needs a nonempty '{field}'")
        if rule["id"] in seen:
            raise ValueError(f"{label} repeats the id {rule['id']!r}")
        seen.add(rule["id"])
        if rule["kind"] not in REPORT_KINDS:
            raise ValueError(f"{label} ({rule['id']}) has the unknown kind {rule['kind']!r}")
        if rule.get("owner_approval") not in APPROVAL_STATES:
            raise ValueError(f"{label} ({rule['id']}) needs 'owner_approval' set to one of {APPROVAL_STATES}")
        try:
            re.compile(rule["match"])
        except re.error as exc:
            raise ValueError(f"{label} ({rule['id']}) has an invalid match pattern: {exc}") from exc
    return rules


def apply_allowed_differences(
    report: dict[str, list[str]], rules: list[dict[str, str]]
) -> tuple[dict[str, list[str]], dict[str, list[tuple[str, str]]]]:
    remaining: dict[str, list[str]] = {kind: [] for kind in REPORT_KINDS}
    allowed: dict[str, list[tuple[str, str]]] = {rule["id"]: [] for rule in rules}
    compiled = [(rule, re.compile(rule["match"])) for rule in rules]
    for kind in REPORT_KINDS:
        for item in report[kind]:
            owner = next((rule for rule, pattern in compiled if rule["kind"] == kind and pattern.fullmatch(item)), None)
            if owner is None:
                remaining[kind].append(item)
            else:
                allowed[owner["id"]].append((kind, item))
    remaining["stale allowance"].extend(
        f"{rule['id']} (matched nothing)"
        for rule in rules
        if not allowed[rule["id"]] and rule["kind"] != "stale allowance"
    )
    return remaining, allowed


def format_report(report: dict[str, list[str]]) -> str:
    lines = [f"{kind}: {item}" for kind in REPORT_KINDS for item in report[kind]]
    lines.append("summary: " + ", ".join(f"{len(report[kind])} {kind}" for kind in REPORT_KINDS))
    return "\n".join(lines) + "\n"


def exit_code(report: dict[str, list[str]], *, strict: bool) -> int:
    failing = FAILING_KINDS + INFO_KINDS if strict else FAILING_KINDS
    return 1 if any(report[kind] for kind in failing) else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inventory an assembled BenchBox public site")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write a site inventory as JSON")
    build.add_argument("--site-dir", type=Path, required=True)
    destination = build.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--output-dir", type=Path)
    build.add_argument("--source-sha")
    diff = commands.add_parser("diff", help="compare two inventories")
    diff.add_argument("--baseline", type=Path, required=True)
    diff.add_argument("--candidate", type=Path, required=True)
    diff.add_argument("--strict", action="store_true", help="also fail on informational changes")
    diff.add_argument(
        "--expected-removals", type=Path, action="append", help="reviewed JSON list of allowed removals; repeatable"
    )
    diff.add_argument(
        "--allowed-differences",
        type=Path,
        action="append",
        help="reviewed JSON list of pattern rules for allowed differences; repeatable",
    )
    check = commands.add_parser("check", help="report broken internal links and images in one inventory")
    check.add_argument("--inventory", type=Path, required=True)
    check.add_argument("--known-broken", type=Path)
    check.add_argument("--write-known-broken", type=Path)
    check.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="also fail when a --known-broken entry no longer matches a broken link, so it is removed with the fix",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            inventory = build_inventory(args.site_dir, args.source_sha)
            if args.output_dir is not None:
                files = write_sharded(inventory, args.output_dir)
                largest = max(file.stat().st_size for file in files)
                destination_label = f"{args.output_dir} ({len(files)} files, largest {largest} bytes)"
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(dump_inventory(inventory), encoding="utf-8")
                destination_label = str(args.output)
            print(f"wrote {destination_label}: {inventory['path_count']} paths, {inventory['page_count']} pages")
            return 0
        if args.command == "diff":
            removals = (
                [entry for path in args.expected_removals for entry in load_expected_removals(path)]
                if args.expected_removals
                else None
            )
            diff_report = diff_inventories(load_inventory(args.baseline), load_inventory(args.candidate), removals)
            if args.allowed_differences:
                rules = [rule for path in args.allowed_differences for rule in load_allowed_differences(path)]
                diff_report, _ = apply_allowed_differences(diff_report, rules)
            sys.stdout.write(format_report(diff_report))
            return exit_code(diff_report, strict=args.strict)
        inventory = load_inventory(args.inventory)
        broken = broken_links(inventory)
        if args.write_known_broken is not None:
            args.write_known_broken.parent.mkdir(parents=True, exist_ok=True)
            args.write_known_broken.write_text(dump_inventory(sorted(map(list, broken))), encoding="utf-8")
            print(f"wrote {args.write_known_broken}: {len(broken)} broken links")
            return 0
        allowed: set[tuple[str, str, str]] = set()
        if args.known_broken is not None:
            allowed = {(source, target, reason) for source, target, reason in _read_json(args.known_broken)}
        report: dict[str, list[str]] = {kind: [] for kind in REPORT_KINDS}
        report["broken internal link"] = [f"{p}: {t} ({r})" for p, t, r in sorted(broken - allowed)]
        report["stale allowance"] = [f"{p}: {t} ({r}) (no longer broken)" for p, t, r in sorted(allowed - broken)]
        report["missing image"] = [f"{p}: {k} (not served)" for p, k in sorted(missing_images(inventory))]
        sys.stdout.write(format_report(report))
        if args.fail_on_stale and report["stale allowance"]:
            print(f"remove the stale allowance(s) above from {args.known_broken}", file=sys.stderr)
            return 1
        return exit_code(report, strict=False)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"site_inventory: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
