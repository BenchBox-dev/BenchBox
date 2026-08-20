"""Interactive SQL shell command."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.prompt import Prompt
from rich.table import Table

from benchbox.cli.config import DirectoryManager
from benchbox.cli.shared import console
from benchbox.utils.database_naming import parse_database_name


def _get_platform_from_extension(extension: str) -> str:
    """Get platform type from file extension.

    Uses the same extension mapping as generate_database_filename() in database_naming.py.

    Args:
        extension: File extension (e.g., ".duckdb", ".sqlite")

    Returns:
        Platform name (e.g., "duckdb", "sqlite") or "unknown"
    """
    # Extension mapping from benchbox.utils.database_naming.generate_database_filename()
    # Each platform has a unique extension to prevent collisions
    extension_to_platform = {
        # SQL databases
        ".duckdb": "duckdb",
        ".sqlite": "sqlite",
        ".chdb": "clickhouse",
        # DataFrame platforms (SQL mode)
        ".datafusion": "datafusion",
        ".polars": "polars",
        ".pandas": "pandas",
        # DataFrame platforms (native API mode)
        ".polars-df": "polars-df",
        ".pandas-df": "pandas-df",
        ".cudf-df": "cudf-df",
        ".modin-df": "modin-df",
        ".dask-df": "dask-df",
        # Other platforms
        ".cudf": "cudf",
        ".spark": "spark",
    }

    ext_lower = extension.lower()
    return extension_to_platform.get(ext_lower, "unknown")


def discover_local_databases(base_dir: Path | None = None) -> list[dict[str, Any]]:
    """Discover all local database files using DirectoryManager infrastructure.

    Searches multiple standard locations for all supported database extensions.

    Args:
        base_dir: Base directory to search (defaults to benchmark_runs)

    Returns:
        List of database metadata dicts with keys: path, platform, benchmark, scale, etc.
    """
    # Use DirectoryManager with custom base_dir if provided
    # This ensures consistent path handling with run command
    dir_mgr = DirectoryManager(base_dir=str(base_dir) if base_dir else None)

    databases = []

    # All supported extensions - must match database_naming.py
    supported_extensions = [
        ".duckdb",
        ".sqlite",
        ".chdb",
        ".datafusion",
        ".polars",
        ".pandas",
        ".polars-df",
        ".pandas-df",
        ".cudf-df",
        ".modin-df",
        ".dask-df",
        ".cudf",
        ".spark",
    ]

    # Search both standard locations where databases can exist
    search_locations = []
    for ext in supported_extensions:
        # Recursive search in datagen subdirs
        search_locations.append((dir_mgr.datagen_dir, f"**/*{ext}"))
        # Flat search in databases dir
        search_locations.append((dir_mgr.databases_dir, f"*{ext}"))

    for search_dir, pattern in search_locations:
        if not search_dir.exists():
            continue

        for db_path in search_dir.glob(pattern):
            if not db_path.is_file():
                continue

            # Use database_naming utilities for parsing
            metadata = parse_database_name(db_path.name)

            # Get platform from extension using consistent logic
            platform = _get_platform_from_extension(db_path.suffix)

            # Get file stats
            stat = db_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            modified = datetime.fromtimestamp(stat.st_mtime)

            # Handle None values from parse_database_name
            if metadata is None:
                metadata = {}

            databases.append(
                {
                    "path": db_path,
                    "platform": platform,
                    "benchmark": metadata.get("benchmark") or "unknown",
                    "scale": metadata.get("scale_factor") or 0.0,
                    "tuning": metadata.get("tuning_mode") or "none",
                    "constraints": metadata.get("constraints") or "none",
                    "size_mb": size_mb,
                    "modified": modified,
                }
            )

    # Sort by modified time (most recent first)
    databases.sort(key=lambda d: d["modified"], reverse=True)

    return databases


def filter_databases(
    databases: list[dict[str, Any]],
    platform: str | None = None,
    benchmark: str | None = None,
    scale: float | None = None,
) -> list[dict[str, Any]]:
    """Filter databases by criteria using consistent comparison logic.

    Uses the same scale factor formatting as DirectoryManager to ensure
    consistent matching with how paths are constructed.

    Args:
        databases: List of database metadata dicts
        platform: Filter by platform (duckdb, sqlite)
        benchmark: Filter by benchmark name
        scale: Filter by scale factor

    Returns:
        Filtered list of databases
    """
    from benchbox.utils.scale_factor import format_scale_factor

    filtered = databases

    if platform:
        platform_lower = platform.lower()
        filtered = [db for db in filtered if db["platform"] == platform_lower]

    if benchmark:
        benchmark_lower = benchmark.lower()
        filtered = [db for db in filtered if db["benchmark"].lower() == benchmark_lower]

    if scale is not None:
        # Use scale factor formatting for consistent comparison
        # This matches how DirectoryManager formats scale factors in paths
        target_sf_str = format_scale_factor(scale)

        result = []
        for db in filtered:
            if db["scale"] is None:
                continue
            db_sf_str = format_scale_factor(db["scale"])
            if db_sf_str == target_sf_str:
                result.append(db)
        filtered = result

    return filtered


def display_database_table(databases: list[dict[str, Any]]) -> None:
    """Display databases in a Rich table.

    Args:
        databases: List of database metadata dicts
    """
    if not databases:
        console.print("[yellow]No databases found[/yellow]")
        return

    table = Table(title="Available Local Databases", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Benchmark", style="green")
    table.add_column("Scale", justify="right", style="blue")
    table.add_column("Platform", style="magenta")
    table.add_column("Tuning", style="yellow")
    table.add_column("Size (MB)", justify="right", style="cyan")
    table.add_column("Modified", style="dim")
    table.add_column("Path", style="dim", overflow="fold")

    for idx, db in enumerate(databases, start=1):
        table.add_row(
            str(idx),
            db["benchmark"],
            f"{db['scale']:.2f}",
            db["platform"],
            db["tuning"],
            f"{db['size_mb']:.1f}",
            db["modified"].strftime("%Y-%m-%d %H:%M"),
            str(db["path"]),
        )

    console.print(table)


def select_database_interactive(databases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prompt user to select a database from the list.

    Args:
        databases: List of database metadata dicts

    Returns:
        Selected database metadata dict, or None if cancelled
    """
    if not databases:
        return None

    if len(databases) == 1:
        # Auto-select if only one option
        console.print(f"[green]Using database: {databases[0]['path']}[/green]")
        return databases[0]

    # Show table
    display_database_table(databases)

    # Prompt for selection
    console.print("\n[dim]Enter database number, or press Ctrl+C to cancel[/dim]")

    try:
        selection = Prompt.ask(
            "Select database",
            default="1",
            show_default=True,
        )

        # Parse selection
        try:
            idx = int(selection)
            if 1 <= idx <= len(databases):
                return databases[idx - 1]
            else:
                console.print(f"[red]Invalid selection: {idx}. Must be 1-{len(databases)}[/red]")
                return None
        except ValueError:
            console.print(f"[red]Invalid input: {selection}. Must be a number[/red]")
            return None

    except KeyboardInterrupt:
        console.print("\n[yellow]Selection cancelled[/yellow]")
        return None


@click.command("shell")
@click.option(
    "--platform",
    type=str,
    help="Platform type (duckdb, datafusion, sqlite, clickhouse). Auto-detected if not specified.",
)
@click.option(
    "--database",
    type=click.Path(),
    help="Database file path or connection string (platform-specific)",
)
@click.option(
    "--benchmark",
    type=str,
    help="Filter by benchmark name when discovering databases",
)
@click.option(
    "--scale",
    type=float,
    help="Filter by scale factor when discovering databases",
)
@click.option(
    "--list",
    "list_only",
    is_flag=True,
    help="List available databases and exit",
)
@click.option(
    "--last",
    is_flag=True,
    help="Connect to most recently modified database",
)
@click.option(
    "--output",
    type=click.Path(exists=True),
    help="Output directory from run command (searches for database files here)",
)
@click.option(
    "--host",
    type=str,
    help="Database host (for remote platforms like clickhouse)",
)
@click.option(
    "--port",
    type=int,
    help="Database port",
)
@click.option(
    "--user",
    type=str,
    help="Database username",
)
@click.option(
    "--password",
    type=str,
    help="Database password",
)
@click.pass_context
def shell(ctx, platform, database, benchmark, scale, list_only, last, output, host, port, user, password):
    """Launch an interactive SQL shell for a database platform.

    Opens an interactive SQL prompt connected to the specified platform,
    useful for debugging queries, inspecting benchmark data, and exploring
    database state after benchmark execution.

    Supports automatic database discovery from benchmark_runs/datagen/ or
    a custom output directory. Can filter by benchmark name and scale factor.

    Supported platforms: DuckDB, SQLite, ClickHouse (more coming soon)

    Examples:
        # Interactive selection from available databases
        benchbox shell

        # List available databases
        benchbox shell --list

        # Connect to most recent database
        benchbox shell --last

        # Filter and select
        benchbox shell --benchmark tpch --scale 1.0

        # Direct connection
        benchbox shell --platform duckdb --database benchmark.duckdb

        # Use database from specific output directory
        benchbox shell --output benchmark_runs/results/tpch_20250101_120000

        # ClickHouse shell
        benchbox shell --platform clickhouse --host localhost --port 9000 \\
          --user default --database benchbox
    """
    # Determine base directory for database discovery
    base_dir = Path(output) if output else None

    # Path 1: Direct database path provided
    if database:
        _shell_direct_connection(database, platform, host, port, user, password)
        return

    # Path 2: Remote platform (ClickHouse) - requires explicit connection params
    if platform and platform.lower() in {"clickhouse", "clickhouse-server"}:
        _launch_clickhouse_shell(host, port, user, password, database)
        return

    # Path 3: Database discovery and selection
    filtered = _shell_discover_databases(base_dir, output, platform, benchmark, scale)

    # Path 3a: List only
    if list_only:
        display_database_table(filtered)
        return

    # Path 3b/3c: Select and launch
    selected = _shell_select_database(filtered, last)
    _launch_shell_for_platform(selected["platform"], str(selected["path"]))


def _shell_direct_connection(
    database: str,
    platform: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
) -> None:
    """Handle direct database path connection."""
    if not platform:
        db_path = Path(database)
        platform = _get_platform_from_extension(db_path.suffix.lower())
        if platform == "unknown":
            console.print("[red]Error: Cannot auto-detect platform. Please specify --platform[/red]")
            sys.exit(1)

    platform_lower = platform.lower()
    if platform_lower in {"clickhouse", "clickhouse-server"}:
        _launch_clickhouse_shell(host, port, user, password, database)
    elif platform_lower in ("duckdb", "sqlite"):
        _launch_shell_for_platform(platform_lower, database)
    else:
        console.print(f"[red]Error: Platform '{platform}' not supported for interactive shell[/red]")
        console.print("Supported platforms: duckdb, sqlite, clickhouse-server")
        sys.exit(1)


def _shell_discover_databases(
    base_dir: Path | None,
    output: str | None,
    platform: str | None,
    benchmark: str | None,
    scale: float | None,
) -> list[dict[str, Any]]:
    """Discover and filter local databases, exiting on failure."""
    console.print("[blue]Discovering local databases...[/blue]")

    if output:
        console.print(f"[dim]Searching in: {output}[/dim]")
    else:
        temp_dir_mgr = DirectoryManager()
        console.print(f"[dim]Searching in: {temp_dir_mgr.base_dir}[/dim]")

    databases = discover_local_databases(base_dir)

    if not databases:
        if base_dir:
            console.print(f"[yellow]No databases found in {base_dir}[/yellow]")
        else:
            console.print("[yellow]No databases found in benchmark_runs[/yellow]")
        console.print("\n[dim]To create databases, run:[/dim]")
        console.print("  benchbox run --benchmark tpch --scale 1 --platform duckdb")
        sys.exit(1)

    filtered = filter_databases(databases, platform, benchmark, scale)

    if not filtered:
        console.print("[yellow]No databases match the specified filters[/yellow]")
        console.print(f"Filters: platform={platform}, benchmark={benchmark}, scale={scale}")
        console.print(f"\nFound {len(databases)} databases total. Try removing some filters.")
        sys.exit(1)

    return filtered


def _shell_select_database(filtered: list[dict[str, Any]], last: bool) -> dict[str, Any]:
    """Select a database from filtered results."""
    if last:
        selected = filtered[0]
        console.print(f"[green]Connecting to most recent database: {selected['path']}[/green]")
        return selected

    selected = select_database_interactive(filtered)
    if not selected:
        console.print("[yellow]No database selected[/yellow]")
        sys.exit(0)
    return selected


def _launch_shell_for_platform(platform: str, db_path: str) -> None:
    """Launch the appropriate shell for a given platform."""
    if platform == "duckdb":
        _launch_duckdb_shell(db_path)
    elif platform == "sqlite":
        _launch_sqlite_shell(db_path)
    else:
        console.print(f"[red]Error: Platform '{platform}' not supported[/red]")
        sys.exit(1)


def _launch_duckdb_shell(database: str | None) -> None:
    """Launch DuckDB interactive shell with enhanced features."""
    try:
        import duckdb
    except ImportError:
        console.print("[red]Error: duckdb package not installed[/red]")
        console.print("Install with: pip install duckdb")
        sys.exit(1)

    db_path = database or ":memory:"
    console.print(f"[blue]Opening DuckDB shell: {db_path}[/blue]")

    try:
        conn = duckdb.connect(db_path, read_only=False)

        # Display database info
        _display_database_info_duckdb(conn, db_path)

        # Show available commands
        console.print("\n[dim]Commands: .quit, .tables, .schema [table], .info, SQL queries[/dim]")
        console.print("[dim]Press Ctrl+C to cancel current input, Ctrl+D or .quit to exit[/dim]\n")

        # Enhanced REPL with command history

        while True:
            try:
                query = input("duckdb> ")
                if not query.strip():
                    continue

                query_lower = query.strip().lower()

                # Handle special commands
                if query_lower in [".quit", ".exit", "exit", "quit"]:
                    break
                elif query_lower == ".tables":
                    _show_tables_duckdb(conn)
                    continue
                elif query_lower.startswith(".schema"):
                    parts = query.strip().split(maxsplit=1)
                    table = parts[1] if len(parts) > 1 else None
                    _show_schema_duckdb(conn, table)
                    continue
                elif query_lower == ".info":
                    _display_database_info_duckdb(conn, db_path)
                    continue

                # Execute SQL query with timing
                import time

                start = time.perf_counter()
                result = conn.execute(query).fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000

                # Display results
                if result:
                    # Get column names
                    desc = conn.description
                    if desc:
                        col_names = [d[0] for d in desc]
                        # Display header
                        console.print("[cyan]" + " | ".join(col_names) + "[/cyan]")
                        console.print("[dim]" + "-" * (len(" | ".join(col_names))) + "[/dim]")

                    # Display rows
                    for row in result:
                        console.print(" | ".join(str(v) for v in row))

                    console.print(f"\n[dim]{len(result)} rows in {elapsed_ms:.2f}ms[/dim]")
                else:
                    console.print(f"[green]Query executed successfully[/green] [dim]({elapsed_ms:.2f}ms)[/dim]")

            except KeyboardInterrupt:
                console.print("\n[dim]Use .quit to exit[/dim]")
                continue
            except EOFError:
                console.print()  # Newline for clean exit
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        conn.close()
        console.print("[blue]Connection closed[/blue]")

    except Exception as e:
        console.print(f"[red]Failed to connect to DuckDB: {e}[/red]")
        sys.exit(1)


def _display_database_info_duckdb(conn: Any, db_path: str) -> None:
    """Display database information for DuckDB."""
    try:
        # Get database size
        if db_path != ":memory:":
            db_file = Path(db_path)
            if db_file.exists():
                size_mb = db_file.stat().st_size / (1024 * 1024)
                console.print(f"[dim]Database size: {size_mb:.2f} MB[/dim]")

        # Get table count and row counts
        tables = conn.execute("SHOW TABLES").fetchall()
        console.print(f"[dim]Tables: {len(tables)}[/dim]")

        if tables:
            total_rows = 0
            for (table_name,) in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    total_rows += count
                except Exception:
                    pass
            if total_rows > 0:
                console.print(f"[dim]Total rows: {total_rows:,}[/dim]")

    except Exception:
        pass  # Silently ignore errors in info display


def _show_tables_duckdb(conn: Any) -> None:
    """Show all tables in DuckDB database."""
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        if not tables:
            console.print("[yellow]No tables found[/yellow]")
            return

        console.print("\n[cyan]Tables:[/cyan]")
        for (table_name,) in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                console.print(f"  {table_name} ({count:,} rows)")
            except Exception:
                console.print(f"  {table_name}")
        console.print()

    except Exception as e:
        console.print(f"[red]Error listing tables: {e}[/red]")


def _show_schema_duckdb(conn: Any, table: str | None) -> None:
    """Show schema for table(s) in DuckDB database."""
    try:
        if table:
            # Show specific table schema
            result = conn.execute(f"DESCRIBE {table}").fetchall()
            console.print(f"\n[cyan]Schema for {table}:[/cyan]")
            for row in result:
                console.print(f"  {row[0]:30} {row[1]}")
            console.print()
        else:
            # Show all tables
            tables = conn.execute("SHOW TABLES").fetchall()
            if not tables:
                console.print("[yellow]No tables found[/yellow]")
                return

            for (table_name,) in tables:
                result = conn.execute(f"DESCRIBE {table_name}").fetchall()
                console.print(f"\n[cyan]{table_name}:[/cyan]")
                for row in result:
                    console.print(f"  {row[0]:30} {row[1]}")

    except Exception as e:
        console.print(f"[red]Error showing schema: {e}[/red]")


def _launch_sqlite_shell(database: str | None) -> None:
    """Launch SQLite interactive shell with enhanced features."""
    try:
        import sqlite3
    except ImportError:
        console.print("[red]Error: sqlite3 not available[/red]")
        sys.exit(1)

    if not database:
        console.print("[red]Error: --database required for SQLite[/red]")
        sys.exit(1)

    db_path = Path(database)
    if not db_path.exists():
        console.print(f"[yellow]Warning: Database file does not exist: {db_path}[/yellow]")
        console.print("A new database will be created")

    console.print(f"[blue]Opening SQLite shell: {db_path}[/blue]")

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row  # Enable column access by name
        cursor = conn.cursor()

        # Display database info
        _display_database_info_sqlite(conn, db_path)

        # Show available commands
        console.print("\n[dim]Commands: .quit, .tables, .schema [table], .info, SQL queries[/dim]")
        console.print("[dim]Press Ctrl+C to cancel current input, Ctrl+D or .quit to exit[/dim]\n")

        # Enhanced REPL with command history

        while True:
            try:
                query = input("sqlite> ")
                if not query.strip():
                    continue

                query_lower = query.strip().lower()

                # Handle special commands
                if query_lower in [".quit", ".exit", "exit", "quit"]:
                    break
                elif query_lower == ".tables":
                    _show_tables_sqlite(cursor)
                    continue
                elif query_lower.startswith(".schema"):
                    parts = query.strip().split(maxsplit=1)
                    table = parts[1] if len(parts) > 1 else None
                    _show_schema_sqlite(cursor, table)
                    continue
                elif query_lower == ".info":
                    _display_database_info_sqlite(conn, db_path)
                    continue

                # Execute SQL query with timing
                import time

                start = time.perf_counter()
                cursor.execute(query)
                result = cursor.fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000

                # Display results
                if result:
                    # Get column names
                    col_names = [description[0] for description in cursor.description]

                    # Display header
                    console.print("[cyan]" + " | ".join(col_names) + "[/cyan]")
                    console.print("[dim]" + "-" * (len(" | ".join(col_names))) + "[/dim]")

                    # Display rows
                    for row in result:
                        console.print(" | ".join(str(v) for v in row))

                    console.print(f"\n[dim]{len(result)} rows in {elapsed_ms:.2f}ms[/dim]")
                else:
                    console.print(f"[green]Query executed successfully[/green] [dim]({elapsed_ms:.2f}ms)[/dim]")

                conn.commit()

            except KeyboardInterrupt:
                console.print("\n[dim]Use .quit to exit[/dim]")
                continue
            except EOFError:
                console.print()  # Newline for clean exit
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        conn.close()
        console.print("[blue]Connection closed[/blue]")

    except Exception as e:
        console.print(f"[red]Failed to connect to SQLite: {e}[/red]")
        sys.exit(1)


def _display_database_info_sqlite(conn: Any, db_path: Path) -> None:
    """Display database information for SQLite."""
    try:
        # Get database size
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            console.print(f"[dim]Database size: {size_mb:.2f} MB[/dim]")

        # Get table count and row counts
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()
        console.print(f"[dim]Tables: {len(tables)}[/dim]")

        if tables:
            total_rows = 0
            for (table_name,) in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    total_rows += count
                except Exception:
                    pass
            if total_rows > 0:
                console.print(f"[dim]Total rows: {total_rows:,}[/dim]")

    except Exception:
        pass  # Silently ignore errors in info display


def _show_tables_sqlite(cursor: Any) -> None:
    """Show all tables in SQLite database."""
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()

        if not tables:
            console.print("[yellow]No tables found[/yellow]")
            return

        console.print("\n[cyan]Tables:[/cyan]")
        for (table_name,) in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                console.print(f"  {table_name} ({count:,} rows)")
            except Exception:
                console.print(f"  {table_name}")
        console.print()

    except Exception as e:
        console.print(f"[red]Error listing tables: {e}[/red]")


def _show_schema_sqlite(cursor: Any, table: str | None) -> None:
    """Show schema for table(s) in SQLite database."""
    try:
        if table:
            # Show specific table schema
            cursor.execute(f"PRAGMA table_info({table})")
            result = cursor.fetchall()

            console.print(f"\n[cyan]Schema for {table}:[/cyan]")
            for row in result:
                col_name = row[1]
                col_type = row[2]
                console.print(f"  {col_name:30} {col_type}")
            console.print()
        else:
            # Show all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()

            if not tables:
                console.print("[yellow]No tables found[/yellow]")
                return

            for (table_name,) in tables:
                cursor.execute(f"PRAGMA table_info({table_name})")
                result = cursor.fetchall()

                console.print(f"\n[cyan]{table_name}:[/cyan]")
                for row in result:
                    col_name = row[1]
                    col_type = row[2]
                    console.print(f"  {col_name:30} {col_type}")

    except Exception as e:
        console.print(f"[red]Error showing schema: {e}[/red]")


def _launch_clickhouse_shell(
    host: str | None, port: int | None, user: str | None, password: str | None, database: str | None
) -> None:
    """Launch ClickHouse interactive shell."""
    console.print("[yellow]ClickHouse shell not yet implemented[/yellow]")
    console.print("Use the ClickHouse client directly for now:")
    console.print(f"  clickhouse-client --host {host or 'localhost'} --port {port or 9000}")
    sys.exit(1)


__all__ = ["shell"]
