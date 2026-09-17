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


def _dask_memory_config(
    memory_limit: str = "2GB",
    spill_directory: str | None = None,
) -> DataFrameTuningConfiguration:
    cfg = DataFrameTuningConfiguration()
    cfg.memory.memory_limit = memory_limit
    cfg.memory.spill_to_disk = True
    if spill_directory is not None:
        cfg.memory.spill_directory = spill_directory
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
        _ = adapter.session_ctx
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
    def test_tuned_dask_non_distributed_run_does_not_record_cluster_settings(self):
        adapter = DaskDataFrameAdapter(
            use_distributed=False,
            tuning_config=_dask_worker_config(),
        )
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_existing_scheduler_does_not_record_cluster_settings(self, monkeypatch):
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", lambda _address: object())
        adapter = DaskDataFrameAdapter(
            use_distributed=False,
            scheduler_address="tcp://scheduler:8786",
            tuning_config=_dask_worker_config(),
        )
        assert adapter._applied_tuning_ledger.is_empty()

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_local_cluster_records_consumed_settings(self, monkeypatch):
        captured: dict[str, object] = {}

        class FakeCluster:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        class FakeClient:
            def __init__(self, cluster):
                self.cluster = cluster

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", FakeClient)
        adapter = DaskDataFrameAdapter(
            use_distributed=True,
            tuning_config=_dask_worker_config(),
        )
        statements = {s.statement for s in adapter._applied_tuning_ledger.statements}

        assert captured["n_workers"] == 3
        assert captured["threads_per_worker"] == 2
        assert statements == {"n_workers=3", "threads_per_worker=2"}

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_records_applied_runtime_settings(self, monkeypatch):
        class FakeCluster:
            def __init__(self, **_kwargs):
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", lambda cluster: cluster)
        adapter = DaskDataFrameAdapter(
            use_distributed=True,
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

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_memory_settings_recorded_when_cluster_consumes_them(self, monkeypatch, tmp_path):
        import dask

        dask_config_sets: list = []
        monkeypatch.setattr(dask.config, "set", lambda *args, **kwargs: dask_config_sets.append((args, kwargs)))
        captured: dict[str, object] = {}

        class FakeCluster:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        class FakeClient:
            def __init__(self, cluster):
                self.cluster = cluster

            def close(self):
                pass

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", FakeClient)
        spill_dir = tmp_path / "spill"
        adapter = DaskDataFrameAdapter(
            use_distributed=True,
            tuning_config=_dask_memory_config(spill_directory=str(spill_dir)),
        )
        ledger = adapter._applied_tuning_ledger
        statements = {s.statement for s in ledger.statements}

        # A memory-only tuned run must not publish noop: every consumed memory
        # setting is recorded, and the values reached the cluster envelope.
        # Scoped to the memory domain so unrelated future recordings do not
        # break this test, while default memory settings leaking in still fail.
        memory_statements = {
            s for s in statements if s.split("=")[0] in {"memory_limit", "spill_to_disk", "spill_directory"}
        }
        assert memory_statements == {
            "memory_limit=2GB",
            "spill_to_disk=on",
            f"spill_directory={spill_dir}",
        }
        for s in ledger.statements:
            assert s.phase == PHASE_SESSION
            assert s.mechanism == DATAFRAME_RUNTIME_MECHANISM
            assert s.status == "executed"
        assert captured["memory_limit"] == "2GB"
        assert captured["local_directory"] == str(spill_dir)
        assert any(
            isinstance(args[0], dict) and args[0].get("distributed.worker.memory.spill") is True
            for args, _kwargs in dask_config_sets
        ), "spill flags must reach dask.config when spilling is enabled"

        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is not None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_dask_spill_directory_consumed_via_default_spill_envelope_is_recorded(self, monkeypatch, tmp_path):
        import dask

        dask_config_sets: list = []
        monkeypatch.setattr(dask.config, "set", lambda *args, **kwargs: dask_config_sets.append((args, kwargs)))
        captured: dict[str, object] = {}

        class FakeCluster:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        class FakeClient:
            def __init__(self, cluster):
                self.cluster = cluster

            def close(self):
                pass

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", FakeClient)
        spill_dir = tmp_path / "spill"
        cfg = DataFrameTuningConfiguration()
        cfg.memory.spill_directory = str(spill_dir)
        adapter = DaskDataFrameAdapter(use_distributed=True, tuning_config=cfg)

        # spill_to_disk was left off, but the local resource envelope enables
        # spilling by default, so the configured directory still reaches the
        # cluster envelope and must be claimed rather than lost to a noop.
        assert captured["local_directory"] == str(spill_dir)
        assert any(
            isinstance(args[0], dict) and args[0].get("distributed.worker.memory.spill") is True
            for args, _kwargs in dask_config_sets
        ), "spill flags must reach dask.config when spilling is enabled"
        statements = {s.statement for s in adapter._applied_tuning_ledger.statements}
        spill_statements = {s for s in statements if s.split("=")[0] in {"spill_to_disk", "spill_directory"}}
        assert spill_statements == {f"spill_directory={spill_dir}"}
        # Spilling itself was a default, not a tuned setting: no false claim.
        assert "spill_to_disk=on" not in statements
        assert adapter._derive_applied_tuning_status() == APPLIED_UNVERIFIED
        assert adapter._applied_tuning_ledger.applied_ledger_hash() is not None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_dask_spill_directory_never_consumed_records_nothing(self, monkeypatch, tmp_path):
        import dask

        import benchbox.core.dataframe.tuning as tuning

        monkeypatch.setattr(dask.config, "set", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            tuning,
            "get_smart_defaults",
            lambda _platform: SimpleNamespace(
                parallelism=SimpleNamespace(worker_count=None, threads_per_worker=None),
                memory=SimpleNamespace(memory_limit=None, spill_to_disk=False),
            ),
        )
        captured: dict[str, object] = {}

        class FakeCluster:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        class FakeClient:
            def __init__(self, cluster):
                self.cluster = cluster

            def close(self):
                pass

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", FakeClient)
        cfg = DataFrameTuningConfiguration()
        cfg.memory.spill_directory = str(tmp_path / "spill")
        adapter = DaskDataFrameAdapter(use_distributed=True, tuning_config=cfg)

        # Spilling stays off, so the directory is stored but never consumed by
        # the cluster envelope: an honest empty ledger, not a false claim.
        assert "local_directory" not in captured
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_constructor_spill_directory_without_tuning_config_stays_noop(self, monkeypatch, tmp_path):
        """A bare constructor spill directory is infrastructure, not tuning.

        With no tuning configuration, a platform-option spill directory that
        reaches the cluster must not flip the run from noop to
        applied_unverified: every other ledger entry gates on the tuning
        config, and spill_directory must be no different.
        """
        import dask

        monkeypatch.setattr(dask.config, "set", lambda *_args, **_kwargs: None)
        captured: dict[str, object] = {}

        class FakeCluster:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        class FakeClient:
            def __init__(self, cluster):
                self.cluster = cluster

            def close(self):
                pass

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", FakeClient)
        spill_dir = tmp_path / "spill"
        adapter = DaskDataFrameAdapter(use_distributed=True, spill_directory=str(spill_dir))

        assert captured["local_directory"] == str(spill_dir)
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP


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
        _ = adapter.session_ctx
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
    def test_tuned_datafusion_lazy_context_is_not_reported_as_applied(self):
        adapter = DataFusionDataFrameAdapter(tuning_config=_datafusion_thread_config())
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_datafusion_context_fallback_does_not_record_tuning(self, monkeypatch):
        class BrokenSessionConfig:
            def __init__(self):
                raise RuntimeError("configuration unavailable")

        monkeypatch.setattr("benchbox.platforms.dataframe.datafusion_df.SessionConfig", BrokenSessionConfig)
        adapter = DataFusionDataFrameAdapter(tuning_config=_datafusion_thread_config())
        _ = adapter.session_ctx
        assert adapter._applied_tuning_ledger.is_empty()
        assert adapter._derive_applied_tuning_status() == NOOP

    @pytest.mark.skipif(not DATAFUSION_DF_AVAILABLE, reason="DataFusion not installed")
    def test_default_datafusion_run_result_is_noop(self):
        adapter = DataFusionDataFrameAdapter()
        result = _run_no_phases(adapter)
        assert result.tuning_validation_status == NOOP
        assert result.applied_tuning_ledger is None
        assert result.applied_ledger_hash is None

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_tuned_dask_run_result_carries_ledger_and_applied_unverified(self, monkeypatch):
        class FakeCluster:
            def __init__(self, **_kwargs):
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", lambda cluster: cluster)
        adapter = DaskDataFrameAdapter(
            use_distributed=True,
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
    def test_tuned_dask_memory_run_result_carries_ledger_and_applied_unverified(self, monkeypatch, tmp_path):
        import dask

        monkeypatch.setattr(dask.config, "set", lambda *_args, **_kwargs: None)

        class FakeCluster:
            def __init__(self, **_kwargs):
                self.scheduler = SimpleNamespace(address="tcp://fixture:8786")
                self.workers = {}

        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.LocalCluster", FakeCluster)
        monkeypatch.setattr("benchbox.platforms.dataframe.dask_df.Client", lambda cluster: cluster)
        adapter = DaskDataFrameAdapter(
            use_distributed=True,
            tuning_config=_dask_memory_config(spill_directory=str(tmp_path / "spill")),
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
        assert "memory_limit=2GB" in recorded
        assert "spill_to_disk=on" in recorded
        assert f"spill_directory={tmp_path / 'spill'}" in recorded

    @pytest.mark.skipif(not DASK_AVAILABLE, reason="Dask not installed")
    def test_default_dask_run_result_is_noop(self):
        adapter = DaskDataFrameAdapter(use_distributed=False)
        result = _run_no_phases(adapter)
        assert result.tuning_validation_status == NOOP
        assert result.applied_tuning_ledger is None
        assert result.applied_ledger_hash is None
