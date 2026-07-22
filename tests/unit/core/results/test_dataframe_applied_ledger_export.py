"""Export parity: a DataFrame run's applied-tuning ledger reaches the bundle.

The DataFrame path populates the same ``applied_tuning_ledger`` /
``applied_ledger_hash`` / ``tuning_validation_status`` result fields the SQL path
does, so it reuses the shared export path unchanged: the ``.applied.json``
companion (``build_applied_ledger_payload``) and the ``platform.tuning`` summary
block (``build_result_payload`` -> ``_build_tuning_summary``, the block the
explorer ingests via ``platform.tuning.applied_ledger_hash``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration
from benchbox.core.results.schema import (
    build_applied_ledger_payload,
    build_result_payload,
    build_tuning_payload,
)
from benchbox.core.schemas import BenchmarkConfig
from benchbox.platforms.dataframe.benchmark_mixin import (
    DataFramePhases,
    DataFrameRunOptions,
)
from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _run(adapter, name: str = "tpch"):
    benchmark = SimpleNamespace(name=name, display_name=name.upper(), scale_factor=1.0, tables={})
    config = BenchmarkConfig(name=name, display_name=name.upper(), scale_factor=1.0)
    return adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=False),
        options=DataFrameRunOptions(ignore_memory_warnings=True, prefer_parquet=False),
    )


def _tuned_polars() -> PolarsDataFrameAdapter:
    cfg = DataFrameTuningConfiguration()
    cfg.parallelism.thread_count = 4
    cfg.execution.streaming_mode = True
    return PolarsDataFrameAdapter(tuning_config=cfg)


def test_tuned_df_result_carries_applied_ledger_hash_in_platform_tuning_summary():
    result = _run(_tuned_polars())
    payload = build_result_payload(result)

    tuning = payload["platform"]["tuning"]
    # Same summary block the explorer ingests (platform.tuning.applied_ledger_hash).
    assert tuning["applied_ledger_hash"] == result.applied_ledger_hash
    assert tuning["applied_ledger_hash"] is not None

    # The honest execution-derived status is exported via the .tuning.json
    # companion (build_tuning_payload), mirroring the SQL side.
    assert build_tuning_payload(result)["validation_status"] == "applied_unverified"


def test_tuned_df_result_emits_applied_json_companion():
    result = _run(_tuned_polars())
    companion = build_applied_ledger_payload(result)

    assert companion is not None
    assert companion["status"] == "applied_unverified"
    assert companion["applied_ledger_hash"] == result.applied_ledger_hash
    recorded = {s["statement"] for s in companion["statements"]}
    assert "POLARS_MAX_THREADS=4" in recorded
    # Recorded by the execution path with the honest DataFrame-runtime mechanism.
    assert all(s.get("mechanism") == "dataframe_runtime" for s in companion["statements"])


def test_default_df_result_emits_no_applied_companion_and_noop_status():
    result = _run(PolarsDataFrameAdapter())

    # A default/untuned run derives noop and writes no companion.
    assert result.tuning_validation_status == "noop"
    assert build_applied_ledger_payload(result) is None

    # With an empty requested config there is no platform.tuning summary block
    # (nothing to summarize) -- the honest status still lives on the result.
    payload = build_result_payload(result)
    assert "tuning" not in payload["platform"]
