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

WHAT THIS ORACLE IS (and is NOT). The stored reference digests
(``benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json``)
were produced by running benchbox-on-DuckDB and frozen. The value oracle therefore
detects CHANGE from that benchbox-on-DuckDB baseline -- a genuine regression
tripwire -- but it is NOT an independent correctness oracle: a conceptual value bug
that was present at freeze time is enshrined in the reference, not caught. It is a
regression SNAPSHOT vs a DuckDB-pinned baseline. Read a green value+cardinality cell
as "unchanged from the frozen DuckDB answer", never as "values proven correct against
an external authority". See
``_project/analysis/value-digest-cross-engine-independence-decision.md`` for the
independence analysis and the deferred cross-engine upgrade.

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
#
# PRECISION-FLOOR DECISION (correctness-gate-value-digest-fidelity-followups w1).
# The floor is ABSOLUTE, not relative: rounding to 4 fractional digits makes a
# per-cell error below 5e-5 ABSOLUTE invisible (and an error of exactly 5e-5 at a
# bucket midpoint invisible too, by round-half-even), regardless of the column's
# magnitude. The exposure this creates is QUANTIFIED and PINNED in
# tests/unit/test_correctness_gate_value_oracle.py
# (test_precision_floor_is_absolute_*):
#   * Large-magnitude columns (e.g. TPC-H revenue ~1e10) -- 5e-5 absolute is ~5e-15
#     relative, effectively perfect.
#   * Small averaged-ratio columns -- the worst exposed gate column is TPC-H Q1's
#     ``avg_disc`` (~0.0500): a sub-5e-5-absolute (~0.1% relative) aggregate/rounding
#     bug on that column survives the gate.
# DECISION: KEEP absolute 4dp; DOCUMENT the small-ratio blind spot (naming
# ``avg_disc``) rather than switch to relative / significant-figure rounding. Reasons:
#   1. Stability is the gate's first duty -- a relative/significant-figure rounding
#      near zero can be LESS reproducible across DuckDB builds than a fixed absolute
#      grid (the ~0 boundary makes the chosen exponent jitter), so a uniform-relative
#      scheme risks spurious RED on a correct tree, the opposite of what the gate is for.
#   2. The exposure is bounded and named: only sub-0.1%-relative errors on small
#      averaged ratios survive, and the value oracle is explicitly a regression
#      SNAPSHOT vs a DuckDB baseline (see module docstring / the reference JSON
#      provenance), not an independent correctness oracle, so a freeze-time bug on
#      ``avg_disc`` would already be enshrined regardless of the floor.
# Any future switch to relative/hybrid rounding MUST re-verify two-run determinism at
# the pinned seed and regenerate the 18 reference digests in the SAME change (see
# ``make correctness-gate-digests-regen``), or the gate goes RED on a correct tree.
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

    VALUE+TYPE COUPLING (correctness-gate-value-digest-fidelity-followups w2). This
    is a value+TYPE-RENDERING digest, not a pure value digest: an ``int`` renders
    exactly (``37734107`` -> ``"37734107"``) while a ``float``/``Decimal`` of the
    SAME numeric value renders at fixed precision (``37734107.0`` -> ``"37734107.0000"``),
    so the same logical value hashes DIFFERENTLY across Python numeric types. This is
    pinned in tests/unit/test_correctness_gate_value_oracle.py
    (test_digest_couples_value_with_numeric_type). It is DELIBERATELY ACCEPTABLE here
    because the oracle is DuckDB-PINNED: DuckDB 1.3.2 returns a stable, deterministic
    column type for each of the 18 gate queries at the reference seed, so the rendered
    type never varies run-to-run and the stored reference digests reproduce exactly.
    The coupling is therefore the BLOCKER for any cross-engine reuse (a second engine
    may return ``Decimal`` where DuckDB returns ``float``), which is why the
    cross-engine independence upgrade (w5) is DEFERRED rather than enabled on this
    primitive -- see _project/analysis/value-digest-cross-engine-independence-decision.md.
    Canonicalizing integer-valued numerics to one representation would change the
    rendered form of every integer cell and thus require regenerating all 18 reference
    digests; it is intentionally NOT done while the oracle stays single-engine.
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
