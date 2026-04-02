"""Coverage-focused tests for remaining TPC-DI worker/pipeline/source modules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import benchbox.utils.printing as printing
from benchbox.core.tpcdi.etl.pipeline import TPCDIETLPipeline
from benchbox.core.tpcdi.source_generators import TPCDISourceDataGenerator
from benchbox.core.tpcdi.worker_pool_examples import (
    SimpleWorkerPoolManager,
    example_usage,
    parallel_file_processing,
    simple_parallel_processing,
    streaming_parallel_processing,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _FetchOne:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class _FetchAll:
    def __init__(self, value):
        self.value = value

    def fetchall(self):
        return self.value


class FakeConnection:
    def __init__(self):
        self.executed: list[str] = []
        self.executemany_calls: list[tuple[str, int]] = []
        self.raise_on_execute = False

    def execute(self, sql):
        self.executed.append(sql)
        if self.raise_on_execute:
            raise RuntimeError("execute failure")
        if "COUNT(*)" in sql:
            return _FetchOne((5,))
        if "SK_CustomerID" in sql:
            return _FetchAll([(1,), (2,)])
        if "SK_AccountID" in sql:
            return _FetchAll([(10,), (11,)])
        if "SK_SecurityID" in sql:
            return _FetchAll([(20,), (21,)])
        if "SK_CompanyID" in sql:
            return _FetchAll([(30,), (31,)])
        if "SK_DateID" in sql:
            return _FetchAll([(1,), (2,), (3,)])
        if "SK_TimeID" in sql:
            return _FetchAll([(100,), (200,)])
        return _FetchOne((None,))

    def query(self, sql):
        self.executed.append(sql)
        return _FetchOne((7,))

    def executemany(self, sql, records):
        self.executemany_calls.append((sql, len(records)))


def test_simple_parallel_processing_modes_and_errors():
    assert simple_parallel_processing([1, 2], lambda x: x * 2, enable_parallel=False) == [2, 4]
    assert simple_parallel_processing([], lambda x: x, enable_parallel=True) == []
    # parallel branch
    out = simple_parallel_processing([1, 2, 3], lambda x: x + 1, max_workers=2, enable_parallel=True)
    assert sorted(out) == [2, 3, 4]

    def flaky(x):
        if x == 2:
            raise ValueError("boom")
        return x

    out = simple_parallel_processing([1, 2, 3], flaky, max_workers=2, enable_parallel=True)
    assert sorted(out) == [1, 3]


def test_parallel_file_processing_and_streaming():
    def proc(path: Path):
        if "bad" in path.name:
            raise RuntimeError("bad")
        return {"file_path": str(path), "record_count": 3}

    seq = parallel_file_processing([Path("a"), Path("bad")], proc, enable_parallel=False)
    assert seq["total_records"] == 3
    assert len(seq["errors"]) == 1

    par = parallel_file_processing([Path("a"), Path("b")], proc, max_workers=2, enable_parallel=True)
    assert par["total_records"] == 6

    stream = iter([1, 2, 3])
    assert list(streaming_parallel_processing(stream, lambda x: x * 3, enable_parallel=False)) == [3, 6, 9]

    stream2 = iter([1, 2, 3, 4])
    out = list(streaming_parallel_processing(stream2, lambda x: x + 10, max_workers=2, enable_parallel=True))
    assert sorted(out) == [11, 12, 13, 14]


def test_worker_pool_manager_and_example_usage(monkeypatch, capsys):
    monkeypatch.setattr(printing, "_QUIET", False)
    monkeypatch.setattr(printing, "_STD_CONSOLE", None)
    manager = SimpleWorkerPoolManager(max_workers=2, enable_parallel=False)
    assert manager.process_batch([1, 2], lambda x: x * 2) == [2, 4]
    assert manager.transform_tables({"a": 1}, lambda n, d: f"{n}-{d}") == {"a": "a-1"}

    manager_p = SimpleWorkerPoolManager(max_workers=2, enable_parallel=True)
    out = manager_p.process_batch([1, 2, 3], lambda x: x + 1)
    assert sorted(out) == [2, 3, 4]
    tables = manager_p.transform_tables({"x": 1, "y": 2}, lambda n, d: f"{n}:{d}")
    assert set(tables) == {"x", "y"}

    monkeypatch.setattr("benchbox.core.tpcdi.worker_pool_examples.time.sleep", lambda *_a, **_k: None)
    example_usage()
    printed = capsys.readouterr().out
    assert "Sequential results:" in printed
    assert "Parallel results:" in printed


def test_pipeline_historical_incremental_and_helpers(monkeypatch):
    conn = FakeConnection()
    pipeline = TPCDIETLPipeline(connection=conn, benchmark=SimpleNamespace())

    # historical success path
    monkeypatch.setattr(pipeline, "_load_dimension_tables", lambda _b, _sf: 10)
    monkeypatch.setattr(pipeline, "_load_fact_tables", lambda _b, _sf: 20)
    monkeypatch.setattr(pipeline, "_create_performance_indexes", lambda: None)
    result = pipeline.run_historical_load(scale_factor=0.01)
    assert result.success is True
    assert result.total_records_processed == 30

    # historical failure path
    def raise_dim(_b, _sf):
        raise RuntimeError("fail")

    monkeypatch.setattr(pipeline, "_load_dimension_tables", raise_dim)
    result_fail = pipeline.run_historical_load(scale_factor=0.01)
    assert result_fail.success is False

    # incremental + scd processing path
    monkeypatch.setattr(pipeline, "_process_dimension_changes", lambda _b, _d, _sf: 7)
    monkeypatch.setattr(pipeline, "_process_fact_increments", lambda _b, _d, _sf: 9)
    inc = pipeline.run_incremental_load(batch_id=2, scale_factor=0.01)
    assert inc.success is True
    assert inc.total_records_processed == 16

    assert pipeline.run_scd_processing(conn, "DimCustomer", 3) == 5
    conn.raise_on_execute = True
    assert pipeline.run_scd_processing(conn, "DimCustomer", 3) == 0

    # index creation tolerates per-index errors
    conn.raise_on_execute = False
    called = {"count": 0}

    def flaky_execute(sql):
        called["count"] += 1
        if called["count"] == 1:
            raise RuntimeError("idx")
        return _FetchOne((None,))

    conn.execute = flaky_execute  # type: ignore[method-assign]
    pipeline._create_performance_indexes()


def test_pipeline_synthetic_generation_methods():
    conn = FakeConnection()
    pipeline = TPCDIETLPipeline(connection=conn, benchmark=SimpleNamespace())

    assert pipeline._generate_date_dimension() > 0
    assert pipeline._generate_time_dimension() > 0
    assert pipeline._generate_customer_dimension(2) == 2
    assert pipeline._generate_company_dimension(2) == 2
    assert pipeline._generate_security_dimension(2) == 2
    assert pipeline._generate_account_dimension(2) == 2
    assert pipeline._generate_trade_fact(3) == 3

    assert pipeline._generate_synthetic_dimension_data(0.01) > 0
    assert pipeline._generate_synthetic_fact_data(0.01) > 0


def test_source_generators_basic_and_output_files(tmp_path: Path, monkeypatch):
    gen = TPCDISourceDataGenerator(scale_factor=0.0001, output_dir=tmp_path)
    assert gen.start_date <= gen.end_date
    assert "Technology" in gen.industries

    # lightweight direct generators
    c = Path(gen._generate_customer_extract())
    a = Path(gen._generate_account_extract())
    t = Path(gen._generate_trade_extract())
    assert c.exists() and a.exists() and t.exists()

    # orchestrators
    all_paths = gen.generate_all_source_data()
    assert set(all_paths) == {"oltp_system", "hr_system", "crm_system", "external_data"}

    info = gen.get_file_format_info()
    assert "oltp_customer_extract.csv" in info
    assert gen.generate_data_quality_issues(str(c), issue_rate=0.1) == str(c)

    # parallel metrics/error branches and context manager hooks
    gen.enable_parallel = False
    assert gen.get_parallel_generation_metrics()["error"] == "Parallel generation not enabled"
    gen.enable_parallel = True
    gen.parallel_config = SimpleNamespace(
        max_workers=2,
        chunk_size=10,
        enable_concurrent_formats=True,
        enable_parallel_batches=False,
    )
    gen.generation_context = SimpleNamespace(get_generation_summary=lambda: {"ok": True})
    gen.shutdown_worker_pools = lambda: None  # type: ignore[method-assign]
    assert "configuration" in gen.get_parallel_generation_metrics()
    with gen as managed:
        assert managed is gen

    # branch that chooses non-chunked extract (chunk path intentionally not invoked)
    gen.enable_parallel = True
    gen.parallel_config = SimpleNamespace(chunk_size=999999)
    assert Path(gen._generate_customer_extract_parallel()).exists()
