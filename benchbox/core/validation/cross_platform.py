# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_NULL = object()


def _canonicalize(value: Any) -> Any:
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


STRICT = Tolerance()


@dataclass(frozen=True)
class Divergence:
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


_TOLERANCE_REGISTRY: dict[tuple[str, str], Tolerance] = {}


def register_query_tolerance(benchmark: str, query_id: str, tolerance: Tolerance) -> None:
    _TOLERANCE_REGISTRY[(benchmark, query_id)] = tolerance


def tolerance_for(benchmark: str, query_id: str) -> Tolerance:
    return _TOLERANCE_REGISTRY.get((benchmark, query_id), STRICT)
