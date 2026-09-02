"""Unit tests for corpus promotion verification fail-closed behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.publication.check_explorer_compat as explorer_compat
from scripts.publication import verify_corpus_promotion as promotion_mod

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _isolate_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, with_inventory: bool) -> Path:
    fake_root = tmp_path / "repo"
    bundles = fake_root / "results-data" / "bundles"
    bundles.mkdir(parents=True)
    (bundles / "b1.json").write_text("{}", encoding="utf-8")
    inventory = fake_root / "results-data" / "corpus-inventory.json"
    if with_inventory:
        inventory.write_text('{"bundles": [{"file": "b1.json"}]}', encoding="utf-8")

    monkeypatch.setattr(promotion_mod, "REPO_ROOT", fake_root)
    monkeypatch.setattr(promotion_mod, "INVENTORY_FILE", inventory)
    monkeypatch.setattr(explorer_compat, "check_schema_compatibility", lambda versions=None: {9: []})
    return fake_root


def test_shadow_without_site_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--shadow must fail when publication/out/site is absent."""
    _isolate_repo(tmp_path, monkeypatch, with_inventory=True)
    rc = promotion_mod.main(["--shadow"])
    assert rc != 0


def test_shadow_without_inventory_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--shadow must fail when corpus-inventory.json is missing (no skip)."""
    fake_root = _isolate_repo(tmp_path, monkeypatch, with_inventory=False)
    site = fake_root / "publication" / "out" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<html></html>", encoding="utf-8")
    rc = promotion_mod.main(["--shadow"])
    assert rc != 0
