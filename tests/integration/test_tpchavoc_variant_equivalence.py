# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
# This implementation is derived from TPC-H.

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.equivalence import (
    EQUIVALENCE_SCALE,
    KNOWN_DIVERGENCES,
    build_duckdb_with_tpch,
    find_divergences,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
    pytest.mark.tpchavoc,
]


@pytest.fixture(scope="module")
def populated_duckdb(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("tpchavoc_equivalence")
    connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, output_dir)
    try:
        yield connection, tpchavoc, tpch
    finally:
        connection.close()


FIXED_DEFECT_QUERIES = (1, 2, 7, 9, 10)


def test_fixed_variant_families_equivalent_to_canonical(populated_duckdb):
    connection, tpchavoc, tpch = populated_duckdb

    divergences = find_divergences(
        connection,
        tpchavoc,
        lambda query_id: tpch.get_query(query_id),
        query_ids=list(FIXED_DEFECT_QUERIES),
    )

    unexpected = {d.key for d in divergences} - set(KNOWN_DIVERGENCES)
    assert not unexpected, "Variant(s) diverge from canonical TPC-H: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )
