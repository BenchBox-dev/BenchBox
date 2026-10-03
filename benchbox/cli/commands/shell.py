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
    extension_to_platform = {
        ".duckdb": "duckdb",
        ".sqlite": "sqlite",
        ".chdb": "clickhouse",
        ".datafusion": "datafusion",
        ".polars": "polars",
        ".pandas": "pandas",
        ".polars-df": "polars-df",
        ".pandas-df": "pandas-df",
        ".cudf-df": "cudf-df",
        ".dask-df": "dask-df",
        ".cudf": "cudf",
        ".spark": "spark",
    }

    ext_lower = extension.lower()
    return extension_to_platform.get(ext_lower, "unknown")


def discover_local_databases(base_dir: Path | None = None) -> list[dict[str, Any]]:
    dir_mgr = DirectoryManager(base_dir=str(base_dir) if base_dir else None)

    databases = []

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
        ".dask-df",
        ".cudf",
        ".spark",
    ]

    search_locations = []
    for ext in supported_extensions:
        search_locations.append((dir_mgr.datagen_dir, f"**/*{ext}"))
        search_locations.append((dir_mgr.databases_dir, f"*{ext}"))

    for search_dir, pattern in search_locations:
        if not search_dir.exists():
            continue

        for db_path in search_dir.glob(pattern):
            if not db_path.is_file():
                continue

            metadata = parse_database_name(db_path.name)

            platform = _get_platform_from_extension(db_path.suffix)

            stat = db_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            modified = datetime.fromtimestamp(stat.st_mtime)

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

    databases.sort(key=lambda d: d["modified"], reverse=True)

    return databases


def filter_databases(
    databases: list[dict[str, Any]],
    platform: str | None = None,
    benchmark: str | None = None,
    scale: float | None = None,
) -> list[dict[str, Any]]:
    from benchbox.utils.scale_factor import format_scale_factor

    filtered = databases

    if platform:
        platform_lower = platform.lower()
        filtered = [db for db in filtered if db["platform"] == platform_lower]

    if benchmark:
        benchmark_lower = benchmark.lower()
        filtered = [db for db in filtered if db["benchmark"].lower() == benchmark_lower]

    if scale is not None:
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
    if not databases:
        return None

    if len(databases) == 1:
        console.print(f"[green]Using database: {databases[0]['path']}[/green]")
        return databases[0]

    display_database_table(databases)

    console.print("\n[dim]Enter database number, or press Ctrl+C to cancel[/dim]")

    try:
        selection = Prompt.ask(
            "Select database",
            default="1",
            show_default=True,
        )

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


@click.command(
    "shell",
    help=(
        "Launch an interactive SQL shell for a database platform.\n"
        "\n"
        "Opens an interactive SQL prompt connected to the specified platform,\n"
        "useful for debugging queries, inspecting benchmark data, and exploring\n"
        "database state after benchmark execution.\n"
        "\n"
        "Supports automatic database discovery from benchmark_runs/datagen/ or\n"
        "a custom output directory. Can filter by benchmark name and scale factor.\n"
        "\n"
        "Supported platforms: DuckDB, SQLite, ClickHouse (more coming soon)\n"
        "\n"
        "\b\n"
        "Examples:\n"
        "    # Interactive selection from available databases\n"
        "    benchbox shell\n"
        "\n"
        "\b\n"
        "    # List available databases\n"
        "    benchbox shell --list\n"
        "\n"
        "\b\n"
        "    # Connect to most recent database\n"
        "    benchbox shell --last\n"
        "\n"
        "\b\n"
        "    # Filter and select\n"
        "    benchbox shell --benchmark tpch --scale 1.0\n"
        "\n"
        "\b\n"
        "    # Direct connection\n"
        "    benchbox shell --platform duckdb --database benchmark.duckdb\n"
        "\n"
        "\b\n"
        "    # Use database from specific output directory\n"
        "    benchbox shell --output benchmark_runs/results/tpch_20250101_120000\n"
        "\n"
        "\b\n"
        "    # ClickHouse shell\n"
        "    benchbox shell --platform clickhouse --host localhost --port 9000 \\\n"
        "      --user default --database benchbox"
    ),
)
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
    base_dir = Path(output) if output else None

    if database:
        _shell_direct_connection(database, platform, host, port, user, password)
        return

    if platform and platform.lower() in {"clickhouse", "clickhouse-server"}:
        _launch_clickhouse_shell(host, port, user, password, database)
        return

    filtered = _shell_discover_databases(base_dir, output, platform, benchmark, scale)

    if list_only:
        display_database_table(filtered)
        return

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
    if platform == "duckdb":
        _launch_duckdb_shell(db_path)
    elif platform == "sqlite":
        _launch_sqlite_shell(db_path)
    else:
        console.print(f"[red]Error: Platform '{platform}' not supported[/red]")
        sys.exit(1)


def _launch_duckdb_shell(database: str | None) -> None:
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

        _display_database_info_duckdb(conn, db_path)

        console.print("\n[dim]Commands: .quit, .tables, .schema [table], .info, SQL queries[/dim]")
        console.print("[dim]Press Ctrl+C to cancel current input, Ctrl+D or .quit to exit[/dim]\n")

        while True:
            try:
                query = input("duckdb> ")
                if not query.strip():
                    continue

                query_lower = query.strip().lower()

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

                import time

                start = time.perf_counter()
                result = conn.execute(query).fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000

                if result:
                    desc = conn.description
                    if desc:
                        col_names = [d[0] for d in desc]
                        console.print("[cyan]" + " | ".join(col_names) + "[/cyan]")
                        console.print("[dim]" + "-" * (len(" | ".join(col_names))) + "[/dim]")

                    for row in result:
                        console.print(" | ".join(str(v) for v in row))

                    console.print(f"\n[dim]{len(result)} rows in {elapsed_ms:.2f}ms[/dim]")
                else:
                    console.print(f"[green]Query executed successfully[/green] [dim]({elapsed_ms:.2f}ms)[/dim]")

            except KeyboardInterrupt:
                console.print("\n[dim]Use .quit to exit[/dim]")
                continue
            except EOFError:
                console.print()
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        conn.close()
        console.print("[blue]Connection closed[/blue]")

    except Exception as e:
        console.print(f"[red]Failed to connect to DuckDB: {e}[/red]")
        sys.exit(1)


def _display_database_info_duckdb(conn: Any, db_path: str) -> None:
    try:
        if db_path != ":memory:":
            db_file = Path(db_path)
            if db_file.exists():
                size_mb = db_file.stat().st_size / (1024 * 1024)
                console.print(f"[dim]Database size: {size_mb:.2f} MB[/dim]")

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
        pass


def _show_tables_duckdb(conn: Any) -> None:
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
    try:
        if table:
            result = conn.execute(f"DESCRIBE {table}").fetchall()
            console.print(f"\n[cyan]Schema for {table}:[/cyan]")
            for row in result:
                console.print(f"  {row[0]:30} {row[1]}")
            console.print()
        else:
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
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        _display_database_info_sqlite(conn, db_path)

        console.print("\n[dim]Commands: .quit, .tables, .schema [table], .info, SQL queries[/dim]")
        console.print("[dim]Press Ctrl+C to cancel current input, Ctrl+D or .quit to exit[/dim]\n")

        while True:
            try:
                query = input("sqlite> ")
                if not query.strip():
                    continue

                query_lower = query.strip().lower()

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

                import time

                start = time.perf_counter()
                cursor.execute(query)
                result = cursor.fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000

                if result:
                    col_names = [description[0] for description in cursor.description]

                    console.print("[cyan]" + " | ".join(col_names) + "[/cyan]")
                    console.print("[dim]" + "-" * (len(" | ".join(col_names))) + "[/dim]")

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
                console.print()
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        conn.close()
        console.print("[blue]Connection closed[/blue]")

    except Exception as e:
        console.print(f"[red]Failed to connect to SQLite: {e}[/red]")
        sys.exit(1)


def _display_database_info_sqlite(conn: Any, db_path: Path) -> None:
    try:
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            console.print(f"[dim]Database size: {size_mb:.2f} MB[/dim]")

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
        pass


def _show_tables_sqlite(cursor: Any) -> None:
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
    try:
        if table:
            cursor.execute(f"PRAGMA table_info({table})")
            result = cursor.fetchall()

            console.print(f"\n[cyan]Schema for {table}:[/cyan]")
            for row in result:
                col_name = row[1]
                col_type = row[2]
                console.print(f"  {col_name:30} {col_type}")
            console.print()
        else:
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
    console.print("[yellow]ClickHouse shell not yet implemented[/yellow]")
    console.print("Use the ClickHouse client directly for now:")
    console.print(f"  clickhouse-client --host {host or 'localhost'} --port {port or 9000}")
    sys.exit(1)


__all__ = ["shell"]
