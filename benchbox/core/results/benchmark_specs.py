"""Per-benchmark knowledge base for result integrity validation.

Hardcoded specifications derived from DuckDB SF1 reference runs.
These specs are intentionally self-contained - they do not import
benchmark modules to avoid transitive dependency issues.

sf1_row_counts values are exact COUNT(*) results from DuckDB SF1
reference runs - not rounded approximations.  Many look round
(e.g. 35_000_000) because the synthetic generators produce exact
multiples of their base counts × scale factor.  The validator
applies a ±1% tolerance (see integrity_validator._check_sf1_row_counts)
to accommodate minor cross-platform or cross-version variation
without masking real failures (wrong SF, failed load).  When
recalibrating, always use exact counts from a fresh DuckDB SF1 run.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from importlib import resources
from typing import Any

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


# --- Benchmark specs loaded lazily from package data ---
#
# Like benchmark_registry, the payload is parsed on first access and cached so
# the YAML I/O stays off the import path. Public names (BENCHMARK_SPECS,
# LEGACY_ALIASES) are served via PEP 562 module __getattr__.


def _load_benchmark_specs_payload() -> dict[str, Any]:
    with resources.files(__package__).joinpath("benchmark_specs.yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("benchmark_specs.yaml must contain a mapping")
    return payload


def _build_spec(entry: dict[str, Any], tpch_sf1_row_counts: dict[str, int]) -> BenchmarkSpec:
    sf1_range = entry.get("sf1_power_at_size_range")
    sf1_row_counts = entry.get("sf1_row_counts")
    if sf1_row_counts is not None:
        sf1_row_counts = dict(sf1_row_counts)
        if sf1_row_counts == tpch_sf1_row_counts:
            sf1_row_counts = tpch_sf1_row_counts
    return BenchmarkSpec(
        benchmark_id=str(entry["benchmark_id"]),
        unique_query_ids=frozenset(str(query_id) for query_id in entry.get("unique_query_ids", ())),
        min_unique_queries=int(entry.get("min_unique_queries", 0)),
        min_success_rate=float(entry.get("min_success_rate", 1.0)),
        high_failure_expected=bool(entry.get("high_failure_expected", False)),
        requires_tables_object=bool(entry.get("requires_tables_object", True)),
        sf1_row_counts=sf1_row_counts,
        sf1_power_at_size_range=tuple(sf1_range) if sf1_range is not None else None,
    )


@dataclass(frozen=True)
class _SpecsData:
    """Derived spec structures, built once from the YAML payload."""

    legacy_aliases: dict[str, str]
    benchmark_specs: dict[str, BenchmarkSpec]


@functools.lru_cache(maxsize=1)
def _specs() -> _SpecsData:
    """Load and build the benchmark specs once, on first access."""
    payload = _load_benchmark_specs_payload()
    tpch_sf1_row_counts = dict(payload["tpch_sf1_row_counts"])
    return _SpecsData(
        legacy_aliases=dict(payload["legacy_aliases"]),
        benchmark_specs={
            benchmark_id: _build_spec(spec, tpch_sf1_row_counts)
            for benchmark_id, spec in payload["benchmark_specs"].items()
        },
    )


_PUBLIC_SPECS_ATTRS = {
    "LEGACY_ALIASES": "legacy_aliases",
    "BENCHMARK_SPECS": "benchmark_specs",
}


def __getattr__(name: str) -> Any:
    attr = _PUBLIC_SPECS_ATTRS.get(name)
    if attr is not None:
        return getattr(_specs(), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_spec(benchmark_id: str) -> BenchmarkSpec | None:
    """Look up a benchmark spec, resolving legacy aliases automatically."""
    specs = _specs()
    canonical = specs.legacy_aliases.get(benchmark_id, benchmark_id)
    return specs.benchmark_specs.get(canonical)
