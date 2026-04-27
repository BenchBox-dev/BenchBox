"""Cross-platform result comparator for benchmark correctness.

BenchBox's product is trustworthy results. This module compares the rows
returned by the SAME query on TWO platforms and reports divergences with
per-query tolerance rules.

Tolerance model
---------------
Default: exact match on every cell.

Per-benchmark overrides are spec-anchored, never convenience-driven:

  * **TPC-H §2.6.3 ordering**: when a query has no ORDER BY, rows may
    appear in any order - the comparator sorts both result sets by all
    columns before diffing.
  * **TPC-H §2.6.4 numeric tolerance**: aggregate floating-point columns
    (SUM/AVG over DECIMAL or DOUBLE) compare to within ``epsilon`` per
    cell. Default epsilon is 1e-6 - TPC-H gives 0.01% relative; the
    tighter absolute is safer for SF=0.01 magnitudes.
  * **NULL handling**: NULL == NULL for comparison purposes (matches
    SQL ``IS NOT DISTINCT FROM`` semantics, NOT default ``=``).

Anything looser must cite a spec rule in the override registry - see
``register_query_tolerance``.

Reference platform
------------------
Use DuckDB by default: it's BenchBox's lingua franca, ships
TPC-H/TPC-DS expected answer sets, and runs locally without
credentials. Override via ``Comparator(reference="snowflake")`` if
you need a different anchor.

Surface
-------
This module exposes a Python comparator. It does NOT add a CLI command
in v1; pytest is the canonical execution surface (see
``tests/integration/validation/test_cross_platform.py``). A
``benchbox validate`` command may follow once the comparator semantics
have stabilized.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# Sentinel for NULL - comparator treats NULL == NULL.
_NULL = object()


def _canonicalize(value: Any) -> Any:
    """Map raw cell values to a comparable canonical form.

    - ``None`` and pandas/polars-style NaN both become the NULL sentinel.
    - ``Decimal`` is preserved; floats become ``float``.
    - Strings are stripped of trailing whitespace (a common cross-platform
      divergence - DuckDB pads CHAR(N), ClickHouse does not).
    """
    if value is None:
        return _NULL
    if isinstance(value, float) and math.isnan(value):
        return _NULL
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return value.rstrip()
    return value


def _cells_equal(a: Any, b: Any, *, epsilon: float) -> bool:
    """True if two canonical cells match under the active tolerance."""
    if a is _NULL or b is _NULL:
        return a is _NULL and b is _NULL
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        try:
            return math.isclose(float(a), float(b), abs_tol=epsilon, rel_tol=epsilon)
        except (TypeError, ValueError):
            return False
    return a == b


def _normalize_rows(rows: list[tuple], *, sort: bool) -> list[tuple]:
    canon = [tuple(_canonicalize(cell) for cell in row) for row in rows]
    if sort:
        canon.sort(key=lambda r: tuple((str(type(c).__name__), str(c)) for c in r))
    return canon


@dataclass(frozen=True)
class Tolerance:
    """Per-query tolerance contract.

    ``ordering_required`` = False means rows may appear in any order
    (e.g., TPC-H queries without ORDER BY). ``epsilon`` is absolute
    float tolerance applied cell-by-cell to numeric values.
    ``rationale`` MUST cite a spec rule when epsilon > 0 or
    ordering_required is False - drift checks reject empty strings.
    """

    epsilon: float = 0.0
    ordering_required: bool = True
    rationale: str = ""

    def __post_init__(self) -> None:
        loose = self.epsilon > 0 or not self.ordering_required
        if loose and not self.rationale.strip():
            raise ValueError(
                "Loose tolerance requires a spec-anchored rationale "
                "(e.g., 'TPC-H §2.6.4 floating-point aggregate epsilon')."
            )


# Strict default - exact match, ordering enforced.
STRICT = Tolerance()


@dataclass(frozen=True)
class Divergence:
    """One row-level mismatch surfaced by the comparator."""

    row_index: int
    column_index: int
    reference_value: Any
    comparison_value: Any

    def describe(self) -> str:
        return (
            f"row {self.row_index}, col {self.column_index}: "
            f"reference={self.reference_value!r} comparison={self.comparison_value!r}"
        )


@dataclass
class ComparisonReport:
    """Result of comparing two platforms' output for a single query."""

    query_id: str
    reference_platform: str
    comparison_platform: str
    matched: bool
    row_count_reference: int
    row_count_comparison: int
    divergences: list[Divergence] = field(default_factory=list)

    def summary(self) -> str:
        if self.matched:
            return (
                f"{self.query_id}: OK "
                f"({self.reference_platform} vs {self.comparison_platform}, "
                f"{self.row_count_reference} rows)"
            )
        head = (
            f"{self.query_id}: DIVERGED "
            f"({self.reference_platform} vs {self.comparison_platform}, "
            f"ref={self.row_count_reference} rows, cmp={self.row_count_comparison} rows)"
        )
        sample = "\n  - ".join(d.describe() for d in self.divergences[:5])
        suffix = "\n  - " + sample if sample else ""
        if len(self.divergences) > 5:
            suffix += f"\n  ... {len(self.divergences) - 5} more divergences"
        return head + suffix


def compare_query_results(
    *,
    query_id: str,
    reference_platform: str,
    comparison_platform: str,
    reference_rows: list[tuple],
    comparison_rows: list[tuple],
    tolerance: Tolerance = STRICT,
) -> ComparisonReport:
    """Compare two platforms' rows for one query under the supplied tolerance.

    Returns a ComparisonReport. A row-count mismatch is itself a
    divergence and short-circuits the per-cell diff.
    """
    ref = _normalize_rows(reference_rows, sort=not tolerance.ordering_required)
    cmp = _normalize_rows(comparison_rows, sort=not tolerance.ordering_required)

    if len(ref) != len(cmp):
        return ComparisonReport(
            query_id=query_id,
            reference_platform=reference_platform,
            comparison_platform=comparison_platform,
            matched=False,
            row_count_reference=len(ref),
            row_count_comparison=len(cmp),
            divergences=[
                Divergence(
                    row_index=-1,
                    column_index=-1,
                    reference_value=f"{len(ref)} rows",
                    comparison_value=f"{len(cmp)} rows",
                )
            ],
        )

    divergences: list[Divergence] = []
    for r_idx, (r_row, c_row) in enumerate(zip(ref, cmp)):
        if len(r_row) != len(c_row):
            divergences.append(
                Divergence(
                    row_index=r_idx,
                    column_index=-1,
                    reference_value=f"{len(r_row)} cols",
                    comparison_value=f"{len(c_row)} cols",
                )
            )
            continue
        for c_idx, (r_cell, c_cell) in enumerate(zip(r_row, c_row)):
            if not _cells_equal(r_cell, c_cell, epsilon=tolerance.epsilon):
                divergences.append(
                    Divergence(
                        row_index=r_idx,
                        column_index=c_idx,
                        reference_value=r_cell if r_cell is not _NULL else None,
                        comparison_value=c_cell if c_cell is not _NULL else None,
                    )
                )

    return ComparisonReport(
        query_id=query_id,
        reference_platform=reference_platform,
        comparison_platform=comparison_platform,
        matched=not divergences,
        row_count_reference=len(ref),
        row_count_comparison=len(cmp),
        divergences=divergences,
    )


# Per-query tolerance overrides. Populate via register_query_tolerance.
_TOLERANCE_REGISTRY: dict[tuple[str, str], Tolerance] = {}


def register_query_tolerance(benchmark: str, query_id: str, tolerance: Tolerance) -> None:
    """Register a non-strict tolerance for one benchmark/query pair."""
    _TOLERANCE_REGISTRY[(benchmark, query_id)] = tolerance


def tolerance_for(benchmark: str, query_id: str) -> Tolerance:
    """Look up the active tolerance, defaulting to STRICT."""
    return _TOLERANCE_REGISTRY.get((benchmark, query_id), STRICT)
