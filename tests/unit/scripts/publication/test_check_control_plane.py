"""Unit tests for publication control-plane checker fail-closed --strict behavior."""

from __future__ import annotations

import pytest

from scripts.publication import check_control_plane as control_mod

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_strict_without_live_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_mod, "check_codeowners", list)
    rc = control_mod.main(["--strict"])
    assert rc != 0


def test_local_without_strict_can_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_mod, "check_codeowners", list)
    rc = control_mod.main([])
    assert rc == 0
