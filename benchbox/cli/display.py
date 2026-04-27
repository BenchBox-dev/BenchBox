"""Standardized CLI display functionality and formatting.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from benchbox.core.results.models import BenchmarkResults
from benchbox.core.schemas import (
    BenchmarkConfig,
    DatabaseConfig,
    DryRunResult,
    QueryResult,
    SystemProfile,
)
from benchbox.utils.printing import quiet_console


@dataclass
class DisplayConfig:
    """Configuration for display formatting."""

    show_detailed: bool = False
    max_query_length: int = 500
    max_table_width: int = 120
    use_colors: bool = True
    show_timestamps: bool = True


class StandardDisplays:
    """Standardized display components for CLI."""

    def __init__(self, console: Console | None = None, config: DisplayConfig | None = None):
        self.console = console or quiet_console
        self.config = config or DisplayConfig()

    def show_banner(self, title: str, version: str, subtitle: str | None = None) -> None:
        """Show standardized banner."""
        banner_text = f"[bold blue]{title}[/bold blue]"
        if version:
            banner_text += f"\n[dim]{version}[/dim]"
        if subtitle:
            banner_text += f"\n[dim]{subtitle}[/dim]"
        else:
            banner_text += "\n[dim]Benchmark Suite[/dim]"

        panel = Panel(
            banner_text,
            border_style="blue",
            padding=(1, 2),
        )
        self.console.print(panel)

    def show_system_profile(self, profile: SystemProfile, detailed: bool = False) -> None:
        """Display system profile in standardized format."""
        table = Table(title="System Information", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=25)
        table.add_column("Value", style="white")

        # Basic information
        table.add_row("OS", f"{profile.os_name} {profile.os_version}")
        table.add_row("Architecture", profile.architecture)
        table.add_row("CPU", profile.cpu_model)
        table.add_row(
            "CPU Cores",
            f"{profile.cpu_cores_physical} physical, {profile.cpu_cores_logical} logical",
        )
        table.add_row(
            "Memory",
            f"{profile.memory_total_gb:.1f} GB total, {profile.memory_available_gb:.1f} GB available",
        )
        table.add_row("Python", profile.python_version)

        if detailed:
            table.add_row("Disk Space", f"{profile.disk_space_gb:.1f} GB free")
            if profile.hostname:
                table.add_row("Hostname", profile.hostname)
            table.add_row("Timestamp", profile.timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        self.console.print(table)

    def show_benchmark_config(
        self,
        benchmark_config: BenchmarkConfig,
        database_config: DatabaseConfig | None = None,
    ) -> None:
        """Display benchmark configuration."""
        table = Table(title="Benchmark Configuration", show_header=True, header_style="bold green")
        table.add_column("Setting", style="cyan", width=20)
        table.add_column("Value", style="white")

        table.add_row("Name", benchmark_config.display_name)
        table.add_row("Scale Factor", str(benchmark_config.scale_factor))
        table.add_row("Test Type", benchmark_config.test_execution_type)
        table.add_row("Concurrency", str(benchmark_config.concurrency))

        if benchmark_config.queries:
            if len(benchmark_config.queries) <= 10:
                table.add_row("Queries", ", ".join(benchmark_config.queries))
            else:
                table.add_row("Queries", f"{len(benchmark_config.queries)} queries selected")

        if benchmark_config.compress_data:
            compression_info = f"{benchmark_config.compression_type}"
            if benchmark_config.compression_level is not None:
                compression_info += f" (level {benchmark_config.compression_level})"
            table.add_row("Compression", compression_info)

        self.console.print(table)

        # Display database config if provided
        if database_config:
            db_table = Table(
                title="Database Configuration",
                show_header=True,
                header_style="bold yellow",
            )
            db_table.add_column("Setting", style="cyan", width=20)
            db_table.add_column("Value", style="white")

            db_type_display = {
                "duckdb": "DuckDB",
                "sqlite3": "SQLite",
                "postgres": "PostgreSQL",
                "mysql": "MySQL",
                "bigquery": "BigQuery",
                "snowflake": "Snowflake",
            }.get(database_config.type, database_config.type)
            db_table.add_row("Type", db_type_display)
            db_table.add_row("Name", database_config.name)

            if database_config.connection_string and not any(
                secret in database_config.connection_string.lower() for secret in ["password", "token", "key"]
            ):
                db_table.add_row("Connection", database_config.connection_string)
            else:
                db_table.add_row("Connection", "[hidden for security]")

            if database_config.options:
                options_str = ", ".join(f"{k}={v}" for k, v in database_config.options.items())
                if len(options_str) > 50:
                    options_str = options_str[:50] + "..."
                db_table.add_row("Options", options_str)

            self.console.print(db_table)

    def show_database_config(self, config: DatabaseConfig) -> None:
        """Display database configuration."""
        table = Table(title="Database Configuration", show_header=True, header_style="bold yellow")
        table.add_column("Setting", style="cyan", width=20)
        table.add_column("Value", style="white")

        db_type_display = {
            "duckdb": "DuckDB",
            "sqlite3": "SQLite",
            "postgres": "PostgreSQL",
            "mysql": "MySQL",
            "bigquery": "BigQuery",
            "snowflake": "Snowflake",
        }.get(config.type, config.type)
        table.add_row("Type", db_type_display)
        table.add_row("Name", config.name)

        if config.connection_string and not any(
            secret in config.connection_string.lower() for secret in ["password", "token", "key"]
        ):
            table.add_row("Connection", config.connection_string)
        else:
            table.add_row("Connection", "[hidden for security]")

        if config.options:
            options_str = ", ".join(f"{k}={v}" for k, v in config.options.items())
            if len(options_str) > 50:
                options_str = options_str[:50] + "..."
            table.add_row("Options", options_str)

        self.console.print(table)

    def _normalize_query_entry(self, entry: QueryResult | dict[str, Any]) -> dict[str, Any]:
        """Return a dict with common query execution fields regardless of source type."""

        if isinstance(entry, dict):
            return {
                "query_id": entry.get("query_id") or entry.get("id") or "UNKNOWN",
                "query_name": entry.get("query_name") or entry.get("name") or entry.get("query_id") or "UNKNOWN",
                "status": entry.get("status", "UNKNOWN"),
                "execution_time_ms": float(
                    entry.get("execution_time_ms")
                    or (float(entry["execution_time_seconds"]) * 1000.0 if "execution_time_seconds" in entry else 0.0)
                    or (float(entry["execution_time"]) * 1000.0 if "execution_time" in entry else 0.0)
                ),
                "rows_returned": entry.get("rows_returned", 0),
                "error_message": entry.get("error_message"),
            }

        # QueryResult dataclass
        return {
            "query_id": entry.query_id,
            "query_name": entry.query_name or entry.query_id,
            "status": entry.status,
            "execution_time_ms": float(entry.execution_time_ms),
            "rows_returned": entry.rows_returned,
            "error_message": entry.error_message,
        }

    def show_query_results(self, results: list[QueryResult | dict[str, Any]], summary_only: bool = False) -> None:
        """Display query execution results."""
        if not results:
            self.console.print("[yellow]No query results available[/yellow]")
            return

        # Summary statistics
        normalized = [self._normalize_query_entry(result) for result in results]

        total_queries = len(normalized)
        successful_queries = len([r for r in normalized if r["status"] == "SUCCESS"])
        failed_queries = total_queries - successful_queries
        total_time = sum(r["execution_time_ms"] for r in normalized) / 1000  # seconds

        # Summary panel
        summary_text = f"""[green]✅ {successful_queries} successful[/green]  [red]❌ {failed_queries} failed[/red]
Total time: {total_time:.2f}s  Average: {total_time / total_queries:.3f}s per query"""

        summary_panel = Panel(
            summary_text,
            title="Query Execution Summary",
            border_style="blue",
            padding=(0, 1),
        )
        self.console.print(summary_panel)

        if not summary_only and total_queries <= 50:  # Show details for reasonable number of queries
            # Detailed results table
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Query", style="cyan", width=15)
            table.add_column("Status", width=10)
            table.add_column("Time (ms)", justify="right", width=10)
            table.add_column("Rows", justify="right", width=10)

            if self.config.show_detailed:
                table.add_column("Error", width=40)

            for result in normalized:
                # Status with color
                if result["status"] == "SUCCESS":
                    status = "[green]SUCCESS[/green]"
                elif result["status"] == "ERROR":
                    status = "[red]ERROR[/red]"
                elif result["status"] == "TIMEOUT":
                    status = "[yellow]TIMEOUT[/yellow]"
                else:
                    status = result["status"]

                row = [
                    result["query_name"],
                    status,
                    f"{result['execution_time_ms']:.1f}",
                    str(result["rows_returned"]),
                ]

                error_message = result.get("error_message")
                if self.config.show_detailed and error_message:
                    error_msg = error_message[:40] + "..." if len(error_message) > 40 else error_message
                    row.append(error_msg)
                elif self.config.show_detailed:
                    row.append("")

                table.add_row(*row)

            self.console.print(table)

    def show_benchmark_result(self, result: BenchmarkResults) -> None:
        """Display complete benchmark results."""
        self.show_banner(
            f"{result.benchmark_name} Results",
            f"Scale Factor: {result.scale_factor} | Type: {result.test_execution_type}",
        )

        # Basic metrics
        metrics_table = Table(show_header=True, header_style="bold magenta")
        metrics_table.add_column("Metric", style="cyan", width=25)
        metrics_table.add_column("Value", style="white")

        metrics_table.add_row("Duration", f"{result.duration_seconds:.2f} seconds")
        metrics_table.add_row("Validation Status", result.validation_status or "UNKNOWN")

        _compliance_class = getattr(result, "compliance_class", None)
        _unofficial = _compliance_class in {"unofficial_nonstandard", "unofficial_subscale"}
        if not _unofficial:
            if result.power_at_size is not None:
                metrics_table.add_row("Power@Size", f"{result.power_at_size:.2f}")

            if result.throughput_at_size is not None:
                metrics_table.add_row("Throughput@Size", f"{result.throughput_at_size:.2f}")
        else:
            metrics_table.add_row("TPC Metrics", f"[yellow]suppressed (compliance: {_compliance_class})[/yellow]")

        if result.geometric_mean_execution_time is not None:
            metrics_table.add_row("Geometric Mean", f"{result.geometric_mean_execution_time:.3f}s")

        # Show summary metrics
        performance_summary = result.performance_summary or {}
        for key, value in performance_summary.items():
            if isinstance(value, float):
                metrics_table.add_row(key.replace("_", " ").title(), f"{value:.3f}")
            else:
                metrics_table.add_row(key.replace("_", " ").title(), str(value))

        self.console.print(metrics_table)

        # Show query results section
        self.console.print()
        self.show_query_results(result.query_results)

    def show_dry_run_summary(self, result: DryRunResult) -> None:
        """Display dry run results summary."""
        self.show_banner("Dry Run Results", "", "Configuration validation and preview")

        # Configuration summary
        config_items = []
        config_items.append(f"[cyan]Benchmark:[/cyan] {result.benchmark_config.get('display_name', 'Unknown')}")
        config_items.append(f"[cyan]Scale Factor:[/cyan] {result.benchmark_config.get('scale_factor', 'Unknown')}")
        config_items.append(
            f"[cyan]Database:[/cyan] {result.database_config.get('name', 'Unknown')} ({result.database_config.get('type', 'Unknown')})"
        )
        config_items.append(f"[cyan]Test Type:[/cyan] {result.benchmark_config.get('test_execution_type', 'standard')}")

        if result.queries:
            config_items.append(f"[cyan]Queries:[/cyan] {len(result.queries)} selected")

        config_panel = Panel(
            "\n".join(config_items),
            title="Configuration Summary",
            border_style="green",
            padding=(1, 2),
        )
        self.console.print(config_panel)

        # Show warnings if any
        if result.warnings:
            warning_text = "\n".join(f"• {warning}" for warning in result.warnings)
            warning_panel = Panel(
                warning_text,
                title=f"Warnings ({len(result.warnings)})",
                border_style="yellow",
                padding=(1, 2),
            )
            self.console.print(warning_panel)

        # Show resource estimates if available
        if result.estimated_resources:
            resource_items = []
            for key, value in result.estimated_resources.items():
                if isinstance(value, (int, float)):
                    if "memory" in key.lower() or "size" in key.lower():
                        # Format memory/size values
                        if value > 1024**3:
                            formatted_value = f"{value / (1024**3):.2f} GB"
                        elif value > 1024**2:
                            formatted_value = f"{value / (1024**2):.2f} MB"
                        else:
                            formatted_value = f"{value:.2f} bytes"
                    else:
                        formatted_value = f"{value:.2f}"
                else:
                    formatted_value = str(value)

                resource_items.append(f"[cyan]{key.replace('_', ' ').title()}:[/cyan] {formatted_value}")

            if resource_items:
                resource_panel = Panel(
                    "\n".join(resource_items),
                    title="Resource Estimates",
                    border_style="blue",
                    padding=(1, 2),
                )
                self.console.print(resource_panel)

    def show_progress_with_context(self, operation: str, context: str = "") -> Progress:
        """Create standardized progress display."""
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
        )

        description = operation
        if context:
            description += f" ({context})"

        return progress

    def show_error_summary(self, errors: list[str]) -> None:
        """Display error summary."""
        if not errors:
            return

        error_text = "\n".join(f"• {error}" for error in errors)
        error_panel = Panel(
            error_text,
            title=f"Errors ({len(errors)})",
            border_style="red",
            padding=(1, 2),
        )
        self.console.print(error_panel)

    def show_success_message(self, message: str, details: list[str] | None = None) -> None:
        """Show standardized success message."""
        content = f"[green]✅[/green] {message}"

        if details:
            content += "\n\n" + "\n".join(f"  • {detail}" for detail in details)

        success_panel = Panel(
            content,
            border_style="green",
            padding=(1, 2),
        )
        self.console.print(success_panel)


def create_display_manager(console: Console | None = None, config: DisplayConfig | None = None) -> StandardDisplays:
    """Factory function to create display manager."""
    return StandardDisplays(console, config)


# Convenience functions for common display operations
def show_benchmark_summary(result: BenchmarkResults, console: Console | None = None) -> None:
    """Convenience function to show benchmark results."""
    display = create_display_manager(console)
    display.show_benchmark_result(result)


def show_system_info(profile: SystemProfile, console: Console | None = None, detailed: bool = False) -> None:
    """Convenience function to show system information."""
    display = create_display_manager(console)
    display.show_system_profile(profile, detailed)


def show_configuration_summary(
    benchmark_config: BenchmarkConfig,
    database_config: DatabaseConfig,
    console: Console | None = None,
) -> None:
    """Convenience function to show configuration summary."""
    display = create_display_manager(console)
    display.show_benchmark_config(benchmark_config, database_config)
