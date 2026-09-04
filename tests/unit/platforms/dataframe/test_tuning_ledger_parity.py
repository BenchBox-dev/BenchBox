"""DataFrame applied-tuning ledger parity with the SQL execution path.

The SQL side records what tuning actually executed into an ``AppliedTuningLedger``
and derives an honest ``tuning_validation_status`` from it. These tests assert the
DataFrame runtime path reaches the same parity: runtime settings (threads/memory/
write-layout) the DF path actually applies are recorded into the SAME shared
ledger (``benchbox.core.tuning.applied_ledger``), a default/untuned run derives
``noop``, and a tuned run derives ``applied_unverified`` and carries the ledger
companion + physical-identity hash on the built ``BenchmarkResults``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration
from benchbox.core.dataframe.tuning.write_config import (
    DataFrameWriteConfiguration,
    SortColumn,
)
from benchbox.core.schemas import BenchmarkConfig
from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    NOOP,
    PHASE_POST_LOAD,
    PHASE_SESSION,
)
from benchbox.platforms.dataframe.benchmark_mixin import (
    DataFramePhases,
    DataFrameRunOptions,
)
from benchbox.platforms.dataframe.dask_df import DASK_AVAILABLE, DaskDataFrameAdapter
from benchbox.platforms.dataframe.datafusion_df import (
    DATAFUSION_DF_AVAILABLE,
    DataFusionDataFrameAdapter,
)
from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter
from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter
from benchbox.platforms.dataframe.tuning_mixin import (
    DATAFRAME_RUNTIME_MECHANISM,
    DATAFRAME_WRITE_LAYOUT_MECHANISM,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _polars_thread_config(threads: int = 6, chunk_size: int = 100_000) -> DataFrameTuningConfiguration:
    cfg = DataFrameTuningConfiguration()
    cfg.parallelism.thread_count = threads
    cfg.memory.chunk_size = chunk_size
    cfg.execution.streaming_mode = True
    return cfg


def _datafusion_thread_config(threads: int = 4, chunk_size: int = 16_384) -> DataFrameTuningConfiguration:
    cfg = DataFrameTuningConfiguration()
    cfg.parallelism.thread_count = threads
    cfg.memory.chunk_size = chunk_size
    # Streaming is per-query in DataFusion; enabling it must not create a ledger entry.
    cfg.execution.streaming_mode = True
    return cfg


def _dask_worker_config(workers: int = 3, threads: int = 2) -> DataFrameTuningConfiguration:
    cfg = DataFrameTuningConfiguration()
    cfg.parallelism.worker_count = workers
    cfg.parallelism.threads_per_worker = threads
    return cfg


# ---------------------------------------------------------------------------
# Construction-time runtime settings -> SESSION ledger statements
# ---------------------------------------------------------------------------
class TestRuntimeSettingsRecorded:
    def test_default_polars_run_is_noop_with_empty_ledger(self):
        adapter = PolarsDataFrameAdapter()
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is None

    def test_tuned_polars_records_applied_runtime_settings(self):
        adapter = PolarsDataFrameAdapter(tuning_config=_polars_thread_config())
        ledger = adapter._applied_tuning_ledger
        statements = {s.statement for s in ledger.statements}

        assert "POLARS_MAX_THREADS=6" in statements
        assert "streaming_chunk_size=100000" in statements
        assert "streaming_mode=on" in statements
        # All recorded as executed SESSION statements with the DF-runtime mechanism.
        for s in ledger.statements:
            assert s.phase == PHASE_SESSION
            assert s.mechanism == DATAFRAME_RUNTIME_MECHANISM
            assert s.status == "executed"

        # >=1 executed statement -> applied_unverified + a physical-identity hash.
        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is not None

    def test_default_pandas_run_is_noop(self):
        adapter = PandasDataFrameAdapter()
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP

    def test_tuned_pandas_records_dtype_backend(self):
        cfg = DataFrameTuningConfiguration()
        cfg.data_types.dtype_backend = "pyarrow"
        adapter = PandasDataFrameAdapter(tuning_config=cfg)

        statements = {s.statement for s in adapter._applied_tuning_ledger.statements}
        assert "dtype_backend=pyarrow" in statements
        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED

    def test_ledger_hash_is_deterministic_across_two_identical_adapters(self):
        cfg_a = _polars_thread_config()
        cfg_b = _polars_thread_config()
        hash_a = PolarsDataFrameAdapter(tuning_config=cfg_a)._applied_tuning_ledger.applied_ledger_hash()
        hash_b = PolarsDataFrameAdapter(tuning_config=cfg_b)._applied_tuning_ledger.applied_ledger_hash()
        assert hash_a == hash_b

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_default_datafusion_run_is_noop_with_empty_ledger(self):
        adapter = DataFusionDataFrameAdapter()
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is None

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_tuned_datafusion_records_applied_runtime_settings(self):
        adapter = DataFusionDataFrameAdapter(tuning_config=_datafusion_thread_config())
        ledger = adapter._applied_tuning_ledger
        statements = {s.statement for s in ledger.statements}

        assert "target_partitions=4" in statements
        assert "batch_size=16384" in statements
        # Streaming is logged as per-query only; must not appear as applied.
        assert not any(s.startswith("streaming_mode=") for s in statements)
        for s in ledger.statements:
            assert s.phase == PHASE_SESSION
            assert s.mechanism == DATAFRAME_RUNTIME_MECHANISM
            assert s.status == "executed"

        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is not None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_default_dask_run_is_noop_with_empty_ledger(self):
        # use_distributed=False avoids starting a LocalCluster for this unit proof.
        adapter = DaskDataFrameAdapter(use_distributed=False)
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_records_applied_runtime_settings(self):
        adapter = DaskDataFrameAdapter(
            use_distributed=False,
            tuning_config=_dask_worker_config(),
        )
        ledger = adapter._applied_tuning_ledger
        statements = {s.statement for s in ledger.statements}

        assert "n_workers=3" in statements
        assert "threads_per_worker=2" in statements
        for s in ledger.statements:
            assert s.phase == PHASE_SESSION
            assert s.mechanism == DATAFRAME_RUNTIME_MECHANISM
            assert s.status == "executed"

        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is not None


# ---------------------------------------------------------------------------
# Physical write-layout -> POST_LOAD ledger statements
# ---------------------------------------------------------------------------
class TestWriteLayoutRecorded:
    def test_write_layout_recorded_as_post_load_statements(self):
        adapter = PolarsDataFrameAdapter()
        write_config = DataFrameWriteConfiguration(
            sort_by=[SortColumn(name="l_shipdate", order="asc")],
            compression="snappy",
            row_group_size=500_000,
        )
        adapter._fold_write_layout_into_ledger(write_config)

        post_load = [s for s in adapter._applied_tuning_ledger.statements if s.phase == PHASE_POST_LOAD]
        statements = {s.statement for s in post_load}

        assert any(s.mechanism == DATAFRAME_WRITE_LAYOUT_MECHANISM for s in post_load)
        assert 'sort_by=[{"name":"l_shipdate","order":"asc"}]' in statements
        assert "compression=snappy" in statements
        assert "row_group_size=500000" in statements
        # A run recording only write-layout still derives applied_unverified.
        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED

    def test_default_write_config_records_nothing(self):
        adapter = PolarsDataFrameAdapter()
        adapter._fold_write_layout_into_ledger(DataFrameWriteConfiguration())
        assert adapter._applied_tuning_ledger.is_empty()

    def test_none_write_config_records_nothing(self):
        adapter = PolarsDataFrameAdapter()
        adapter._fold_write_layout_into_ledger(None)
        assert adapter._applied_tuning_ledger.is_empty()

    def test_refold_is_idempotent(self):
        adapter = PolarsDataFrameAdapter(tuning_config=_polars_thread_config())
        write_config = DataFrameWriteConfiguration(compression="zstd", compression_level=9)

        adapter._fold_write_layout_into_ledger(write_config)
        adapter._fold_write_layout_into_ledger(write_config)

        post_load = [s for s in adapter._applied_tuning_ledger.statements if s.phase == PHASE_POST_LOAD]
        session = [s for s in adapter._applied_tuning_ledger.statements if s.phase == PHASE_SESSION]
        # write-layout statements are not duplicated by a second fold ...
        assert len(post_load) == 1
        assert post_load[0].statement == "compression_level=9"
        # ... and the construction-time SESSION statements are left untouched.
        assert len(session) == 3


# ---------------------------------------------------------------------------
# run_benchmark result wiring: the built BenchmarkResults carries the ledger
# ---------------------------------------------------------------------------
def _run_no_phases(adapter, name: str = "tpch"):
    """Drive run_benchmark with no load/execute phases so the result reflects
    only the construction-time applied ledger (no data files needed)."""
    benchmark = SimpleNamespace(name=name, display_name=name.upper(), scale_factor=1.0, tables={})
    config = BenchmarkConfig(name=name, display_name=name.upper(), scale_factor=1.0)
    return adapter.run_benchmark(
        benchmark,
        benchmark_config=config,
        phases=DataFramePhases(load=False, execute=False),
        options=DataFrameRunOptions(ignore_memory_warnings=True, prefer_parquet=False),
    )


class TestRunBenchmarkCarriesLedger:
    def test_tuned_run_result_carries_ledger_and_applied_unverified(self):
        adapter = PolarsDataFrameAdapter(tuning_config=_polars_thread_config())
        result = _run_no_phases(adapter)

        assert result.tuning_validation_status == APPLIED_UNVERIFIED
        assert result.applied_ledger_hash is not None
        assert result.applied_ledger_hash == adapter._applied_tuning_ledger.applied_ledger_hash()

        payload = result.applied_tuning_ledger
        assert isinstance(payload, dict)
        assert payload["status"] == APPLIED_UNVERIFIED
        assert payload["applied_ledger_hash"] == result.applied_ledger_hash
        recorded = {s["statement"] for s in payload["statements"]}
        assert "POLARS_MAX_THREADS=6" in recorded

    def test_default_run_result_is_noop_without_companion(self):
        adapter = PolarsDataFrameAdapter()
        result = _run_no_phases(adapter)

        assert result.tuning_validation_status == NOOP
        # Empty ledger writes no companion payload/hash (a default run is a no-op).
        assert result.applied_tuning_ledger is None
        assert result.applied_ledger_hash is None

    def test_default_pandas_run_result_is_noop(self):
        adapter = PandasDataFrameAdapter()
        result = _run_no_phases(adapter)
        assert result.tuning_validation_status == NOOP

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_tuned_datafusion_run_result_carries_ledger_and_applied_unverified(self):
        adapter = DataFusionDataFrameAdapter(tuning_config=_datafusion_thread_config())
        result = _run_no_phases(adapter)

        assert result.tuning_validation_status == APPLIED_UNVERIFIED
        assert result.applied_ledger_hash is not None
        assert result.applied_ledger_hash == adapter._applied_tuning_ledger.applied_ledger_hash()

        payload = result.applied_tuning_ledger
        assert isinstance(payload, dict)
        assert payload["status"] == APPLIED_UNVERIFIED
        assert payload["applied_ledger_hash"] == result.applied_ledger_hash
        recorded = {s["statement"] for s in payload["statements"]}
        assert "target_partitions=4" in recorded

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_default_datafusion_run_result_is_noop(self):
        adapter = DataFusionDataFrameAdapter()
        result = _run_no_phases(adapter)
        assert result.tuning_validation_status == NOOP
        assert result.applied_tuning_ledger is None
        assert result.applied_ledger_hash is None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_run_result_carries_ledger_and_applied_unverified(self):
        adapter = DaskDataFrameAdapter(
            use_distributed=False,
            tuning_config=_dask_worker_config(),
        )
        result = _run_no_phases(adapter)

        assert result.tuning_validation_status == APPLIED_UNVERIFIED
        assert result.applied_ledger_hash is not None
        assert result.applied_ledger_hash == adapter._applied_tuning_ledger.applied_ledger_hash()

        payload = result.applied_tuning_ledger
        assert isinstance(payload, dict)
        assert payload["status"] == APPLIED_UNVERIFIED
        assert payload["applied_ledger_hash"] == result.applied_ledger_hash
        recorded = {s["statement"] for s in payload["statements"]}
        assert "n_workers=3" in recorded

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_default_dask_run_result_is_noop(self):
        adapter = DaskDataFrameAdapter(use_distributed=False)
        result = _run_no_phases(adapter)
        assert result.tuning_validation_status == NOOP
        assert result.applied_tuning_ledger is None
        assert result.applied_ledger_hash is None
