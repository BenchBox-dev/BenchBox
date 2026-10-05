from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from benchbox.core.results.metrics import TPCMetricsCalculator
from tests.uat.throughput_baseline import (
    build_baseline_record,
    load_baseline_records,
    main,
    rolling_median,
    runner_class_for,
    write_baseline_record,
)

pytestmark = pytest.mark.fast


def _good_result(throughput_at_size: float) -> dict:
    return {
        "phases": {"throughput_test": {"duration_ms": 1_000_000}},
        "summary": {"tpc_metrics": {"throughput_at_size": throughput_at_size}},
    }


_ENV = {
    "RUNNER_OS": "Linux",
    "RUNNER_ARCH": "X64",
    "ImageVersion": "20260930.1",
    "GITHUB_RUN_ID": "555",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_SHA": "abc123",
}


def _record(
    value: float, *, run_id: str, day: int, cpu: str = "AMD EPYC 7763 64-Core Processor", cpus: int = 4
) -> dict:
    return build_baseline_record(
        _good_result(value),
        platform="duckdb",
        benchmark="tpch",
        scale=1,
        streams=3,
        cpu_model=cpu,
        cpu_count=cpus,
        env={**_ENV, "GITHUB_RUN_ID": run_id},
        recorded_at=datetime(2026, 10, day, 6, 0, tzinfo=timezone.utc),
    )


def test_build_baseline_record_captures_throughput_runner_and_run_identity():
    record = _record(98548.3, run_id="555", day=4)
    assert record["throughput_at_size"] == pytest.approx(98548.3)
    assert record["throughput_duration_ms"] == 1_000_000
    assert record["runner_class"] == "amd-epyc-7763-64-core-processor-4cpu"
    assert record["cpu_model"] == "AMD EPYC 7763 64-Core Processor"
    assert record["run_id"] == "555"
    assert record["run_attempt"] == "2"
    assert record["commit_sha"] == "abc123"
    assert record["platform"] == "duckdb"
    assert record["scale_factor"] == 1.0
    assert record["recorded_at"] == "2026-10-04T06:00:00+00:00"


def test_runner_class_separates_cpu_models_and_core_counts():
    assert runner_class_for("Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz", 4) != runner_class_for(
        "AMD EPYC 7763 64-Core Processor", 4
    )
    assert runner_class_for("AMD EPYC 7763 64-Core Processor", 2) != runner_class_for(
        "AMD EPYC 7763 64-Core Processor", 4
    )
    assert runner_class_for("", 4) == "unknown-4cpu"


def test_write_and_load_baseline_records_round_trip_through_nested_artifact_dirs(tmp_path: Path):
    first = write_baseline_record(tmp_path / "run-555", _record(1.0, run_id="555", day=4))
    write_baseline_record(tmp_path / "run-556", _record(2.0, run_id="556", day=5))
    (tmp_path / "run-557").mkdir()
    (tmp_path / "run-557" / "throughput-baseline-garbage.json").write_text("{oops", encoding="utf-8")
    (tmp_path / "run-558").mkdir()
    (tmp_path / "run-558" / "throughput-baseline-old.json").write_text('{"schema_version": 0}', encoding="utf-8")
    assert first.name == "throughput-baseline-duckdb-tpch-sf1-555-2.json"
    records = load_baseline_records(tmp_path)
    assert sorted(record["run_id"] for record in records) == ["555", "556"]


def test_rolling_median_is_computed_per_runner_class():
    slow = "AMD EPYC 7763 64-Core Processor"
    fast = "Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz"
    records = [
        _record(value, run_id=str(day), day=day, cpu=slow) for day, value in zip(range(1, 4), (73000, 75000, 79000))
    ]
    records += [
        _record(value, run_id=str(10 + day), day=day, cpu=fast)
        for day, value in zip(range(1, 4), (92000, 96000, 98000))
    ]

    slow_median = rolling_median(
        records, platform="duckdb", benchmark="tpch", scale=1, runner_class=runner_class_for(slow, 4)
    )
    fast_median = rolling_median(
        records, platform="duckdb", benchmark="tpch", scale=1, runner_class=runner_class_for(fast, 4)
    )

    assert slow_median is not None and fast_median is not None
    assert slow_median.median == 75000
    assert fast_median.median == 96000
    assert slow_median.count == 3


def test_rolling_median_uses_only_the_latest_window_of_runs():
    records = [_record(float(day * 1000), run_id=str(day), day=day) for day in range(1, 8)]
    result = rolling_median(
        records,
        platform="duckdb",
        benchmark="tpch",
        scale=1,
        runner_class=runner_class_for("AMD EPYC 7763 64-Core Processor", 4),
        window=3,
    )
    assert result is not None
    assert result.run_ids == ("7", "6", "5")
    assert result.median == 6000


def test_rolling_median_requires_min_samples_and_matching_cell():
    records = [_record(1000.0, run_id="1", day=1)]
    runner_class = runner_class_for("AMD EPYC 7763 64-Core Processor", 4)
    assert (
        rolling_median(records, platform="duckdb", benchmark="tpch", scale=1, runner_class=runner_class, min_samples=2)
        is None
    )
    assert rolling_median(records, platform="postgresql", benchmark="tpch", scale=1, runner_class=runner_class) is None
    assert rolling_median(records, platform="duckdb", benchmark="tpch", scale=10, runner_class=runner_class) is None
    assert rolling_median(records, platform="duckdb", benchmark="tpch", scale=1, runner_class="other") is None


def test_cli_rolling_median_prints_per_class_median(tmp_path: Path, capsys):
    for day, value in zip(range(1, 4), (1000.0, 2000.0, 3000.0)):
        write_baseline_record(tmp_path / f"run-{day}", _record(value, run_id=str(day), day=day))
    runner_class = runner_class_for("AMD EPYC 7763 64-Core Processor", 4)

    code = main(
        [
            "rolling-median",
            "--baseline-dir",
            str(tmp_path),
            "--platform",
            "duckdb",
            "--benchmark",
            "tpch",
            "--scale",
            "1",
            "--runner-class",
            runner_class,
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["median"] == 2000.0
    assert payload["count"] == 3
    assert payload["runner_class"] == runner_class


def test_cli_rolling_median_fails_without_enough_baselines(tmp_path: Path, capsys):
    code = main(
        [
            "rolling-median",
            "--baseline-dir",
            str(tmp_path),
            "--platform",
            "duckdb",
            "--benchmark",
            "tpch",
            "--scale",
            "1",
            "--runner-class",
            "none",
            "--min-samples",
            "3",
        ]
    )
    assert code == 1
    assert "fewer than 3 retained baselines" in capsys.readouterr().out
