"""TPC-specific benchmark test drivers for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 6a). Houses the seven
dispatch methods that bridge `PlatformAdapter` to the production TPC test
implementations:

- `_execute_tpch_power_test`, `_execute_generic_power_test`,
  `_execute_tpcds_power_test` - power test harnesses.
- `_execute_tpch_throughput_test`, `_execute_tpcds_throughput_test` -
  throughput harnesses.
- `_execute_tpch_maintenance_test`, `_execute_tpcds_maintenance_test` -
  refresh-function (RF1/RF2) harnesses.

Each method wraps the adapter connection in `PlatformAdapterConnection`,
instantiates the appropriate `TPC{H,DS}{Power,Throughput,Maintenance}Test`
class from `benchbox.core.{tpch,tpcds}.*`, and funnels the structured
query-level results back into the adapter's flat list-of-dicts format.

The abstract `execute_query` contract method stays on the facade - it
has 38+ subclass overrides and the adapter-level per-query timing wrap
is what test drivers ultimately call into.

Generic query pipeline helpers (`_execute_power_test`,
`_execute_throughput_test`, `run_power_test`, etc.) remain on
`PlatformAdapter` for now; a follow-up slice will move those.
"""

from __future__ import annotations

import contextlib
import signal
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from benchbox.core.constants import (
    GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS,
    GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS,
)
from benchbox.core.errors import PlanCaptureError
from benchbox.core.operations import OperationExecutor
from benchbox.core.plan_capture_phase import propagate_plan_capture_fields
from benchbox.core.power_harnesses import (
    resolve_combined_harness,
    resolve_maintenance_harness,
    resolve_power_harness,
    resolve_throughput_harness,
)
from benchbox.core.results.builder import benchmark_family, normalize_benchmark_id
from benchbox.core.results.models import QUERY_RUN_TYPE_MEASUREMENT, QUERY_RUN_TYPE_WARMUP
from benchbox.core.tpch.platform_power import _power_query_result, _power_test_error_result
from benchbox.platforms.base.connection_wrappers import (
    PlatformAdapterConnection,
    _make_stream_cursor,
)
from benchbox.utils.dialect_utils import SQLTranslationError
from benchbox.utils.printing import quiet_console

__all__ = ["TestDriversMixin", "_power_query_result", "_power_test_error_result"]


class _CapturedPlan(NamedTuple):
    """One query's captured plan, accumulated across isolated capture passes.

    Stored in the per-run ``_captured_plans`` accumulator keyed by capture key so a
    pre-mutation checkpoint and the final post-measurement pass can each contribute
    plans that are attached to result rows exactly once. ``plan`` is ``None`` when
    capture failed or the query was filtered out; ``capture_ms`` is recorded even
    then so plan-capture timing is reported honestly. ``normalized_fingerprint`` is
    only populated when the adapter's ``normalize_plan_literals`` option is enabled
    (see --normalize-plan-literals); otherwise it stays ``None``.
    """

    plan: Any
    fingerprint: str | None
    capture_ms: float | None
    normalized_fingerprint: str | None = None


class TestDriversMixin:
    """Mixin providing benchmark test drivers and the generic query pipeline.

    Combines the TPC-specific power/throughput/maintenance drivers with the
    generic query pipeline (`_execute_power_test`, `_execute_all_queries`,
    `_filter_queries`, etc.) that fans out to the appropriate driver based
    on benchmark family / run type.

    Expects host class to expose:
    - `get_target_dialect()` / `get_tpc_base_dialect()` (DialectTranslationMixin)
    - `execute_query()` (abstract, contract on facade)
    - `platform_name` property, `logger`, `very_verbose`
    - `_format_execution_time`, `_build_query_result_with_validation`,
      `_build_query_failure_result`, `_build_dry_run_result`
    """

    def _make_power_connection_adapter(self, connection: Any, benchmark_id: str, scale_factor: float):
        """Wrap a platform connection for core TPC power harnesses."""
        connection_adapter = PlatformAdapterConnection(_make_stream_cursor(connection), self)
        connection_adapter.benchmark_type = benchmark_id
        connection_adapter.scale_factor = scale_factor
        return connection_adapter

    def _make_direct_power_connection_adapter(self, connection: Any, benchmark_id: str, scale_factor: float):
        """Wrap a direct platform connection for single-stream core TPC power harnesses."""
        connection_adapter = PlatformAdapterConnection(connection, self)
        connection_adapter.benchmark_type = benchmark_id
        connection_adapter.scale_factor = scale_factor
        return connection_adapter

    def _execute_tpch_power_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-H Power Test using the core TPCH power harness."""
        from benchbox.core.tpch.platform_power import execute_tpch_power_test

        return execute_tpch_power_test(
            self,
            benchmark,
            connection,
            run_config,
            make_connection_adapter=self._make_direct_power_connection_adapter,
            console=quiet_console,
        )

    def _execute_generic_power_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute power test for non-TPC benchmarks with warmup + iterations.

        This method provides the same warmup + measurement iteration pattern used by
        TPC-H and TPC-DS power tests, but for generic benchmarks like ClickBench, SSB,
        H2O-DB, etc.

        Args:
            benchmark: Benchmark instance to execute
            connection: Database connection
            run_config: Runtime configuration including:
                - iterations: Number of measurement runs (default: 1)
                - warm_up_iterations: Number of warmup runs (default: 0)
                - verbose: Enable verbose logging
                - scale_factor: Benchmark scale factor

        Returns:
            List of query results from all warmup and measurement iterations, with each result
            tagged with iteration number and run_type ("warmup" or "measurement").
        """
        console = quiet_console

        # Extract configuration (same defaults as TPC-H power test)
        iterations = run_config.get("iterations", GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS)
        warm_up_iterations = run_config.get("warm_up_iterations", GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS)
        fail_fast = run_config.get("power_fail_fast", False)
        run_config.get("verbose", False)

        benchmark_name = run_config.get("benchmark_name", "")  # display-only; routing does not depend on this
        scale_factor = run_config.get("scale_factor", getattr(benchmark, "scale_factor", 1.0))

        console.print(f"[green]Running {benchmark_name} Power Test (Scale Factor: {scale_factor})[/green]")
        console.print(f"[green]Warm-up runs: {warm_up_iterations}, Measurement runs: {iterations}[/green]")

        all_measurement_results = []

        # Warm-up runs (results captured)
        for i in range(warm_up_iterations):
            console.print(f"[cyan]--- Warm-up Run {i + 1}/{warm_up_iterations} ---[/cyan]")
            warmup_results = self._execute_all_queries(benchmark, connection, run_config)
            for result in warmup_results:
                result["iteration"] = 0
                result["stream_id"] = 0
                result["run_type"] = "warmup"
                all_measurement_results.append(result)

        # Measurement runs (results collected)
        for i in range(iterations):
            console.print(f"[cyan]--- Measurement Run {i + 1}/{iterations} ---[/cyan]")
            iteration_results = self._execute_all_queries(benchmark, connection, run_config)

            # Tag each result with iteration number and run type
            for result in iteration_results:
                result["iteration"] = i + 1
                result["stream_id"] = i + 1
                result["run_type"] = "measurement"

            all_measurement_results.extend(iteration_results)

            # Abort remaining iterations if all queries failed (connection/infra issue)
            # or if fail_fast is enabled and any query failed
            successful = sum(1 for r in iteration_results if r.get("status") == "SUCCESS")
            if iteration_results and successful == 0:
                console.print("[yellow]⚠️  All queries failed - aborting remaining measurement runs[/yellow]")
                break
            if fail_fast and successful < len(iteration_results):
                console.print(
                    "[yellow]⚠️  Query failures detected (fail_fast enabled) - aborting remaining runs[/yellow]"
                )
                break

        # Display summary
        if all_measurement_results:
            total_queries = len([r for r in all_measurement_results if r.get("iteration") == 1])
            successful = len([r for r in all_measurement_results if r.get("status") == "SUCCESS"])
            total_exec = len(all_measurement_results)
            success_rate = (successful / total_exec * 100) if total_exec > 0 else 0

            console.print("[green]✅ Power Test completed[/green]")
            console.print(f"  Queries: {total_queries}, Iterations: {iterations}")
            console.print(f"  Total executions: {total_exec}, Successful: {successful}")
            console.print(f"  Success rate: {success_rate:.1f}%")

        return all_measurement_results

    def _execute_tpcds_power_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-DS Power Test using the core TPCDS power harness."""
        from benchbox.core.tpcds.platform_power import execute_tpcds_power_test

        return execute_tpcds_power_test(
            self,
            benchmark,
            connection,
            run_config,
            make_connection_adapter=self._make_power_connection_adapter,
            console=quiet_console,
        )

    def _execute_tpcds_throughput_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-DS Throughput Test using production TPCDSThroughputTest implementation."""
        from benchbox.core.expected_results.tpcds_results import set_config_validation_mode
        from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest

        console = quiet_console

        try:
            # Extract configuration
            scale_factor = run_config.get("scale_factor", 1.0)
            validation_mode = run_config.get("validation_mode")  # Universal validation mode
            num_streams = run_config.get("num_streams", 2)
            verbose = run_config.get("verbose", False)

            # Set TPC-DS validation mode from config (takes precedence over environment variable)
            set_config_validation_mode(validation_mode)

            console.print(
                f"[green]Running TPC-DS Throughput Test (Scale Factor: {scale_factor}, Streams: {num_streams})[/green]"
            )

            # Create connection factory that wraps the platform adapter connection
            def connection_factory():
                # Create thread-safe cursor for concurrent stream execution
                # See: https://duckdb.org/docs/stable/guides/python/multiple_threads
                stream_cursor = _make_stream_cursor(connection)
                conn_wrapper = PlatformAdapterConnection(stream_cursor, self)
                # Configure benchmark context for query validation
                conn_wrapper.benchmark_type = "tpcds"
                conn_wrapper.scale_factor = scale_factor
                return conn_wrapper

            # Create and configure the TPC-DS throughput test
            throughput_test = TPCDSThroughputTest(
                benchmark=benchmark,
                connection_factory=connection_factory,
                scale_factor=scale_factor,
                num_streams=num_streams,
                verbose=verbose,
                dialect=self.get_target_dialect(),
            )

            # Execute the throughput test (support overriding base seed via run_config['seed'])
            seed = run_config.get("seed")
            if seed is not None:
                from benchbox.core.tpcds.throughput_test import (
                    TPCDSThroughputTestConfig,
                )

                cfg = TPCDSThroughputTestConfig(
                    scale_factor=scale_factor,
                    num_streams=num_streams,
                    base_seed=int(seed),
                    verbose=verbose,
                )
                throughput_test_result = throughput_test.run(config=cfg)
            else:
                throughput_test_result = throughput_test.run()

            # Display results
            if self.very_verbose:
                with contextlib.suppress(Exception):
                    console.print(
                        f"[dim]Target dialect: {getattr(self, 'get_target_dialect', lambda: 'standard')()} | Detailed per-query results:[/dim]"
                    )
                for stream_result in throughput_test_result.stream_results:
                    for qr in stream_result.query_results:
                        qname = f"q{qr.get('query_id')}"
                        dur = qr.get("execution_time_seconds", 0.0)
                        status = "SUCCESS" if qr.get("success") else "FAILED"
                        rows = qr.get("result_count", 0)
                        console.print(
                            f"  • {qname} [stream {stream_result.stream_id}]: {dur:.2f}s, {status}, rows={rows}"
                        )

            self._last_throughput_test_result = throughput_test_result

            if throughput_test_result.success:
                console.print(
                    f"[green]✅ TPC-DS Throughput Test completed: Throughput@Size = {throughput_test_result.throughput_at_size:.2f}[/green]"
                )
                console.print(
                    f"  Streams executed: {throughput_test_result.streams_executed}, Successful: {throughput_test_result.streams_successful}"
                )
                console.print(f"  Total execution time: {throughput_test_result.total_time:.2f}s")

                # Show per-stream statistics
                for stream_result in throughput_test_result.stream_results:
                    success_rate = stream_result.queries_successful / max(stream_result.queries_executed, 1)
                    console.print(
                        f"  Stream {stream_result.stream_id}: {stream_result.queries_successful}/{stream_result.queries_executed} queries ({success_rate:.1%})"
                    )

            else:
                console.print("[red]❌ TPC-DS Throughput Test failed[/red]")
                for error in throughput_test_result.errors:
                    console.print(f"  Error: {error}")

            # Convert TPCDSThroughputTestResult to platform adapter format
            query_results = []
            for stream_result in throughput_test_result.stream_results:
                for query_result in stream_result.query_results:
                    platform_result = {
                        "query_id": query_result["query_id"],
                        "execution_time_seconds": query_result["execution_time_seconds"],
                        "status": "SUCCESS" if query_result["success"] else "FAILED",
                        "rows_returned": query_result.get("result_count", 0),
                        "test_type": "throughput",
                        "stream_id": stream_result.stream_id,
                    }
                    if not query_result["success"]:
                        platform_result["error"] = query_result.get("error", "Unknown error")
                    # Carry the internal _plan_capture_key (and any captured plan
                    # fields) through to the row _attach_captured_plans sees, so a
                    # combined power+throughput run matches by exact key instead of
                    # the ambiguous public-id fallback.
                    propagate_plan_capture_fields(query_result, platform_result)
                    query_results.append(platform_result)

            return query_results

        except Exception as e:
            console.print(f"[red]❌ TPC-DS Throughput Test failed: {e}[/red]")
            self._last_throughput_test_result = None
            return [
                {
                    "query_id": "throughput_test_error",
                    "execution_time_seconds": 0.0,
                    "status": "FAILED",
                    "rows_returned": 0,
                    "error": str(e),
                    "test_type": "throughput",
                }
            ]

    def _execute_tpch_throughput_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-H Throughput Test using production TPCHThroughputTest implementation."""
        from benchbox.core.tpch.throughput_test import (
            TPCHThroughputTest,
            TPCHThroughputTestConfig,
        )

        console = quiet_console

        try:
            scale_factor = run_config.get("scale_factor", 1.0)
            num_streams = run_config.get("num_streams", run_config.get("streams", 2))
            verbose = run_config.get("verbose", False)

            console.print(
                f"[green]Running TPC-H Throughput Test (Scale Factor: {scale_factor}, Streams: {num_streams})[/green]"
            )

            def connection_factory():
                # Create thread-safe cursor for concurrent stream execution
                # See: https://duckdb.org/docs/stable/guides/python/multiple_threads
                stream_cursor = _make_stream_cursor(connection)
                conn_wrapper = PlatformAdapterConnection(stream_cursor, self)
                # Configure benchmark context for query validation
                conn_wrapper.benchmark_type = "tpch"
                conn_wrapper.scale_factor = scale_factor
                return conn_wrapper

            throughput_test = TPCHThroughputTest(
                benchmark=benchmark,
                connection_factory=connection_factory,
                scale_factor=scale_factor,
                num_streams=num_streams,
                verbose=verbose,
            )

            seed = run_config.get("seed")
            if seed is not None:
                cfg = TPCHThroughputTestConfig(
                    scale_factor=scale_factor,
                    num_streams=num_streams,
                    base_seed=int(seed),
                    verbose=verbose,
                )
                throughput_test_result = throughput_test.run(config=cfg)
            else:
                throughput_test_result = throughput_test.run()

            self._last_throughput_test_result = throughput_test_result

            if throughput_test_result.success:
                console.print(
                    f"[green]✅ TPC-H Throughput Test completed: Throughput@Size = {throughput_test_result.throughput_at_size:.2f}[/green]"
                )
                console.print(
                    f"  Streams executed: {throughput_test_result.streams_executed}, Successful: {throughput_test_result.streams_successful}"
                )
                console.print(f"  Total execution time: {throughput_test_result.total_time:.2f}s")
            else:
                console.print("[red]❌ TPC-H Throughput Test failed[/red]")
                for error in throughput_test_result.errors:
                    console.print(f"  Error: {error}")

            query_results = []
            for stream_result in throughput_test_result.stream_results:
                for qr in stream_result.query_results:
                    platform_result = {
                        "query_id": qr.get("query_id"),
                        "execution_time_seconds": qr.get("execution_time_seconds", 0.0),
                        "status": "SUCCESS" if qr.get("success") else "FAILED",
                        "rows_returned": qr.get("result_count", 0),
                        "test_type": "throughput",
                        "stream_id": stream_result.stream_id,
                    }
                    if not qr.get("success"):
                        platform_result["error"] = qr.get("error", "Unknown error")
                    # Carry the internal _plan_capture_key (and any captured plan
                    # fields) through to the row _attach_captured_plans sees, so a
                    # combined power+throughput run matches by exact key instead of
                    # the ambiguous public-id fallback.
                    propagate_plan_capture_fields(qr, platform_result)
                    query_results.append(platform_result)

            return query_results

        except Exception as e:
            console.print(f"[red]❌ TPC-H Throughput Test failed: {e}[/red]")
            self._last_throughput_test_result = None
            return [
                {
                    "query_id": "throughput_test_error",
                    "execution_time_seconds": 0.0,
                    "status": "FAILED",
                    "rows_returned": 0,
                    "error": str(e),
                    "test_type": "throughput",
                }
            ]

    def _execute_tpcds_maintenance_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-DS Maintenance Test using production TPCDSMaintenanceTest implementation."""

        from benchbox.core.tpcds.maintenance_test import TPCDSMaintenanceTest

        # Maintenance mutates table cardinalities. Capture any read-phase plans
        # recorded so far (combined mode: power/throughput) against the current
        # pre-mutation data state, before this phase changes it.
        self._plan_capture_checkpoint(connection)

        console = quiet_console

        try:
            # Extract configuration
            scale_factor = run_config.get("scale_factor", 1.0)
            verbose = run_config.get("verbose", False)
            output_dir = run_config.get("output_dir", Path.cwd() / "tpcds_maintenance_test")

            console.print(f"[green]Running TPC-DS Maintenance Test (Scale Factor: {scale_factor})[/green]")

            # Create connection factory that wraps the platform adapter connection
            def connection_factory():
                # Create thread-safe cursor for concurrent stream execution
                # See: https://duckdb.org/docs/stable/guides/python/multiple_threads
                stream_cursor = _make_stream_cursor(connection)
                conn_wrapper = PlatformAdapterConnection(stream_cursor, self)
                # Configure benchmark context for query validation
                conn_wrapper.benchmark_type = "tpcds"
                conn_wrapper.scale_factor = scale_factor
                return conn_wrapper

            # Create and configure the TPC-DS maintenance test
            maintenance_test = TPCDSMaintenanceTest(
                benchmark=benchmark,
                connection_factory=connection_factory,
                scale_factor=scale_factor,
                output_dir=Path(output_dir) if isinstance(output_dir, str) else output_dir,
                verbose=verbose,
                dialect=self.get_target_dialect(),
            )

            # Execute the maintenance test
            maintenance_test_result = maintenance_test.run()

            # Display results
            if maintenance_test_result["success"]:
                console.print("[green]✅ TPC-DS Maintenance Test completed[/green]")
                console.print(f"  Insert operations: {maintenance_test_result['insert_operations']}")
                console.print(f"  Update operations: {maintenance_test_result['update_operations']}")
                console.print(f"  Delete operations: {maintenance_test_result['delete_operations']}")
                console.print(
                    f"  Total operations: {maintenance_test_result['total_operations']}, Successful: {maintenance_test_result['successful_operations']}"
                )
                console.print(f"  Total execution time: {maintenance_test_result['total_time']:.2f}s")
                console.print(f"  Throughput: {maintenance_test_result['overall_throughput']:.2f} ops/sec")

            else:
                console.print("[red]❌ TPC-DS Maintenance Test failed[/red]")
                for error in maintenance_test_result["errors"]:
                    console.print(f"  Error: {error}")

            # Convert maintenance test results to platform adapter format
            query_results = []
            for operation in maintenance_test_result["operations"]:
                platform_result = {
                    "query_id": f"{operation.operation_type.lower()}_{operation.table_name}",
                    "execution_time_seconds": operation.duration,
                    "status": "SUCCESS" if operation.success else "FAILED",
                    "rows_returned": operation.rows_affected,
                    "test_type": "maintenance",
                    "operation_type": operation.operation_type,
                    "table_name": operation.table_name,
                }
                if not operation.success:
                    platform_result["error"] = operation.error or "Unknown error"
                query_results.append(platform_result)

            return query_results

        except Exception as e:
            console.print(f"[red]❌ TPC-DS Maintenance Test failed: {e}[/red]")
            return [
                {
                    "query_id": "maintenance_test_error",
                    "execution_time_seconds": 0.0,
                    "status": "FAILED",
                    "rows_returned": 0,
                    "error": str(e),
                    "test_type": "maintenance",
                }
            ]

    def _execute_tpch_maintenance_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC-H Maintenance Test using production TPCHMaintenanceTest implementation."""

        from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

        # Maintenance mutates table cardinalities. Capture any read-phase plans
        # recorded so far (combined mode: power/throughput) against the current
        # pre-mutation data state, before this phase changes it.
        self._plan_capture_checkpoint(connection)

        console = quiet_console

        try:
            scale_factor = run_config.get("scale_factor", 1.0)
            verbose = run_config.get("verbose", False)
            maintenance_pairs = run_config.get("maintenance_pairs", 1)
            rf1_interval = run_config.get("rf1_interval", 0.0)
            rf2_interval = run_config.get("rf2_interval", 0.0)
            validate_integrity = run_config.get("validate_integrity", True)
            output_dir = run_config.get("output_dir", Path.cwd() / "tpch_maintenance_test")

            console.print(f"[green]Running TPC-H Maintenance Test (Scale Factor: {scale_factor})[/green]")

            def connection_factory():
                # Create thread-safe cursor for maintenance operations
                # See: https://duckdb.org/docs/stable/guides/python/multiple_threads
                stream_cursor = _make_stream_cursor(connection)
                # Use maintenance_mode=True to execute all queries directly on the connection
                # (RF1/RF2 operations need real data, not validation-wrapped results)
                conn_wrapper = PlatformAdapterConnection(stream_cursor, self, maintenance_mode=True)
                conn_wrapper.benchmark_type = "tpch"
                conn_wrapper.scale_factor = scale_factor
                return conn_wrapper

            maintenance_test = TPCHMaintenanceTest(
                connection_factory=connection_factory,
                scale_factor=scale_factor,
                output_dir=Path(output_dir) if isinstance(output_dir, str) else output_dir,
                verbose=verbose,
            )

            result = maintenance_test.run_maintenance_test(
                maintenance_pairs=maintenance_pairs,
                concurrent_with_queries=False,
                rf1_interval=rf1_interval,
                rf2_interval=rf2_interval,
                validate_integrity=validate_integrity,
            )

            if result.success:
                console.print("[green]✅ TPC-H Maintenance Test completed[/green]")
                console.print(
                    f"  Operations: {result.total_operations}, Successful: {result.successful_operations}, Failed: {result.failed_operations}"
                )
                console.print(
                    f"  Total time: {result.total_time:.2f}s, Overall throughput: {result.overall_throughput:.2f} ops/s"
                )
            else:
                console.print("[red]❌ TPC-H Maintenance Test failed[/red]")
                for err in result.errors:
                    console.print(f"  Error: {err}")

            # Convert to platform adapter query-like results: record operations
            query_results = []
            for op in result.operations:
                query_results.append(
                    {
                        "query_id": op.operation_type,
                        "execution_time_seconds": op.duration,
                        "status": "SUCCESS" if op.success else "FAILED",
                        "rows_returned": op.rows_affected,
                        "test_type": "maintenance",
                    }
                )

            return query_results

        except Exception as e:
            console.print(f"[red]❌ TPC-H Maintenance Test failed: {e}[/red]")
            return [
                {
                    "query_id": "maintenance_test_error",
                    "execution_time_seconds": 0.0,
                    "status": "FAILED",
                    "rows_returned": 0,
                    "error": str(e),
                    "test_type": "maintenance",
                }
            ]

    def _execute_queries_by_type(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute queries for the requested test type, with isolated plan capture.

        Plan capture is fully isolated from measured execution for EVERY test type
        (power, throughput, maintenance, combined). For phase-eligible EXPLAIN-based
        engines, inline capture is suppressed for the entire timed run — the inline
        chokepoint records each executed query instead — and all plans are captured in
        a single post-measurement pass on the same connection, strictly after the last
        timed query and never inside a concurrent stream. This is the canonical
        contract (see ``benchbox/core/plan_capture_phase.py``); engines that obtain a
        plan only as a side effect of the measured job keep inline capture.
        """
        phase_eligible = (
            bool(getattr(self, "capture_plans", False))
            and getattr(self, "plan_capture_phase_eligible", False)
            and not getattr(self, "dry_run_mode", False)
        )
        if not phase_eligible:
            return self._dispatch_queries_by_type(benchmark, connection, run_config)

        # Isolate capture: record executed queries during the timed run, capture after.
        # ``_captured_plans`` is the per-run accumulator keyed by capture key; it lets
        # capture happen in more than one isolated pass (a pre-mutation checkpoint plus
        # the final pass) while plans are attached to result rows exactly once at the
        # end. Reset here so a reused adapter never carries plans across runs.
        self._plan_capture_phase_active = True
        self._phase_recorded_queries = {}
        self._captured_plans = {}
        try:
            results = self._dispatch_queries_by_type(benchmark, connection, run_config)
        finally:
            self._plan_capture_phase_active = False

        self._capture_plans_post_measurement(connection, dict(self._phase_recorded_queries), results)
        return results

    def _dispatch_queries_by_type(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Route to the per-test-type driver (no plan-capture concerns)."""
        test_execution_type = run_config.get("test_execution_type", "standard")

        if test_execution_type == "power":
            return self._ensure_query_results_run_type(self._execute_power_test(benchmark, connection, run_config))
        elif test_execution_type == "throughput":
            return self._ensure_query_results_run_type(self._execute_throughput_test(benchmark, connection, run_config))
        elif test_execution_type == "maintenance":
            return self._ensure_query_results_run_type(
                self._execute_maintenance_test(benchmark, connection, run_config)
            )
        elif test_execution_type == "combined":
            return self._ensure_query_results_run_type(self._execute_combined_test(benchmark, connection, run_config))
        else:
            # Standard execution
            return self._ensure_query_results_run_type(self._execute_all_queries(benchmark, connection, run_config))

    @staticmethod
    def _infer_query_result_run_type(result: dict[str, Any]) -> str:
        """Infer run_type for compatibility when producer output is incomplete."""
        explicit_run_type = result.get("run_type")
        if explicit_run_type:
            return str(explicit_run_type)

        if result.get("is_warmup"):
            return QUERY_RUN_TYPE_WARMUP

        iteration = result.get("iteration")
        if iteration is not None:
            with contextlib.suppress(TypeError, ValueError):
                if int(iteration) == 0:
                    return QUERY_RUN_TYPE_WARMUP

        return QUERY_RUN_TYPE_MEASUREMENT

    @staticmethod
    def _ensure_query_results_run_type(query_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ensure all query result rows include explicit run_type."""
        for result in query_results:
            if isinstance(result, dict) and ("run_type" not in result or not result.get("run_type")):
                result["run_type"] = TestDriversMixin._infer_query_result_run_type(result)
        return query_results

    @staticmethod
    def _resolve_benchmark_slug(benchmark, run_config: dict) -> str:
        """Return the canonical benchmark slug for routing decisions.

        Reads ``run_config["benchmark_name"]``, which the runner always populates
        from ``BenchmarkConfig.name``.  Returns ``""`` when absent (e.g. callers
        that bypass the runner must supply it explicitly).

        All routing methods (_execute_power/throughput/maintenance/combined_test)
        use this helper so the lookup is defined in exactly one place.
        """
        return run_config.get("benchmark_name") or ""

    def _execute_power_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute Power Test with warmup + iterations for all benchmarks.

        Routes TPC benchmarks to specialized implementations and other benchmarks
        to the generic power test handler that supports the same warmup + iteration
        pattern.
        """
        benchmark_name = self._resolve_benchmark_slug(benchmark, run_config)
        benchmark_id = normalize_benchmark_id(benchmark_name)

        harness = resolve_power_harness(benchmark_id)
        if harness is not None:
            return getattr(self, harness.adapter_method)(benchmark, connection, run_config)
        return self._execute_generic_power_test(benchmark, connection, run_config)

    def _execute_throughput_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC Throughput Test with concurrent query streams.

        Fallback path: when the benchmark has no specialized throughput
        implementation, falls back to ``_execute_all_queries`` and sets
        ``run_config["_effective_execution_type"] = "power"`` so that
        downstream consumers (``_build_execution_phases``, final result
        assembly) emit a ``power_test`` phase rather than an empty
        ``throughput_test`` phase.  The same convention applies in
        ``_execute_maintenance_test`` and ``_execute_combined_test``.
        """
        console = quiet_console

        benchmark_name = self._resolve_benchmark_slug(benchmark, run_config)
        benchmark_id = normalize_benchmark_id(benchmark_name)

        harness = resolve_throughput_harness(benchmark_id)
        if harness is not None:
            return getattr(self, harness.adapter_method)(benchmark, connection, run_config)
        console.print(f"[yellow]⚠️ Throughput test not supported for benchmark: {benchmark_name}[/yellow]")
        console.print("[yellow]  Falling back to standard query execution[/yellow]")
        run_config["_effective_execution_type"] = "power"
        return self._execute_all_queries(benchmark, connection, run_config)

    def _execute_maintenance_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute TPC Maintenance Test with data maintenance operations."""
        console = quiet_console

        benchmark_name = self._resolve_benchmark_slug(benchmark, run_config)
        benchmark_id = normalize_benchmark_id(benchmark_name)

        harness = resolve_maintenance_harness(benchmark_id)
        if harness is not None:
            return getattr(self, harness.adapter_method)(benchmark, connection, run_config)
        console.print(f"[yellow]⚠️ Maintenance test not supported for benchmark: {benchmark_name}[/yellow]")
        console.print("[yellow]  Falling back to standard query execution[/yellow]")
        run_config["_effective_execution_type"] = "power"
        return self._execute_all_queries(benchmark, connection, run_config)

    def _execute_combined_test(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute requested combined TPC phases.

        Defaults to all query phases (power, throughput, maintenance) when no
        explicit phase list is provided.
        """
        console = quiet_console
        requested_phases = set((run_config.get("options") or {}).get("requested_phases") or [])
        if not requested_phases:
            requested_phases = {"power", "throughput", "maintenance"}

        benchmark_name = self._resolve_benchmark_slug(benchmark, run_config)
        benchmark_id = normalize_benchmark_id(benchmark_name)

        combined = resolve_combined_harness(benchmark_id)
        if combined is None:
            console.print(f"[yellow]⚠️ Combined test not supported for benchmark: {benchmark_name}[/yellow]")
            console.print("[yellow]  Falling back to standard query execution[/yellow]")
            run_config["_effective_execution_type"] = "power"
            return self._execute_all_queries(benchmark, connection, run_config)

        console.print(f"[blue]Running combined {combined.label} test[/blue]")

        # Execute each requested phase in order (power -> throughput -> maintenance).
        all_results: list[dict[str, Any]] = []
        phases = (
            ("power", "Power Test", combined.power_method),
            ("throughput", "Throughput Test", combined.throughput_method),
            ("maintenance", "Maintenance Test", combined.maintenance_method),
        )
        for phase_key, phase_label, method_name in phases:
            if phase_key in requested_phases:
                console.print(f"[cyan]Phase: {phase_label}[/cyan]")
                all_results.extend(getattr(self, method_name)(benchmark, connection, run_config))
        return all_results

    def _get_runtime_platform_version(self, connection: Any | None) -> str | None:
        """Return the current platform version for version-gated compat rules."""
        if connection is None:
            return None
        try:
            platform_info = self.get_platform_info(connection)
        except Exception:
            return None

        version = platform_info.get("platform_version")
        if version in (None, "", "unknown"):
            return None
        return str(version)

    def _get_dialect_queries(self, benchmark, benchmark_slug: str, connection: Any | None = None) -> dict:
        """Get queries with platform-specific dialect translation if supported.

        Args:
            benchmark_slug: Canonical benchmark slug (e.g. "tpch") from run_config.
                When supplied, used to determine the TPC family for base-dialect
                selection instead of inspecting benchmark object internals.
        """
        if hasattr(self, "get_target_dialect") and hasattr(benchmark, "get_queries"):
            try:
                import inspect

                sig = inspect.signature(benchmark.get_queries)
                params = sig.parameters
                target = self.get_target_dialect()

                bench_family_id = normalize_benchmark_id(benchmark_slug) if benchmark_slug else "generic"
                bench_family = benchmark_family(bench_family_id)
                base = self.get_tpc_base_dialect(bench_family)
                platform_version = self._get_runtime_platform_version(connection)

                if "dialect" in params and "base_dialect" in params:
                    query_kwargs: dict[str, Any] = {"dialect": target, "base_dialect": base}
                    if "platform_version" in params:
                        query_kwargs["platform_version"] = platform_version
                    return benchmark.get_queries(**query_kwargs)
                elif "dialect" in params:
                    query_kwargs = {"dialect": target}
                    if "platform_version" in params:
                        query_kwargs["platform_version"] = platform_version
                    return benchmark.get_queries(**query_kwargs)
                else:
                    return benchmark.get_queries()
            except SQLTranslationError:
                raise
            except Exception:
                return benchmark.get_queries()
        return benchmark.get_queries()

    def _filter_queries(self, queries: dict, benchmark, benchmark_name: str, run_config: dict) -> dict:
        """Filter queries by subset or category from run_config."""
        query_subset = run_config.get("query_subset")
        categories = run_config.get("categories")

        if query_subset and categories:
            raise ValueError(
                "Cannot specify both 'query_subset' and 'categories'. "
                "Use query_subset to select specific queries by ID, or categories to select by category, but not both."
            )

        try:
            if query_subset:
                queries = self._apply_query_subset(queries, query_subset, benchmark_name)
            elif categories:
                filtered_queries = {}
                for category in categories:
                    if hasattr(benchmark, "get_queries_by_category"):
                        cat_queries = benchmark.get_queries_by_category(category)
                        filtered_queries.update(cat_queries)
                queries = filtered_queries
        except ValueError as e:
            raise RuntimeError(f"Query filtering failed: {e}") from e

        # Apply platform-specific skip list when the benchmark provides one.
        # Skipped queries are excluded silently (not counted as failures).
        if hasattr(benchmark, "get_platform_skip_queries"):
            platform_skip = {str(s).strip().lower() for s in benchmark.get_platform_skip_queries(self.platform_name)}
            if platform_skip:
                queries = {qid: sql for qid, sql in queries.items() if str(qid).strip().lower() not in platform_skip}

        return queries

    def _apply_query_subset(self, queries: dict, query_subset: list, benchmark_name: str) -> dict:
        """Validate and apply query subset filtering while preserving user-specified order.

        Accepts both bare ("37") and Q-prefixed ("Q37") IDs transparently. The interactive
        wizard collects Q-prefixed IDs while the non-interactive CLI and benchmark query
        dicts (e.g. TPC-H/TPC-DS) key by bare integers, so we resolve each input against
        all candidate forms before treating it as invalid.
        """

        def _resolve(qid: object) -> object | None:
            """Return the actual key used in `queries` for this user input, or None."""
            if qid in queries:
                return qid
            qid_str = str(qid)
            if qid_str in queries:
                return qid_str
            # Try stripping a leading Q/q from a numeric-suffix id (e.g. "Q37" -> "37")
            if len(qid_str) > 1 and qid_str[0] in ("Q", "q") and qid_str[1:].isdigit():
                stripped = qid_str[1:]
                if stripped in queries:
                    return stripped
            return None

        invalid_queries: list[str] = []
        resolved: list[object] = []
        for i, query_id in enumerate(query_subset):
            actual_key = _resolve(query_id)
            if actual_key is None:
                invalid_queries.append(str(query_id))
            else:
                resolved.append(actual_key)
            if len(invalid_queries) >= 10:
                remaining = len(query_subset) - i - 1
                if remaining > 0:
                    invalid_queries.append(f"...and {remaining} more")
                break

        if invalid_queries:
            available_queries = sorted(str(k) for k in queries.keys())
            if len(available_queries) > 20:
                available_display = ", ".join(available_queries[:20]) + ", ..."
            else:
                available_display = ", ".join(available_queries)
            raise ValueError(
                f"Invalid query IDs specified: {', '.join(invalid_queries)}. "
                f"Available queries for {benchmark_name}: {available_display}"
            )

        ordered_queries = {}
        for actual_key in resolved:
            ordered_queries[actual_key] = queries[actual_key]
        return ordered_queries

    def _execute_single_query(
        self,
        benchmark,
        connection: Any,
        query_id: str,
        query_sql: str,
        benchmark_type: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single query or operation and return the result dict.

        Args:
            benchmark_type: Explicit canonical slug (e.g. "tpch") sourced from
                run_config["benchmark_name"].  When supplied the adapter does not
                need to infer the type from benchmark object internals.
        """
        if isinstance(benchmark, OperationExecutor):
            return self._execute_operation_query(benchmark, connection, query_id)

        scale_factor = getattr(benchmark, "scale_factor", None)
        return self.execute_query(
            connection,
            query_sql,
            query_id,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=self.enable_validation,
        )

    def _execute_operation_query(self, benchmark, connection: Any, query_id: str) -> dict[str, Any]:
        """Execute a benchmark operation (INSERT/UPDATE/DELETE) and return result dict."""
        op_kwargs: dict[str, Any] = {}
        op_kwargs["platform_key"] = self.get_target_dialect()
        op_kwargs["platform_name"] = self.platform_name

        # Adapter SQL preprocessing (e.g. bulk-load rewrites) is threaded through as
        # sql_override so execute_operation runs the rewritten statement.
        operation = None
        if hasattr(self, "preprocess_operation_sql") and hasattr(benchmark, "get_operation"):
            with contextlib.suppress(Exception):
                operation = benchmark.get_operation(str(query_id))
        if operation is not None:
            preprocessed = self.preprocess_operation_sql(str(query_id), operation)
            if preprocessed is not None:
                op_kwargs["sql_override"] = preprocessed

        op_result = benchmark.execute_operation(query_id, connection, **op_kwargs)
        op_status = getattr(op_result, "status", None) or ("SUCCESS" if op_result.success else "FAILED")

        # Record the SQL the operation ACTUALLY executed for deferred plan capture, so
        # write/transaction primitives get structural plans under --capture-plans.
        # execute_operation exposes the final statement (after platform overrides,
        # dialect rewrites, and placeholder replacement) as ``executed_sql``; we never
        # fall back to the catalog-default ``operation.write_sql``, which can differ
        # from what ran (e.g. ON CONFLICT -> INSERT OR IGNORE on sqlite/duckdb) and
        # would make the post-measurement phase EXPLAIN a wrong/dialect-incompatible
        # statement. Operations bypass execute_query()/_merge_plan_capture_into_result(),
        # so this mirrors that chokepoint's phase-recording (SUCCESS only, under the
        # shared lock since throughput streams run concurrently).
        phase_active = getattr(self, "_plan_capture_phase_active", False)
        executed_sql = getattr(op_result, "executed_sql", None)
        plan_capture_key = None
        if phase_active and op_status == "SUCCESS" and executed_sql:
            from benchbox.platforms.base.result_capture import _plan_capture_key

            plan_capture_key = _plan_capture_key(query_id, executed_sql)
            with self._plan_capture_lock:
                self._phase_recorded_queries.setdefault(plan_capture_key, executed_sql)

        result: dict[str, Any] = {
            "query_id": str(query_id),
            "status": op_status,
            "execution_time_seconds": op_result.write_duration_ms / 1000.0,
            "rows_returned": op_result.rows_affected if op_result.rows_affected > 0 else 0,
            "error": op_result.error,
            "validation_time": op_result.validation_duration_ms / 1000.0,
            "validation_passed": op_result.validation_passed,
            "cleanup_time": op_result.cleanup_duration_ms / 1000.0,
        }
        if plan_capture_key is not None:
            result["_plan_capture_key"] = plan_capture_key
        if op_result.skip_reason:
            result["skip_reason"] = op_result.skip_reason
        return result

    def _log_query_result(self, result: dict[str, Any], index: int, total: int, query_id: str) -> None:
        """Log the result of a single query execution to console."""
        console = quiet_console
        status = result.get("status", "SUCCESS")

        if status == "FAILED":
            error_msg = result.get("error", "Unknown error")
            error_preview = error_msg[:80] + "..." if len(error_msg) > 80 else error_msg
            console.print(f"[red]❌ Query {index}/{total}: {query_id} FAILED - {error_preview}[/red]")
        elif status == "SKIPPED":
            skip_reason = result.get("skip_reason") or result.get("error") or "Operation not supported on this platform"
            reason_preview = skip_reason[:80] + "..." if len(skip_reason) > 80 else skip_reason
            console.print(f"[yellow]⏭️ Query {index}/{total}: {query_id} SKIPPED - {reason_preview}[/yellow]")
        else:
            execution_time = result.get("execution_time_seconds", 0)
            rows_returned = result.get("rows_returned", 0)
            time_display = self._format_execution_time(execution_time)
            validation_status = result.get("row_count_validation_status")

            if validation_status == "PASSED":
                console.print(
                    f"[green]✅ Query {index}/{total}: {query_id} completed in {time_display} ({rows_returned:,} rows) [validation: PASSED][/green]"
                )
            elif validation_status == "SKIPPED":
                console.print(
                    f"[green]✅ Query {index}/{total}: {query_id} completed in {time_display} ({rows_returned:,} rows) [validation: SKIPPED][/green]"
                )
            else:
                console.print(
                    f"[green]✅ Query {index}/{total}: {query_id} completed in {time_display} ({rows_returned:,} rows)[/green]"
                )

    def _log_execution_summary(self, results: list[dict[str, Any]], total_queries: int, cancelled: bool) -> None:
        """Log the final execution summary to console."""
        console = quiet_console
        if cancelled:
            console.print(f"[yellow]Benchmark cancelled. Processed {len(results)}/{total_queries} queries.[/yellow]")
            return

        successful = len([r for r in results if r.get("status") == "SUCCESS"])
        skipped = len([r for r in results if r.get("status") == "SKIPPED"])
        failed = len([r for r in results if r.get("status") == "FAILED"])
        if failed > 0:
            console.print(
                f"[yellow]Completed {total_queries} queries: {successful} passed, {skipped} skipped, {failed} failed.[/yellow]"
            )
        elif skipped > 0:
            console.print(f"[green]Completed {total_queries} queries: {successful} passed, {skipped} skipped.[/green]")
        else:
            console.print(f"[green]Completed all {total_queries} queries.[/green]")

    def _execute_all_queries(self, benchmark, connection: Any, run_config: dict) -> list[dict[str, Any]]:
        """Execute all benchmark queries and collect results."""

        console = quiet_console

        queries = self._get_dialect_queries(
            benchmark,
            benchmark_slug=run_config.get("benchmark_name", ""),
            connection=connection,
        )
        benchmark_name = run_config.get("benchmark_name", "")
        queries = self._filter_queries(queries, benchmark, benchmark_name, run_config)

        results = []
        total_queries = len(queries)

        # Set up cancellation handler
        cancelled = False

        def signal_handler(sig, frame):
            nonlocal cancelled
            cancelled = True
            console.print("\n[yellow]⚠️️  Cancellation requested. Will stop after current query completes.[/yellow]")
            console.print("[yellow]   Partial results will be saved.[/yellow]")

        # Register signal handlers for graceful cancellation
        original_sigint = signal.signal(signal.SIGINT, signal_handler)
        original_sigterm = None
        if hasattr(signal, "SIGTERM"):
            original_sigterm = signal.signal(signal.SIGTERM, signal_handler)

        # Plan capture isolation is handled centrally by _execute_queries_by_type
        # (it records executed queries during the timed loop and runs a single
        # post-measurement capture phase for every test type). This loop only
        # executes the timed queries; for phase-eligible engines the inline capture
        # chokepoint records instead of running EXPLAIN, so nothing extra is needed
        # here.
        try:
            console.print(
                f"[cyan]Running {total_queries} {benchmark_name} queries. Press Ctrl+C to cancel (will stop after current query).[/cyan]"
            )

            for i, (query_id, query_sql) in enumerate(queries.items(), 1):
                if cancelled:
                    break

                console.print(f"[blue]Executing query {i}/{total_queries}: {query_id}[/blue]")

                try:
                    result = self._execute_single_query(
                        benchmark,
                        connection,
                        query_id,
                        query_sql,
                        benchmark_type=benchmark_name or None,
                    )

                    if "run_type" not in result or not result.get("run_type"):
                        result["run_type"] = QUERY_RUN_TYPE_MEASUREMENT

                    results.append(result)
                    self._log_query_result(result, i, total_queries, query_id)

                except PlanCaptureError:
                    # Strict plan capture failure should halt the benchmark execution
                    raise
                except Exception as e:
                    error_result = {
                        "query_id": str(query_id),
                        "status": "FAILED",
                        "execution_time_seconds": 0.0,
                        "rows_returned": 0,
                        "error": str(e),
                        "run_type": QUERY_RUN_TYPE_MEASUREMENT,
                    }
                    results.append(error_result)
                    console.print(f"[red]❌ Query {i}/{total_queries}: {query_id} failed - {str(e)[:100]}[/red]")

        finally:
            # Restore original signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            if hasattr(signal, "SIGTERM") and original_sigterm is not None:
                signal.signal(signal.SIGTERM, original_sigterm)

        self._log_execution_summary(results, total_queries, cancelled)

        return results

    def _capture_plans_post_measurement(
        self,
        connection: Any,
        queries: dict[str, str],
        results: list[dict[str, Any]],
    ) -> None:
        """Capture query plans in an isolated pass after the timed run.

        Driven by ``_execute_queries_by_type`` for EVERY test type (power,
        throughput, maintenance, combined): ``queries`` is the set of distinct
        executed queries recorded by the inline chokepoint during the timed run
        (``_phase_recorded_queries``), so the capture covers exactly what ran and
        fires once per distinct query — never inside a concurrent stream.

        Runs ``run_plan_capture_phase`` for the successfully-executed queries on
        the *measurement* connection, strictly after all timed queries have run,
        then merges ``query_plan`` / ``plan_fingerprint`` / ``plan_capture_time_ms``
        into every result row sharing that ``query_id`` (a throughput run has one
        row per stream for the same query).

        The measurement connection is reused (rather than a fresh one) so embedded
        in-memory engines still see the loaded data; isolation comes from running
        post-measurement, not from a separate connection.

        The phase honours the adapter's ``analyze_plans`` (the canonical, and only,
        capture knob): with ``analyze_plans=True`` (the default) each SELECT is
        re-run once with EXPLAIN ANALYZE for full execution detail — strictly after
        the timed loop, so measured timing is unaffected — while DML/write-DDL is
        downgraded to a non-ANALYZE EXPLAIN by the ``is_dml_query`` guard in
        ``get_query_plan`` and is therefore never re-executed. With
        ``analyze_plans=False`` the phase captures the static (structural) plan
        only. Previously the phase hard-coded structural-only and silently dropped
        ANALYZE timing for ``--capture-plans``; honouring ``analyze_plans`` restores
        the one knob the canonical contract defines.

        The ``plan_query_filter`` query-selection set (``--plan-queries``) is still
        honoured; the per-iteration / per-stream sampling machinery
        (``plan_first_n`` / ``plan_sampling_rate``) has been retired.

        Capture and attachment are split: :meth:`_capture_recorded_plans` runs the
        isolated EXPLAIN pass and accumulates plans by capture key, while
        :meth:`_attach_captured_plans` merges them into the result rows. This lets a
        workload that mutates data mid-run capture its read-phase plans earlier, at a
        pre-mutation checkpoint (:meth:`_plan_capture_checkpoint`), so a captured plan
        always reflects the data state its query was measured against rather than the
        post-mutation end state — while still attaching every plan exactly once here.

        ``results`` is accepted for backward compatibility but capture is driven by
        ``queries`` (the recorded-query buffer), which is already SUCCESS-only.
        """
        self._capture_recorded_plans(connection, queries)
        self._attach_captured_plans(results)

    def _capture_recorded_plans(self, connection: Any, queries: dict[str, str]) -> None:
        """Run the isolated EXPLAIN pass for not-yet-captured recorded queries.

        ``queries`` is the recorded-query buffer (``_phase_recorded_queries``),
        keyed by capture key (``<public_id>#<sql_digest>``) and populated only for
        queries that SUCCEEDED during the timed run. Capture is buffer-driven rather
        than results-driven because the TPC power/throughput drivers rebuild their
        result rows and drop the internal capture key — so a results-driven selection
        would silently capture nothing for them. Each not-yet-captured key is
        EXPLAINed exactly once and stored in the per-run ``_captured_plans``
        accumulator; a key captured by an earlier pass (a pre-mutation checkpoint) is
        skipped, so its plan reflects the data state present at its FIRST capture.
        """
        from benchbox.core.plan_capture_phase import run_plan_capture_phase

        captured = self._ensure_plan_capture_accumulator()
        pending = {key: sql for key, sql in queries.items() if key not in captured}
        if not pending:
            return

        phase = run_plan_capture_phase(
            self,
            pending,
            connection=connection,
            analyze_plans=getattr(self, "analyze_plans", True),
        )

        for capture_key in pending:
            captured[capture_key] = _CapturedPlan(
                plan=phase.plans.get(capture_key),
                fingerprint=phase.fingerprints.get(capture_key),
                capture_ms=phase.per_query_capture_ms.get(capture_key),
                normalized_fingerprint=phase.normalized_fingerprints.get(capture_key),
            )

    def _attach_captured_plans(self, results: list[dict[str, Any]]) -> None:
        """Merge accumulated captured plans into result rows.

        Per-row SUCCESS guard mirrors the inline capture chokepoint: a captured plan
        is attached only to rows whose own status succeeded; a failed row sharing a
        query_id must never be annotated as plan-captured (it would skew downstream
        plan stats). The internal ``_plan_capture_key`` is popped from every row.

        A row is matched to its captured plan by exact capture key when it carries
        one (the standard ``_execute_all_queries`` path), else by its public
        query_id — the TPC power/throughput drivers rebuild result rows without the
        capture key, leaving only the bare id. The public-id fallback attaches a plan
        only when that id maps to a single captured variant; a query_id that ran as
        multiple distinct SQL variants (e.g. seed-varied throughput streams) is left
        unattached rather than risk pairing a row with another variant's plan.
        """
        from benchbox.platforms.base.result_capture import _plan_capture_public_id

        captured = self._ensure_plan_capture_accumulator()

        # Public-id -> the single captured variant for that id, or None when the id
        # ran as several distinct variants (ambiguous: do not guess which row ran which).
        by_public_id: dict[str, _CapturedPlan | None] = {}
        for capture_key, entry in captured.items():
            public_id = _plan_capture_public_id(capture_key)
            by_public_id[public_id] = None if public_id in by_public_id else entry

        for result in results:
            if result.get("status") != "SUCCESS":
                result.pop("_plan_capture_key", None)
                continue
            query_id = str(result.get("query_id"))
            row_key = result.pop("_plan_capture_key", None)
            entry = captured.get(str(row_key)) if row_key else by_public_id.get(query_id)
            if entry is None:
                continue
            if entry.plan is not None:
                entry.plan.query_id = query_id
                result["query_plan"] = entry.plan
                result["plan_fingerprint"] = entry.fingerprint
                if entry.normalized_fingerprint is not None:
                    result["plan_fingerprint_normalized"] = entry.normalized_fingerprint
            if entry.capture_ms is not None:
                result["plan_capture_time_ms"] = entry.capture_ms

    def _ensure_plan_capture_accumulator(self) -> dict[str, _CapturedPlan]:
        """Return the per-run captured-plan accumulator, creating it if absent.

        ``_execute_queries_by_type`` resets this at the start of every run; the lazy
        fallback here keeps direct callers of ``_capture_plans_post_measurement``
        (tests, bespoke pipelines) working without going through that wrapper.
        """
        captured = getattr(self, "_captured_plans", None)
        if captured is None:
            captured = {}
            self._captured_plans = captured
        return captured

    def _plan_capture_checkpoint(self, connection: Any) -> None:
        """Capture recorded plans now, before a subsequent data-mutating phase.

        No-op unless the isolated capture phase is active (so it never fires for
        non-eligible adapters or read-only inline capture). Captures the read-phase
        plans recorded so far against the current pre-mutation data state so they are
        not later EXPLAINed against post-mutation cardinalities (the combined-mode
        divergence). Attachment still happens once, in the final post-measurement
        pass; this only fixes *when* each read plan is captured.
        """
        if not getattr(self, "_plan_capture_phase_active", False):
            return
        self._capture_recorded_plans(connection, dict(self._phase_recorded_queries))

    # -------------------------------------------------------------------------
    # Dry-run and SQL capture helpers (extracted w9)
    # -------------------------------------------------------------------------

    def enable_dry_run(self) -> None:
        """Enable dry-run mode for SQL capture without execution."""
        self.dry_run_mode = True
        self.captured_sql = []
        self.query_counter = 0
        self.logger.info("Dry-run mode enabled - SQL will be captured instead of executed")

    def disable_dry_run(self) -> None:
        """Disable dry-run mode and return to normal execution."""
        self.dry_run_mode = False
        self.logger.info("Dry-run mode disabled - returning to normal execution")

    def capture_sql(self, sql: str, operation_type: str = "query", table_name: str | None = None) -> None:
        """Capture SQL statement for dry-run mode.

        Args:
            sql: The SQL statement to capture
            operation_type: Type of operation (query, ddl, dml, etc.)
            table_name: Associated table name if applicable
        """
        if not self.dry_run_mode:
            return

        self.query_counter += 1
        entry = {
            "order": self.query_counter,
            "sql": sql,
            "operation_type": operation_type,
            "table_name": table_name,
            "timestamp": datetime.now().isoformat(),
        }
        self.captured_sql.append(entry)

        truncated_sql = sql if len(sql) <= 100 else f"{sql[:100]}..."
        self.logger.debug("Captured SQL (%s): %s", operation_type, truncated_sql)

    def get_captured_sql(self) -> dict[str, str]:
        """Return captured SQL statements as dictionary for dry-run display.

        Returns:
            Dictionary of query_id -> SQL statements
        """
        return {str(entry["order"]): entry["sql"] for entry in self.captured_sql}

    def run_power_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC power test measuring single-stream query performance.

        The power test executes queries sequentially in a single stream to measure
        the database's ability to process complex analytical queries efficiently.
        This test focuses on query optimization and execution performance.

        Args:
            benchmark: Benchmark instance with queries and data
            **kwargs: Configuration options for the power test including:
                - query_timeout: Maximum time per query (default: platform-specific)
                - query_subset: List of specific queries to run (default: all)
                - validation: Whether to validate query results (default: True)

        Returns:
            Dictionary containing power test results with keys:
                - test_type: "power"
                - total_execution_time: Total time for all queries in seconds
                - query_count: Number of queries executed
                - successful_queries: Number of successful query executions
                - failed_queries: Number of failed query executions
                - query_results: List of individual query execution results
                - geometric_mean: Geometric mean of query execution times
                - validation_status: Overall validation result status
        """
        self.log_operation_start("Power test execution", f"benchmark: {benchmark.__class__.__name__}")

        # Check if benchmark has its own run_power_test method (TPC benchmarks)
        if hasattr(benchmark, "run_power_test") and callable(benchmark.run_power_test):
            # TPC benchmarks expect connection as first positional argument
            connection = kwargs.pop("connection", None)
            if connection is None:
                raise ValueError("TPC benchmarks require a connection object for power tests")

            # Inject platform's target dialect if not already specified
            if "dialect" not in kwargs:
                kwargs["dialect"] = self.get_target_dialect()

            return benchmark.run_power_test(connection, **kwargs)
        else:
            # Use the base class run_benchmark method for other benchmarks
            return self.run_benchmark(benchmark, **kwargs).__dict__

    def run_throughput_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC throughput test measuring concurrent multi-stream performance.

        The throughput test executes multiple concurrent query streams to measure
        the database's ability to handle concurrent analytical workloads.
        This test focuses on scalability and concurrent query processing.

        Args:
            benchmark: Benchmark instance with queries and data
            **kwargs: Configuration options for the throughput test including:
                - stream_count: Number of concurrent query streams (default: platform-specific)
                - query_timeout: Maximum time per query (default: platform-specific)
                - warmup_runs: Number of warmup iterations per stream (default: 1)
                - measurement_runs: Number of measurement iterations (default: 1)
                - validation: Whether to validate query results (default: True)

        Returns:
            Dictionary containing throughput test results with keys:
                - test_type: "throughput"
                - stream_count: Number of concurrent streams used
                - total_execution_time: Total wall-clock time in seconds
                - aggregate_query_time: Sum of all query execution times
                - queries_per_hour: Throughput metric (queries/hour)
                - stream_results: List of individual stream execution results
                - validation_status: Overall validation result status
        """
        # Check if benchmark has its own run_throughput_test method (TPC benchmarks)
        if hasattr(benchmark, "run_throughput_test") and callable(benchmark.run_throughput_test):
            # TPC benchmarks may expect different calling conventions
            connection = kwargs.pop("connection", None)
            if connection is None:
                raise ValueError("TPC benchmarks require a connection object for throughput tests")

            # TPC-DS uses connection_factory pattern
            # Create thread-safe cursor for concurrent stream execution
            # See: https://duckdb.org/docs/stable/guides/python/multiple_threads
            def _default_connection_factory():
                return _make_stream_cursor(connection)

            connection_factory = kwargs.pop("connection_factory", _default_connection_factory)

            # Inject platform's target dialect if not already specified
            if "dialect" not in kwargs:
                kwargs["dialect"] = self.get_target_dialect()

            return benchmark.run_throughput_test(connection_factory=connection_factory, **kwargs).__dict__
        else:
            # For now, run as single stream - could be extended for multi-stream
            # Don't pop connection since run_power_test may need it
            return self.run_power_test(benchmark, **kwargs)

    def run_maintenance_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC maintenance test measuring data modification performance.

        The maintenance test executes data modification operations (INSERT, UPDATE, DELETE)
        to measure the database's ability to handle data maintenance workloads while
        concurrent query streams are running.

        Args:
            benchmark: Benchmark instance with maintenance functions and data
            **kwargs: Configuration options for the maintenance test including:
                - maintenance_operations: List of operations to perform (default: all)
                - concurrent_streams: Number of concurrent query streams (default: 1)
                - batch_size: Size of maintenance operation batches (default: platform-specific)
                - validation: Whether to validate results (default: True)

        Returns:
            Dictionary containing maintenance test results with keys:
                - test_type: "maintenance"
                - operations_executed: Number of maintenance operations performed
                - total_execution_time: Total time for all operations in seconds
                - operation_results: List of individual operation execution results
                - concurrent_query_impact: Impact on concurrent query performance
                - data_integrity_status: Data consistency validation results
                - validation_status: Overall validation result status
        """
        # Use the base class run_benchmark method
        return self.run_benchmark(benchmark, **kwargs).__dict__
