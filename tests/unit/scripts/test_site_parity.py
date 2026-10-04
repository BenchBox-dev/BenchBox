from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import site_inventory, site_parity
from scripts.assemble_public_site import RESULTS_FALLBACK

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>https://benchbox.dev/blog/a.html</id><title>First</title><link href="{link}"/></entry>
</feed>
"""

THEME_RULE = {
    "id": "theme-ids",
    "kind": "missing fragment",
    "match": r".*#(__toc|svg-[a-z]+)",
    "reason": "theme ids belong to the retired Sphinx theme",
    "owner_approval": "pending",
}
FEED_RULE = {
    "id": "feed-links",
    "kind": "feed regression",
    "match": r".* lost link /blog/blog/.*",
    "reason": "the retired feed linked paths that never existed",
    "owner_approval": "pending",
}
REDIRECT = {
    "path": "/404.html",
    "target": "/results/",
    "reason": "the fallback restores Explorer deep links",
    "owner_approval": "pending",
}
ADDED = {"path": "/sitemap.xml", "reason": "new file", "owner_approval": "pending"}


def _write(root: Path, name: str, content: str = "x") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _site(root: Path, *, theme: bool, feed_link: str, tag: bool = True) -> Path:
    toc = '<div id="__toc"></div><svg id="svg-sun"></svg>' if theme else ""
    _write(root, "index.html", "<title>Home</title><h1>Home</h1>")
    _write(root, "docs/api.html", f'<title>API</title><h1 id="api">API</h1><dt id="benchbox.TPCH"></dt>{toc}')
    _write(root, "blog/a.html", "<title>A</title><h1>A</h1>")
    _write(root, "blog/atom.xml", ATOM.format(link=feed_link))
    if tag:
        _write(root, "blog/tag/duckdb.html", "<title>duckdb</title><h1>duckdb</h1>")
    _write(root, "results/index.html", "<title>Results</title><h1>Results</h1>")
    _write(root, "404.html", RESULTS_FALLBACK)
    return root


def _inventory(site: Path, destination: Path) -> Path:
    site_inventory.write_sharded(site_inventory.build_inventory(site, "abc123"), destination)
    return destination


def _json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _api_map(path: Path, ids: list[str]) -> Path:
    page = {"url": "/docs/api.html", "ids": {name: {} for name in ids}, "note_anchor": None}
    return _json(path, {"pages": [page]})


def _run(
    tmp_path: Path,
    baseline: Path,
    candidate: Path,
    *,
    rules: list[dict[str, str]] | None = None,
    api_ids: list[str] | None = None,
    published: Path | None = None,
    extra: list[str] | None = None,
) -> tuple[int, dict]:
    out = tmp_path / "report"
    argv = [
        "--baseline",
        str(_inventory(baseline, tmp_path / "inv-base")),
        "--candidate",
        str(_inventory(candidate, tmp_path / "inv-cand")),
        "--baseline-site",
        str(baseline),
        "--candidate-site",
        str(candidate),
        "--output-dir",
        str(out),
        "--expected-removals",
        str(_json(tmp_path / "removals.json", [])),
        "--allowed-differences",
        str(_json(tmp_path / "allowed.json", [THEME_RULE, FEED_RULE] if rules is None else rules)),
        "--redirect-pages",
        str(_json(tmp_path / "redirects.json", [REDIRECT])),
        "--added-paths",
        str(_json(tmp_path / "added.json", [ADDED])),
        "--known-broken",
        str(_json(tmp_path / "known.json", [])),
        "--api-map",
        str(_api_map(tmp_path / "api.json", ["api", "benchbox.TPCH"] if api_ids is None else api_ids)),
        *(extra or []),
    ]
    if published is not None:
        argv += ["--published-baseline", str(_inventory(published, tmp_path / "inv-published"))]
    code = site_parity.main(argv)
    return code, json.loads((out / site_parity.REPORT_JSON).read_text(encoding="utf-8"))


def test_clean_parity_lists_allowed_differences_and_redirects(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=True, feed_link="/blog/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")

    code, report = _run(tmp_path, baseline, candidate)

    assert code == 0
    assert report["verdict"] == "PASS"
    assert report["broken_public_urls"] == 0
    assert report["broken_fragments"] == 0
    allowed = {row["id"]: row for row in report["allowed_differences"]}
    assert allowed["theme-ids"]["count"] == 2
    assert allowed["feed-links"]["count"] == 1
    assert all(row["reason"] and row["owner_approval"] == "pending" for row in report["allowed_differences"])
    assert [row["path"] for row in report["redirects"]["pages"]] == ["/404.html"]
    assert report["redirects"]["pages"][0]["owner_approval"] == "pending"
    markdown = (tmp_path / "report" / site_parity.REPORT_MARKDOWN).read_text(encoding="utf-8")
    assert "Verdict: PASS" in markdown and "Owner approval: pending" in markdown
    assert "| theme-ids | missing fragment | 2 |" in markdown


def test_missing_tag_page_is_real_breakage_in_its_category(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html", tag=False)

    code, report = _run(tmp_path, baseline, candidate)

    assert code == 1
    assert report["broken_public_urls"] == 1
    categories = {row["category"]: row for row in report["comparisons"][0]["categories"]}
    assert categories["blog tag pages"]["missing"] == 1
    assert report["real_breakage"]["differences"][0]["finding"] == "missing path: /blog/tag/duckdb.html"


def test_lost_fragment_without_a_rule_is_a_broken_fragment(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=True, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")

    code, report = _run(tmp_path, baseline, candidate, rules=[])

    assert code == 1
    assert report["broken_fragments"] == 2
    assert report["comparisons"][0]["by_kind"]["missing fragment"] == {"found": 2, "allowed": 0, "remaining": 2}


def test_undeclared_redirect_and_api_anchor_loss_fail(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")
    for site in (baseline, candidate):
        _write(site, "docs/old.html", '<meta http-equiv="refresh" content="0; url=/docs/api.html">')

    code, report = _run(tmp_path, baseline, candidate, api_ids=["api", "benchbox.Gone"])

    assert code == 1
    assert report["real_breakage"]["redirect_pages"] == ["/docs/old.html"]
    assert report["real_breakage"]["api_url_map"] == ["/docs/api.html#benchbox.Gone"]
    assert report["redirects"]["pages"][1]["reason"] == ""


def test_api_anchors_lost_to_a_theme_rule_are_allowed_not_missing(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=True, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")

    code, report = _run(tmp_path, baseline, candidate, api_ids=["api", "__toc"])

    assert code == 0
    assert report["api_url_map"]["allowed_ids"] == ["/docs/api.html#__toc"]
    assert report["api_url_map"]["missing_ids"] == []


def test_lost_feed_entry_id_is_reported(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")
    feed = ATOM.format(link="/blog/a.html").replace("blog/a.html</id>", "blog/z.html</id>")
    _write(candidate, "blog/atom.xml", feed)

    code, report = _run(tmp_path, baseline, candidate)

    assert code == 1
    assert report["comparisons"][0]["feeds"][0]["lost_ids"] == ["https://benchbox.dev/blog/a.html"]
    assert report["real_breakage"]["atom_entry_ids"] == [
        f"{site_parity.SAME_TREE}: /blog/atom.xml: https://benchbox.dev/blog/a.html"
    ]


def test_browser_failures_fail_the_report(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")
    failures = ["landing light: axe color-contrast"]
    browser = _json(tmp_path / "browser.json", {"axe": {"docs page light": {}}, "failures": failures})

    code, report = _run(tmp_path, baseline, candidate, extra=["--e2e-report", str(browser)])

    assert code == 1
    assert report["real_breakage"]["browser_checks"] == ["browser.json: landing light: axe color-contrast"]


def test_published_baseline_is_informational_and_never_fails_the_verdict(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")
    published = _site(tmp_path / "published", theme=False, feed_link="/blog/a.html")
    _write(published, "docs/removed.html", "<title>Gone</title>")

    code, report = _run(tmp_path, baseline, candidate, published=published)

    assert code == 0
    assert [comparison["gating"] for comparison in report["comparisons"]] == [True, False]
    assert report["broken_public_urls"] == 0
    assert report["changed_since_published"]["urls"] == 1


def test_unreviewed_additions_are_listed_without_failing(tmp_path: Path) -> None:
    baseline = _site(tmp_path / "base", theme=False, feed_link="/blog/a.html")
    candidate = _site(tmp_path / "cand", theme=False, feed_link="/blog/a.html")
    _write(candidate, "sitemap.xml")
    _write(candidate, "docs/new.html", "<title>New</title>")

    code, report = _run(tmp_path, baseline, candidate)

    assert code == 0
    added = report["comparisons"][0]["added_paths"]
    assert (added["total"], added["unreviewed"]) == (2, ["/docs/new.html"])
    assert added["by_rule"] == {"/sitemap.xml": ["/sitemap.xml"]}


def test_committed_policy_files_carry_reasons_and_pending_approval() -> None:
    rules = site_inventory.load_allowed_differences(site_parity.DEFAULT_ALLOWED)
    redirects = site_parity.load_redirect_pages(site_parity.DEFAULT_REDIRECTS)
    added = site_parity.load_added_paths(site_parity.DEFAULT_ADDED)
    entries = site_parity.removal_entries(sorted(site_parity.DESIGN_DIR.glob("expected-removals-*.json")))

    everything = rules + redirects + added + entries
    assert redirects and added and all(entry["reason"].strip() for entry in everything)
    assert {entry["owner_approval"] for entry in everything} == {"pending"}
