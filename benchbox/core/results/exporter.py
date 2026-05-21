"""Result exporter for BenchBox schema v2.0.

Provides JSON/CSV/HTML export of benchmark results with optional anonymization,
and utilities to list, load, compare results. This module is UI-agnostic and can
be used by both CLI and non-CLI runners.

Schema v2.0 Companion Files:

- Primary: ``{run_id}.json`` - Main result with queries, timing, summary
- Plans: ``{run_id}.plans.json`` - Query plans (if captured)
- Tuning: ``{run_id}.tuning.json`` - Tuning clauses applied (if any)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from rich.console import Console

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.utils.cloud_storage import DatabricksPath

PathLike = Union[Path, "CloudPath", "DatabricksPath"]

from benchbox.core.results.anonymization import (
    AnonymizationConfig,
    AnonymizationManager,
)
from benchbox.core.results.canonical_json import canonical_json_text
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.normalizer import get_query_map, normalize_result_dict
from benchbox.core.results.schema import (
    SchemaV2ValidationError,
    SchemaV2Validator,
    build_plans_payload,
    build_result_payload,
    build_tuning_payload,
)
from benchbox.core.runtime_paths import resolve_results_dir
from benchbox.utils.cloud_storage import create_path_handler, is_cloud_path

logger = logging.getLogger(__name__)

SIGNIFICANT_IMPROVEMENT_ASSESSMENT = "significant_improvement"

ResultLike = BenchmarkResults
QueryResultLike = "QueryResult | dict[str, Any]"


class ResultExporter:
    """Export benchmark results with detailed metadata and anonymization.

    Schema v2.0 exports:

    - Primary result file: Contains run, benchmark, platform, summary, queries
    - Companion files (optional): ``.plans.json`` for query plans, ``.tuning.json`` for tuning config
    """

    EXPORTER_NAME = "benchbox-exporter"

    def __init__(
        self,
        output_dir: str | Path | None = None,
        anonymize: bool = True,
        anonymization_config: AnonymizationConfig | None = None,
        console: Console | None = None,
    ):
        """Initialize the result exporter.

        Args:
            output_dir: Output directory for results. Defaults to benchmark_runs/results.
            anonymize: Whether to anonymize system information. Defaults to True.
            anonymization_config: Configuration for anonymization.
            console: Rich console for output. Creates new one if not provided.
        """
        if output_dir is None:
            self.output_dir = resolve_results_dir(env=os.environ)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.is_cloud_output = False
        else:
            if is_cloud_path(str(output_dir)):
                self.output_dir = create_path_handler(output_dir)
                self.is_cloud_output = True
            else:
                self.output_dir = Path(output_dir)
                try:
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                except (FileNotFoundError, PermissionError, OSError) as exc:
                    raise FileNotFoundError(str(exc)) from exc
                self.is_cloud_output = False

        self.console = console or Console()
        self.anonymize = anonymize
        self.anonymization_manager = (
            AnonymizationManager(anonymization_config or AnonymizationConfig()) if anonymize else None
        )
        self._validator = SchemaV2Validator()

    def _write_file(self, file_path: Path, content: str, mode: str = "w") -> None:
        """Write content to file, handling both local and cloud paths."""
        if self.is_cloud_output and hasattr(file_path, "write_text"):
            file_path.write_text(content, encoding="utf-8")
        elif self.is_cloud_output and hasattr(file_path, "write_bytes"):
            file_path.write_bytes(content.encode("utf-8"))
        else:
            with open(file_path, mode, encoding="utf-8", newline="\n") as handle:
                handle.write(content)

    def _create_file_path(self, filename: str):
        """Create file path, ensuring parent directory exists."""
        if self.is_cloud_output:
            return self.output_dir / filename
        file_path = self.output_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        return file_path

    def export_result(
        self,
        result: ResultLike,
        formats: list[str] | None = None,
    ) -> dict[str, Path]:
        """Export benchmark result to specified formats using schema v2.0.

        Args:
            result: The BenchmarkResults to export.
            formats: List of formats to export. Defaults to ["json"].

        Returns:
            Dictionary mapping format names to exported file paths.
        """
        # Add cost estimation if available
        if isinstance(result, BenchmarkResults):
            try:
                from benchbox.core.cost.integration import add_cost_estimation_to_results

                result = add_cost_estimation_to_results(result)
            except Exception as e:
                logger.debug(f"Cost estimation skipped: {e}")

        if formats is None:
            formats = ["json"]

        exported_files: dict[str, Path] = {}

        timestamp = (
            result.timestamp.strftime("%Y%m%d_%H%M%S")
            if hasattr(result, "timestamp") and result.timestamp
            else datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        explicit_name = getattr(result, "output_filename", None)
        filename_base = Path(explicit_name).stem if explicit_name else self._generate_filename_base(result, timestamp)

        for format_name in formats:
            try:
                if format_name == "json":
                    filepath = self._export_json_v2(result, filename_base)
                elif format_name == "csv":
                    filepath = self._export_csv_detailed(result, filename_base)
                elif format_name == "html":
                    filepath = self._export_html_detailed(result, filename_base)
                else:
                    self.console.print(f"[yellow]Unknown export format: {format_name}[/yellow]")
                    continue

                exported_files[format_name] = filepath
                self.console.print(f"[green]Exported {format_name.upper()}:[/green] {filepath}")

            except Exception as exc:
                message = f"Failed to export {format_name}: {exc}"
                logger.error(message)
                # Mirror to root logger so test harness caplog captures failures reliably.
                logging.error(message)
                # Some tests elevate global logging to CRITICAL; emit at CRITICAL too
                # so failure diagnostics are still observable via caplog.
                logging.critical(message)
                self.console.print(f"[red]Failed to export {format_name}: {exc}[/red]")

        return exported_files

    def _generate_filename_base(self, result: ResultLike, timestamp: str) -> str:
        """Generate base filename for exports.

        Delegates to centralized filename builder.
        """
        from benchbox.core.results.filenames import build_result_filename_base

        benchmark_id = getattr(result, "benchmark_id", None) or getattr(result, "benchmark_name", "unknown")
        platform = getattr(result, "platform", "unknown")
        scale_factor = getattr(result, "scale_factor", 1.0)
        exec_id = getattr(result, "execution_id", None)

        # Extract mode from execution_context if available
        mode = None
        exec_ctx = getattr(result, "execution_context", None)
        if isinstance(exec_ctx, dict):
            mode = exec_ctx.get("mode") or exec_ctx.get("execution_mode")

        return build_result_filename_base(
            benchmark_id=str(benchmark_id).lower(),
            scale_factor=scale_factor,
            platform=str(platform).lower(),
            timestamp=timestamp,
            execution_id=exec_id,
            mode=mode,
        )

    def _export_json_v2(self, result: ResultLike, filename_base: str) -> Path:
        """Export result to JSON using schema v2.0 with companion files."""
        # Build primary payload
        payload = build_result_payload(result)

        # Apply anonymization if enabled
        if self.anonymize and self.anonymization_manager:
            self._apply_anonymization(payload)
            anonymized = True
        else:
            anonymized = False

        # Add export metadata
        payload["export"] = {
            "timestamp": datetime.now().isoformat(),
            "tool": self.EXPORTER_NAME,
            "anonymized": anonymized,
        }

        # Validate before writing
        try:
            self._validator.validate(payload)
        except SchemaV2ValidationError as e:
            logger.warning(f"Schema validation warning: {e}")

        # Write primary result file
        filepath = self._create_file_path(f"{filename_base}.json")
        json_content = canonical_json_text(self._convert_datetimes_to_iso(payload))
        self._write_file(filepath, json_content)

        # Write companion files
        self._write_companion_files(result, filename_base)

        return filepath

    def _write_companion_files(self, result: ResultLike, filename_base: str) -> None:
        """Write companion files for plans and tuning if present."""
        # Plans companion file
        plans_payload = build_plans_payload(result)
        if plans_payload:
            plans_path = self._create_file_path(f"{filename_base}.plans.json")
            self._write_file(plans_path, canonical_json_text(plans_payload))
            self.console.print(f"[dim]Exported plans: {plans_path}[/dim]")

        # Tuning companion file
        tuning_payload = build_tuning_payload(result)
        if tuning_payload:
            tuning_path = self._create_file_path(f"{filename_base}.tuning.json")
            self._write_file(tuning_path, canonical_json_text(tuning_payload))
            self.console.print(f"[dim]Exported tuning: {tuning_path}[/dim]")

    def _apply_anonymization(self, payload: dict[str, Any]) -> None:
        """Apply public-export anonymization to environment, platform, config, and execution metadata."""
        if not self.anonymization_manager:
            return

        anonymized_payload = self.anonymization_manager.anonymize_result_payload(payload)
        payload.clear()
        payload.update(anonymized_payload)

        # Ensure public exports have a stable grouping key without replacing
        # any captured client-host or platform-runtime metadata.
        machine_id = self.anonymization_manager.get_anonymous_machine_id()
        if not machine_id:
            return

        env_block = payload.get("environment")
        if not isinstance(env_block, dict):
            env_block = {}
            payload["environment"] = env_block

        client_host = env_block.get("client_host")
        client_host_block = client_host if isinstance(client_host, dict) else None
        captured_machine_id = env_block.get("machine_id")
        if captured_machine_id in (None, "") and client_host_block is not None:
            captured_machine_id = client_host_block.get("machine_id")

        effective_machine_id = captured_machine_id or machine_id
        if env_block.get("machine_id") in (None, ""):
            env_block["machine_id"] = effective_machine_id
        if client_host_block is not None:
            if client_host_block.get("machine_id") in (None, ""):
                client_host_block["machine_id"] = effective_machine_id
        elif not captured_machine_id:
            env_block["client_host"] = {"machine_id": effective_machine_id}

    def _convert_datetimes_to_iso(self, obj: Any) -> Any:
        """Convert datetime objects to ISO format strings."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {key: self._convert_datetimes_to_iso(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [self._convert_datetimes_to_iso(item) for item in obj]
        return obj

    def _export_csv_detailed(self, result: ResultLike, filename_base: str) -> Path:
        """Export query results to CSV format."""
        filepath = self._create_file_path(f"{filename_base}.csv")

        headers = [
            "query_id",
            "execution_time_ms",
            "rows_returned",
            "status",
            "error_message",
            "iteration",
            "stream",
        ]

        def _query_exec_time_ms(query: dict[str, Any]) -> float:
            exec_time_ms = query.get("execution_time_ms")
            if exec_time_ms is not None:
                return float(exec_time_ms)
            exec_time_seconds = query.get("execution_time_seconds")
            if exec_time_seconds is not None:
                return float(exec_time_seconds) * 1000.0
            return 0.0

        if self.is_cloud_output:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(headers)

            for query in self._iter_query_results(result):
                writer.writerow(
                    [
                        query.get("query_id", ""),
                        _query_exec_time_ms(query),
                        query.get("rows_returned", 0),
                        query.get("status", "UNKNOWN"),
                        query.get("error_message", ""),
                        query.get("iteration", ""),
                        query.get("stream_id", ""),
                    ]
                )

            self._write_file(filepath, buffer.getvalue())
            buffer.close()
            return filepath

        with open(filepath, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)

            for query in self._iter_query_results(result):
                writer.writerow(
                    [
                        query.get("query_id", ""),
                        _query_exec_time_ms(query),
                        query.get("rows_returned", 0),
                        query.get("status", "UNKNOWN"),
                        query.get("error") or query.get("error_message", ""),
                        query.get("iteration", ""),
                        query.get("stream_id", ""),
                    ]
                )

        return filepath

    def _export_html_detailed(self, result: ResultLike, filename_base: str) -> Path:
        """Export result to HTML format."""
        filepath = self._create_file_path(f"{filename_base}.html")

        benchmark_name = getattr(result, "benchmark_name", "Unknown Benchmark")
        execution_id = getattr(result, "execution_id", "")
        timestamp = getattr(result, "timestamp", datetime.now())
        duration = getattr(result, "duration_seconds", 0.0)
        scale_factor = getattr(result, "scale_factor", 1.0)
        platform = getattr(result, "platform", "Unknown")

        total_queries, successful_queries = self._count_queries(result)
        failed_queries = max(total_queries - successful_queries, 0)

        if isinstance(result, BenchmarkResults):
            total_time = result.total_execution_time
            avg_time = result.average_query_time
        else:
            successes = [
                (
                    query.get("execution_time_ms")
                    if query.get("execution_time_ms") is not None
                    else (
                        float(query.get("execution_time_seconds")) * 1000.0
                        if query.get("execution_time_seconds") is not None
                        else 0
                    )
                )
                for query in self._iter_query_results(result)
                if query.get("status") == "SUCCESS"
            ]
            total_time = sum(successes) / 1000 if successes else 0.0
            avg_time = (total_time / len(successes)) if successes else 0.0

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>BenchBox Results - {benchmark_name}</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a1a1a; margin-bottom: 8px; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .stat {{ background: #f8f9fa; padding: 16px; border-radius: 6px; text-align: center; }}
        .stat-value {{ font-size: 1.5em; font-weight: 600; color: #1a1a1a; }}
        .stat-label {{ font-size: 0.85em; color: #666; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
        th, td {{ border: 1px solid #e5e5e5; padding: 10px 12px; text-align: left; }}
        th {{ background: #f8f9fa; font-weight: 500; }}
        .success {{ color: #22863a; }}
        .failed {{ color: #cb2431; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{benchmark_name}</h1>
        <div class="meta">
            <strong>Platform:</strong> {platform} |
            <strong>Scale:</strong> {scale_factor} |
            <strong>Run:</strong> {execution_id} |
            <strong>Time:</strong> {timestamp.isoformat() if timestamp else "N/A"}
        </div>
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{total_queries}</div>
                <div class="stat-label">Total Queries</div>
            </div>
            <div class="stat">
                <div class="stat-value success">{successful_queries}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat">
                <div class="stat-value failed">{failed_queries}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat">
                <div class="stat-value">{duration:.2f}s</div>
                <div class="stat-label">Duration</div>
            </div>
            <div class="stat">
                <div class="stat-value">{total_time:.3f}s</div>
                <div class="stat-label">Query Time</div>
            </div>
            <div class="stat">
                <div class="stat-value">{avg_time * 1000:.1f}ms</div>
                <div class="stat-label">Avg Query</div>
            </div>
        </div>
        <h2>Query Results</h2>
        <table>
            <tr><th>Query</th><th>Time (ms)</th><th>Rows</th><th>Status</th><th>Error</th></tr>
            {"".join(self._render_query_row(query) for query in self._iter_query_results(result))}
        </table>
        <p style="margin-top: 24px; color: #666; font-size: 0.85em;">
            Generated by BenchBox v2.0 at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </p>
    </div>
</body>
</html>"""

        self._write_file(filepath, html_content)
        return filepath

    def _count_queries(self, result: ResultLike) -> tuple[int, int]:
        """Count total and successful queries."""
        successful = 0
        total = 0
        for query in self._iter_query_results(result):
            total += 1
            if query.get("status") == "SUCCESS":
                successful += 1
        return total, successful

    def _render_query_row(self, query: dict[str, Any]) -> str:
        """Render a single query as an HTML table row."""
        status = query.get("status", "UNKNOWN")
        status_class = "success" if status == "SUCCESS" else "failed"
        exec_time_ms = query.get("execution_time_ms")
        exec_time_seconds = query.get("execution_time_seconds")
        if exec_time_ms is None and exec_time_seconds is not None:
            exec_time_ms = float(exec_time_seconds) * 1000.0

        time_display = f"{exec_time_ms:.1f}" if exec_time_ms is not None else ""

        return (
            "<tr>"
            f"<td>{query.get('query_id', '')}</td>"
            f"<td>{time_display}</td>"
            f"<td>{query.get('rows_returned', '')}</td>"
            f"<td class='{status_class}'>{status}</td>"
            f"<td>{query.get('error') or query.get('error_message', '')}</td>"
            "</tr>"
        )

    def _iter_query_results(self, result: ResultLike) -> Iterable[dict[str, Any]]:
        """Iterate over query results, normalizing format."""
        if isinstance(result, BenchmarkResults):
            for query in result.query_results or []:
                yield query
        else:
            for query in getattr(result, "query_results", []) or []:
                if isinstance(query, dict):
                    yield query

    def list_results(self) -> list[dict[str, Any]]:
        """List all exported results in the output directory.

        Returns:
            List of result metadata dictionaries sorted by timestamp (newest first).
        """
        results: list[dict[str, Any]] = []

        for json_file in self.output_dir.glob("*.json"):
            # Skip companion files
            if (
                json_file.name.endswith(".plans.json")
                or json_file.name.endswith(".tuning.json")
                or json_file.name.endswith(".submission.json")
            ):
                continue

            try:
                with open(json_file, encoding="utf-8") as handle:
                    data = json.load(handle)

                version = data.get("version")
                if version not in ("2.0", "2.1"):
                    continue

                # Schema v2.x format
                results.append(
                    {
                        "file": json_file,
                        "version": version,
                        "benchmark": data.get("benchmark", {}).get("name", "Unknown"),
                        "platform": data.get("platform", {}).get("name", "Unknown"),
                        "scale_factor": data.get("benchmark", {}).get("scale_factor", 1.0),
                        "execution_id": data.get("run", {}).get("id", ""),
                        "timestamp": data.get("run", {}).get("timestamp", ""),
                        "duration": data.get("run", {}).get("total_duration_ms", 0) / 1000,
                        "queries": data.get("summary", {}).get("queries", {}).get("total", 0),
                        "status": data.get("summary", {}).get("validation", "unknown"),
                    }
                )

            except Exception as exc:
                logger.debug("Could not read %s: %s", json_file, exc)

        return sorted(results, key=lambda item: item["timestamp"], reverse=True)

    def show_results_summary(self) -> None:
        """Display a summary of exported results."""
        results = self.list_results()
        if not results:
            self.console.print("[yellow]No exported results found[/yellow]")
            return

        self.console.print(f"\n[bold]Exported Results ({len(results)} total)[/bold]")
        self.console.print(f"Output directory: [cyan]{self.output_dir}[/cyan]")

        from rich.table import Table

        table = Table()
        table.add_column("Benchmark", style="green")
        table.add_column("Platform", style="blue")
        table.add_column("Timestamp", style="dim")
        table.add_column("Duration", style="yellow")
        table.add_column("Queries", style="cyan")
        table.add_column("Version", style="dim")

        for result in results[:10]:
            duration_str = f"{result['duration']:.2f}s"
            timestamp_str = str(result["timestamp"])[:19].replace("T", " ")
            table.add_row(
                result["benchmark"],
                result.get("platform", ""),
                timestamp_str,
                duration_str,
                str(result["queries"]),
                result.get("version", ""),
            )

        self.console.print(table)

        if len(results) > 10:
            self.console.print(f"\n[dim]... and {len(results) - 10} more results[/dim]")

    def load_result_from_file(self, filepath: Path) -> dict[str, Any] | None:
        """Load a result file and return parsed data.

        Args:
            filepath: Path to the result JSON file.

        Returns:
            Dictionary with data, version, and filepath, or None on error.
        """
        try:
            with open(filepath, encoding="utf-8") as handle:
                data = json.load(handle)

            version = data.get("version", "unknown")
            return {"data": data, "version": version, "filepath": filepath}

        except Exception as exc:
            logger.error("Failed to load result from %s: %s", filepath, exc)
            return None

    def compare_results(self, baseline_path: Path, current_path: Path) -> dict[str, Any]:
        """Compare two result files and return performance analysis.

        Args:
            baseline_path: Path to baseline result file.
            current_path: Path to current result file.

        Returns:
            Comparison dictionary with performance changes and query comparisons.
        """
        baseline_result = self.load_result_from_file(baseline_path)
        current_result = self.load_result_from_file(current_path)

        if not baseline_result or not current_result:
            return {
                "error": "Failed to load one or both result files",
                "baseline_loaded": bool(baseline_result),
                "current_loaded": bool(current_result),
            }

        baseline_data = baseline_result["data"]
        current_data = current_result["data"]
        baseline_version = baseline_result.get("version", "unknown")
        current_version = current_result.get("version", "unknown")

        # Extract metrics using schema-agnostic normalizer
        perf_baseline = self._extract_performance_metrics(baseline_data)
        perf_current = self._extract_performance_metrics(current_data)

        comparison: dict[str, Any] = {
            "baseline_file": str(baseline_path),
            "current_file": str(current_path),
            "baseline_version": baseline_version,
            "current_version": current_version,
            "performance_changes": {},
            "query_comparisons": [],
        }

        # Compare overall metrics
        for metric in ["total_execution_time", "average_query_time"]:
            if metric in perf_baseline and metric in perf_current:
                baseline_value = perf_baseline[metric]
                current_value = perf_current[metric]
                change = ((current_value - baseline_value) / baseline_value * 100) if baseline_value else 0
                comparison["performance_changes"][metric] = {
                    "baseline": baseline_value,
                    "current": current_value,
                    "change_percent": round(change, 2),
                    "improved": current_value < baseline_value,
                }

        # Compare individual queries
        baseline_queries = self._extract_query_map(baseline_data)
        current_queries = self._extract_query_map(current_data)

        for query_id, baseline_query in baseline_queries.items():
            current_query = current_queries.get(query_id)
            if not current_query:
                continue

            baseline_time = baseline_query.get("execution_time_ms") or 0
            current_time = current_query.get("execution_time_ms") or 0
            change = ((current_time - baseline_time) / baseline_time * 100) if baseline_time else 0

            comparison["query_comparisons"].append(
                {
                    "query_id": query_id,
                    "baseline_time_ms": baseline_time,
                    "current_time_ms": current_time,
                    "change_percent": round(change, 2),
                    "improved": current_time < baseline_time,
                }
            )

        # Generate summary
        if comparison["query_comparisons"]:
            improved = len([q for q in comparison["query_comparisons"] if q["improved"]])
            regressed = len(
                [q for q in comparison["query_comparisons"] if not q["improved"] and q["change_percent"] > 0]
            )
            comparison["summary"] = {
                "total_queries_compared": len(comparison["query_comparisons"]),
                "improved_queries": improved,
                "regressed_queries": regressed,
                "unchanged_queries": len(comparison["query_comparisons"]) - improved - regressed,
                "overall_assessment": self._assess_performance_change(comparison["performance_changes"]),
            }

        return comparison

    def _extract_performance_metrics(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract performance metrics from result data.

        Uses the shared normalizer for schema-agnostic extraction.
        """
        normalized = normalize_result_dict(data)
        return {
            "total_queries": normalized.total_queries,
            "successful_queries": normalized.passed_queries,
            "failed_queries": normalized.failed_queries,
            "total_execution_time": (normalized.total_time_ms or 0) / 1000,
            "average_query_time": (normalized.avg_time_ms or 0) / 1000,
        }

    def _extract_query_map(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Extract query results as a map from query ID to query data.

        Uses the shared normalizer for schema-agnostic extraction.
        """
        normalized = normalize_result_dict(data)
        query_map = get_query_map(normalized)
        return {
            query_id: {
                "query_id": query_id,
                "execution_time_ms": q.execution_time_ms or 0,
                "rows_returned": q.rows_returned,
            }
            for query_id, q in query_map.items()
        }

    def _assess_performance_change(self, performance_changes: dict[str, Any]) -> str:
        """Assess overall performance change."""
        if not performance_changes:
            return "no_data"

        time_metrics = ["total_execution_time", "average_query_time"]
        time_changes = [performance_changes[m]["change_percent"] for m in time_metrics if m in performance_changes]

        if not time_changes:
            return "unknown"

        avg_change = sum(time_changes) / len(time_changes)

        if avg_change < -10:
            return SIGNIFICANT_IMPROVEMENT_ASSESSMENT
        if avg_change < -5:
            return "improvement"
        if avg_change > 10:
            return "significant_regression"
        if avg_change > 5:
            return "regression"
        return "no_significant_change"

    def export_comparison_report(
        self,
        comparison: dict[str, Any],
        output_path: PathLike | None = None,
    ) -> PathLike:
        """Export comparison results as an HTML report.

        Args:
            comparison: Comparison dictionary from compare_results().
            output_path: Output file path. Auto-generates if not provided.

        Returns:
            Path to the exported report.
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.output_dir / f"comparison_report_{timestamp}.html"

        summary = comparison.get("summary", {})
        performance_changes = comparison.get("performance_changes", {})
        query_comparisons = comparison.get("query_comparisons", [])

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>BenchBox Comparison Report</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 24px; border-radius: 8px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .metric {{ padding: 16px; border-radius: 8px; text-align: center; }}
        .metric.improved {{ background: #d4edda; border: 1px solid #c3e6cb; }}
        .metric.regressed {{ background: #f8d7da; border: 1px solid #f5c6cb; }}
        .metric.neutral {{ background: #f8f9fa; border: 1px solid #e9ecef; }}
        .metric h3 {{ margin: 0; font-size: 0.85em; text-transform: uppercase; color: #666; }}
        .metric p {{ margin: 8px 0 0 0; font-size: 1.4em; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
        th, td {{ border: 1px solid #e5e5e5; padding: 10px 12px; }}
        th {{ background: #f8f9fa; font-weight: 500; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Performance Comparison Report</h1>
            <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>
        <div class="summary">
            <div class="metric neutral">
                <h3>Queries Compared</h3>
                <p>{summary.get("total_queries_compared", 0)}</p>
            </div>
            <div class="metric improved">
                <h3>Improved</h3>
                <p>{summary.get("improved_queries", 0)}</p>
            </div>
            <div class="metric regressed">
                <h3>Regressed</h3>
                <p>{summary.get("regressed_queries", 0)}</p>
            </div>
            <div class="metric neutral">
                <h3>Unchanged</h3>
                <p>{summary.get("unchanged_queries", 0)}</p>
            </div>
        </div>
        <h2>Performance Changes</h2>
        <ul>
            {
            "".join(
                f"<li>{metric.replace('_', ' ').title()}: {vals['change_percent']:+.1f}% "
                f"({'Improved' if vals['improved'] else 'Regressed'})</li>"
                for metric, vals in performance_changes.items()
            )
        }
        </ul>
        <h2>Query Details</h2>
        <table>
            <tr><th>Query</th><th>Baseline (ms)</th><th>Current (ms)</th><th>Change</th><th>Status</th></tr>
            {
            "".join(
                f"<tr><td>{q['query_id']}</td><td>{q['baseline_time_ms']:.1f}</td>"
                f"<td>{q['current_time_ms']:.1f}</td><td>{q['change_percent']:+.1f}%</td>"
                f"<td>{'Improved' if q['improved'] else 'Regressed'}</td></tr>"
                for q in query_comparisons
            )
        }
        </table>
    </div>
</body>
</html>"""

        self._write_file(output_path, html_content)
        return output_path
