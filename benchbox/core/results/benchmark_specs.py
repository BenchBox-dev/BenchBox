"""Per-benchmark knowledge base for result integrity validation.

Specifications are derived from DuckDB SF1 reference runs and loaded from
``benchmark_specs.yaml`` to keep declarative validation data out of Python.

``sf1_row_counts`` values are exact COUNT(*) results from DuckDB SF1
reference runs - not rounded approximations. Many look round
(e.g. 35_000_000) because the synthetic generators produce exact
multiples of their base counts x scale factor. The validator applies
a +/-1% tolerance (see integrity_validator._check_sf1_row_counts) to
accommodate minor cross-platform or cross-version variation without
masking real failures. When recalibrating, always use exact counts from
a fresh DuckDB SF1 run.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class BenchmarkSpec:
    """Expected characteristics of a benchmark's result output."""

    benchmark_id: str
    unique_query_ids: frozenset[str]
    min_unique_queries: int = 0
    min_success_rate: float = 1.0
    high_failure_expected: bool = False
    requires_tables_object: bool = True
    sf1_row_counts: dict[str, int] | None = None
    sf1_power_at_size_range: tuple[float, float] | None = None


def _load_specs() -> tuple[dict[str, str], dict[str, BenchmarkSpec]]:
    with (Path(__file__).with_name("benchmark_specs.yaml")).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    specs = {
        key: BenchmarkSpec(
            benchmark_id=data["benchmark_id"],
            unique_query_ids=frozenset(data.get("unique_query_ids", [])),
            min_unique_queries=data.get("min_unique_queries", 0),
            min_success_rate=data.get("min_success_rate", 1.0),
            high_failure_expected=data.get("high_failure_expected", False),
            requires_tables_object=data.get("requires_tables_object", True),
            sf1_row_counts=data.get("sf1_row_counts"),
            sf1_power_at_size_range=tuple(data["sf1_power_at_size_range"])
            if data.get("sf1_power_at_size_range") is not None
            else None,
        )
        for key, data in raw["benchmark_specs"].items()
    }
    return raw["legacy_aliases"], specs


LEGACY_ALIASES, BENCHMARK_SPECS = _load_specs()


def get_spec(benchmark_id: str) -> BenchmarkSpec | None:
    """Look up a benchmark spec, resolving legacy aliases automatically."""
    canonical = LEGACY_ALIASES.get(benchmark_id, benchmark_id)
    return BENCHMARK_SPECS.get(canonical)
