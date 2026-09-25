"""Tests for the generated-rerun-shard retention check."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "check_rerun_shard_retention_under_test"
    path = REPO_ROOT / "scripts" / "check_rerun_shard_retention.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_script()


class TestStemDates:
    def test_parses_sweep_date(self):
        assert checker.shard_sweep_date(Path("uat-tuned-followup-resume-cedardb-20260505.yaml")) == date(2026, 5, 5)

    def test_rejects_undated_stem(self):
        assert checker.shard_sweep_date(Path("uat-smoke.yaml")) is None

    def test_rejects_impossible_date(self):
        assert checker.shard_sweep_date(Path("shard-20261345.yaml")) is None


class TestExpiry:
    def test_live_shards_within_default_retention(self):
        expired = checker.find_expired(date(2026, 9, 25), checker.RETENTION_DAYS)
        assert expired == []

    def test_short_retention_expires_known_shards(self):
        expired = checker.find_expired(date(2026, 9, 25), 30)
        assert len(expired) == 17
        names = [p.name for p, _, _ in expired]
        assert "uat-tuned-followup-resume-20260505.yaml" in names

    def test_main_reports_ok_when_current(self, capsys):
        assert checker.main([]) == 0
        assert "OK" in capsys.readouterr().out
