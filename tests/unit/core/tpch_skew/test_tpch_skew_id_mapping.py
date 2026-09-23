"""SQL<->DataFrame query-id correspondence for TPC-H Skew.

TPC-H Skew runs the standard TPC-H queries (1-22) unchanged on skewed data:
``TPCHSkewBenchmark`` subclasses ``TPCHBenchmark`` for the SQL surface, and the
DataFrame registry re-registers TPC-H's DataFrame implementations under the
same ``Q1`` .. ``Q22`` ids. The SQL<->DataFrame correspondence is therefore the
mechanical ``Q`` prefix inherited from TPC-H itself -- an independently
authored numbering on each surface, not a guessed mapping (the same convention
as enforced amplab and datavault). This locks that correspondence so a future
gate can wire it without re-proving it. Gating itself is out of scope here.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_sql_surface_numbers_queries_1_to_22() -> None:
    """The SQL surface is TPC-H's unchanged 1..22 query set."""
    from benchbox.core.benchmark_loader import get_core_benchmark_class
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    cls = get_core_benchmark_class("tpch_skew")
    assert issubclass(cls, TPCHBenchmark)
    sql_ids = sorted((str(q) for q in cls(scale_factor=0.01).get_queries().keys()), key=int)
    assert sql_ids == [str(n) for n in range(1, 23)]


def test_dataframe_registry_numbers_queries_q1_to_q22() -> None:
    """The DataFrame surface re-registers TPC-H's Q1..Q22 implementations."""
    from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
    from benchbox.core.tpch_skew.dataframe_queries import TPCH_SKEW_DATAFRAME_QUERIES

    df_ids = sorted(
        (str(q) for q in TPCH_SKEW_DATAFRAME_QUERIES.get_query_ids()),
        key=lambda q: int(q.lstrip("Q")),
    )
    assert df_ids == [f"Q{n}" for n in range(1, 23)]
    tpch_ids = sorted(
        (str(q) for q in TPCH_DATAFRAME_QUERIES.get_query_ids()),
        key=lambda q: int(q.lstrip("Q")),
    )
    assert df_ids == tpch_ids, "skew registry must stay a 1:1 re-registration of TPC-H"
