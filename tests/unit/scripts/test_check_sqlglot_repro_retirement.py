"""Tests for the sqlglot repro-retirement upgrade trigger."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "check_sqlglot_repro_retirement_under_test"
    path = REPO_ROOT / "scripts" / "check_sqlglot_repro_retirement.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_script()


class TestVersionParsing:
    def test_parses_locked_version(self):
        text = 'name = "sqlglot"\nversion = "30.18.0"\n'
        assert checker._LOCK_VERSION_RE.search(text).group(1) == "30.18.0"  # type: ignore[union-attr]

    def test_live_lockfile_has_version(self):
        assert checker.locked_sqlglot_version(None) is not None


class TestSummaryParsing:
    SUMMARY = """=== Summary (FAIL = observation differs from expected; PASS = observation matches)
  [FAIL] #1 duckdb-all-keyword (Tier B)
  [PASS] #6 questdb-dialect-missing (Tier A)
"""

    def test_extracts_passing_only(self):
        assert checker.newly_passing(self.SUMMARY) == ["#6 questdb-dialect-missing (Tier A)"]

    def test_empty_when_all_fail(self):
        assert checker.newly_passing("=== Summary\n  [FAIL] #1 x\n") == []


class TestNoUpgradePath:
    def test_same_version_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(checker, "merge_base", lambda ref="origin/develop": "abc123")
        monkeypatch.setattr(checker, "locked_sqlglot_version", lambda ref=None: "30.18.0")
        assert checker.main([]) == 0
        assert "no upgrade" in capsys.readouterr().out
