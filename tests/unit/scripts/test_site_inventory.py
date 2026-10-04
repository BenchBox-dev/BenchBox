from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import site_inventory
from scripts.assemble_public_site import RESULTS_FALLBACK

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>https://benchbox.dev/blog/b.html</id><title>Second</title><link href="https://benchbox.dev/blog/b.html"/></entry>
  <entry><id>https://benchbox.dev/blog/a.html</id><title>First</title><link href="a.html"/></entry>
</feed>
"""

INDEX = """<!doctype html><html><head><title> Home  Page </title>
<meta name="description" content="The   home">
<link rel="canonical" href="https://benchbox.dev/">
<link rel="stylesheet" href="/_static/theme.css"><script src="/_static/app.js"></script>
</head><body id="top-body"><h1>Home<a class="headerlink" href="#x">¶</a></h1>
<h2 id="intro">Intro</h2><h3>Detail</h3><h2>Outro</h2>
<a href="#intro">jump</a><a href="docs/guide.html#setup">guide</a><a href="https://benchbox.dev/blog/a.html">post</a>
<a href="https://example.com/x">ext</a><a href="mailto:a@b.c">mail</a><a href="/results/benchmarks/">spa</a>
<img src="/_images/logo.svg"></body></html>
"""

GUIDE = """<html><head><title>Guide</title></head><body><h1>Guide</h1>
<h2 id="setup">Setup</h2><a href="../index.html">home</a></body></html>
"""


def _write(root: Path, name: str, content: str = "x") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(root: Path) -> Path:
    _write(root, "index.html", INDEX)
    _write(root, "docs/guide.html", GUIDE)
    _write(root, "blog/a.html", "<title>A</title><h1>A</h1>")
    _write(root, "blog/b.html", "<title>B</title><h1>B</h1>")
    _write(root, "blog/atom.xml", ATOM)
    _write(root, "_static/theme.css")
    _write(root, "_static/app.js")
    _write(root, "_images/logo.svg")
    _write(root, "results/index.html", "<title>Results</title><h1>Results</h1>")
    _write(root, "results/assets/index-AbCd1234.js")
    _write(root, "404.html", RESULTS_FALLBACK)
    return root


def _build(root: Path) -> dict:
    return site_inventory.build_inventory(root)


def test_inventory_extracts_page_fields(tmp_path: Path) -> None:
    inventory = _build(_fixture(tmp_path / "site"))

    page = inventory["pages"]["/index.html"]
    assert page["title"] == "Home Page"
    assert page["description"] == "The home"
    assert page["canonical"] == "/"
    assert page["h1"] == ["Home"]
    assert page["headings"] == [["h2", "Intro"], ["h3", "Detail"], ["h2", "Outro"]]
    assert page["links"] == [
        "/blog/a.html",
        "/docs/guide.html#setup",
        "/index.html#intro",
        "/index.html#x",
        "/results/benchmarks/",
    ]
    assert page["images"] == ["/_images/logo.svg"]
    assert inventory["assets"] == ["/_static/app.js", "/_static/theme.css"]
    assert "intro" in page["ids"]
    assert inventory["chrome_links"] == []
    assert inventory["path_count"] == len(inventory["paths"]) == 11
    assert inventory["page_count"] == 6


def test_inventory_records_feed_not_found_and_routes(tmp_path: Path) -> None:
    inventory = _build(_fixture(tmp_path / "site"))

    assert [entry["title"] for entry in inventory["feeds"]["/blog/atom.xml"]] == ["First", "Second"]
    assert inventory["feeds"]["/blog/atom.xml"][0]["links"] == ["/blog/a.html"]
    assert inventory["not_found"]["session_storage_keys"] == ["benchbox.results.redirect"]
    assert inventory["not_found"]["redirect_targets"] == ["/results/"]
    assert inventory["routes"]["/"] == "/index.html"
    assert inventory["routes"]["/results/benchmarks/"] == "spa-fallback"
    assert inventory["routes"]["/docs/usage/getting-started.html"] == ""


def test_output_is_deterministic_and_sorted(tmp_path: Path) -> None:
    site = _fixture(tmp_path / "site")
    first, second = tmp_path / "a.json", tmp_path / "b.json"

    assert site_inventory.main(["build", "--site-dir", str(site), "--output", str(first)]) == 0
    assert site_inventory.main(["build", "--site-dir", str(site), "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert text.endswith("\n") and not text.endswith("\n\n")
    data = json.loads(text)
    assert data["paths"] == sorted(data["paths"])
    assert text == json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_unchanged_site_has_empty_diff(tmp_path: Path) -> None:
    inventory = _build(_fixture(tmp_path / "site"))
    report = site_inventory.diff_inventories(inventory, inventory)

    assert all(not items for items in report.values())
    assert site_inventory.exit_code(report, strict=True) == 0


def test_diff_classifies_missing_path_heading_link_and_image(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    (candidate_site / "blog" / "b.html").unlink()
    (candidate_site / "_images" / "logo.svg").unlink()
    _write(
        candidate_site, "docs/guide.html", GUIDE.replace('id="setup"', 'id="other"').replace("<h1>Guide", "<h1>Manual")
    )
    candidate = _build(candidate_site)

    report = site_inventory.diff_inventories(baseline, candidate)

    assert report["missing path"] == ["/_images/logo.svg", "/blog/b.html"]
    assert len(report["changed heading"]) == 1
    assert "[h1]" in report["changed heading"][0] and "Manual" in report["changed heading"][0]
    assert report["broken internal link"] == [
        "/blog/atom.xml: /blog/b.html (missing path)",
        "/index.html: /docs/guide.html#setup (missing fragment)",
    ]
    assert report["missing fragment"] == ["/docs/guide.html#setup"]
    assert report["missing image"] == ["/index.html: /_images/logo.svg (not served)"]
    assert site_inventory.exit_code(report, strict=False) == 1


def test_changed_heading_alone_fails_only_when_strict(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    _write(candidate_site, "blog/a.html", "<title>A</title><h1>Renamed</h1>")
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert [key for key, items in report.items() if items] == ["changed heading"]
    assert site_inventory.exit_code(report, strict=False) == 0
    assert site_inventory.exit_code(report, strict=True) == 1


def test_hashed_explorer_assets_are_not_missing_paths(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    (candidate_site / "results" / "assets" / "index-AbCd1234.js").rename(
        candidate_site / "results" / "assets" / "index-ZyXw9876.js"
    )

    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert report["missing path"] == []


def test_lost_spa_fallback_reports_capture_route(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    (candidate_site / "404.html").unlink()

    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert "/404.html" in report["missing path"]
    assert "/results/benchmarks/ (capture route)" in report["missing path"]


def test_cli_diff_exit_codes_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base_site = _fixture(tmp_path / "base")
    cand_site = _fixture(tmp_path / "cand")
    base_json, cand_json = tmp_path / "base.json", tmp_path / "cand.json"
    site_inventory.main(["build", "--site-dir", str(base_site), "--output", str(base_json)])
    site_inventory.main(["build", "--site-dir", str(cand_site), "--output", str(cand_json)])
    args = ["diff", "--baseline", str(base_json), "--candidate", str(cand_json)]
    assert site_inventory.main(args) == 0

    (cand_site / "docs" / "guide.html").unlink()
    site_inventory.main(["build", "--site-dir", str(cand_site), "--output", str(cand_json)])
    capsys.readouterr()
    assert site_inventory.main(args) == 1
    out = capsys.readouterr().out
    assert "missing path: /docs/guide.html" in out
    assert "broken internal link: /index.html: /docs/guide.html#setup (missing path)" in out
    assert out.splitlines()[-1].startswith("summary: 1 missing path, 0 missing fragment, 1 broken internal link")


def test_check_reports_broken_links_within_one_inventory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = _fixture(tmp_path / "site")
    _write(site, "docs/guide.html", GUIDE.replace('id="setup"', 'id="other"'))
    inventory_path = tmp_path / "inv.json"
    site_inventory.main(["build", "--site-dir", str(site), "--output", str(inventory_path)])
    capsys.readouterr()

    assert site_inventory.main(["check", "--inventory", str(inventory_path)]) == 1
    assert "/docs/guide.html#setup (missing fragment)" in capsys.readouterr().out


def test_missing_site_dir_is_a_usage_error(tmp_path: Path) -> None:
    code = site_inventory.main(["build", "--site-dir", str(tmp_path / "none"), "--output", str(tmp_path / "o.json")])

    assert code == 2


def test_internal_target_normalization() -> None:
    assert site_inventory.internal_target("https://benchbox.dev/a/b.html#x", "/") == ("/a/b.html", "x")
    assert site_inventory.internal_target("../c.html", "/a/b.html") == ("/c.html", "")
    assert site_inventory.internal_target("#frag", "/a/b.html") == ("/a/b.html", "frag")
    assert site_inventory.internal_target("https://example.com/", "/") is None
    assert site_inventory.internal_target("javascript:void(0)", "/") is None


def test_chrome_links_are_hoisted_and_checked_once(tmp_path: Path) -> None:
    site = _fixture(tmp_path / "site")
    _write(
        site,
        "docs/guide.html",
        '<html><body><nav><a href="/index.html">home</a><a href="/gone.html">gone</a></nav>'
        '<h1 id="g">Guide</h1><a href="/index.html#intro">intro</a></body></html>',
    )
    inventory = _build(site)

    assert inventory["pages"]["/docs/guide.html"]["links"] == ["/index.html#intro"]
    assert inventory["chrome_links"] == ["/gone.html", "/index.html"]
    assert ("(site chrome)", "/gone.html", "missing path") in site_inventory.broken_links(inventory)


def test_all_ids_and_names_are_recorded(tmp_path: Path) -> None:
    site = _fixture(tmp_path / "site")
    _write(site, "docs/guide.html", GUIDE.replace("</body>", '<a name="legacy"></a><p id="unlinked"></p></body>'))
    inventory = _build(site)

    assert inventory["pages"]["/index.html"]["ids"] == ["intro", "top-body"]
    assert inventory["pages"]["/docs/guide.html"]["ids"] == ["legacy", "setup", "unlinked"]


def test_title_ignores_svg_titles_and_later_titles(tmp_path: Path) -> None:
    site = _fixture(tmp_path / "site")
    markup = (
        "<html><head><title>Real</title></head><body><svg><title>Icon</title></svg>"
        "<h1>H</h1><svg><title>Other</title></svg></body></html>"
    )
    _write(site, "docs/guide.html", markup)
    svg_first = "<html><head><svg><title>Icon</title></svg><title>Real</title></head><body></body></html>"
    _write(site, "docs/other.html", svg_first)
    inventory = _build(site)

    assert inventory["pages"]["/docs/guide.html"]["title"] == "Real"
    assert inventory["pages"]["/docs/other.html"]["title"] == "Real"


def _removal(path: str, reason: str = "reviewed") -> dict[str, str]:
    return {"path": path, "reason": reason}


def test_missing_fragment_fails_unless_expected(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    _write(candidate_site, "docs/guide.html", GUIDE.replace('id="setup"', 'id="other"'))
    candidate = _build(candidate_site)

    report = site_inventory.diff_inventories(baseline, candidate)
    assert report["missing fragment"] == ["/docs/guide.html#setup"]
    assert site_inventory.exit_code(report, strict=False) == 1

    allowed = site_inventory.diff_inventories(baseline, candidate, [_removal("/docs/guide.html#setup")])
    assert allowed["missing fragment"] == []
    assert allowed["broken internal link"] == []
    assert allowed["stale allowance"] == []
    assert site_inventory.exit_code(allowed, strict=True) == 0


def test_expected_removals_support_prefixes_and_report_stale_entries(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    (candidate_site / "blog" / "b.html").unlink()
    (candidate_site / "blog" / "a.html").unlink()
    candidate = _build(candidate_site)

    removals = [_removal("/blog/"), _removal("/nothing/*"), _removal("/_images/logo.svg")]
    report = site_inventory.diff_inventories(baseline, candidate, removals)

    assert report["missing path"] == []
    assert report["broken internal link"] == []
    assert report["stale allowance"] == ["/_images/logo.svg (matched nothing)", "/nothing/* (matched nothing)"]
    assert site_inventory.exit_code(report, strict=False) == 0
    assert site_inventory.exit_code(report, strict=True) == 1


def test_expected_removals_file_requires_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = _fixture(tmp_path / "site")
    inventory_path, removals = tmp_path / "inv.json", tmp_path / "removals.json"
    site_inventory.main(["build", "--site-dir", str(site), "--output", str(inventory_path)])
    args = ["diff", "--baseline", str(inventory_path), "--candidate", str(inventory_path)]

    removals.write_text(json.dumps([{"path": "/blog/", "reason": "  "}]), encoding="utf-8")
    assert site_inventory.main([*args, "--expected-removals", str(removals)]) == 2
    removals.write_text(json.dumps([_removal("/blog/")]), encoding="utf-8")
    capsys.readouterr()
    assert site_inventory.main([*args, "--expected-removals", str(removals)]) == 0
    assert "1 stale allowance" in capsys.readouterr().out


def test_feed_links_are_link_sources(tmp_path: Path) -> None:
    site = _fixture(tmp_path / "site")
    _write(site, "blog/atom.xml", ATOM.replace('href="a.html"', 'href="blog/a.html"'))
    inventory = _build(site)

    assert ("/blog/atom.xml", "/blog/blog/a.html", "missing path") in site_inventory.broken_links(inventory)
    assert not any(
        source == "/blog/atom.xml" for source, _, _ in site_inventory.broken_links(_build(_fixture(tmp_path / "ok")))
    )


def test_feed_entry_and_link_loss_fail(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    shortened = ATOM.replace('<link href="a.html"/>', "").replace("Second", "Renamed")
    _write(candidate_site, "blog/atom.xml", shortened)
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert report["feed regression"] == [
        "/blog/atom.xml: entry https://benchbox.dev/blog/a.html lost link /blog/a.html"
    ]
    assert len(report["changed metadata"]) == 1 and "Renamed" in report["changed metadata"][0]
    assert site_inventory.exit_code(report, strict=False) == 1

    dropped = ATOM.replace(ATOM.splitlines()[2], "")
    _write(candidate_site, "blog/atom.xml", dropped)
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))
    assert report["feed regression"] == ["/blog/atom.xml: entry https://benchbox.dev/blog/b.html removed"]


def test_canonical_loss_fails_but_description_change_is_informational(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    _write(candidate_site, "index.html", INDEX.replace("The   home", "Changed"))
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert [key for key, items in report.items() if items] == ["changed metadata"]
    assert site_inventory.exit_code(report, strict=False) == 0
    assert site_inventory.exit_code(report, strict=True) == 1

    _write(candidate_site, "index.html", INDEX.replace('<link rel="canonical" href="https://benchbox.dev/">', ""))
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))
    assert report["canonical loss"] == ["/index.html [canonical]: '/' -> ''"]
    assert site_inventory.exit_code(report, strict=False) == 1


def test_not_found_fallback_change_fails(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    _write(candidate_site, "404.html", RESULTS_FALLBACK.replace("benchbox.results.redirect", "benchbox.other.key"))
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert any("session_storage_keys" in item for item in report["404 fallback change"])
    assert site_inventory.exit_code(report, strict=False) == 1


def test_dropped_image_reference_is_informational_but_unserved_image_fails(tmp_path: Path) -> None:
    baseline = _build(_fixture(tmp_path / "base"))
    candidate_site = _fixture(tmp_path / "cand")
    _write(candidate_site, "index.html", INDEX.replace('<img src="/_images/logo.svg">', ""))
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))

    assert report["unreferenced image"] == ["/index.html: /_images/logo.svg (no longer referenced)"]
    assert report["missing image"] == []
    assert site_inventory.exit_code(report, strict=False) == 0
    assert site_inventory.exit_code(report, strict=True) == 1

    _write(candidate_site, "index.html", INDEX.replace("/_images/logo.svg", "/_images/gone.svg"))
    report = site_inventory.diff_inventories(baseline, _build(candidate_site))
    assert report["missing image"] == ["/index.html: /_images/gone.svg (not served)"]
    assert site_inventory.exit_code(report, strict=False) == 1


def test_capture_routes_are_parsed_from_the_playwright_spec() -> None:
    assert site_inventory.capture_routes() == [
        "/",
        "/docs/usage/getting-started.html",
        "/blog/2026-05-18-v0-3-0-release-overview.html",
        "/results/",
        "/results/benchmarks/",
        "/results/platforms/",
    ]


def test_capture_routes_reject_a_spec_without_routes(tmp_path: Path) -> None:
    spec = tmp_path / "spec.ts"
    spec.write_text("const ROUTES = [];\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no capture routes"):
        site_inventory.capture_routes(spec)


def _big_site(root: Path, pages: int) -> Path:
    _fixture(root)
    for number in range(pages):
        _write(root, f"docs/q/page{number:03d}.html", f"<title>P{number}</title><h1>{'x' * 3000}</h1><h2>{number}</h2>")
    return root


def test_sharded_output_matches_single_file_and_respects_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(site_inventory, "SHARD_BUDGET", 20_000)
    monkeypatch.setattr(site_inventory, "SHARD_LIMIT", 24_000)
    site = _big_site(tmp_path / "site", 30)
    single = tmp_path / "single.json"
    sharded = tmp_path / "sharded"
    assert site_inventory.main(["build", "--site-dir", str(site), "--output", str(single), "--source-sha", "abc"]) == 0
    assert (
        site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(sharded), "--source-sha", "abc"])
        == 0
    )

    files = sorted(sharded.glob("*.json"))
    assert len([f for f in files if f.name.startswith("pages-docs-")]) > 1
    assert all(f.stat().st_size < 24_000 for f in files)
    assert site_inventory.load_inventory(sharded) == site_inventory.load_inventory(single)
    assert json.loads((sharded / "index.json").read_text(encoding="utf-8"))["source_sha"] == "abc"


def test_sharded_output_is_deterministic_and_clears_stale_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(site_inventory, "SHARD_BUDGET", 20_000)
    monkeypatch.setattr(site_inventory, "SHARD_LIMIT", 24_000)
    site = _big_site(tmp_path / "site", 20)
    out = tmp_path / "out"
    site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(out)])
    first = {f.name: f.read_bytes() for f in out.glob("*.json")}
    _write(out, "pages-stale-001.json", "{}")
    site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(out)])

    assert {f.name: f.read_bytes() for f in out.glob("*.json")} == first


def test_oversized_single_entry_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_inventory, "SHARD_BUDGET", 500)
    site = _big_site(tmp_path / "site", 1)

    assert site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(tmp_path / "o")]) == 2


def test_diff_and_check_accept_directories(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base_dir, cand_file = tmp_path / "base", tmp_path / "cand.json"
    base_site = _fixture(tmp_path / "bs")
    cand_site = _fixture(tmp_path / "cs")
    (cand_site / "blog" / "b.html").unlink()
    site_inventory.main(["build", "--site-dir", str(base_site), "--output-dir", str(base_dir)])
    site_inventory.main(["build", "--site-dir", str(cand_site), "--output", str(cand_file)])
    capsys.readouterr()

    assert site_inventory.main(["diff", "--baseline", str(base_dir), "--candidate", str(cand_file)]) == 1
    assert "missing path: /blog/b.html" in capsys.readouterr().out
    assert site_inventory.main(["check", "--inventory", str(base_dir)]) == 1


def test_known_broken_allows_listed_links_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = _fixture(tmp_path / "site")
    inventory_dir, known = tmp_path / "inv", tmp_path / "known.json"
    site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(inventory_dir)])
    assert site_inventory.main(["check", "--inventory", str(inventory_dir), "--write-known-broken", str(known)]) == 0
    entries = json.loads(known.read_text(encoding="utf-8"))
    assert entries == sorted(entries) and entries
    check = ["check", "--inventory", str(inventory_dir), "--known-broken", str(known)]
    assert site_inventory.main(check) == 0

    _write(site, "docs/guide.html", GUIDE.replace('id="setup"', 'id="other"'))
    site_inventory.main(["build", "--site-dir", str(site), "--output-dir", str(inventory_dir)])
    capsys.readouterr()
    assert site_inventory.main(check) == 1
    assert "/docs/guide.html#setup (missing fragment)" in capsys.readouterr().out
