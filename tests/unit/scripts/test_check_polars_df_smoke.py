from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_polars_df_smoke as smoke

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _payload(query_ids: list[str], *, failed: tuple[str, ...] = ()) -> dict:
    queries = [{"id": query_id, "run_type": "warmup", "status": "SUCCESS"} for query_id in query_ids]
    queries += [
        {"id": query_id, "run_type": "measurement", "status": "FAILED" if query_id in failed else "SUCCESS"}
        for query_id in query_ids
    ]
    return {"queries": queries}


def _write(results_dir: Path, benchmark: str, payload: dict) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{benchmark}_sf001_polars_df_20260101_000000_abcd.json").write_text(json.dumps(payload))


def test_complete_successful_run_passes() -> None:
    assert smoke.check_result("ssb", _payload([str(n) for n in range(13)])) == []


def test_missing_queries_are_reported() -> None:
    problems = smoke.check_result("ssb", _payload([str(n) for n in range(12)]))

    assert problems == ["ssb: expected 13 distinct queries, measured 12"]


def test_failed_queries_are_reported() -> None:
    problems = smoke.check_result("ssb", _payload([str(n) for n in range(13)], failed=("4",)))

    assert problems == ["ssb: non-successful queries 4"]


def test_main_fails_when_a_benchmark_result_is_missing(tmp_path: Path) -> None:
    _write(tmp_path, "ssb", _payload([str(n) for n in range(13)]))

    assert smoke.main([str(tmp_path), "--benchmark", "ssb"]) == 0
    assert smoke.main([str(tmp_path), "--benchmark", "ssb", "--benchmark", "tpch"]) == 1
