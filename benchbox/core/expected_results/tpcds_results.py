"""TPC-DS expected query results provider.

This module provides expected row counts for TPC-DS queries based on the official
TPC-DS answer sets. It supports scale factor 1.0 from parsed answer files.

## Validation Mode

By default, TPC-DS queries use SKIP validation mode because queries are parameterized
with random substitution values (RNGSEED). The answer files represent ONE specific
parameterization, while benchmark runs may use different seeds.

To enable EXACT validation (for advanced users who have aligned seeds):
- Set environment variable: BENCHBOX_QUERY_VALIDATION_MODE=exact
- Or call: set_query_validation_mode(ValidationMode.EXACT)

**Warning:** EXACT validation will fail if seeds don't match answer file generation.

## TPC-DS loose ±50% band: scope and keep/tighten decision

TPC-DS row-count validation runs in LOOSE mode with a ±50% default tolerance
(``benchbox/core/expected_results/models.py`` ``loose_tolerance_percent=50.0``), so a
regression that shifts TPC-DS cardinality by <50% can hide. Scoped honestly:

* **Where it lives:** the loose band is exercised only by the broad, opt-in stress
  matrix (``tests/integration/test_local_platform_benchmark_matrix.py`` sets
  ``BENCHBOX_QUERY_VALIDATION_MODE=loose`` for TPC-DS). It is **not** in the bounded
  ``make test-correctness-gate``, which is TPC-H/DuckDB only. So it is less
  load-bearing than a reader of the #830/#834 review might assume — no required
  develop-PR gate depends on TPC-DS row counts at all.
* **Decision (keep LOOSE for now, per query class):** unlike TPC-H, BenchBox does not
  pin TPC-DS to a single reference dsqgen parameterization whose stored answer set is
  cardinality-stable across builds — the answer files represent one RNGSEED, while
  runs use different seeds, and several query classes (windowed/top-N/threshold
  ``HAVING`` queries) have genuinely seed-sensitive cardinality. Tightening those to
  EXACT/RANGE would be flaky across dsqgen builds and seeds. The loose band is
  therefore retained as a 0-row / order-of-magnitude *crash* guard (the critical
  ``expected>0 but actual==0`` failure always fails regardless of tolerance), not as a
  precise oracle.
* **When to tighten:** the right place to add a precise TPC-DS value oracle is the
  same value-digest mechanism TPC-H now uses (a pinned reference seed + stored
  full-result digest at SF=1), tracked by ``bounded-correctness-gate-value-oracle``
  (deferred for TPC-DS) and the breadth item
  ``benchmark-correctness-oracle-coverage-map``. Until a pinned TPC-DS seed + digest
  store exists, EXACT row counts would regress reliability without adding a real value
  guarantee.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os

from benchbox.core.expected_results.loader import load_tpcds_expected_results
from benchbox.core.expected_results.models import (
    BenchmarkExpectedResults,
    ExpectedQueryResult,
    ValidationMode,
)

logger = logging.getLogger(__name__)

# Module-level configuration for validation mode override
_query_validation_mode_override: ValidationMode | None = None
_config_validation_mode_override: str | None = None


def set_query_validation_mode(mode: ValidationMode | None) -> None:
    """Set query validation mode override for TPC-DS.

    This affects validation for TPC-DS queries, which default to SKIP mode due to
    parameterization. Use with caution - EXACT mode requires seed alignment.

    Args:
        mode: Validation mode to use (EXACT, SKIP, RANGE, LOOSE), or None to use default (SKIP)

    Example:
        >>> from benchbox.core.expected_results.models import ValidationMode
        >>> from benchbox.core.expected_results.tpcds_results import set_query_validation_mode
        >>> set_query_validation_mode(ValidationMode.EXACT)
    """
    global _query_validation_mode_override
    _query_validation_mode_override = mode
    if mode is not None:
        logger.info(f"Query validation mode override set to: {mode.value}")


def set_config_validation_mode(mode_str: str | None) -> None:
    """Set validation mode from benchmark configuration.

    This is called by the benchmark runner to pass validation_mode from CLI/config
    to the TPC-DS provider. Takes precedence over environment variable but not
    over programmatic override.

    Args:
        mode_str: Validation mode string ("exact", "loose", "range", "disabled"), or None
    """
    global _config_validation_mode_override
    _config_validation_mode_override = mode_str
    if mode_str is not None:
        logger.debug(f"Config validation mode set to: {mode_str}")


def get_query_validation_mode() -> ValidationMode:
    """Get the current query validation mode for TPC-DS.

    Checks in order:
    1. Module-level override set via set_query_validation_mode() (programmatic)
    2. Config override set via set_config_validation_mode() (from CLI --validation-mode)
    3. Environment variable BENCHBOX_QUERY_VALIDATION_MODE (backward compatibility)
    4. Default: SKIP (safe for parameterized queries)

    Returns:
        ValidationMode to use for TPC-DS queries
    """
    # Check module-level override first (programmatic takes precedence)
    if _query_validation_mode_override is not None:
        return _query_validation_mode_override

    # Check config override (from CLI --validation-mode flag)
    if _config_validation_mode_override is not None:
        try:
            mode = ValidationMode(_config_validation_mode_override)
            logger.debug(f"Using query validation mode from config: {mode.value}")
            return mode
        except ValueError:
            logger.warning(
                f"Invalid config validation mode: {_config_validation_mode_override}. "
                f"Valid values: exact, loose, range, skip. Using default: skip"
            )

    # Check environment variable (backward compatibility)
    env_mode = os.environ.get("BENCHBOX_QUERY_VALIDATION_MODE", "").lower()
    if env_mode:
        try:
            mode = ValidationMode(env_mode)
            logger.info(f"Using query validation mode from environment: {mode.value}")
            return mode
        except ValueError:
            logger.warning(
                f"Invalid BENCHBOX_QUERY_VALIDATION_MODE: {env_mode}. "
                f"Valid values: exact, loose, range, skip. Using default: skip"
            )

    # Default to SKIP (safe default for parameterized TPC-DS queries)
    return ValidationMode.SKIP


def get_tpcds_expected_results(scale_factor: float = 1.0) -> BenchmarkExpectedResults | None:
    """Get expected results for TPC-DS queries at a given scale factor.

    This function loads expected row counts from TPC-DS answer files (SF=1.0 only currently).
    For scale factors other than 1.0, returns None to trigger graceful validation skip.
    Scale-independent queries (if any) can still be validated via registry fallback to SF=1.0.

    Args:
        scale_factor: Scale factor (currently only 1.0 is supported from answer files)

    Returns:
        BenchmarkExpectedResults with all TPC-DS query expectations, or None if SF != 1.0
    """
    # Only SF=1.0 is supported - return None for others to trigger graceful SKIP
    if scale_factor != 1.0:
        logger.info(
            f"TPC-DS expected results only available for SF=1.0. "
            f"Validation will be skipped for SF={scale_factor}. "
            f"Most TPC-DS queries are scale-dependent."
        )
        return None

    # Load row counts from answer files (SF=1.0)
    row_counts = load_tpcds_expected_results(scale_factor=1.0)

    # Build ExpectedQueryResult objects
    query_results = {}

    # TPC-DS queries are mostly scale-dependent
    # Only a few queries have scale-independent results
    scale_independent_queries = {
        # Most TPC-DS queries are scale-dependent
        # Add specific queries here if identified as scale-independent
    }

    # Get validation mode (can be overridden via environment variable or programmatically)
    validation_mode = get_query_validation_mode()

    for query_id, row_count in row_counts.items():
        is_scale_independent = scale_independent_queries.get(query_id, False)

        # Build notes based on validation mode
        if validation_mode == ValidationMode.SKIP:
            mode_notes = (
                "Validation set to SKIP because TPC-DS queries are parameterized with random "
                "substitution values controlled by RNGSEED. The answer files represent ONE specific "
                "parameterization, while benchmark runs may use different seeds. "
                "To enable EXACT validation, set BENCHBOX_QUERY_VALIDATION_MODE=exact or call "
                "set_query_validation_mode(ValidationMode.EXACT)."
            )
        elif validation_mode == ValidationMode.EXACT:
            mode_notes = (
                "Validation set to EXACT mode (override enabled). "
                "Query results MUST match answer files exactly. Failures indicate either: "
                "(1) seed mismatch between power test and answer generation, "
                "(2) platform-specific differences (NULL sorting, precision), or "
                "(3) incorrect query execution. "
                "Power test uses parameter seed = base_seed + stream_id + 1000 (e.g., seed=1001 for stream 0 with base_seed=1)."
            )
        else:
            mode_notes = f"Validation mode: {validation_mode.value}"

        query_results[query_id] = ExpectedQueryResult(
            query_id=query_id,
            scale_factor=scale_factor,
            expected_row_count=row_count,
            validation_mode=validation_mode,
            scale_independent=is_scale_independent,
            notes=f"Expected result from TPC-DS answer file for SF={scale_factor}. {mode_notes}",
        )

    return BenchmarkExpectedResults(
        benchmark_name="tpcds",
        scale_factor=scale_factor,
        query_results=query_results,
        metadata={
            "source": "TPC-DS answer files",
            "answer_files_scale_factor": 1.0,
            "total_queries": len(query_results),
        },
    )


# Register the provider with the global registry
from benchbox.core.expected_results.registry import register_benchmark_provider

register_benchmark_provider("tpcds", get_tpcds_expected_results)
