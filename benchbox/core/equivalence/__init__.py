"""Benchmark-agnostic result-equivalence harness.

Shared machinery for the live, answer-key-free correctness oracles: execute a
candidate surface and a trusted reference over the SAME bounded DuckDB data and
compare results with a reused validator. The TPC-Havoc gates
(:mod:`benchbox.core.tpchavoc.equivalence`,
:mod:`benchbox.core.tpchavoc.dataframe_equivalence`) are thin benchmark-specific
wrappers over this package, and the cross-surface SQL<->DataFrame gates reuse the
same harness rather than forking a new comparator or data builder.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.equivalence.dataframe_surface import (
    DATAFRAME_BACKENDS,
    SurfaceDivergence,
    build_dataframe_contexts,
    build_dataframe_contexts_from_specs,
    fetch_reference_rows,
    find_surface_divergences,
    materialize_rows,
)

__all__ = [
    "DATAFRAME_BACKENDS",
    "SurfaceDivergence",
    "build_dataframe_contexts",
    "build_dataframe_contexts_from_specs",
    "fetch_reference_rows",
    "find_surface_divergences",
    "materialize_rows",
]
