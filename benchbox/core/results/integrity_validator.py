"""Three-tier integrity validator for benchmark result JSON files.

Tiers:
  STRUCTURAL     - schema, required keys, cross-field math
  COMPLETENESS   - expected queries, measurement presence, phases
  BELIEVABILITY  - statistical plausibility, row counts, outliers

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .benchmark_specs import get_spec
from .schema import SchemaV2ValidationError, SchemaV2Validator


class CheckStatus(str, Enum):
    PASS = "PASS"
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"


class CheckCategory(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    COMPLETENESS = "COMPLETENESS"
    BELIEVABILITY = "BELIEVABILITY"


@dataclass
class CheckResult:
    category: CheckCategory
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] | None = None


@dataclass
class IntegrityReport:
    file: str
    benchmark_id: str
    platform: str
    scale_factor: float
    overall_status: CheckStatus
    checks: list[CheckResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def passed(self) -> bool:
        return self.overall_status == CheckStatus.PASS

    def has_warnings(self) -> bool:
        return any(c.status == CheckStatus.WARN for c in self.checks)


# Phase status values observed in real result files.
_VALID_PHASE_STATUSES = frozenset(
    {
        "SUCCESS",
        "COMPLETED",
        "PASSED",
        "FAILED",
        "SKIPPED",
        "NOT_RUN",
        "ERROR",
        "TIMEOUT",
    }
)

# Benchmarks that should have tpc_metrics in summary.
_TPC_METRICS_BENCHMARKS = frozenset({"tpch", "tpcds", "tpchavoc", "tpch_skew"})

# Required top-level keys in result JSON.
_REQUIRED_KEYS = frozenset(
    {
        "version",
        "run",
        "benchmark",
        "platform",
        "config",
        "summary",
        "phases",
        "queries",
        "execution",
        "environment",
        "export",
    }
)

# Benchmarks that don't load data (metadata-only).
_NO_LOAD_BENCHMARKS = frozenset({"metadata_primitives"})


class ResultIntegrityValidator:
    """Validates a raw result dict through structural, completeness, and believability checks."""

    def __init__(self) -> None:
        self._schema_validator = SchemaV2Validator()

    def validate(self, raw: dict[str, Any], filepath: str = "") -> IntegrityReport:
        benchmark_id = raw.get("benchmark", {}).get("id", "unknown")
        platform = raw.get("platform", {}).get("name", "unknown")
        scale_factor = raw.get("benchmark", {}).get("scale_factor", 0.0)

        checks: list[CheckResult] = []

        # Tier 1: Structural
        schema_ok = self._check_schema(raw, checks)
        if schema_ok:
            self._check_required_keys(raw, checks)
            self._check_query_count_math(raw, checks)
            self._check_timing_non_negative(raw, checks)
            self._check_percentile_ordering(raw, checks)
            self._check_phase_status_values(raw, checks)
            self._check_query_entry_fields(raw, checks)
            self._check_query_ms_non_negative(raw, checks)

        # Tier 2: Completeness
        spec = get_spec(benchmark_id)
        self._check_expected_query_ids(raw, spec, checks)
        self._check_measurement_queries_present(raw, checks)
        self._check_power_phase_completed(raw, checks)
        self._check_tables_object(raw, spec, checks)
        self._check_tpc_metrics(raw, benchmark_id, checks)

        # Tier 3: Believability
        self._check_avg_between_min_max(raw, checks)
        self._check_geomean_plausible(raw, checks)
        self._check_success_rate(raw, spec, checks)
        self._check_sf1_row_counts(raw, spec, scale_factor, checks)
        self._check_timing_outliers(raw, checks)
        self._check_no_duplicate_executions(raw, checks)
        self._check_load_time_nonzero(raw, benchmark_id, checks)

        # Compute overall status and summary counts
        # INFO does not elevate overall status - it is purely informational.
        status_counts = {CheckStatus.PASS: 0, CheckStatus.INFO: 0, CheckStatus.WARN: 0, CheckStatus.FAIL: 0}
        for c in checks:
            status_counts[c.status] += 1

        if status_counts[CheckStatus.FAIL] > 0:
            overall = CheckStatus.FAIL
        elif status_counts[CheckStatus.WARN] > 0:
            overall = CheckStatus.WARN
        else:
            overall = CheckStatus.PASS

        return IntegrityReport(
            file=filepath,
            benchmark_id=benchmark_id,
            platform=platform,
            scale_factor=scale_factor,
            overall_status=overall,
            checks=checks,
            summary={s.value: count for s, count in status_counts.items()},
        )

    # --- Tier 1: Structural checks ---

    def _check_schema(self, raw: dict[str, Any], checks: list[CheckResult]) -> bool:
        try:
            self._schema_validator.validate(raw)
        except SchemaV2ValidationError as e:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "schema_v2",
                    CheckStatus.FAIL,
                    f"Schema validation failed: {e}",
                )
            )
            return False
        checks.append(
            CheckResult(
                CheckCategory.STRUCTURAL,
                "schema_v2",
                CheckStatus.PASS,
                "Schema v2 validation passed",
            )
        )
        return True

    def _check_required_keys(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        present = set(raw.keys())
        missing = _REQUIRED_KEYS - present
        if missing:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "required_keys",
                    CheckStatus.FAIL,
                    f"Missing required keys: {sorted(missing)}",
                    details={"missing": sorted(missing)},
                )
            )
            return
        checks.append(
            CheckResult(
                CheckCategory.STRUCTURAL,
                "required_keys",
                CheckStatus.PASS,
                f"All {len(_REQUIRED_KEYS)} required keys present",
            )
        )

    def _check_query_count_math(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        sq = raw.get("summary", {}).get("queries", {})
        total = sq.get("total", 0)
        passed = sq.get("passed", 0)
        failed = sq.get("failed", 0)
        if passed + failed != total:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_count_math",
                    CheckStatus.FAIL,
                    f"{passed} passed + {failed} failed != {total} total",
                    details={"passed": passed, "failed": failed, "total": total},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_count_math",
                    CheckStatus.PASS,
                    f"{total} = {passed} passed + {failed} failed",
                )
            )

    def _check_timing_non_negative(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        timing = raw.get("summary", {}).get("timing", {})
        negative = {k: v for k, v in timing.items() if isinstance(v, (int, float)) and v < 0}
        if negative:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "timing_non_negative",
                    CheckStatus.FAIL,
                    f"Negative timing values: {negative}",
                    details={"negative_fields": negative},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "timing_non_negative",
                    CheckStatus.PASS,
                    "All timing values non-negative",
                )
            )

    def _check_percentile_ordering(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        timing = raw.get("summary", {}).get("timing", {})
        p90 = timing.get("p90_ms")
        p95 = timing.get("p95_ms")
        p99 = timing.get("p99_ms")
        if p90 is not None and p95 is not None and p99 is not None:
            if not (p90 <= p95 <= p99):
                checks.append(
                    CheckResult(
                        CheckCategory.STRUCTURAL,
                        "percentile_ordering",
                        CheckStatus.FAIL,
                        f"Percentiles out of order: p90={p90}, p95={p95}, p99={p99}",
                        details={"p90_ms": p90, "p95_ms": p95, "p99_ms": p99},
                    )
                )
                return
        checks.append(
            CheckResult(
                CheckCategory.STRUCTURAL,
                "percentile_ordering",
                CheckStatus.PASS,
                "Percentile ordering correct (p90 <= p95 <= p99)",
            )
        )

    def _check_phase_status_values(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        phases = raw.get("phases", {})
        invalid = {}
        for name, phase in phases.items():
            if isinstance(phase, dict):
                status = phase.get("status", "")
                if status and status not in _VALID_PHASE_STATUSES:
                    invalid[name] = status
        if invalid:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "phase_status_values",
                    CheckStatus.FAIL,
                    f"Invalid phase statuses: {invalid}",
                    details={"invalid_phases": invalid},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "phase_status_values",
                    CheckStatus.PASS,
                    f"All {len(phases)} phase statuses valid",
                )
            )

    def _check_query_entry_fields(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        queries = raw.get("queries", [])
        missing_fields = []
        for i, q in enumerate(queries):
            if not isinstance(q, dict):
                missing_fields.append({"index": i, "error": "not a dict"})
                continue
            for field_name in ("id", "ms", "status"):
                if field_name not in q:
                    missing_fields.append({"index": i, "missing": field_name})
        if missing_fields:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_entry_fields",
                    CheckStatus.FAIL,
                    f"{len(missing_fields)} query entries missing required fields",
                    details={"issues": missing_fields[:10]},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_entry_fields",
                    CheckStatus.PASS,
                    f"All {len(queries)} query entries have id, ms, status",
                )
            )

    def _check_query_ms_non_negative(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        queries = raw.get("queries", [])
        negative = [
            {"id": q.get("id"), "ms": q.get("ms")}
            for q in queries
            if isinstance(q, dict) and isinstance(q.get("ms"), (int, float)) and q["ms"] < 0
        ]
        if negative:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_ms_non_negative",
                    CheckStatus.FAIL,
                    f"{len(negative)} queries with negative ms",
                    details={"negative_queries": negative[:10]},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "query_ms_non_negative",
                    CheckStatus.PASS,
                    "No queries with negative ms",
                )
            )

    # --- Tier 2: Completeness checks ---

    def _check_expected_query_ids(self, raw: dict[str, Any], spec: Any | None, checks: list[CheckResult]) -> None:
        if spec is None:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "expected_query_ids",
                    CheckStatus.PASS,
                    "Unknown benchmark - skipping query ID check",
                )
            )
            return

        queries = raw.get("queries", [])
        actual_ids = {q["id"] for q in queries if isinstance(q, dict) and "id" in q}

        if spec.unique_query_ids:
            expected = spec.unique_query_ids
            found = actual_ids & expected
            ratio = len(found) / len(expected) if expected else 1.0
            if ratio < 0.8:
                checks.append(
                    CheckResult(
                        CheckCategory.COMPLETENESS,
                        "expected_query_ids",
                        CheckStatus.FAIL,
                        f"{len(found)}/{len(expected)} expected query IDs found ({ratio:.0%})",
                        details={"missing": sorted(expected - actual_ids)},
                    )
                )
            elif ratio < 1.0:
                checks.append(
                    CheckResult(
                        CheckCategory.COMPLETENESS,
                        "expected_query_ids",
                        CheckStatus.WARN,
                        f"{len(found)}/{len(expected)} expected query IDs found ({ratio:.0%})",
                        details={"missing": sorted(expected - actual_ids)},
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        CheckCategory.COMPLETENESS,
                        "expected_query_ids",
                        CheckStatus.PASS,
                        f"{len(found)}/{len(expected)} expected query IDs found",
                    )
                )
        elif spec.min_unique_queries > 0:
            unique_count = len(actual_ids)
            if unique_count < spec.min_unique_queries:
                checks.append(
                    CheckResult(
                        CheckCategory.COMPLETENESS,
                        "expected_query_ids",
                        CheckStatus.FAIL,
                        f"Only {unique_count} unique queries, expected >= {spec.min_unique_queries}",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        CheckCategory.COMPLETENESS,
                        "expected_query_ids",
                        CheckStatus.PASS,
                        f"{unique_count} unique queries (>= {spec.min_unique_queries} minimum)",
                    )
                )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "expected_query_ids",
                    CheckStatus.PASS,
                    "Open-ended benchmark - no fixed query set",
                )
            )

    def _check_measurement_queries_present(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        queries = raw.get("queries", [])
        has_measurement = any(
            (isinstance(q, dict) and (q.get("run_type") == "measurement" or q.get("iter", 0) > 0)) for q in queries
        )
        if not has_measurement:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "measurement_queries_present",
                    CheckStatus.FAIL,
                    "No measurement queries found (no run_type='measurement' or iter > 0)",
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "measurement_queries_present",
                    CheckStatus.PASS,
                    "Measurement queries present",
                )
            )

    def _check_power_phase_completed(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        phases = raw.get("phases", {})
        power = phases.get("power_test", {})
        if not isinstance(power, dict):
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "power_phase_completed",
                    CheckStatus.WARN,
                    "No power_test phase found",
                )
            )
            return
        status = power.get("status", "")
        if status in ("COMPLETED", "SUCCESS", "PASSED"):
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "power_phase_completed",
                    CheckStatus.PASS,
                    f"Power test phase status: {status}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "power_phase_completed",
                    CheckStatus.WARN,
                    f"Power test phase status: {status}",
                )
            )

    def _check_tables_object(self, raw: dict[str, Any], spec: Any | None, checks: list[CheckResult]) -> None:
        tables = raw.get("tables")
        if spec is not None and spec.requires_tables_object and tables is None:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "tables_object",
                    CheckStatus.WARN,
                    "Tables object missing but required by spec",
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "tables_object",
                    CheckStatus.PASS,
                    "Tables object present" if tables is not None else "Tables not required",
                )
            )

    def _check_tpc_metrics(self, raw: dict[str, Any], benchmark_id: str, checks: list[CheckResult]) -> None:
        from .benchmark_specs import LEGACY_ALIASES

        canonical = LEGACY_ALIASES.get(benchmark_id, benchmark_id)
        if canonical not in _TPC_METRICS_BENCHMARKS:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "tpc_metrics",
                    CheckStatus.PASS,
                    "Not a TPC benchmark - skipped",
                )
            )
            return
        summary = raw.get("summary", {})
        if "tpc_metrics" in summary:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "tpc_metrics",
                    CheckStatus.PASS,
                    "TPC metrics present in summary",
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.COMPLETENESS,
                    "tpc_metrics",
                    CheckStatus.INFO,
                    f"TPC metrics absent for {canonical} benchmark (unofficial run - no QphH/QthDS expected)",
                )
            )

    # --- Tier 3: Believability checks ---

    def _check_avg_between_min_max(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        timing = raw.get("summary", {}).get("timing", {})
        avg = timing.get("avg_ms")
        min_ms = timing.get("min_ms")
        max_ms = timing.get("max_ms")
        if avg is not None and min_ms is not None and max_ms is not None:
            if not (min_ms <= avg <= max_ms):
                checks.append(
                    CheckResult(
                        CheckCategory.BELIEVABILITY,
                        "avg_between_min_max",
                        CheckStatus.FAIL,
                        f"avg_ms={avg} not in [{min_ms}, {max_ms}]",
                        details={"avg_ms": avg, "min_ms": min_ms, "max_ms": max_ms},
                    )
                )
                return
        checks.append(
            CheckResult(
                CheckCategory.BELIEVABILITY,
                "avg_between_min_max",
                CheckStatus.PASS,
                "Average within [min, max] range",
            )
        )

    def _check_geomean_plausible(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        timing = raw.get("summary", {}).get("timing", {})
        geomean = timing.get("geometric_mean_ms")
        min_ms = timing.get("min_ms")
        max_ms = timing.get("max_ms")
        if geomean is not None and min_ms is not None and max_ms is not None:
            if not (min_ms <= geomean <= max_ms):
                checks.append(
                    CheckResult(
                        CheckCategory.BELIEVABILITY,
                        "geomean_plausible",
                        CheckStatus.FAIL,
                        f"geometric_mean_ms={geomean} not in [{min_ms}, {max_ms}]",
                        details={"geometric_mean_ms": geomean, "min_ms": min_ms, "max_ms": max_ms},
                    )
                )
                return
        checks.append(
            CheckResult(
                CheckCategory.BELIEVABILITY,
                "geomean_plausible",
                CheckStatus.PASS,
                "Geometric mean within [min, max] range",
            )
        )

    def _check_success_rate(self, raw: dict[str, Any], spec: Any | None, checks: list[CheckResult]) -> None:
        sq = raw.get("summary", {}).get("queries", {})
        total = sq.get("total", 0)
        passed = sq.get("passed", 0)
        if total == 0:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "success_rate",
                    CheckStatus.FAIL,
                    "No queries recorded",
                )
            )
            return

        rate = passed / total
        if spec is not None and spec.high_failure_expected:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "success_rate",
                    CheckStatus.PASS,
                    f"{rate:.1%} success rate (high failure expected for this benchmark)",
                )
            )
            return

        floor = spec.min_success_rate if spec is not None else 0.8
        if rate < floor:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "success_rate",
                    CheckStatus.FAIL,
                    f"{rate:.1%} success rate below {floor:.0%} floor",
                    details={"rate": rate, "floor": floor, "passed": passed, "total": total},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "success_rate",
                    CheckStatus.PASS,
                    f"{rate:.1%} >= {floor:.0%} floor",
                )
            )

    def _check_sf1_row_counts(
        self,
        raw: dict[str, Any],
        spec: Any | None,
        scale_factor: float,
        checks: list[CheckResult],
    ) -> None:
        if spec is None or spec.sf1_row_counts is None or scale_factor != 1.0:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "sf1_row_counts",
                    CheckStatus.PASS,
                    "Row count check not applicable (no spec, no SF1 counts, or SF != 1.0)",
                )
            )
            return
        tables = raw.get("tables")
        if tables is None:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "sf1_row_counts",
                    CheckStatus.PASS,
                    "No tables metadata to check",
                )
            )
            return

        # Normalize tables format (list of dicts or dict of dicts)
        table_rows: dict[str, int] = {}
        if isinstance(tables, list):
            for t in tables:
                if isinstance(t, dict) and "name" in t:
                    table_rows[t["name"]] = t.get("rows", 0)
        elif isinstance(tables, dict):
            for name, info in tables.items():
                if isinstance(info, dict):
                    table_rows[name] = info.get("rows", 0)
                elif isinstance(info, int):
                    table_rows[name] = info

        # ±1% tolerance: spec values are exact DuckDB SF1 counts, but we allow
        # slack for cross-platform variation (e.g. approximate COUNT(*), NULL
        # handling differences during load) and minor generator evolution.
        # The check targets gross failures (wrong SF → 10-100x off, failed
        # load → 0 rows), not bit-exact reproducibility across platforms.
        tolerance = 0.01

        mismatches = {}
        missing_tables = []
        for table_name, expected_rows in spec.sf1_row_counts.items():
            actual = table_rows.get(table_name)
            if actual is None:
                missing_tables.append(table_name)
                continue
            if expected_rows == 0:
                continue
            pct_diff = abs(actual - expected_rows) / expected_rows
            if pct_diff > tolerance:
                mismatches[table_name] = {"expected": expected_rows, "actual": actual, "diff": f"{pct_diff:.1%}"}

        if mismatches:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "sf1_row_counts",
                    CheckStatus.FAIL,
                    f"{len(mismatches)} tables outside ±1% of SF1 expected rows",
                    details={"mismatches": mismatches, "missing": missing_tables},
                )
            )
        elif missing_tables:
            checked = len(spec.sf1_row_counts) - len(missing_tables)
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "sf1_row_counts",
                    CheckStatus.FAIL,
                    f"{len(missing_tables)} expected tables missing from tables metadata "
                    f"({checked}/{len(spec.sf1_row_counts)} checked)",
                    details={"missing": missing_tables},
                )
            )
        else:
            matched = len(spec.sf1_row_counts)
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "sf1_row_counts",
                    CheckStatus.PASS,
                    f"{matched} tables within ±1% of SF1 expected",
                )
            )

    def _check_timing_outliers(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        queries = raw.get("queries", [])
        outliers = [
            q.get("id")
            for q in queries
            if isinstance(q, dict) and isinstance(q.get("ms"), (int, float)) and q["ms"] > 1_800_000
        ]
        if outliers:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "timing_outliers",
                    CheckStatus.WARN,
                    f"{len(outliers)} queries exceed 30 minutes",
                    details={"query_ids": outliers[:10]},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "timing_outliers",
                    CheckStatus.PASS,
                    "No queries exceed 30-minute threshold",
                )
            )

    def _check_no_duplicate_executions(self, raw: dict[str, Any], checks: list[CheckResult]) -> None:
        queries = raw.get("queries", [])
        seen: set[tuple[str, int, int]] = set()
        dupes: list[tuple[str, int, int]] = []
        for q in queries:
            if not isinstance(q, dict):
                continue
            key = (str(q.get("id", "")), q.get("iter", 0), q.get("stream", 0))
            if key in seen:
                dupes.append(key)
            else:
                seen.add(key)
        if dupes:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "no_duplicate_executions",
                    CheckStatus.WARN,
                    f"{len(dupes)} duplicate (id, iter, stream) entries",
                    details={"duplicates": [{"id": d[0], "iter": d[1], "stream": d[2]} for d in dupes[:10]]},
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "no_duplicate_executions",
                    CheckStatus.PASS,
                    "No duplicate (id, iter, stream) entries",
                )
            )

    def _check_load_time_nonzero(self, raw: dict[str, Any], benchmark_id: str, checks: list[CheckResult]) -> None:
        from .benchmark_specs import LEGACY_ALIASES

        canonical = LEGACY_ALIASES.get(benchmark_id, benchmark_id)
        if canonical in _NO_LOAD_BENCHMARKS:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "load_time_nonzero",
                    CheckStatus.PASS,
                    "No data loading expected for this benchmark",
                )
            )
            return

        phases = raw.get("phases", {})
        loading = phases.get("data_loading", {})
        if not isinstance(loading, dict):
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "load_time_nonzero",
                    CheckStatus.PASS,
                    "No data_loading phase found",
                )
            )
            return
        load_time = loading.get("duration_ms", loading.get("load_time_ms"))
        if load_time is not None and load_time == 0:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "load_time_nonzero",
                    CheckStatus.WARN,
                    "Load time is 0ms",
                )
            )
        else:
            checks.append(
                CheckResult(
                    CheckCategory.BELIEVABILITY,
                    "load_time_nonzero",
                    CheckStatus.PASS,
                    "Load time is non-zero" if load_time else "No load time recorded",
                )
            )


# --- Module-level convenience functions ---


def validate_file(path: Path | str) -> IntegrityReport:
    """Validate a single result JSON file."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return IntegrityReport(
            file=str(path),
            benchmark_id="unknown",
            platform="unknown",
            scale_factor=0.0,
            overall_status=CheckStatus.FAIL,
            checks=[
                CheckResult(
                    CheckCategory.STRUCTURAL,
                    "file_readable",
                    CheckStatus.FAIL,
                    f"Failed to read or parse {path.name}",
                )
            ],
            summary={"PASS": 0, "WARN": 0, "FAIL": 1},
        )
    validator = ResultIntegrityValidator()
    return validator.validate(raw, filepath=str(path))


def validate_directory(
    path: Path | str,
    pattern: str = "*.json",
) -> list[IntegrityReport]:
    """Validate all result JSON files in a directory.

    Excludes .plans.json and .tuning.json companion files.
    """
    path = Path(path)
    validator = ResultIntegrityValidator()
    reports = []
    for filepath in sorted(path.glob(pattern)):
        if filepath.name.endswith((".plans.json", ".tuning.json")):
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                raw = json.load(f)
            reports.append(validator.validate(raw, filepath=str(filepath)))
        except (json.JSONDecodeError, OSError):
            reports.append(
                IntegrityReport(
                    file=str(filepath),
                    benchmark_id="unknown",
                    platform="unknown",
                    scale_factor=0.0,
                    overall_status=CheckStatus.FAIL,
                    checks=[
                        CheckResult(
                            CheckCategory.STRUCTURAL,
                            "file_readable",
                            CheckStatus.FAIL,
                            f"Failed to read or parse {filepath.name}",
                        )
                    ],
                    summary={"PASS": 0, "WARN": 0, "FAIL": 1},
                )
            )
    return reports
