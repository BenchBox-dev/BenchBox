"""Tests for release version updates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "update_version.py"

spec = importlib.util.spec_from_file_location("update_version", SCRIPT_PATH)
update_version = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(update_version)


def test_update_landing_page_version_handles_multiline_anchor(tmp_path, monkeypatch):
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir()
    landing = landing_dir / "index.html"
    landing.write_text(
        """<a
    href="https://github.com/joeharris76/benchbox/releases"
    target="_blank"
    class="badge badge-version"
    >v0.2.1</a
>""",
        encoding="utf-8",
    )
    monkeypatch.setattr(update_version, "get_project_root", lambda: tmp_path)

    assert update_version.update_landing_page_version("0.3.1")

    assert ">v0.3.1</a" in landing.read_text(encoding="utf-8")


def test_update_landing_page_version_only_updates_version_badge(tmp_path, monkeypatch):
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir()
    landing = landing_dir / "index.html"
    landing.write_text(
        """<a class="badge">v0.2.1</a>
<a class="badge badge-version">v0.2.1</a>""",
        encoding="utf-8",
    )
    monkeypatch.setattr(update_version, "get_project_root", lambda: tmp_path)

    assert update_version.update_landing_page_version("0.3.1")

    assert (
        landing.read_text(encoding="utf-8")
        == """<a class="badge">v0.2.1</a>
<a class="badge badge-version">v0.3.1</a>"""
    )
