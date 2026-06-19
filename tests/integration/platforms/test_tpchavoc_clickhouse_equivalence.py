"""Fourth-engine (ClickHouse) TPC-Havoc variant-equivalence sample.

The DuckDB equivalence gate (``benchbox/core/tpchavoc/equivalence.py``, run via
``make tpchavoc-equivalence-report``) proves every variant is result-equivalent
to canonical TPC-H on ONE engine, DuckDB at SF=0.1. The PostgreSQL and DataFusion
samples added two more, both systematic-zero. This test is the bounded
*fourth-engine sample* on the in-process ClickHouse engine (chDB /
``clickhouse-local``): it runs canonical TPC-H and every variant through the SAME
translation to the SAME chDB instance (so shared translation cancels out),
excludes the variants ClickHouse cannot execute (CLICKHOUSE_TPCHAVOC_SKIPS), and
asserts no residual divergence beyond the classified CLICKHOUSE_KNOWN_DIVERGENCES
baseline.

ClickHouse is the first sampled engine that translates through a NATIVE,
non-Postgres SQLGlot dialect (``normalize_dialect_for_sqlglot("clickhouse") ==
"clickhouse"``), so it exercises a DIFFERENT seam code path than the three
Postgres-family engines. Unlike them it is NOT systematic-zero:
CLICKHOUSE_KNOWN_DIVERGENCES is non-empty and records the irreducible
engine-semantic RESULT differences ClickHouse surfaces (Decimal-vs-Float division
truncation, ``SUM`` of an empty group returning 0 not NULL, partial
correlated-subquery decorrelation). The DuckDB gate remains the hard, blocking
gate; this sample (and the gate body of the non-blocking ``clickhouse-integration``
CI job) catches translation-induced divergence a fourth engine over without gating
all ~20 platforms.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.equivalence import (
    CLICKHOUSE_KNOWN_DIVERGENCES,
    EQUIVALENCE_SCALE,
    _close_quietly,
    build_clickhouse_with_tpch,
    find_clickhouse_divergences,
)
from benchbox.sql_compat.rules.execution_filter.clickhouse_tpchavoc import CLICKHOUSE_TPCHAVOC_SKIPS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tpchavoc,
    pytest.mark.slow,
]


@pytest.fixture(scope="module")
def clickhouse_divergences(tmp_path_factory):
    """Load SF=0.1 TPC-H into an in-process chDB instance and sweep ONCE.

    ClickHouse runs in-process via chDB, so "unreachable" means "chDB not
    installed" - skip cleanly in that case (mirroring the DataFusion sample's
    import-only skip). The 202-variant sweep is the expensive part, so it is
    computed a single time at module scope and shared across the assertions below.
    """
    pytest.importorskip("chdb", reason="chDB (clickhouse-local) not installed")
    output_dir = tmp_path_factory.mktemp("tpchavoc_ch_equivalence")
    connection, tpchavoc, tpch = build_clickhouse_with_tpch(EQUIVALENCE_SCALE, output_dir)
    try:
        yield find_clickhouse_divergences(connection, tpchavoc, tpch)
    finally:
        _close_quietly(connection)


def test_all_executable_variants_match_classified_baseline(clickhouse_divergences):
    """Every ClickHouse-executable variant matches canonical TPC-H on ClickHouse,
    modulo the classified CLICKHOUSE_KNOWN_DIVERGENCES.

    Both sides are translated to the native clickhouse dialect through the same
    seam and compared on the same chDB instance, so a divergence here points at
    the dialect translation layer, a real variant defect, or a classified
    engine-semantic difference - never a cross-engine mismatch against DuckDB,
    Postgres, or DataFusion. An UNCLASSIFIED divergence (not in the baseline) is
    the failure condition.
    """
    unexpected = {d.key for d in clickhouse_divergences} - set(CLICKHOUSE_KNOWN_DIVERGENCES)
    assert not unexpected, "Unclassified variant divergence(s) from canonical TPC-H on ClickHouse: " + ", ".join(
        f"{d.key} ({d.detail})" for d in clickhouse_divergences if d.key in unexpected
    )


def test_classified_divergences_still_diverge(clickhouse_divergences):
    """Every CLICKHOUSE_KNOWN_DIVERGENCES entry is still observed as a divergence.

    Guards against a stale baseline: if a previously-classified engine-semantic
    difference is now equivalent (e.g. a ClickHouse upgrade fixed it), the entry
    should be removed rather than left masking a future regression.
    """
    observed = {d.key for d in clickhouse_divergences}
    stale = sorted(set(CLICKHOUSE_KNOWN_DIVERGENCES) - observed)
    assert not stale, f"CLICKHOUSE_KNOWN_DIVERGENCES entries no longer diverge - remove them: {stale}"


def test_skipped_variants_are_excluded_never_marked_equivalent(clickhouse_divergences):
    """CLICKHOUSE_TPCHAVOC_SKIPS variants are excluded from the sweep entirely."""
    reported = {d.key for d in clickhouse_divergences}
    assert reported.isdisjoint(set(CLICKHOUSE_TPCHAVOC_SKIPS)), (
        "Un-executable (skip-list) variants must be excluded, not evaluated"
    )


def test_clickhouse_skip_list_wiring():
    """The skip-list is wired to every ClickHouse deployment-mode platform.

    No database needed: this pins the get_platform_skip_queries mapping so real
    ClickHouse benchmark runs (local/server/cloud) exclude exactly the variants
    the ClickHouse SQL engine cannot execute. It checks BOTH the platform selector
    ("clickhouse-local") and the adapter DISPLAY name ("ClickHouse Local") - the
    latter is what platforms/base/execution.py actually passes at runtime, so a
    normalization regression that returned [] for real runs would fail here.
    """
    from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

    benchmark = TPCHavocBenchmark(scale_factor=EQUIVALENCE_SCALE)
    selectors = ("clickhouse-local", "clickhouse-server", "clickhouse-cloud")
    display_names = ("ClickHouse Local", "ClickHouse Server", "ClickHouse Cloud")
    for platform in (*selectors, *display_names):
        assert set(benchmark.get_platform_skip_queries(platform)) == set(CLICKHOUSE_TPCHAVOC_SKIPS), platform
    assert benchmark.get_platform_skip_queries("duckdb") == []
