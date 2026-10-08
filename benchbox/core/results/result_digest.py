# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import math
import os
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Iterable, Sequence

EMIT_RESULT_DIGEST_ENV = "BENCHBOX_EMIT_RESULT_DIGEST"

RESULT_DIGEST_FIELD = "digest"

_DIGEST_FLOAT_SIGFIGS = 6
_NEAR_ZERO_ABS = 1e-12


def result_digest_enabled() -> bool:
    return os.environ.get(EMIT_RESULT_DIGEST_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_cell(value: Any, sigfigs: int = _DIGEST_FLOAT_SIGFIGS) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return value
        return _format_real(value, sigfigs)
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return value
        return _format_real(float(value), sigfigs)
    return value


def _format_real(value: float, sigfigs: int) -> str:
    if abs(value) < _NEAR_ZERO_ABS:
        return "0e0"
    decimal_value = Decimal(value)
    most_significant_exp = decimal_value.adjusted()
    quantum = Decimal(1).scaleb(most_significant_exp - (sigfigs - 1))
    rounded = decimal_value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    sign, digits, exponent = rounded.as_tuple()
    return f"{'-' if sign else ''}{''.join(map(str, digits))}e{exponent}"


def normalize_rows_for_digest(rows: Iterable[Sequence[Any]], sigfigs: int = _DIGEST_FLOAT_SIGFIGS) -> list[tuple]:
    return [tuple(_normalize_cell(cell, sigfigs) for cell in row) for row in rows]


def compute_result_digest(rows: Iterable[Sequence[Any]], sigfigs: int = _DIGEST_FLOAT_SIGFIGS) -> str:
    from benchbox.core.tpchavoc.validation import calculate_checksum

    return calculate_checksum(normalize_rows_for_digest(rows, sigfigs))


def digests_match(expected_digest: str | None, actual_digest: str | None) -> bool:
    if expected_digest is None or actual_digest is None:
        return False
    return expected_digest == actual_digest
