"""Tests for scripts/_compose_joinorder_hero.py."""

from __future__ import annotations

import _compose_joinorder_hero as compose_joinorder_hero
import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_joinorder_json_input_path_is_repo_relative() -> None:
    expected = (
        compose_joinorder_hero.ROOT
        / "benchmark_runs"
        / "results"
        / "joinorder_sf1_duckdb_sql_20260518_161132_e392ddcb.json"
    )

    assert expected == compose_joinorder_hero.JSON_PATH
    assert "/Users/joe/Developer/BenchBox/" not in str(compose_joinorder_hero.JSON_PATH)
