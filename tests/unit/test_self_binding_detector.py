"""Tests for the correlated-subquery self-binding detector.

Locks in the durable guard from
``_project/TODO/main/active/correlated-subquery-self-binding-cross-surface-audit.yaml``:
the detector must flag the three historical PR #756 self-binding defects when
reintroduced, stay clean on the current (fixed) variants, and not fire on plain
filters or fully-qualified correlations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The detector lives in _project/scripts (an audit/lint tool, not shipped in the
# package); ensure the repo root is importable so `_project.scripts` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _project.scripts.detect_self_binding import (  # noqa: E402
    build_column_table_index,
    find_self_binding_candidates,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# The three correlated subqueries PR #756 fixed, as (variant, fixed_fragment,
# reverted_fragment). Reverting drops the outer-table qualifier so the column
# self-binds to the inner relation.
PR756_CASES = {
    "11_v1": ("ps2.ps_partkey = partsupp.ps_partkey", "ps2.ps_partkey = ps_partkey"),
    "2_v8": ("ps2.ps_supplycost < partsupp.ps_supplycost", "ps2.ps_supplycost < ps_supplycost"),
    "17_v8": ("avg_calc.l_partkey = lineitem.l_partkey", "avg_calc.l_partkey = l_partkey"),
}


@pytest.fixture(scope="module")
def tpch_index() -> dict[str, set[str]]:
    from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

    benchmark = TPCHavocBenchmark(scale_factor=1.0)
    return build_column_table_index(benchmark.get_create_tables_sql(dialect="duckdb"))


@pytest.fixture(scope="module")
def tpchavoc_benchmark():
    from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

    return TPCHavocBenchmark(scale_factor=1.0)


@pytest.mark.parametrize("variant", sorted(PR756_CASES))
def test_detector_flags_reverted_pr756_fix(variant, tpchavoc_benchmark, tpch_index):
    """Reintroducing any #756 self-bind must be flagged; the fixed form must be clean."""
    fixed_fragment, reverted_fragment = PR756_CASES[variant]
    fixed_sql = tpchavoc_benchmark.get_query(variant)
    assert fixed_fragment in fixed_sql, f"{variant} no longer contains the #756 fix fragment"

    assert find_self_binding_candidates(fixed_sql, tpch_index) == [], f"{variant} (fixed) should not be flagged"

    reverted_sql = fixed_sql.replace(fixed_fragment, reverted_fragment)
    flagged = find_self_binding_candidates(reverted_sql, tpch_index)
    assert flagged, f"detector failed to flag reintroduced self-bind in {variant}"


def test_all_current_tpchavoc_variants_are_clean(tpchavoc_benchmark, tpch_index):
    """The shipped TPC-Havoc SQL variants must have no self-binding candidates."""
    flagged: dict[str, list[str]] = {}
    for query_id in tpchavoc_benchmark.get_implemented_queries():
        for variant_id in range(1, 11):
            key = f"{query_id}_v{variant_id}"
            candidates = find_self_binding_candidates(tpchavoc_benchmark.get_query(key), tpch_index)
            if candidates:
                flagged[key] = [c.predicate for c in candidates]
    assert not flagged, f"unexpected self-binding candidates in shipped variants: {flagged}"


def test_plain_filter_is_not_flagged(tpch_index):
    """A bare column compared to a literal is a filter, not a self-bind."""
    sql = """
        select ps_partkey from partsupp
        where ps_availqty > (
            select avg(ps2.ps_availqty) from partsupp ps2 where ps2.ps_availqty > 0
        )
    """
    assert find_self_binding_candidates(sql, tpch_index) == []


def test_fully_qualified_correlation_is_not_flagged(tpch_index):
    """A correlation qualified to the outer table is correct and must not be flagged."""
    sql = """
        select ps_partkey from partsupp
        where ps_supplycost = (
            select min(ps2.ps_supplycost) from partsupp ps2
            where ps2.ps_partkey = partsupp.ps_partkey
        )
    """
    assert find_self_binding_candidates(sql, tpch_index) == []
