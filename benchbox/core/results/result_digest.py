"""Gate-only per-query result digest emission for the bounded correctness gate.

The bounded TPC-H/TPC-DS correctness gate historically validated only ROW COUNTS,
so a wrong-but-same-cardinality answer (e.g. a perturbed TPC-H Q1 aggregate, a
swapped column, a wrong rounding) shipped GREEN. This module adds the missing
value axis: an order-normalized digest of a query's *full* result set, emitted
into the per-query result payload so the gate can assert it against a stored
reference digest.

Design constraints (see
``_project/TODO/main/planning/bounded-correctness-gate-value-oracle.yaml``):

* GATE-ONLY: digest emission is behind :data:`EMIT_RESULT_DIGEST_ENV`
  (``BENCHBOX_EMIT_RESULT_DIGEST=1``), set only by ``make test-correctness-gate``.
  A normal ``benchbox run`` keeps its current payload shape and cost — no digest
  field is added when the flag is unset.
* ONE DIGEST DEFINITION: the digest reuses
  :func:`benchbox.core.tpchavoc.validation.calculate_checksum` (the promoted
  single-result primitive that also backs the TPC-Havoc gates) rather than
  forking a second hash.
* CROSS-BUILD STABLE: numeric cells are normalized to a fixed decimal precision
  *before* hashing so a stored reference digest reproduces across DuckDB builds
  at the pinned reference seed, while remaining sensitive to value mutations
  (which shift values by far more than the normalization granularity).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
import os
from decimal import Decimal
from typing import Any, Iterable, Sequence

# Env flag the correctness gate sets to request digest emission. Deliberately not
# read at import time so tests can toggle it via monkeypatch.
EMIT_RESULT_DIGEST_ENV = "BENCHBOX_EMIT_RESULT_DIGEST"

# Per-query result field carrying the emitted digest through the result payload.
RESULT_DIGEST_FIELD = "digest"

# Fixed fractional precision applied to real-numbered cells before hashing. Large
# enough to absorb sub-precision float-formatting noise across DuckDB builds, far
# smaller than any value-mutation the gate must catch.
_DIGEST_FLOAT_PRECISION = 4


def result_digest_enabled() -> bool:
    """Return True when gate-only result-digest emission is requested via env."""
    return os.environ.get(EMIT_RESULT_DIGEST_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_cell(value: Any, ndigits: int = _DIGEST_FLOAT_PRECISION) -> Any:
    """Normalize a single result cell for stable, value-sensitive hashing.

    Integers (and booleans) are preserved exactly. Real numbers (``float`` /
    ``Decimal``) are rendered with a fixed number of fractional digits so tiny
    float-formatting differences across engine builds do not change the digest,
    while genuine value differences still do. All other types are left untouched
    (``calculate_checksum`` renders them with ``str``).
    """
    # bool is an int subclass; keep it distinct from numeric rounding.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return value
        return _format_real(value, ndigits)
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return value
        return _format_real(float(value), ndigits)
    return value


def _format_real(value: float, ndigits: int) -> str:
    """Render a real number at fixed precision, collapsing -0.0 to 0.0.

    Negative zero is collapsed so an aggregate that cancels to ``-0.0`` on one
    engine build and ``0.0`` on another hashes identically (``f"{-0.0:.4f}"`` is
    ``"-0.0000"`` but ``f"{0.0:.4f}"`` is ``"0.0000"``).
    """
    if value == 0.0:  # True for both 0.0 and -0.0
        value = 0.0
    return f"{value:.{ndigits}f}"


def normalize_rows_for_digest(rows: Iterable[Sequence[Any]], ndigits: int = _DIGEST_FLOAT_PRECISION) -> list[tuple]:
    """Return rows with numeric cells normalized to a fixed precision."""
    return [tuple(_normalize_cell(cell, ndigits) for cell in row) for row in rows]


def compute_result_digest(rows: Iterable[Sequence[Any]], ndigits: int = _DIGEST_FLOAT_PRECISION) -> str:
    """Compute the order-normalized value digest of a full result set.

    Reuses the canonical :func:`calculate_checksum` digest primitive after
    normalizing numeric precision, so the gate and SQL share one digest
    definition.
    """
    # Imported lazily: benchbox.core.tpchavoc.* pulls DuckDB/NumPy at import, and
    # this module is imported on the normal result-export path too.
    from benchbox.core.tpchavoc.validation import calculate_checksum

    return calculate_checksum(normalize_rows_for_digest(rows, ndigits))


def digests_match(expected_digest: str | None, actual_digest: str | None) -> bool:
    """Return True when a stored reference digest equals an emitted digest.

    Both must be present and equal. A missing emitted digest never silently
    matches — callers (the gate) treat that as a RED, never a skip, under strict
    arming.
    """
    if expected_digest is None or actual_digest is None:
        return False
    return expected_digest == actual_digest
