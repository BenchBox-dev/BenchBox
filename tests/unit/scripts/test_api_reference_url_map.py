from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import api_reference_url_map as tool

pytestmark = [pytest.mark.unit, pytest.mark.fast]

PAGE = """<html><body><nav id="chrome"></nav><article id="main">
<section id="widgets"><h2 id="widget-heading">Widgets</h2>
<span id="module-benchbox.thing"></span><a name="legacy"></a>
<dl><dt id="benchbox.thing.Widget">Widget</dt><dt id="benchbox.thing.Widget.run">run</dt><dt id="run">run</dt>
<dt id="benchbox.old.Gone">Gone</dt><dt id="benchbox.old.Gone.size">size</dt><dt id="size">size</dt></dl>
</section></article></body></html>"""


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    docs = tmp_path / "docs"
    (docs / "reference" / "python-api").mkdir(parents=True)
    (docs / "api.rst").write_text("API\n===\n\n.. automodule:: benchbox\n", encoding="utf-8")
    (docs / "reference" / "python-api" / "thing.rst").write_text(
        "Thing\n=====\n\n.. method:: run()\n", encoding="utf-8"
    )
    (docs / "reference" / "python-api" / "prose.rst").write_text("Prose\n=====\n\nNo autodoc.\n", encoding="utf-8")
    (docs / "guide.rst").write_text(".. autoclass:: benchbox.x\n", encoding="utf-8")
    html = tmp_path / "html"
    (html / "reference" / "python-api").mkdir(parents=True)
    (html / "api.html").write_text(PAGE, encoding="utf-8")
    (html / "reference" / "python-api" / "thing.html").write_text(PAGE, encoding="utf-8")
    symbols = tmp_path / "symbols.json"
    symbols.write_text(
        json.dumps(
            {
                "dropped": ["benchbox.old.Gone"],
                "symbols": [{"symbol": "benchbox.thing.Widget", "aliases": []}],
            }
        ),
        encoding="utf-8",
    )
    return {"docs": docs, "html": html, "symbols": symbols, "out": tmp_path / "map.json"}


def _run(tree: dict[str, Path]) -> dict:
    argv = [
        "--html",
        str(tree["html"]),
        "--docs",
        str(tree["docs"]),
        "--symbols",
        str(tree["symbols"]),
        "--out",
        str(tree["out"]),
        "--source-sha",
        "abc123",
    ]
    assert tool.main(argv) == 0
    return json.loads(tree["out"].read_text(encoding="utf-8"))


def test_page_discovery_uses_autodoc_and_directive_lines(tree: dict[str, Path]) -> None:
    data = _run(tree)

    assert [page["url"] for page in data["pages"]] == ["/docs/api.html", "/docs/reference/python-api/thing.html"]
    assert data["source_sha"] == "abc123"
    assert "scripts/api_reference_url_map.py" in data["command"]


def test_every_id_and_name_is_classified(tree: dict[str, Path]) -> None:
    ids = _run(tree)["pages"][1]["ids"]

    assert "chrome" not in ids
    assert ids["widgets"]["class"] == "section"
    assert ids["widget-heading"]["class"] == "section"
    assert ids["module-benchbox.thing"]["class"] == "other"
    assert ids["legacy"] == {"class": "other", "disposition": "alias", "via": ["name"]}
    assert ids["benchbox.thing.Widget"] == {"class": "object", "disposition": "heading", "via": ["id"]}
    assert ids["benchbox.thing.Widget.run"]["disposition"] == "alias"
    assert ids["run"]["class"] == "object"
    assert ids["run"]["disposition"] == "alias"


def test_dropped_symbols_alias_to_note(tree: dict[str, Path]) -> None:
    page = _run(tree)["pages"][1]

    for key in ("benchbox.old.Gone", "benchbox.old.Gone.size", "size"):
        assert page["ids"][key]["disposition"] == "alias-to-note"
        assert page["ids"][key]["target"] == "#not-part-of-public-contract"
    assert page["note_anchor"] == "not-part-of-public-contract"
    assert page["counts"]["object:alias-to-note"] == 3


def test_totals_and_bare_anchor_count(tree: dict[str, Path]) -> None:
    totals = _run(tree)["totals"]

    assert totals["bare_object_anchors"] == 4
    assert totals["class:object"] == 12
    assert totals["disposition:alias-to-note"] == 6


def test_output_is_deterministic(tree: dict[str, Path]) -> None:
    _run(tree)
    first = tree["out"].read_text(encoding="utf-8")
    _run(tree)

    assert tree["out"].read_text(encoding="utf-8") == first
    assert first.endswith("}\n")


def test_missing_built_page_exits_2(tree: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    (tree["html"] / "api.html").unlink()

    assert (
        tool.main(
            [
                "--html",
                str(tree["html"]),
                "--docs",
                str(tree["docs"]),
                "--symbols",
                str(tree["symbols"]),
                "--out",
                str(tree["out"]),
                "--source-sha",
                "x",
            ]
        )
        == 2
    )
    assert "built page missing" in capsys.readouterr().err
