"""Result capture, plan capture, and post-load validation helpers.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 5). Houses:

- `_collect_resource_utilization` - psutil-based host + process metrics
  snapshot attached to benchmark results.
- `_reset_plan_capture_stats` - per-run plan-capture counter reset.
- Plan capture pipeline: `display_query_plan_if_enabled`,
  `get_query_plan`, `get_query_plan_parser`, `_record_plan_capture_failure`,
  and `capture_query_plan` (EXPLAIN-output capture + parse + size guard).
- `validate_loaded_data` / `validate_row_counts` - post-load database
  validation entry points that delegate to `ValidationService` /
  `DataValidator`.

Instance attributes these methods read (initialized on the host adapter):
- `query_plans_captured`, `plan_capture_failures`, `plan_capture_errors`
- `capture_plans`, `plan_query_filter`, `plan_first_n`,
  `plan_sampling_rate`, `plan_capture_timeout_seconds`,
  `strict_plan_capture`, `_plan_capture_iteration_counts`
- `show_query_plans`, `enable_validation`
- `platform_name` (property), `logger`
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import os
import platform
import random
import re
import statistics
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from benchbox.core.errors import PlanCaptureError, SerializationError
from benchbox.core.results.builder import (
    _BENCHMARK_FAMILY,
    normalize_benchmark_id,
)
from benchbox.core.results.models import QUERY_RUN_TYPE_MEASUREMENT
from benchbox.platforms.base.models import (
    PowerTestPhase,
    QueryExecution,
    SetupPhase,
    ThroughputStream,
    ThroughputTestPhase,
)
from benchbox.platforms.base.runtime_metadata import build_default_normalized_result_metadata
from benchbox.platforms.base.utils import is_non_interactive
from benchbox.utils.clock import elapsed_seconds
from benchbox.utils.printing import quiet_console

try:
    from benchbox.core.results.models import ExecutionPhases, QueryDefinition
except ImportError:  # pragma: no cover - result models always present in real install
    ExecutionPhases = None  # type: ignore[assignment, misc]
    QueryDefinition = None  # type: ignore[assignment, misc]

try:
    from benchbox.core.validation import ValidationResult
except ImportError:  # pragma: no cover - validation always present in real install
    ValidationResult = None  # type: ignore[assignment, misc]


# A data-changing verb at the very start of the statement (word-bounded so an
# identifier like ``COPYRIGHTS`` or ``MERGEABLE`` is not misread as DML).
_DML_LEADING_RE = re.compile(r"^(?:INSERT|UPDATE|DELETE|MERGE|COPY)\b", re.IGNORECASE)
# A data-modifying verb anywhere — used only after a leading WITH to catch
# CTE-prefixed DML (``WITH cte AS (...) INSERT INTO ...``). COPY is excluded:
# it cannot appear inside a CTE, and its leading form is already caught above.
_DML_AFTER_CTE_RE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|MERGE)\b", re.IGNORECASE)


def _strip_leading_sql_comments(statement: str) -> str:
    """Drop leading ``--`` line comments and ``/* */`` block comments + whitespace."""
    statement = statement.lstrip()
    while True:
        if statement.startswith("--"):
            newline_pos = statement.find("\n")
            if newline_pos == -1:
                return ""
            statement = statement[newline_pos + 1 :].lstrip()
        elif statement.startswith("/*"):
            end = statement.find("*/")
            if end == -1:
                return ""
            statement = statement[end + 2 :].lstrip()
        else:
            return statement


def is_dml_query(query: str) -> bool:
    """Return True for data-changing DML statements (INSERT/UPDATE/DELETE/MERGE/COPY).

    Used to guard plan capture against double-execution: adapters that capture
    plans via ``EXPLAIN ANALYZE`` (DuckDB, MotherDuck) physically re-run the
    statement, so a DML query would mutate data twice. Callers downgrade to a
    non-ANALYZE ``EXPLAIN`` for these statements.

    Detection covers the data-modifying verbs INSERT/UPDATE/DELETE/MERGE/COPY,
    including when they are preceded by a leading ``WITH`` CTE clause. DDL
    (CREATE/DROP/ALTER/TRUNCATE) is intentionally excluded: DDL does not produce
    duplicate data mutations, so it does not need the ANALYZE guard. Leading
    line and block comments are stripped first so a commented preamble (e.g. a
    ``/* query 12 */`` banner) does not mask the verb.
    """
    statement = _strip_leading_sql_comments(query)
    if not statement:
        return False
    if _DML_LEADING_RE.match(statement):
        return True
    # CTE-prefixed DML: the data-modifying verb follows the CTE definitions, so a
    # leading-verb check alone misses it. Conservatively treat a WITH-prefixed
    # statement that contains a DML verb as DML — worst case a read-only CTE
    # query loses ANALYZE stats, which is far cheaper than a double mutation.
    if re.match(r"^WITH\b", statement, re.IGNORECASE) and _DML_AFTER_CTE_RE.search(statement):
        return True
    return False


def _extract_result_field(result: Any, attr: str, default: Any = None) -> Any:
    """Read ``attr`` from object or dict-style query result."""
    if hasattr(result, attr):
        return getattr(result, attr)
    if isinstance(result, dict):
        return result.get(attr, default)
    return default


def _coerce_time_seconds(result: Any) -> float | None:
    """Best-effort conversion of execution time to seconds."""
    time_ms = _extract_result_field(result, "execution_time_ms")
    if time_ms is not None:
        try:
            return float(time_ms) / 1000.0
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None

    time_value = _extract_result_field(result, "execution_time_seconds")
    if time_value is None:
        time_value = _extract_result_field(result, "duration")

    if time_value is None:
        return None

    try:
        seconds = float(time_value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None

    # Heuristic: treat very large numbers as milliseconds
    if seconds > 1000:
        seconds /= 1000.0
    return seconds


def _percentile(values: list[float], percentile: float) -> float:
    """Linear-interpolation percentile on a sorted list."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    rank = (percentile / 100) * (len(values) - 1)
    lower_idx = math.floor(rank)
    upper_idx = math.ceil(rank)

    if lower_idx == upper_idx:
        return values[int(rank)]

    weight = rank - lower_idx
    return values[lower_idx] + weight * (values[upper_idx] - values[lower_idx])


def _build_latency_stats(values: list[float]) -> dict[str, Any] | None:
    """Compute latency stats (min/max/mean/median/p90/p95/p99/stdev) in both units."""
    if not values:
        return None

    sorted_values = sorted(values)
    count = len(sorted_values)
    stats_seconds = {
        "count": count,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "mean": statistics.fmean(sorted_values),
        "median": statistics.median(sorted_values),
        "p90": _percentile(sorted_values, 90),
        "p95": _percentile(sorted_values, 95),
        "p99": _percentile(sorted_values, 99),
        "stdev": statistics.pstdev(sorted_values) if count > 1 else 0.0,
    }

    stats_milliseconds = {key: (value * 1000.0 if key != "count" else value) for key, value in stats_seconds.items()}

    return {"seconds": stats_seconds, "milliseconds": stats_milliseconds}


def _build_numeric_stats(values: list[float]) -> dict[str, Any] | None:
    """Compute basic numeric stats (min/max/mean/median/p90/p95/stdev)."""
    if not values:
        return None

    sorted_values = sorted(values)
    count = len(sorted_values)
    return {
        "count": count,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "mean": statistics.fmean(sorted_values),
        "median": statistics.median(sorted_values),
        "p90": _percentile(sorted_values, 90),
        "p95": _percentile(sorted_values, 95),
        "stdev": statistics.pstdev(sorted_values) if count > 1 else 0.0,
    }


def _collect_process_metrics(process: Any) -> dict[str, Any]:
    """Collect per-process resource metrics. Returns empty dict on any failure.

    Each metric is best-effort: psutil reports different attributes on different
    OSes, and some (io_counters, num_fds, num_handles) are frequently missing.
    We swallow per-metric failures rather than losing the whole snapshot.
    """
    process_snapshot: dict[str, Any] = {}
    try:
        with process.oneshot():
            try:
                mem_info = process.memory_full_info()
            except AttributeError:
                mem_info = process.memory_info()

            rss_mb = round(mem_info.rss / (1024 * 1024), 2) if mem_info else None
            vms = getattr(mem_info, "vms", None)
            vms_mb = round(vms / (1024 * 1024), 2) if vms else None

            process_snapshot.update(
                {
                    "pid": process.pid,
                    "name": process.name(),
                    "status": process.status(),
                    "memory_mb": rss_mb,
                    "virtual_memory_mb": vms_mb,
                    "memory_percent": process.memory_percent(),
                    "cpu_percent": process.cpu_percent(interval=0.0),
                    "num_threads": process.num_threads(),
                }
            )

            try:
                process_snapshot["create_time"] = datetime.fromtimestamp(process.create_time()).isoformat()
            except Exception:
                process_snapshot["create_time"] = None

            try:
                process_snapshot["num_fds"] = process.num_fds()
            except Exception:
                process_snapshot["num_fds"] = None

            try:
                process_snapshot["num_handles"] = process.num_handles()  # type: ignore[attr-defined]
            except Exception:
                process_snapshot["num_handles"] = None

            try:
                io_counters = process.io_counters()
                process_snapshot["io_counters"] = {
                    "read_mb": round(io_counters.read_bytes / (1024 * 1024), 2),
                    "write_mb": round(io_counters.write_bytes / (1024 * 1024), 2),
                    "read_ops": io_counters.read_count,
                    "write_ops": io_counters.write_count,
                }
            except Exception:
                process_snapshot["io_counters"] = None

            try:
                open_files = process.open_files()
                process_snapshot["open_files"] = [f.path for f in open_files]
            except Exception:
                process_snapshot["open_files"] = None

            try:
                ctx = process.num_ctx_switches()
                process_snapshot["context_switches"] = {
                    "voluntary": ctx.voluntary,
                    "involuntary": ctx.involuntary,
                }
            except Exception:
                process_snapshot["context_switches"] = None

    except Exception:  # pragma: no cover - defensive safeguard
        return {}

    return process_snapshot


def _accumulate_query_metrics(
    query_results: list[Any],
) -> tuple[int, int, list[float], list[float], list[int], list[int], list[dict[str, Any]], dict[str, int]]:
    """Walk query results once, accumulating the per-status metrics used in performance summary."""
    successes = 0
    skipped = 0
    durations_all: list[float] = []
    durations_success: list[float] = []
    rows_all: list[int] = []
    rows_success: list[int] = []
    failure_samples: list[dict[str, Any]] = []
    error_breakdown: dict[str, int] = {}

    for result in query_results:
        status = str(_extract_result_field(result, "status", "UNKNOWN")).upper() or "UNKNOWN"
        time_seconds = _coerce_time_seconds(result)
        rows_returned = _extract_result_field(result, "rows_returned", 0)

        try:
            row_value = int(rows_returned) if rows_returned is not None else 0
        except (TypeError, ValueError):
            row_value = 0

        rows_all.append(row_value)
        if time_seconds is not None:
            durations_all.append(time_seconds)

        if status == "SUCCESS":
            successes += 1
            rows_success.append(row_value)
            if time_seconds is not None:
                durations_success.append(time_seconds)
        elif status == "SKIPPED":
            skipped += 1
        else:
            error_message = _extract_result_field(result, "error_message") or _extract_result_field(result, "error")
            error_key = str(error_message).strip()[:120] or status if error_message else status
            error_breakdown[error_key] = error_breakdown.get(error_key, 0) + 1

            failure_entry: dict[str, Any] = {
                "query_id": _extract_result_field(result, "query_id", "unknown"),
                "status": status,
                "rows_returned": row_value,
            }
            if time_seconds is not None:
                failure_entry["execution_time_seconds"] = time_seconds
            if error_message:
                failure_entry["error"] = str(error_message)
            failure_samples.append(failure_entry)

    return (
        successes,
        skipped,
        durations_all,
        durations_success,
        rows_all,
        rows_success,
        failure_samples,
        error_breakdown,
    )


class ResultCaptureMixin:
    """Mixin providing result capture, plan capture, and validation helpers.

    Expects host class to expose `logger` and the plan-capture /
    validation configuration attributes (initialized in
    `PlatformAdapter.__init__`).
    """

    logger: logging.Logger

    def _reset_plan_capture_stats(self) -> None:
        """Reset plan capture counters for a new benchmark run."""
        self.query_plans_captured = 0
        self.plan_capture_failures = 0
        self.plan_capture_errors: list[dict[str, Any]] = []
        self._plan_capture_iteration_counts: dict[str, int] = {}

    def get_normalized_result_metadata(
        self,
        *,
        connection: Any | None = None,
        platform_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return normalized runtime/deployment metadata for result construction.

        Subclasses may override this optional hook to provide richer observed
        metadata. The default maps legacy ``get_platform_info()`` output into
        conservative normalized blocks.
        """
        return build_default_normalized_result_metadata(
            self,
            connection=connection,
            platform_info=platform_info,
        )

    def _collect_resource_utilization(self) -> dict[str, Any]:
        """Collect host and process resource utilization metrics when possible."""
        snapshot: dict[str, Any] = {
            "available": False,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "timestamp": datetime.now().isoformat(),
            "non_interactive": is_non_interactive(),
        }

        try:
            import psutil  # type: ignore
        except ImportError:
            snapshot["reason"] = "psutil not installed"
            return snapshot

        snapshot["available"] = True
        snapshot["psutil_version"] = getattr(psutil, "__version__", None)

        try:
            process = psutil.Process(os.getpid())
        except Exception:  # pragma: no cover - defensive safeguard
            process = None

        # CPU metrics
        cpu_percent = None
        per_cpu_percent: list[float] | None = None
        try:
            psutil.cpu_percent(interval=None)  # Prime measurement for accuracy
            cpu_percent = psutil.cpu_percent(interval=0.0)
            per_cpu_percent = psutil.cpu_percent(interval=0.0, percpu=True)
        except Exception:  # pragma: no cover - defensive safeguard
            cpu_percent = None
            per_cpu_percent = None

        snapshot["cpu_percent"] = cpu_percent
        snapshot["cpu"] = {"percent": cpu_percent, "per_cpu_percent": per_cpu_percent}

        try:
            load_avg = psutil.getloadavg()
        except Exception:  # pragma: no cover - not available on Windows
            load_avg = None
        snapshot["cpu"]["load_average"] = load_avg

        try:
            freq = psutil.cpu_freq()
            snapshot["cpu"]["frequency_mhz"] = freq.current if freq else None
        except Exception:  # pragma: no cover - platform dependent
            snapshot["cpu"]["frequency_mhz"] = None

        try:
            counted = psutil.cpu_count()
            if counted:
                snapshot["cpu_count"] = counted
        except Exception:  # pragma: no cover - fallback to os.cpu_count()
            pass

        # Memory metrics
        try:
            vm = psutil.virtual_memory()
            snapshot["memory"] = {
                "total_mb": round(vm.total / (1024 * 1024), 2),
                "available_mb": round(vm.available / (1024 * 1024), 2),
                "used_mb": round((vm.total - vm.available) / (1024 * 1024), 2),
                "percent": vm.percent,
            }
        except Exception:  # pragma: no cover - defensive safeguard
            snapshot["memory"] = None

        try:
            swap = psutil.swap_memory()
            snapshot["swap"] = {
                "total_mb": round(swap.total / (1024 * 1024), 2),
                "used_mb": round(swap.used / (1024 * 1024), 2),
                "percent": swap.percent,
            }
        except Exception:  # pragma: no cover - optional
            snapshot["swap"] = None

        # Disk and network
        try:
            disk = psutil.disk_usage(str(Path.cwd()))
            snapshot["disk"] = {
                "mount_point": str(Path.cwd()),
                "total_mb": round(disk.total / (1024 * 1024), 2),
                "used_mb": round(disk.used / (1024 * 1024), 2),
                "free_mb": round(disk.free / (1024 * 1024), 2),
                "percent": disk.percent,
            }
        except Exception:  # pragma: no cover - defensive safeguard
            snapshot["disk"] = None

        try:
            disk_io = psutil.disk_io_counters()
            snapshot["disk_io"] = {
                "read_mb": round(disk_io.read_bytes / (1024 * 1024), 2),
                "write_mb": round(disk_io.write_bytes / (1024 * 1024), 2),
                "read_ops": disk_io.read_count,
                "write_ops": disk_io.write_count,
            }
        except Exception:  # pragma: no cover - optional
            snapshot["disk_io"] = None

        try:
            net_io = psutil.net_io_counters()
            snapshot["network_io"] = {
                "sent_mb": round(net_io.bytes_sent / (1024 * 1024), 2),
                "received_mb": round(net_io.bytes_recv / (1024 * 1024), 2),
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
            }
        except Exception:  # pragma: no cover - optional
            snapshot["network_io"] = None

        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()
        except Exception:  # pragma: no cover - optional
            boot_time = None
        snapshot["boot_time"] = boot_time

        # Process metrics
        process_snapshot = _collect_process_metrics(process) if process is not None else {}

        if process_snapshot:
            snapshot["process_memory_mb"] = process_snapshot.get("memory_mb")
            snapshot["process_cpu_percent"] = process_snapshot.get("cpu_percent")
            snapshot["process"] = process_snapshot
        else:
            snapshot["process_memory_mb"] = None
            snapshot["process_cpu_percent"] = None
            snapshot["process"] = None

        return snapshot

    def display_query_plan_if_enabled(self, connection: Any, query: str, query_id: str) -> None:
        """Display query execution plan if show_query_plans is enabled.

        Args:
            connection: Database connection
            query: SQL query text
            query_id: Query identifier
        """
        if not self.show_query_plans or self.capture_plans:
            return

        try:
            plan = self.get_query_plan(connection, query)
            if plan:
                from rich.panel import Panel

                console = quiet_console
                console.print(Panel.fit("Query Profiling Information", style="cyan"))
                console.print(f"{query}")
                console.print(plan)
                console.print()  # Add spacing
        except Exception as e:
            self.logger.debug(f"Failed to get query plan for {query_id}: {e}")

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Get query execution plan for analysis.

        Override this method in platform adapters to provide platform-specific plans.

        Args:
            connection: Database connection
            query: SQL query text

        Returns:
            Query execution plan as string, or None if not available
        """
        return None

    def get_query_plan_parser(self):
        """Get query plan parser for this platform.

        Override this method in platform adapters to provide platform-specific parser.

        Returns:
            QueryPlanParser instance or None if not available
        """
        return None

    def _record_plan_capture_failure(
        self,
        query_id: str,
        reason: str,
        message: str | None = None,
        *,
        log_warning: bool = True,
    ) -> None:
        """Record a plan capture failure and optionally raise in strict mode."""
        error_record = {
            "query_id": str(query_id),
            "platform": self.platform_name,
            "reason": reason,
        }
        if message:
            error_record["message"] = message

        self.plan_capture_failures += 1
        self.plan_capture_errors.append(error_record)

        if log_warning:
            self.logger.warning(
                "Failed to capture query plan for %s (query_id=%s): %s",
                self.platform_name,
                query_id,
                message or reason,
            )

        if self.strict_plan_capture:
            raise PlanCaptureError(
                reason=reason,
                platform=self.platform_name,
                query_id=str(query_id),
                details=message,
            )

    def capture_query_plan(self, connection: Any, query: str, query_id: str) -> tuple[Any, float]:
        """Capture structured query plan using platform-specific parser.

        Calls get_query_plan() to obtain EXPLAIN output and parses it into a QueryPlanDAG.
        Returns timing information for observability of capture overhead.

        By default (analyze_plans=True), DuckDB uses EXPLAIN (ANALYZE, FORMAT JSON) which
        re-executes the query to capture actual per-operator timing and cardinality.
        Set analyze_plans=False in the adapter config to use plain EXPLAIN (FORMAT JSON)
        for estimated-plan-only capture with no re-execution overhead.

        Plan fingerprints exclude timing/cardinality by design - structural comparisons
        are unaffected by this setting.

        Args:
            connection: Database connection
            query: SQL query text
            query_id: Query identifier

        Returns:
            Tuple of (QueryPlanDAG | None, capture_time_ms)
        """
        if not self.capture_plans:
            return None, 0.0

        # Apply query filter if specified
        if self.plan_query_filter and query_id not in self.plan_query_filter:
            return None, 0.0

        # Apply first-N iterations filter if specified
        if self.plan_first_n is not None:
            iteration = self._plan_capture_iteration_counts.get(query_id, 0)
            self._plan_capture_iteration_counts[query_id] = iteration + 1
            if iteration >= self.plan_first_n:
                return None, 0.0

        # Apply sampling rate if specified
        if self.plan_sampling_rate is not None:
            if random.random() > self.plan_sampling_rate:
                return None, 0.0

        start_time = time.perf_counter()

        try:
            # Apply timeout protection for EXPLAIN query
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.get_query_plan, connection, query)
                try:
                    explain_output = future.result(timeout=self.plan_capture_timeout_seconds)
                except concurrent.futures.TimeoutError:
                    capture_time_ms = (time.perf_counter() - start_time) * 1000
                    self.logger.warning(
                        "Query plan capture timed out for %s after %ds (%.2fms elapsed)",
                        query_id,
                        self.plan_capture_timeout_seconds,
                        capture_time_ms,
                    )
                    self._record_plan_capture_failure(
                        query_id,
                        reason="timeout",
                        message=f"EXPLAIN query timed out after {self.plan_capture_timeout_seconds}s",
                        log_warning=False,
                    )
                    return None, capture_time_ms
        except PlanCaptureError:
            raise
        except Exception as exc:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self._record_plan_capture_failure(
                query_id,
                reason="explain_failed",
                message=str(exc),
            )
            return None, capture_time_ms

        if not explain_output:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self._record_plan_capture_failure(
                query_id,
                reason="explain_failed",
                message="No EXPLAIN output returned",
            )
            return None, capture_time_ms

        parser = self.get_query_plan_parser()
        if not parser:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self.logger.warning(
                "Query plan capture disabled for %s: no parser available. "
                "Plans will not be captured for this benchmark run.",
                self.platform_name,
            )
            self._record_plan_capture_failure(
                query_id,
                reason="parser_unavailable",
                message=f"No parser available for {self.platform_name}",
                log_warning=False,
            )
            return None, capture_time_ms

        try:
            plan = parser.parse_explain_output(query_id, explain_output)
        except PlanCaptureError:
            raise
        except Exception as exc:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self._record_plan_capture_failure(
                query_id,
                reason="parse_error",
                message=str(exc),
            )
            return None, capture_time_ms

        if plan is None:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self._record_plan_capture_failure(
                query_id,
                reason="parse_error",
                message="Parser returned no plan",
            )
            return None, capture_time_ms

        try:
            size_kb = plan.estimate_serialized_size() / 1024
            if size_kb > 100:
                self.logger.warning(
                    "Large query plan for %s: %.1f KB. Consider using external plan storage.",
                    query_id,
                    size_kb,
                )
        except SerializationError as exc:
            capture_time_ms = (time.perf_counter() - start_time) * 1000
            self._record_plan_capture_failure(
                query_id,
                reason="serialization_error",
                message=str(exc),
            )
            return None, capture_time_ms

        capture_time_ms = (time.perf_counter() - start_time) * 1000
        self.query_plans_captured += 1
        return plan, capture_time_ms

    def _merge_plan_capture_into_result(
        self,
        result: dict[str, Any],
        connection: Any,
        query: str,
        query_id: str,
    ) -> None:
        """Capture the query plan and merge the plan fields into ``result`` in place.

        Encapsulates the per-adapter plan-capture block so it lives in exactly one
        place. The SUCCESS guard is baked in universally: capture only runs when
        ``capture_plans`` is enabled and the result succeeded, so a validation-
        failed result never triggers a wasted EXPLAIN round-trip.

        No-op when ``capture_plans`` is False or ``result["status"]`` is not
        ``"SUCCESS"``. On success, sets ``query_plan`` and ``plan_fingerprint`` when
        a plan was parsed, and always records ``plan_capture_time_ms`` when measured.

        Args:
            result: Result dict to mutate in place.
            connection: Database connection.
            query: SQL query text.
            query_id: Query identifier.
        """
        if not self.capture_plans or result.get("status") != "SUCCESS":
            return
        query_plan, plan_capture_time_ms = self.capture_query_plan(connection, query, query_id)
        if query_plan:
            result["query_plan"] = query_plan
            result["plan_fingerprint"] = query_plan.plan_fingerprint
        if plan_capture_time_ms is not None:
            result["plan_capture_time_ms"] = plan_capture_time_ms

    def validate_loaded_data(self, connection: Any, benchmark_type: str, scale_factor: float) -> ValidationResult:
        """Validate database state after data loading using platform-specific methods.

        Args:
            connection: Database connection object
            benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')
            scale_factor: Scale factor for the benchmark

        Returns:
            ValidationResult with database validation status
        """
        if not self.enable_validation:
            # Return a pass-through result if validation is disabled
            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=["Validation disabled"],
                details={
                    "benchmark_type": benchmark_type,
                    "scale_factor": scale_factor,
                    "platform": self.platform_name,
                    "validation_enabled": False,
                },
            )

        from benchbox.core.validation import ValidationService

        service = ValidationService()
        result = service.run_database(connection, benchmark_type, scale_factor)

        # Include platform-specific details
        result.details.update({"platform": self.platform_name, "validation_enabled": True})

        return result

    def validate_row_counts(self, connection: Any, expected_counts: dict[str, int]):
        """Validate actual row counts against expected counts.

        Args:
            connection: Database connection
            expected_counts: Dictionary mapping table names to expected row counts

        Returns:
            ValidationResult with row count comparison results
        """
        self.log_operation_start("Row count validation", f"{len(expected_counts)} tables to validate")

        try:
            # Import here to avoid circular dependencies
            from benchbox.core.validation.data import DataValidator

            validator = DataValidator(self)
            result = validator.validate_row_counts(expected_counts)

            if result.is_valid:
                self.log_operation_complete("Row count validation", details="All row counts match expected values")
            else:
                self.log_verbose(f"Row count validation failed: {len(result.issues)} issues found")

            return result

        except Exception as e:
            self.logger.error(f"Failed to validate row counts: {e}")
            from benchbox.core.validation.data import ValidationResult

            result = ValidationResult()
            result.add_error(f"Row count validation failed: {e}")
            return result

    # -------------------------------------------------------------------------
    # Performance summarization and result formatting helpers (extracted w9)
    # -------------------------------------------------------------------------

    def _summarize_performance_characteristics(
        self,
        query_results: list[Any] | None,
        total_duration: float,
        total_rows_loaded: int,
    ) -> dict[str, Any]:
        """Summarize performance characteristics for benchmark execution results."""

        summary: dict[str, Any] = {
            "total_duration_seconds": total_duration,
            "total_rows_loaded": total_rows_loaded,
            "total_queries": 0,
            "successful_queries": 0,
            "skipped_queries": 0,
            "failed_queries": 0,
            "success_rate": None,
            "average_query_time_ms": None,
            "average_success_query_time_ms": None,
            "throughput_qps": None,
            "successful_throughput_qps": None,
            "rows_returned_total": 0,
            "rows_returned_average": None,
            "rows_returned_per_second": None,
            "execution_time_stats": None,
            "rows_returned_stats": None,
            "error_breakdown": {},
            "failure_samples": [],
        }

        if not query_results:
            return summary

        total_queries = len(query_results)
        summary["total_queries"] = total_queries

        (
            successes,
            skipped,
            durations_all,
            durations_success,
            rows_all,
            rows_success,
            failure_samples,
            error_breakdown,
        ) = _accumulate_query_metrics(query_results)

        summary["rows_returned_total"] = sum(rows_all)
        summary["successful_queries"] = successes
        summary["skipped_queries"] = skipped
        summary["failed_queries"] = total_queries - successes - skipped
        summary["error_breakdown"] = error_breakdown
        summary["failure_samples"] = failure_samples[:5]

        if total_queries:
            summary["success_rate"] = successes / total_queries

        if durations_all:
            summary["average_query_time_ms"] = statistics.fmean(durations_all) * 1000.0

        if durations_success:
            summary["average_success_query_time_ms"] = statistics.fmean(durations_success) * 1000.0

        if rows_all:
            summary["rows_returned_average"] = statistics.fmean(rows_all)

        if total_duration and total_duration > 0:
            summary["throughput_qps"] = total_queries / total_duration if total_queries else 0.0
            summary["successful_throughput_qps"] = successes / total_duration if successes else 0.0
            if summary["rows_returned_total"]:
                summary["rows_returned_per_second"] = summary["rows_returned_total"] / total_duration

        summary["execution_time_stats"] = {
            "all": _build_latency_stats(durations_all),
            "successful": _build_latency_stats(durations_success),
        }

        summary["rows_returned_stats"] = {
            "all": _build_numeric_stats([float(r) for r in rows_all]),
            "successful": _build_numeric_stats([float(r) for r in rows_success]),
        }

        return summary

    def _format_execution_time(self, execution_time_seconds: float) -> str:
        """Format execution time with adaptive precision.

        Args:
            execution_time_seconds: Execution time in seconds

        Returns:
            Formatted time string with appropriate unit and precision
        """
        if execution_time_seconds < 0.001:
            # < 1ms: show as microseconds with 0 decimal places
            return f"{execution_time_seconds * 1000000:.0f}μs"
        elif execution_time_seconds < 1.0:
            # < 1s: show as milliseconds with 1 decimal place
            return f"{execution_time_seconds * 1000:.1f}ms"
        elif execution_time_seconds < 60.0:
            # < 1min: show as seconds with 2 decimal places
            return f"{execution_time_seconds:.2f}s"
        else:
            # >= 1min: show as minutes:seconds
            minutes = int(execution_time_seconds // 60)
            seconds = execution_time_seconds % 60
            return f"{minutes}:{seconds:04.1f}"

    # Derived from _BENCHMARK_FAMILY (TPC family members) + standalone benchmarks.
    # Adding a derived benchmark to _BENCHMARK_FAMILY automatically registers it here.
    _KNOWN_BENCHMARK_IDS = frozenset(_BENCHMARK_FAMILY) | {"ssb", "clickbench"}

    @staticmethod
    def _normalize_known_benchmark_id(name: str) -> str | None:
        """Normalize a benchmark label when it matches a known benchmark family."""
        benchmark_id = normalize_benchmark_id(name)
        if benchmark_id in ResultCaptureMixin._KNOWN_BENCHMARK_IDS:
            return benchmark_id
        return None

    @staticmethod
    def _class_name_benchmark_type(class_name: str) -> str | None:
        """Resolve benchmark IDs from class-name patterns for non-TPC families."""
        benchmark_patterns = [
            ("amplab", "amplab"),
            ("h2odb", "h2odb"),
            ("h2o", "h2odb"),
            ("coffeeshop", "coffeeshop"),
            ("joinorder", "joinorder"),
            ("join_order", "joinorder"),
            ("tpcdi", "tpcdi"),
            ("tpc_di", "tpcdi"),
            ("star_schema", "ssb"),
        ]
        for pattern, benchmark_id in benchmark_patterns:
            if pattern in class_name:
                return benchmark_id
        return None

    def _build_query_result_with_validation(
        self,
        query_id: str,
        execution_time: float,
        actual_row_count: int,
        first_row: Any = None,
        validation_result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Build query result dictionary with consistent validation field mapping.

        This centralizes validation result processing to ensure all platform adapters
        use the same field names and status mapping logic.

        Args:
            query_id: Query identifier
            execution_time: Query execution time in seconds
            actual_row_count: Number of rows returned
            first_row: First row of results (optional)
            validation_result: ValidationResult from QueryValidator (optional)
            error: Error message if query failed (optional)

        Returns:
            Dictionary with standardized query result fields
        """
        # Import ValidationMode here to avoid circular dependency
        from benchbox.core.expected_results.models import ValidationMode

        # Start with base result fields
        result_dict = {
            "query_id": str(query_id),
            "status": "FAILED" if error else "SUCCESS",
            "execution_time_seconds": execution_time,
            "rows_returned": actual_row_count,
            "first_row": first_row,
        }

        if error:
            result_dict["error"] = error

        # Include validation metadata if validation was performed
        if validation_result:
            # Create nested validation object
            row_count_validation = {
                "expected": validation_result.expected_row_count,
                "actual": actual_row_count,
            }

            # Correct SKIP vs PASSED vs FAILED mapping
            if validation_result.validation_mode == ValidationMode.SKIP:
                row_count_validation["status"] = "SKIPPED"
                if validation_result.warning_message:
                    row_count_validation["warning"] = validation_result.warning_message
            elif validation_result.is_valid:
                row_count_validation["status"] = "PASSED"
            else:
                # Validation failed - mark query as FAILED
                row_count_validation["status"] = "FAILED"
                row_count_validation["error"] = validation_result.error_message
                result_dict["status"] = "FAILED"
                result_dict["error"] = validation_result.error_message

            result_dict["row_count_validation"] = row_count_validation

        return result_dict

    def _build_query_failure_result(
        self,
        query_id: str,
        start_time: float,
        exception: Exception,
        log_error: bool = True,
    ) -> dict[str, Any]:
        """Build standardized query failure result dictionary.

        This centralizes error handling to ensure all platform adapters
        use the same failure result format.

        Args:
            query_id: Query identifier
            start_time: Query start time (from mono_time())
            exception: The exception that occurred
            log_error: Whether to log the error (default True)

        Returns:
            Dictionary with standardized failure result fields
        """
        execution_time = elapsed_seconds(start_time)

        if log_error:
            self.logger.error(
                f"Query {query_id} failed after {execution_time:.3f}s: {exception}",
                exc_info=True,
            )

        return {
            "query_id": query_id,
            "status": "FAILED",
            "execution_time_seconds": execution_time,
            "rows_returned": 0,
            "error": str(exception),
            "error_type": type(exception).__name__,
        }

    def _build_dry_run_result(self, query_id: str) -> dict[str, Any]:
        """Build standardized dry-run query result dictionary.

        Used when dry_run_mode is enabled - SQL is captured but not executed.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary with standardized dry-run result fields
        """
        self.log_very_verbose(f"Captured query {query_id} for dry-run")
        return {
            "query_id": query_id,
            "status": "DRY_RUN",
            "execution_time_seconds": 0.0,
            "rows_returned": 0,
            "first_row": None,
            "error": None,
            "dry_run": True,
        }

    @staticmethod
    def _normalize_and_validate_file_paths(
        file_paths: list | Any,
    ) -> list[Path]:
        """Normalize file paths to list and filter valid files.

        This centralizes file path validation to ensure consistent handling
        across all platform adapters during data loading.

        Args:
            file_paths: File path(s) - can be string, Path, or list

        Returns:
            List of valid Path objects (filtered by existence and size > 0)
        """
        # Normalize to list
        if not isinstance(file_paths, list):
            file_paths = [file_paths]

        # Filter valid files
        valid_files = [Path(f) for f in file_paths if Path(f).exists() and Path(f).stat().st_size > 0]

        return valid_files

    def _create_failed_benchmark_result(
        self,
        benchmark,
        validation_phase,
        table_stats,
        loading_time,
        schema_creation_phase,
        data_loading_phase,
        tunings_applied_dict,
        tuning_validation_status,
        tuning_metadata_saved,
    ):
        """Create a benchmark result indicating validation failure."""
        from datetime import datetime as _datetime

        # Create basic execution phases
        setup_phase = SetupPhase(
            data_loading=data_loading_phase,
            schema_creation=schema_creation_phase,
            validation=validation_phase,
        )

        # Create failed power test phase
        power_test_phase = PowerTestPhase(
            start_time=_datetime.now().isoformat(),
            end_time=_datetime.now().isoformat(),
            duration_ms=0,
            query_executions=[],
            geometric_mean_time=0.0,
            power_at_size=0.0,
        )

        execution_phases = ExecutionPhases(setup=setup_phase, power_test=power_test_phase)

        # Get platform info
        try:
            platform_info = self.get_platform_info(None)  # Connection might be invalid
        except Exception:
            platform_info = {"error": "Could not retrieve platform info"}
        normalized_metadata = self.get_normalized_result_metadata(platform_info=platform_info)

        # Create execution metadata
        execution_metadata = {
            "execution_timestamp": _datetime.now().isoformat(),
            "data_validation_failed": True,
            "validation_details": validation_phase.validation_details,
            "benchbox_version": "0.1.0",
            "sorted_ingestion": self.get_sorted_ingestion_metadata(),
        }

        # Calculate basic metrics
        total_rows_loaded = sum(table_stats.values()) if table_stats else 0
        data_size_mb = self._calculate_data_size(benchmark.output_dir) if hasattr(benchmark, "output_dir") else 0.0

        # Create failed benchmark result
        return benchmark.create_enhanced_benchmark_result(
            platform=self.platform_name,
            query_results=[],  # No queries were executed
            execution_metadata=execution_metadata,
            phases=execution_phases,
            resource_utilization={},
            performance_characteristics={},
            # Override defaults with failure status
            total_rows_loaded=total_rows_loaded,
            data_size_mb=data_size_mb,
            data_loading_time=loading_time,
            schema_creation_time=getattr(schema_creation_phase, "duration_ms", 0) / 1000.0,
            table_statistics=table_stats,
            tunings_applied=tunings_applied_dict,
            tuning_validation_status=tuning_validation_status,
            tuning_metadata_saved=tuning_metadata_saved,
            platform_info=platform_info,
            **normalized_metadata,
            validation_status="FAILED",  # This is the key fix
            validation_details=validation_phase.validation_details,
        )

    def _create_throughput_phase(self, throughput_result) -> ThroughputTestPhase | None:
        """Convert throughput test outputs into structured execution metadata."""
        if throughput_result is None:
            return None

        streams: list[ThroughputStream] = []
        total_queries_executed = 0

        for stream_result in getattr(throughput_result, "stream_results", []) or []:
            start_iso = self._format_timestamp(stream_result.start_time)
            end_iso = self._format_timestamp(stream_result.end_time)

            duration_seconds = float(getattr(stream_result, "duration", 0.0) or 0.0)
            if (
                not duration_seconds
                and isinstance(stream_result.start_time, (int, float))
                and isinstance(stream_result.end_time, (int, float))
            ):
                duration_seconds = max(stream_result.end_time - stream_result.start_time, 0.0)
            duration_ms = int(duration_seconds * 1000)

            query_executions: list[QueryExecution] = []
            for idx, query_result in enumerate(stream_result.query_results, start=1):
                execution_order = query_result.get("position") or query_result.get("execution_order") or idx
                execution_time_ms = int(float(query_result.get("execution_time_seconds", 0.0)) * 1000)

                query_executions.append(
                    QueryExecution(
                        query_id=str(query_result.get("query_id")),
                        stream_id=str(stream_result.stream_id),
                        execution_order=int(execution_order),
                        execution_time_ms=execution_time_ms,
                        status="SUCCESS" if query_result.get("success", True) else "FAILED",
                        rows_returned=query_result.get("result_count"),
                        error_message=query_result.get("error"),
                        run_type=self._infer_query_result_run_type(query_result),
                    )
                )

            streams.append(
                ThroughputStream(
                    stream_id=stream_result.stream_id,
                    start_time=start_iso,
                    end_time=end_iso,
                    duration_ms=duration_ms,
                    query_executions=query_executions,
                )
            )
            total_queries_executed += getattr(stream_result, "queries_executed", len(stream_result.query_results))

        duration_ms = int(float(getattr(throughput_result, "total_time", 0.0)) * 1000)
        end_time_iso = throughput_result.end_time or datetime.now().isoformat()

        return ThroughputTestPhase(
            start_time=throughput_result.start_time,
            end_time=end_time_iso,
            duration_ms=duration_ms,
            num_streams=getattr(getattr(throughput_result, "config", None), "num_streams", len(streams)),
            streams=streams,
            total_queries_executed=total_queries_executed,
            throughput_at_size=getattr(throughput_result, "throughput_at_size", 0.0),
        )

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        """Convert numeric timestamps to ISO-8601 strings."""
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value).isoformat()
        return datetime.now().isoformat()

    def _determine_overall_validation_status(self, validation_phase) -> str:
        """Determine overall validation status from individual validation results."""
        if (
            validation_phase.row_count_validation == "FAILED"
            or validation_phase.schema_validation == "FAILED"
            or validation_phase.data_integrity_checks == "FAILED"
        ):
            return "FAILED"
        elif (
            validation_phase.row_count_validation == "PARTIAL"
            or validation_phase.schema_validation == "PARTIAL"
            or validation_phase.data_integrity_checks == "PARTIAL"
        ):
            return "PARTIAL"
        else:
            return "PASSED"

    def _extract_query_definitions(
        self, benchmark, queries: dict[str, str], stream_id: str = "standard"
    ) -> dict[str, dict[str, QueryDefinition]]:
        """Extract query definitions for storage optimization."""
        query_definitions = {stream_id: {}}

        for query_id, sql_text in queries.items():
            query_definitions[stream_id][query_id] = QueryDefinition(
                sql=sql_text,
                parameters={},  # For now, parameters are embedded in SQL
            )

        return query_definitions

    def _create_standard_execution_phase(
        self, query_results: list[dict[str, Any]], stream_id: str = "standard"
    ) -> list[QueryExecution]:
        """Convert legacy query results to enhanced query executions."""
        query_executions = []

        for i, result in enumerate(query_results):
            query_executions.append(
                QueryExecution(
                    query_id=result.get("query_id", f"Q{i + 1}"),
                    stream_id=stream_id,
                    execution_order=i + 1,
                    execution_time_ms=round(result.get("execution_time_seconds", 0) * 1000, 2),
                    status=result.get("status", "UNKNOWN"),
                    rows_returned=result.get("rows_returned"),
                    error_message=result.get("error"),
                    run_type=result.get("run_type", QUERY_RUN_TYPE_MEASUREMENT),
                )
            )

        return query_executions

    def _setup_reused_database_phases(self, benchmark, connection: Any) -> tuple:
        """Set up phases when database is being reused (skip schema creation and data loading).

        When ``self.table_mode == "external"`` the reuse path still calls
        ``create_external_tables`` so that VIEWs/external references are
        recreated over the staged data files.

        Returns:
            Tuple of (schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, tuning_metadata_saved)
        """
        if self.table_mode == "external":
            return self._setup_reused_external_phases(benchmark, connection)

        quiet_console.print("✅ Database being reused - skipping schema creation and data loading")
        schema_time = 0.0
        schema_creation_phase = self._create_enhanced_schema_creation_phase(benchmark, connection, schema_time)
        loading_time = 0.0
        table_stats = {}
        if hasattr(benchmark, "get_schema"):
            schema = benchmark.get_schema()
            if isinstance(schema, dict):
                self.logger.debug(f"Collecting table stats for {len(schema)} tables from reused database")
                for table_name in schema:
                    try:
                        count = self.get_table_row_count(connection, table_name)
                        table_stats[table_name] = count
                        self.logger.debug(f"Table {table_name}: {count} rows")
                    except Exception as e:
                        self.logger.warning(f"Could not get row count for {table_name}: {e}")
                        table_stats[table_name] = 0
        data_loading_phase = self._create_enhanced_data_loading_phase(table_stats, loading_time, None)
        tuning_metadata_saved = False
        return schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, tuning_metadata_saved

    def _setup_reused_external_phases(self, benchmark, connection: Any) -> tuple:
        """Set up external table phases when database is being reused.

        Even when a database file is reused, external mode must recreate
        VIEWs/external table references because the previous run may have
        used native tables.
        """
        if not self.supports_external_tables:
            raise RuntimeError(f"Platform '{self.platform_name}' does not support --table-mode external")

        validate_fn = getattr(self, "validate_external_table_requirements", None)
        if callable(validate_fn):
            validate_fn()

        data_dir = Path(benchmark.output_dir) if hasattr(benchmark, "output_dir") else Path(".")

        quiet_console.print("Creating external tables (reusing existing database)...")
        schema_time = 0.0
        schema_creation_phase = self._create_enhanced_schema_creation_phase(benchmark, connection, schema_time)
        schema_creation_phase.status = "SKIPPED"

        table_stats, loading_time, per_table_timings = self.create_external_tables(benchmark, connection, data_dir)
        _fmt_tag = f" [{self.external_format}]" if self.external_format else ""
        quiet_console.print(f"✅ External tables created in {loading_time:.2f}s{_fmt_tag}")
        data_loading_phase = self._create_enhanced_data_loading_phase(table_stats, loading_time, per_table_timings)
        return schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, False

    def _setup_fresh_database_phases(self, benchmark, connection: Any, effective_tuning_config) -> tuple:
        """Set up phases for fresh database (schema creation, tuning, data loading).

        When ``self.table_mode == "external"`` the adapter skips native schema
        creation and tuning, and calls ``create_external_tables`` instead of
        ``load_data``.

        Returns:
            Tuple of (schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, tuning_metadata_saved)
        """
        data_dir = Path(benchmark.output_dir) if hasattr(benchmark, "output_dir") else Path(".")

        if self.table_mode == "external":
            # External table mode: skip native schema/tuning, create external references
            if not self.supports_external_tables:
                raise RuntimeError(f"Platform '{self.platform_name}' does not support --table-mode external")
            validate_fn = getattr(self, "validate_external_table_requirements", None)
            if callable(validate_fn):
                validate_fn()

            schema_time = 0.0
            schema_creation_phase = self._create_enhanced_schema_creation_phase(benchmark, connection, 0.0)
            schema_creation_phase.status = "SKIPPED"

            quiet_console.print("Creating external tables...")
            table_stats, loading_time, per_table_timings = self.create_external_tables(benchmark, connection, data_dir)
            _fmt_tag = f" [{self.external_format}]" if self.external_format else ""
            quiet_console.print(f"✅ External tables created in {loading_time:.2f}s{_fmt_tag}")
            data_loading_phase = self._create_enhanced_data_loading_phase(table_stats, loading_time, per_table_timings)
            return schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, False

        quiet_console.print("Creating database schema...")
        schema_time = self.create_schema(benchmark, connection)
        schema_creation_phase = self._create_enhanced_schema_creation_phase(benchmark, connection, schema_time)

        tuning_metadata_saved = False
        if self.tuning_enabled and effective_tuning_config:
            quiet_console.print("Applying unified tuning configuration...")
            self.apply_unified_tuning(effective_tuning_config, connection)
            quiet_console.print("✅ Unified tuning configuration applied")

            quiet_console.print("Saving tuning metadata...")
            tuning_metadata_saved = self.save_tuning_metadata(connection)
            if tuning_metadata_saved:
                quiet_console.print("✅ Tuning metadata saved")
            else:
                quiet_console.print("⚠️ Failed to save tuning metadata")

        quiet_console.print("Loading benchmark data...")
        table_stats, loading_time, per_table_timings = self.load_data(benchmark, connection, data_dir)
        quiet_console.print(f"✅ Data loading completed in {loading_time:.2f}s")
        data_loading_phase = self._create_enhanced_data_loading_phase(table_stats, loading_time, per_table_timings)
        return schema_time, schema_creation_phase, loading_time, table_stats, data_loading_phase, tuning_metadata_saved

    def _check_validation_failure(self, validation_phase) -> bool:
        """Check if validation failed and log details. Returns True if validation failed."""
        if (
            validation_phase.row_count_validation == "FAILED"
            or validation_phase.schema_validation == "FAILED"
            or validation_phase.data_integrity_checks == "FAILED"
        ):
            quiet_console.print("❌ Data validation failed - benchmark execution halted")
            if validation_phase.validation_details:
                details = validation_phase.validation_details
                if "empty_tables" in details and details["empty_tables"]:
                    quiet_console.print(f"⚠️  Empty tables detected: {', '.join(details['empty_tables'])}")
                if "missing_tables" in details and details["missing_tables"]:
                    quiet_console.print(f"⚠️  Missing tables: {', '.join(details['missing_tables'])}")
                if "inaccessible_tables" in details and details["inaccessible_tables"]:
                    quiet_console.print(f"⚠️  Inaccessible tables: {', '.join(details['inaccessible_tables'])}")
            return True
        return False

    def _build_execution_phases(self, query_results, query_executions, run_config, setup_phase) -> tuple:
        """Build power/throughput test phases and return execution phases with metrics.

        Returns:
            Tuple of (execution_phases, total_exec_time)
        """
        from datetime import datetime as _datetime

        successful_queries = len([r for r in query_results if r["status"] == "SUCCESS"])
        total_exec_time = sum(r["execution_time_seconds"] for r in query_results if r["status"] == "SUCCESS")
        avg_time = total_exec_time / max(successful_queries, 1)

        if self.capture_plans:
            total_queries_executed = len(query_results)
            summary_message = f"Query plans: {self.query_plans_captured}/{total_queries_executed} captured"
            if self.plan_capture_failures:
                summary_message = f"{summary_message}, {self.plan_capture_failures} failed"
            log_fn = self.logger.warning if self.plan_capture_failures else self.logger.info
            log_fn(summary_message)

        # When a fallback occurred (e.g. throughput requested but unsupported),
        # _effective_execution_type reflects the actual execution shape.
        eet = run_config.get("_effective_execution_type")
        execution_type = eet if eet is not None else run_config.get("test_execution_type", "standard")

        power_at_size_value = 0.0
        if getattr(self, "_last_power_test_result", None) is not None:
            power_at_size_value = getattr(self._last_power_test_result, "power_at_size", 0.0) or 0.0
            self._last_power_test_result = None

        power_test_phase = None
        if execution_type not in {"throughput"}:
            power_test_phase = PowerTestPhase(
                start_time=_datetime.now().isoformat(),
                end_time=_datetime.now().isoformat(),
                duration_ms=int(total_exec_time * 1000),
                query_executions=query_executions,
                geometric_mean_time=avg_time,
                power_at_size=power_at_size_value,
            )

        throughput_test_phase = None
        if getattr(self, "_last_throughput_test_result", None) is not None:
            throughput_test_phase = self._create_throughput_phase(self._last_throughput_test_result)
            self._last_throughput_test_result = None

        execution_phases = ExecutionPhases(
            setup=setup_phase,
            power_test=power_test_phase,
            throughput_test=throughput_test_phase,
        )
        return execution_phases, total_exec_time, power_test_phase, throughput_test_phase

    def _build_execution_metadata(self, run_config: dict) -> tuple:
        """Build execution metadata and system profile.

        Returns:
            Tuple of (execution_metadata, system_profile, anonymous_machine_id)
        """
        try:
            from benchbox.core.results.anonymization import (
                AnonymizationConfig,
                AnonymizationManager,
            )
            from benchbox.utils.system_info import get_system_info

            anonymization_manager = AnonymizationManager(AnonymizationConfig())
            system_info = get_system_info()
            system_profile = system_info.to_dict()
            anonymous_machine_id = anonymization_manager.get_anonymous_machine_id()
        except ImportError:
            system_profile = None
            anonymous_machine_id = None

        execution_metadata = {
            "benchmark_type": run_config.get("benchmark_type", "olap"),
            "query_subset": run_config.get("query_subset"),
            "categories": run_config.get("categories"),
            "connection_config_hash": self._hash_connection_config(run_config.get("connection", {})),
            "python_version": platform.python_version(),
            "benchbox_version": "0.1.0",
            "mode": "sql",
            # Canonical slug propagated by the runner from BenchmarkConfig.name.
            "benchmark_id": run_config.get("benchmark_name"),
            "run_config": {
                "compression": {
                    "type": run_config.get("compression_type"),
                    "level": run_config.get("compression_level"),
                }
                if run_config.get("compression_type")
                else None,
                "seed": run_config.get("seed"),
                "phases": run_config.get("phases"),
                "query_subset": run_config.get("query_subset"),
                "platform_options": run_config.get("platform_options"),
                "platform_option_sources": run_config.get("platform_option_sources"),
                "tuning_mode": run_config.get("tuning_mode"),
                "tuning_config": run_config.get("tuning_config"),
                "table_mode": self.table_mode if self.table_mode != "native" else None,
                "external_format": self.external_format,
                "table_format": run_config.get("table_format"),
                "table_format_compression": (
                    run_config.get("table_format_compression") if run_config.get("table_format") else None
                ),
                "table_format_partition_cols": (
                    run_config.get("table_format_partition_cols") if run_config.get("table_format") else None
                ),
            },
            "sorted_ingestion": self.get_sorted_ingestion_metadata(),
        }
        tuning_profile_metadata = self._build_tuning_profile_metadata(run_config)
        if tuning_profile_metadata:
            execution_metadata["tuning_profile"] = tuning_profile_metadata
        return execution_metadata, system_profile, anonymous_machine_id

    def _build_tuning_profile_metadata(self, run_config: dict) -> dict[str, Any] | None:
        """Build workload-profile tuning metadata without making result capture brittle."""
        try:
            from benchbox.core.tuning.profile_validation import build_tuning_profile_metadata

            effective_config = self.get_effective_tuning_configuration()
            return build_tuning_profile_metadata(
                benchmark=run_config.get("benchmark_name"),
                platform=getattr(self, "platform_name", None),
                tuning_config=effective_config,
            )
        except Exception as exc:  # pragma: no cover - metadata must not fail result capture
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.debug("Unable to build tuning profile metadata: %s", exc)
            return None
