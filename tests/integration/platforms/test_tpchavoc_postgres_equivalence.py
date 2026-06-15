"""Second-engine (PostgreSQL) TPC-Havoc variant-equivalence sample.

The DuckDB equivalence gate (``benchbox/core/tpchavoc/equivalence.py``, run via
``make tpchavoc-equivalence-report``) proves every variant is result-equivalent
to canonical TPC-H on ONE engine, DuckDB at SF=0.1. But variants are authored
once and run, after dialect translation, on ~20 platforms - so "equivalent on
DuckDB" does not imply "equivalent everywhere". This test is the bounded
*second-engine sample*: it runs canonical TPC-H and every variant through the
SAME translation to the SAME PostgreSQL instance (so shared translation cancels
out), excludes the variants PostgreSQL cannot execute (POSTGRES_TPCHAVOC_SKIPS),
and asserts no residual divergence beyond the classified POSTGRES_KNOWN_DIVERGENCES
baseline (empty).

This is the gate body of the non-blocking ``postgres-integration`` CI job. The
DuckDB gate remains the hard, blocking gate; this sample catches the largest
class of translation-induced divergence one engine over without gating all ~20
platforms.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.equivalence import (
    EQUIVALENCE_SCALE,
    POSTGRES_KNOWN_DIVERGENCES,
    build_postgres_with_tpch,
    find_postgres_divergences,
    postgres_connection_config,
)
from benchbox.sql_compat.rules.execution_filter.postgres_tpchavoc import POSTGRES_TPCHAVOC_SKIPS

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_postgresql,
    pytest.mark.tpchavoc,
    pytest.mark.slow,
]


@pytest.fixture(scope="module")
def postgres_divergences(tmp_path_factory):
    """Load SF=0.1 TPC-H into the live Postgres and run the sweep ONCE.

    The 203-variant sweep is the expensive part, so it is computed a single time
    at module scope and shared across the assertions below (keeping the
    non-blocking CI job well inside its budget).
    """
    config = postgres_connection_config()
    skip_unless_docker_service(config["host"], config["port"], platform="PostgreSQL")
    output_dir = tmp_path_factory.mktemp("tpchavoc_pg_equivalence")
    connection, tpchavoc, tpch = build_postgres_with_tpch(
        EQUIVALENCE_SCALE, output_dir, connection_config=config
    )
    try:
        yield find_postgres_divergences(connection, tpchavoc, tpch)
    finally:
        connection.close()


def test_all_executable_variants_equivalent_on_postgres(postgres_divergences):
    """Every Postgres-executable variant matches canonical TPC-H on Postgres.

    Both sides are translated to the postgres dialect through the same seam and
    compared on the same instance, so a divergence here points at the dialect
    translation layer (or a real variant defect), never at a DuckDB-vs-Postgres
    engine mismatch.
    """
    unexpected = {d.key for d in postgres_divergences} - set(POSTGRES_KNOWN_DIVERGENCES)
    assert not unexpected, "Variant(s) diverge from canonical TPC-H on PostgreSQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in postgres_divergences if d.key in unexpected
    )


def test_skipped_variants_are_excluded_never_marked_equivalent(postgres_divergences):
    """POSTGRES_TPCHAVOC_SKIPS variants are excluded from the sweep entirely."""
    reported = {d.key for d in postgres_divergences}
    assert reported.isdisjoint(set(POSTGRES_TPCHAVOC_SKIPS)), (
        "Un-executable (skip-list) variants must be excluded, not evaluated"
    )
