"""Sphinx side of the publish list for docs/development/ and docs/operations/.

The Astro converter applies the same list; website/tests/sources.test.ts checks
that side and that every page in those directories has been classified.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

DOCS = Path(__file__).parents[3] / "docs"


@pytest.fixture(scope="module")
def conf() -> dict:
    return runpy.run_path(str(DOCS / "conf.py"))


def test_sphinx_excludes_every_unlisted_page_in_gated_directories(conf: dict) -> None:
    listed = conf["_read_publish_list"](DOCS)
    gated = {
        page.relative_to(DOCS).as_posix() for root in conf["PUBLISH_LIST_ROOTS"] for page in (DOCS / root).rglob("*.md")
    }
    excluded = set(conf["exclude_patterns"])
    assert gated - listed <= excluded
    assert not (listed & excluded)


def test_sphinx_excludes_a_new_unlisted_page(conf: dict, tmp_path: Path) -> None:
    (tmp_path / "development").mkdir()
    (tmp_path / "development" / "kept.md").write_text("# Kept\n")
    (tmp_path / "development" / "new-page.md").write_text("# New\n")
    (tmp_path / "publish-allowlist.txt").write_text("# comment\ndevelopment/kept.md\n")
    assert conf["_unlisted_publish_list_pages"](tmp_path) == ["development/new-page.md"]


def test_missing_publish_list_publishes_nothing_in_gated_directories(conf: dict, tmp_path: Path) -> None:
    (tmp_path / "operations").mkdir()
    (tmp_path / "operations" / "runbook.md").write_text("# Runbook\n")
    assert conf["_unlisted_publish_list_pages"](tmp_path) == ["operations/runbook.md"]
