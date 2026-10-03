"""The TPC-DS cross-surface gate must render its reference SQL at the gate's scale factor.

dsqgen derives some values from the scale (Q9, Q44, Q46 and Q68 differ between scale factor 1 and 0.01), so
SQL rendered at scale 1 against data generated at 0.01 is a different query from the one the DataFrame
side is compared with. The builder gets its SQL from ``benchmark.get_queries``; these tests pin that the
benchmark is built at the gate's scale and that the SQL it yields is the scale's SQL.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium, pytest.mark.tpcds]

GATE_SCALE = 0.01


class _FakeBenchmark:
    instances: list[_FakeBenchmark] = []

    def __init__(self, scale_factor, output_dir, **_):
        self.scale_factor = scale_factor
        self.queries_dialects: list[str] = []
        _FakeBenchmark.instances.append(self)

    def generate_data(self):
        return []

    def get_queries(self, dialect=None, **_):
        self.queries_dialects.append(dialect)
        return {"1": f"select {self.scale_factor}"}


def test_builder_constructs_the_benchmark_at_the_gate_scale_and_renders_through_get_queries(monkeypatch, tmp_path):
    import benchbox.core.equivalence.builders.base as base
    import benchbox.tpcds as tpcds_module
    from benchbox.core.equivalence.builders.tpcds import build_tpcds_duckdb

    _FakeBenchmark.instances.clear()
    monkeypatch.setattr(tpcds_module, "TPCDS", _FakeBenchmark)
    monkeypatch.setattr(base, "_load_duckdb_cell", lambda *args, **kwargs: object())

    data = build_tpcds_duckdb(GATE_SCALE, tmp_path)

    (benchmark,) = _FakeBenchmark.instances
    assert benchmark.scale_factor == GATE_SCALE
    assert benchmark.queries_dialects == ["duckdb"]
    assert data.reference_sql("1") == f"select {GATE_SCALE}"


def test_gate_sql_is_the_scale_dependent_rendering_not_the_scale_one_rendering(monkeypatch, tmp_path):
    import benchbox.core.equivalence.builders.base as base
    import benchbox.tpcds as tpcds_module
    from benchbox.core.equivalence.builders.tpcds import build_tpcds_duckdb
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark
    from benchbox.core.tpcds.c_tools import TPCDSError

    try:
        gate_benchmark = TPCDSBenchmark(scale_factor=GATE_SCALE, output_dir=tmp_path / "gate")
        scale_one = TPCDSBenchmark(scale_factor=1.0, output_dir=tmp_path / "one").get_query(44, dialect="duckdb")
    except (TPCDSError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"dsqgen binary or templates unavailable: {exc}")

    monkeypatch.setattr(tpcds_module.TPCDS, "generate_data", lambda self: [])
    monkeypatch.setattr(base, "_load_duckdb_cell", lambda *args, **kwargs: object())

    data = build_tpcds_duckdb(GATE_SCALE, tmp_path / "built")

    assert data.reference_sql("44") == gate_benchmark.get_query(44, dialect="duckdb")
    assert data.reference_sql("44") != scale_one
