#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import site_inventory as inventory_tool

DESIGN_DIR = REPO_ROOT / "_project" / "design" / "site-inventory"
DEFAULT_ALLOWED = DESIGN_DIR / "allowed-differences.json"
DEFAULT_REDIRECTS = DESIGN_DIR / "redirect-pages.json"
DEFAULT_ADDED = DESIGN_DIR / "added-paths.json"
DEFAULT_INVENTORY_LOSSES = DESIGN_DIR / "allowed-inventory-losses.json"
DEFAULT_KNOWN_BROKEN = DESIGN_DIR / "known-broken-links.json"
DEFAULT_API_MAP = DESIGN_DIR / "api-reference-url-map.json"
DEFAULT_PUBLISHED = DESIGN_DIR / "baseline-develop"
REPORT_JSON = "url-compatibility-report.json"
REPORT_MARKDOWN = "url-compatibility-report.md"
SAME_TREE = "same-tree Sphinx build"
PUBLISHED = "published baseline"
SITE_ORIGIN = "https://benchbox.dev"
PENDING = "pending"
PASS = "PASS"
FAIL = "FAIL"
REDIRECT_META = re.compile(
    r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>\s]+)""", re.IGNORECASE
)
REDIRECT_SCRIPT = re.compile(r"""location\.(?:replace\(\s*|href\s*=\s*)['"]([^'"]+)['"]""")
MISSING_FRAGMENT_LINK = re.compile(r"\(missing fragment\)$")
SAMPLE_LIMIT = 5
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("blog tag pages", r"^/blog/tag(/|\.html)"),
    ("blog archives and authors", r"^/blog/(archive\.html|drafts\.html|\d{4}\.html|author(/|\.html))"),
    ("blog series and categories", r"^/blog/(category|series)(/|\.html)"),
    ("docs tag pages", r"^/docs/_tags/"),
    ("generated query pages", r"^/docs/benchmarks/queries/"),
    ("API reference pages", r"^/docs/(api\.html|reference/python-api/)"),
    ("Explorer routes", r"^/results/(?!assets/|data/)"),
)
MISSING_CLASSES: tuple[tuple[str, str], ...] = (
    ("Sphinx theme and extension assets", r"^/(docs/)?_static/|^/docs/_sphinx_design_static/"),
    ("Sphinx build files", r"^/docs/(\.buildinfo|objects\.inv|searchindex\.js)$"),
    ("Sphinx generated pages", r"^/docs/(genindex|search|blog)\.html$"),
    ("documentation downloads", r"^/docs/_downloads/"),
    ("documentation images", r"^/docs/_images/"),
    ("landing page assets", r"^/(style\.css|script\.js|shared/)"),
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_entries(path: Path, entries: Any, fields: Sequence[str]) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a JSON list")
    for position, entry in enumerate(entries):
        for field in fields:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"{path}: entry {position} needs a nonempty '{field}'")
        if entry.get("owner_approval") not in inventory_tool.APPROVAL_STATES:
            raise ValueError(f"{path}: entry {position} needs 'owner_approval' in {inventory_tool.APPROVAL_STATES}")
    return entries


def load_redirect_pages(path: Path) -> list[dict[str, str]]:
    return _check_entries(path, _read_json(path), ("path", "target", "reason"))


def load_added_paths(path: Path) -> list[dict[str, str]]:
    return _check_entries(path, _read_json(path), ("path", "reason"))


def find_redirects(site_dir: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for page in sorted(site_dir.rglob("*.html")):
        path = "/" + page.relative_to(site_dir).as_posix()
        if path.startswith("/results/assets/"):
            continue
        markup = page.read_text(encoding="utf-8", errors="replace")
        match = REDIRECT_META.search(markup) or REDIRECT_SCRIPT.search(markup)
        if match:
            found[path] = match.group(1)
    return found


def removal_entries(files: Sequence[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for file in files:
        for entry in inventory_tool.load_expected_removals(file):
            approval = entry.get("owner_approval", PENDING)
            if approval not in inventory_tool.APPROVAL_STATES:
                raise ValueError(f"{file}: {entry['path']} has owner_approval {approval!r}")
            entries.append({**entry, "source": file.name, "owner_approval": approval})
    return entries


def _removal_matches(entry: dict[str, Any], raw: dict[str, list[str]]) -> list[str]:
    kind = "missing fragment" if "#" in entry["path"] else "missing path"
    return [
        item
        for item in raw[kind]
        if inventory_tool._entry_matches(entry["path"], item.removesuffix(" (capture route)"))
    ]


def _pattern_class(path: str, classes: Sequence[tuple[str, str]], fallback: str) -> str:
    return next((label for label, pattern in classes if re.search(pattern, path)), fallback)


def _category_rows(baseline: dict[str, Any], candidate: dict[str, Any], missing: set[str]) -> list[dict[str, Any]]:
    rows = []
    for name, pattern in CATEGORIES:
        compiled = re.compile(pattern)
        base_paths = [path for path in baseline["paths"] if compiled.match(path)]
        rows.append(
            {
                "category": name,
                "baseline": len(base_paths),
                "candidate": sum(1 for path in candidate["paths"] if compiled.match(path)),
                "missing": sum(1 for path in base_paths if path in missing),
            }
        )
    return rows


def _feed_rows(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for feed_path, base_entries in sorted(baseline.get("feeds", {}).items()):
        base_ids = {entry["id"] for entry in base_entries}
        cand_ids = {entry["id"] for entry in candidate.get("feeds", {}).get(feed_path, [])}
        rows.append(
            {
                "feed": feed_path,
                "baseline_ids": len(base_ids),
                "candidate_ids": len(cand_ids),
                "lost_ids": sorted(base_ids - cand_ids),
                "added_ids": sorted(cand_ids - base_ids),
            }
        )
    return rows


def _allowed_rows(
    entries: list[dict[str, Any]],
    rules: list[dict[str, str]],
    raw: dict[str, list[str]],
    matched: dict[str, list[tuple[str, str]]],
) -> list[dict[str, Any]]:
    rows = []
    for entry in entries:
        items = _removal_matches(entry, raw)
        rows.append(
            {
                "id": entry["path"],
                "kind": "missing fragment" if "#" in entry["path"] else "missing path",
                "source": entry["source"],
                "reason": entry["reason"],
                "owner_approval": entry["owner_approval"],
                "items": items,
            }
        )
    for rule in rules:
        rows.append(
            {
                "id": rule["id"],
                "kind": rule["kind"],
                "source": DEFAULT_ALLOWED.name,
                "reason": rule["reason"],
                "owner_approval": rule["owner_approval"],
                "items": [item for _, item in matched[rule["id"]]],
            }
        )
    return rows


def compare(
    label: str,
    gating: bool,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    entries: list[dict[str, Any]],
    rules: list[dict[str, str]],
    added_rules: list[dict[str, str]],
) -> dict[str, Any]:
    raw = inventory_tool.diff_inventories(baseline, candidate, None)
    after_removals = inventory_tool.diff_inventories(baseline, candidate, entries)
    remaining, matched = inventory_tool.apply_allowed_differences(after_removals, rules)
    remaining["stale allowance"] = []
    missing = {item.removesuffix(" (capture route)") for item in remaining["missing path"]}
    by_class: dict[str, list[str]] = {}
    for path in sorted(missing):
        by_class.setdefault(_pattern_class(path, MISSING_CLASSES, "other"), []).append(path)
    baseline_keys = {inventory_tool._path_key(path) for path in baseline["paths"]}
    added = [path for path in candidate["paths"] if inventory_tool._path_key(path) not in baseline_keys]
    unreviewed = [
        path for path in added if not any(inventory_tool._entry_matches(rule["path"], path) for rule in added_rules)
    ]
    broken_fragments = remaining["missing fragment"] + [
        item for item in remaining["broken internal link"] if MISSING_FRAGMENT_LINK.search(item)
    ]
    broken_urls = remaining["missing path"] + [
        item for item in remaining["broken internal link"] if not MISSING_FRAGMENT_LINK.search(item)
    ]
    return {
        "label": label,
        "gating": gating,
        "baseline_source_sha": baseline.get("source_sha"),
        "baseline_paths": baseline["path_count"],
        "baseline_pages": baseline["page_count"],
        "broken_url_items": broken_urls,
        "broken_fragment_items": broken_fragments,
        "by_kind": {
            kind: {
                "found": len(raw[kind]),
                "allowed": len(raw[kind]) - len(remaining[kind]),
                "remaining": len(remaining[kind]),
            }
            for kind in inventory_tool.REPORT_KINDS
            if kind != "stale allowance"
        },
        "remaining": {kind: remaining[kind] for kind in inventory_tool.REPORT_KINDS if remaining[kind]},
        "missing_by_class": by_class,
        "categories": _category_rows(baseline, candidate, missing),
        "feeds": _feed_rows(baseline, candidate),
        "added_paths": {
            "total": len(added),
            "unreviewed": unreviewed,
            "by_rule": {
                rule["path"]: [path for path in added if inventory_tool._entry_matches(rule["path"], path)]
                for rule in added_rules
            },
        },
        "allowed": _allowed_rows(entries, rules, raw, matched),
    }


def api_map_check(api_map: dict[str, Any], candidate: dict[str, Any], rules: list[dict[str, str]]) -> dict[str, Any]:
    served = frozenset(candidate["paths"])
    pages: dict[str, Any] = candidate["pages"]
    missing_pages: list[str] = []
    missing_ids: list[str] = []
    allowed_ids: list[str] = []
    patterns = [re.compile(rule["match"]) for rule in rules if rule["kind"] == "missing fragment"]
    total = 0
    for entry in api_map["pages"]:
        resolved = inventory_tool.resolve_path(entry["url"], served)
        if resolved is None or resolved not in pages:
            missing_pages.append(entry["url"])
            continue
        present = set(pages[resolved]["ids"])
        wanted = list(entry["ids"])
        if entry["note_anchor"]:
            wanted.append(entry["note_anchor"])
        total += len(wanted)
        for identifier in wanted:
            key = f"{entry['url']}#{identifier}"
            if identifier in present:
                continue
            (allowed_ids if any(pattern.fullmatch(key) for pattern in patterns) else missing_ids).append(key)
    return {
        "pages": len(api_map["pages"]),
        "ids": total,
        "missing_pages": missing_pages,
        "missing_ids": missing_ids,
        "allowed_ids": allowed_ids,
    }


def link_checks(candidate: dict[str, Any], known_broken: Path) -> dict[str, Any]:
    allowed = {tuple(entry) for entry in _read_json(known_broken)}
    broken = inventory_tool.broken_links(candidate)
    return {
        "broken_total": len(broken),
        "known_in_both": len(broken & allowed),
        "beyond_known": [f"{source}: {target} ({reason})" for source, target, reason in sorted(broken - allowed)],
        "known_now_fixed": len(allowed - broken),
    }


def redirect_checks(baseline_site: Path | None, candidate_site: Path, declared: list[dict[str, str]]) -> dict[str, Any]:
    found = find_redirects(candidate_site)
    known = {entry["path"]: entry for entry in declared}
    listed = [
        {
            "path": path,
            "target": target,
            "reason": known[path]["reason"] if path in known else "",
            "owner_approval": known[path]["owner_approval"] if path in known else PENDING,
            "declared": path in known,
            "target_matches": path in known and known[path]["target"] == target,
        }
        for path, target in sorted(found.items())
    ]
    return {
        "pages": listed,
        "undeclared": [row["path"] for row in listed if not row["declared"]],
        "target_changed": [row["path"] for row in listed if row["declared"] and not row["target_matches"]],
        "declared_missing": sorted(set(known) - set(found)),
        "baseline_redirects_lost": sorted(set(find_redirects(baseline_site)) - set(found)) if baseline_site else [],
    }


INVENTORY_LINE = re.compile(r"(?P<name>.+?)\s+(?P<role>\S+)\s+(?P<priority>-?\d+)\s+(?P<uri>\S*)\s+(?P<title>.*)")


def parse_inventory(path: Path) -> dict[tuple[str, str], str]:
    raw = path.read_bytes()
    header, position = [], 0
    for _ in range(4):
        end = raw.index(b"\n", position)
        header.append(raw[position:end].decode("utf-8"))
        position = end + 1
    if header[0] != "# Sphinx inventory version 2":
        raise ValueError(f"{path}: not a Sphinx version 2 inventory")
    entries: dict[tuple[str, str], str] = {}
    for line in zlib.decompress(raw[position:]).decode("utf-8").splitlines():
        match = INVENTORY_LINE.fullmatch(line)
        if match:
            entries[(match["role"], match["name"])] = match["uri"]
    return entries


def load_inventory_losses(path: Path) -> list[dict[str, str]]:
    return _check_entries(path, _read_json(path), ("id", "reason"))


OFF_SITE = "\0off-site"


def _resolved(uri: str, name: str) -> tuple[str, str]:
    parts = urlsplit(urljoin(f"{SITE_ORIGIN}/docs/", uri.replace("$", name)))
    if f"{parts.scheme}://{parts.netloc}" != SITE_ORIGIN:
        return OFF_SITE, ""
    return parts.path, parts.fragment


def _blog_mapping(before: tuple[str, str], target: tuple[str, str], name: str) -> bool:
    path, _ = before
    return (
        path.startswith("/docs/blog/")
        and target[0] == path.replace("/docs/blog/", "/blog/", 1)
        and target[1] in ("", name)
    )


def _dangling(path: str, fragment: str, inventory: dict[str, Any]) -> bool:
    served = frozenset(inventory["paths"])
    resolved = inventory_tool.resolve_path(path, served)
    if resolved is None:
        return True
    page = inventory["pages"].get(resolved)
    if not fragment:
        return False
    return page is None or fragment not in page["ids"]


def inventory_check(
    baseline_site: Path | None,
    candidate_site: Path,
    baseline: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    allowed: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if baseline_site is None or baseline is None or candidate is None:
        return {
            "baseline": 0,
            "candidate": 0,
            "lost": [],
            "allowed": [],
            "added": 0,
            "uri_problems": [],
            "validity_only": 0,
        }
    old = parse_inventory(baseline_site / "docs" / "objects.inv")
    new = parse_inventory(candidate_site / "docs" / "objects.inv")
    lost = [f"{role} {name}" for role, name in sorted(set(old) - set(new))]
    permitted = {entry["id"] for entry in allowed or []}
    problems = []
    validity_only = 0
    for (role, name), uri in sorted(new.items()):
        target = _resolved(uri, name)
        if _dangling(*target, candidate):
            problems.append(f"{role} {name}: {uri} does not resolve in the Astro site")
            continue
        if (role, name) in old:
            before = _resolved(old[(role, name)], name)
            if _dangling(*before, baseline) and _blog_mapping(before, target, name):
                validity_only += 1
            elif before != target:
                problems.append(f"{role} {name}: {old[(role, name)]} in Sphinx, {uri} in Astro")
    return {
        "baseline": len(old),
        "candidate": len(new),
        "lost": [entry for entry in lost if entry not in permitted],
        "allowed": [entry for entry in lost if entry in permitted],
        "added": len(set(new) - set(old)),
        "uri_problems": problems,
        "validity_only": validity_only,
    }


def canonical_check(candidate: dict[str, Any], redirects: dict[str, str]) -> list[str]:
    problems = []
    for path, page in sorted(candidate["pages"].items()):
        if path == "/results/index.html":
            expected = f"{SITE_ORIGIN}/results/"
        elif path in redirects:
            expected = f"{SITE_ORIGIN}{redirects[path]}"
        elif path == "/index.html":
            expected = f"{SITE_ORIGIN}/"
        else:
            expected = f"{SITE_ORIGIN}{path}"
        if page["canonical"] != expected:
            problems.append(f"{path}: canonical {page['canonical']!r}, expected {expected!r}")
    return problems


def e2e_summary(paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if not path.is_file():
            rows.append({"report": path.name, "failures": ["the expected browser report is missing"], "checks": 0})
            continue
        data = _read_json(path)
        rows.append(
            {"report": path.name, "failures": list(data.get("failures", [])), "checks": len(data.get("axe", {}))}
        )
    return rows


def step_summary(paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if not path.is_file():
            rows.append({"check": path.stem, "exit": None, "failures": [f"{path.stem}: the step result is missing"]})
            continue
        data = _read_json(path)
        failed = data.get("exit") != 0
        failures = [f"{data['check']} exited {data.get('exit')}"] if failed else []
        rows.append({"check": data["check"], "exit": data.get("exit"), "failures": failures})
    return rows


def _merge_allowed(comparisons: list[dict[str, Any]], added_rules: list[dict[str, str]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for comparison in comparisons:
        for row in comparison["allowed"]:
            entry = merged.setdefault(
                row["id"], {**{k: v for k, v in row.items() if k != "items"}, "matches": {}, "samples": []}
            )
            entry["matches"][comparison["label"]] = len(row["items"])
            entry["samples"].extend(item for item in row["items"][:SAMPLE_LIMIT] if item not in entry["samples"])
            entry.setdefault("items", set()).update(row["items"])
    for rule in added_rules:
        found = {comparison["label"]: comparison["added_paths"]["by_rule"][rule["path"]] for comparison in comparisons}
        merged[f"added:{rule['path']}"] = {
            "id": rule["path"],
            "kind": "added path",
            "source": DEFAULT_ADDED.name,
            "reason": rule["reason"],
            "owner_approval": rule["owner_approval"],
            "matches": {label: len(paths) for label, paths in found.items()},
            "samples": sorted({path for paths in found.values() for path in paths})[:SAMPLE_LIMIT],
            "items": {path for paths in found.values() for path in paths},
        }
    rows = []
    for entry in merged.values():
        entry["count"] = len(entry.pop("items", ()))
        entry["samples"] = entry["samples"][:SAMPLE_LIMIT]
        rows.append(entry)
    return rows


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    candidate = inventory_tool.load_inventory(args.candidate)
    rules = inventory_tool.load_allowed_differences(args.allowed_differences)
    added_rules = load_added_paths(args.added_paths)
    entries = removal_entries(args.expected_removals)
    sources = [(SAME_TREE, True, args.baseline)]
    if args.published_baseline is not None:
        sources.append((PUBLISHED, False, args.published_baseline))
    comparisons = [
        compare(label, gating, inventory_tool.load_inventory(path), candidate, entries, rules, added_rules)
        for label, gating, path in sources
    ]
    gated = [comparison for comparison in comparisons if comparison["gating"]]
    drift = [comparison for comparison in comparisons if not comparison["gating"]]
    links = link_checks(candidate, args.known_broken)
    api = api_map_check(_read_json(args.api_map), candidate, rules)
    redirects = redirect_checks(args.baseline_site, args.candidate_site, load_redirect_pages(args.redirect_pages))
    e2e = e2e_summary(args.e2e_report or [])
    steps = step_summary(args.step_result or [])
    inventory_losses = load_inventory_losses(args.allowed_inventory_losses)
    baseline_inventory = inventory_tool.load_inventory(args.baseline)
    inventory = inventory_check(
        args.baseline_site, args.candidate_site, baseline_inventory, candidate, inventory_losses
    )
    meta_redirects = {
        row["path"]: row["target"] for row in redirects["pages"] if row["path"] != "/404.html" and row["declared"]
    }
    canonicals = canonical_check(candidate, meta_redirects)
    allowed = _merge_allowed(comparisons, added_rules)
    allowed.extend(
        {
            "id": entry["id"],
            "kind": "inventory entry",
            "source": DEFAULT_INVENTORY_LOSSES.name,
            "reason": entry["reason"],
            "owner_approval": entry["owner_approval"],
            "matches": {},
            "samples": [],
            "count": int(entry["id"] in inventory["allowed"]),
        }
        for entry in inventory_losses
    )
    differences: dict[str, dict[str, list[str]]] = {}
    for comparison in gated:
        for kind, items in comparison["remaining"].items():
            for item in items:
                differences.setdefault(f"{kind}: {item}", {"comparisons": []})["comparisons"].append(
                    comparison["label"]
                )
    problems = {
        "differences": [
            {"finding": finding, "comparisons": found["comparisons"]} for finding, found in sorted(differences.items())
        ],
        "links_beyond_known_list": links["beyond_known"],
        "api_url_map": api["missing_pages"] + api["missing_ids"],
        "atom_entry_ids": [
            f"{comparison['label']}: {row['feed']}: {identifier}"
            for comparison in gated
            for row in comparison["feeds"]
            for identifier in row["lost_ids"]
        ],
        "redirect_pages": redirects["undeclared"]
        + redirects["target_changed"]
        + [f"declared but not built: {path}" for path in redirects["declared_missing"]]
        + [f"present in the Sphinx site and gone: {path}" for path in redirects["baseline_redirects_lost"]],
        "unreviewed_added_paths": [path for comparison in gated for path in comparison["added_paths"]["unreviewed"]],
        "objects_inventory": inventory["lost"] + inventory["uri_problems"],
        "canonical_links": canonicals,
        "gate_steps": [failure for row in steps for failure in row["failures"]],
        "browser_checks": [f"{row['report']}: {failure}" for row in e2e for failure in row["failures"]],
    }
    return {
        "verdict": FAIL if any(problems.values()) else PASS,
        "source_sha": candidate.get("source_sha"),
        "owner_approval": PENDING,
        "broken_public_urls": len({item for comparison in gated for item in comparison["broken_url_items"]}),
        "broken_fragments": len({item for comparison in gated for item in comparison["broken_fragment_items"]}),
        "changed_since_published": {
            "urls": len({item for comparison in drift for item in comparison["broken_url_items"]}),
            "fragments": len({item for comparison in drift for item in comparison["broken_fragment_items"]}),
            "headings": sum(len(comparison["remaining"].get("changed heading", [])) for comparison in drift),
        },
        "candidate_paths": candidate["path_count"],
        "candidate_pages": candidate["page_count"],
        "comparisons": comparisons,
        "real_breakage": problems,
        "api_url_map": api,
        "links": links,
        "redirects": redirects,
        "browser": e2e,
        "steps": steps,
        "objects_inventory": inventory,
        "allowed_differences": allowed,
        "unused_allowances": sorted(row["id"] for row in allowed if not row["count"]),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines + [""]


def _breakage_rows(problems: dict[str, list[Any]]) -> list[list[str]]:
    rows = []
    collapsed = 0
    for group, items in problems.items():
        for item in items:
            if isinstance(item, dict) and item["finding"].startswith("missing path: "):
                collapsed += 1
            elif isinstance(item, dict):
                rows.append([group.replace("_", " "), f"{item['finding']} ({', '.join(item['comparisons'])})"])
            else:
                rows.append([group.replace("_", " "), item])
    if collapsed:
        rows.insert(0, ["differences", f"{collapsed} missing paths, listed by class in the next section"])
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# URL compatibility report",
        "",
        f"Verdict: {report['verdict']}",
        "",
        f"Source SHA: {report['source_sha']}",
        "",
        f"Owner approval: {report['owner_approval']}",
        "",
        "## Summary",
        "",
    ]
    lines += _table(
        ["Measure", "Value"],
        [
            ["Public paths in the Astro site", report["candidate_paths"]],
            ["Pages in the Astro site", report["candidate_pages"]],
            ["Broken public URLs (Sphinx and Astro built from one tree)", report["broken_public_urls"]],
            ["Broken fragments (Sphinx and Astro built from one tree)", report["broken_fragments"]],
            [
                "Paths missing from the Astro site, against the published baseline (informational)",
                report["changed_since_published"]["urls"],
            ],
            [
                "Fragments missing from the Astro site, against the published baseline (informational)",
                report["changed_since_published"]["fragments"],
            ],
            ["Redirect pages", len(report["redirects"]["pages"])],
            ["Allowed differences (rules and entries)", len(report["allowed_differences"])],
            ["Allowances that matched nothing", len(report["unused_allowances"])],
        ],
    )
    for comparison in report["comparisons"]:
        scope = "gating" if comparison["gating"] else "informational, content changed since the baseline was taken"
        lines += [f"## Differences by kind: {comparison['label']} ({scope})", ""]
        lines += [
            f"Baseline paths {comparison['baseline_paths']}, baseline pages {comparison['baseline_pages']}, "
            f"baseline source {comparison['baseline_source_sha']}.",
            "",
        ]
        lines += _table(
            ["Kind", "Found", "Allowed", "Remaining"],
            [[kind, row["found"], row["allowed"], row["remaining"]] for kind, row in comparison["by_kind"].items()],
        )
    lines += ["## Real breakage", ""]
    rows = _breakage_rows(report["real_breakage"])
    lines += _table(["Check", "Finding"], rows) if rows else ["None.", ""]
    lines += ["## Missing paths that no allowance covers, by class", ""]
    classes = {
        name: paths
        for comparison in report["comparisons"]
        if comparison["gating"]
        for name, paths in comparison["missing_by_class"].items()
    }
    class_rows = [[name, len(paths), ", ".join(paths[:SAMPLE_LIMIT])] for name, paths in sorted(classes.items())]
    lines += _table(["Class", "Paths", "Examples"], class_rows) if class_rows else ["None.", ""]
    lines += ["## Checks", ""]
    for comparison in report["comparisons"]:
        lines += [f"### {comparison['label']}", ""]
        lines += _table(
            ["Category", "Baseline paths", "Astro paths", "Missing"],
            [[row["category"], row["baseline"], row["candidate"], row["missing"]] for row in comparison["categories"]],
        )
        lines += _table(
            ["Atom feed", "Baseline entry ids", "Astro entry ids", "Lost ids", "Added ids"],
            [
                [row["feed"], row["baseline_ids"], row["candidate_ids"], len(row["lost_ids"]), len(row["added_ids"])]
                for row in comparison["feeds"]
            ],
        )
        added = comparison["added_paths"]
        lines += [
            f"Paths only in the Astro site: {added['total']}, of which {len(added['unreviewed'])} unreviewed.",
            "",
        ]
    api, links = report["api_url_map"], report["links"]
    lines += _table(
        ["Check", "Result"],
        [
            ["API URL map pages", api["pages"]],
            ["API URL map anchors checked", api["ids"]],
            ["API URL map missing pages", len(api["missing_pages"])],
            ["API URL map anchors missing but allowed (retired theme ids)", len(api["allowed_ids"])],
            ["API URL map missing anchors", len(api["missing_ids"])],
            ["Broken internal links in the Astro site", links["broken_total"]],
            ["Of those, broken in both renderers and listed as known", links["known_in_both"]],
            ["Of those, beyond the known list", len(links["beyond_known"])],
            ["Known-broken entries now fixed", links["known_now_fixed"]],
        ],
    )
    inventory = report["objects_inventory"]
    lines += _table(
        ["Objects inventory", "Entries"],
        [
            ["Sphinx entries", inventory["baseline"]],
            ["Astro entries", inventory["candidate"]],
            ["Sphinx entries lost", len(inventory["lost"])],
            ["Entries whose address does not resolve or differs from Sphinx", len(inventory["uri_problems"])],
            ["Entries checked for validity only (blog pages moved out of docs)", inventory["validity_only"]],
        ],
    )
    if report["steps"]:
        lines += _table(["Gate step", "Exit status"], [[row["check"], row["exit"]] for row in report["steps"]])
    if report["browser"]:
        lines += _table(
            ["Browser report", "Axe checks", "Failures"],
            [[row["report"], row["checks"], len(row["failures"])] for row in report["browser"]],
        )
    lines += ["## Redirect pages", ""]
    redirect_rows = [
        [row["path"], row["target"], row["reason"] or "undeclared", row["owner_approval"]]
        for row in report["redirects"]["pages"]
    ]
    lines += _table(["Page", "Target", "Reason", "Owner approval"], redirect_rows) if redirect_rows else ["None.", ""]
    lines += ["## Allowed differences", ""]
    lines += _table(
        ["Rule or path", "Kind", "Matches", "Reason", "Owner approval"],
        [
            [row["id"], row["kind"], row["count"], row["reason"], row["owner_approval"]]
            for row in report["allowed_differences"]
        ],
    )
    added_rows = [row for row in report["allowed_differences"] if row["kind"] == "added path"]
    if added_rows:
        lines += ["## Added paths by rule", ""]
        lines += _table(
            ["Rule", "Paths matched", "Examples"],
            [[row["id"], row["count"], ", ".join(row["samples"])] for row in added_rows],
        )
    if report["unused_allowances"]:
        lines += ["## Warnings: allowances that matched nothing", ""]
        lines += [f"- {identifier}" for identifier in report["unused_allowances"]] + [""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare the Sphinx and Astro public sites and write the URL report")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--published-baseline", type=Path, nargs="?", const=DEFAULT_PUBLISHED)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-site", type=Path)
    parser.add_argument("--candidate-site", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-removals", type=Path, action="append")
    parser.add_argument("--allowed-differences", type=Path, default=DEFAULT_ALLOWED)
    parser.add_argument("--redirect-pages", type=Path, default=DEFAULT_REDIRECTS)
    parser.add_argument("--added-paths", type=Path, default=DEFAULT_ADDED)
    parser.add_argument("--allowed-inventory-losses", type=Path, default=DEFAULT_INVENTORY_LOSSES)
    parser.add_argument("--known-broken", type=Path, default=DEFAULT_KNOWN_BROKEN)
    parser.add_argument("--api-map", type=Path, default=DEFAULT_API_MAP)
    parser.add_argument("--e2e-report", type=Path, action="append")
    parser.add_argument("--step-result", type=Path, action="append")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.expected_removals:
        args.expected_removals = sorted(DESIGN_DIR.glob("expected-removals-*.json"))
    try:
        report = build_report(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"site_parity: {exc}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / REPORT_JSON).write_text(inventory_tool.dump_inventory(report), encoding="utf-8")
    (args.output_dir / REPORT_MARKDOWN).write_text(render_markdown(report), encoding="utf-8")
    print(f"url compatibility: {report['verdict']}")
    print(f"broken public URLs {report['broken_public_urls']}, broken fragments {report['broken_fragments']}")
    for group, items in report["real_breakage"].items():
        if items:
            print(f"real breakage: {group}: {len(items)}")
    return 0 if report["verdict"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
