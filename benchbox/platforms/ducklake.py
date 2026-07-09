"""DuckLake platform adapter for BenchBox benchmarking.

DuckLake is an open lakehouse table format shipped as a DuckDB extension.
Table DATA lives as Parquet on local disk or object storage; catalog
METADATA lives in a SQL database (DuckDB/SQLite/Postgres). It reuses
DuckDB's execution engine and SQL dialect unchanged:

    INSTALL ducklake; LOAD ducklake;
    ATTACH 'ducklake:<metadata_path>' AS lake (DATA_PATH '<data_path>');
    USE lake;

This MVP adapter supports the DuckDB-file catalog + local Parquet storage
combination only. SQLite/Postgres catalogs and S3-backed DATA_PATH are a
follow-on scope.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from benchbox.core.config_inheritance import resolve_dialect_for_query_translation
from benchbox.platforms.base.data_loading import escape_sql_string_literal

from .duckdb import DuckDBAdapter, DuckDBConnectionWrapper

logger = logging.getLogger(__name__)

# DuckLake's DuckDB extension requires DuckDB >= 1.3. The global pyproject
# duckdb pin stays <2.0 for duckdb-wasm on-disk-format compatibility
# (pyproject.toml:90-94), so this floor is enforced at runtime here instead.
_MIN_DUCKDB_VERSION_FOR_DUCKLAKE: tuple[int, int] = (1, 3)

_VERSION_PREFIX_RE = re.compile(r"(\d+)\.(\d+)")


def _parse_duckdb_major_minor(version: Any) -> tuple[int, int] | None:
    """Parse the leading MAJOR.MINOR components from a DuckDB version string.

    Accepts forms like "1.3.2", "v1.3.2", "1.3", or "1.4.0-dev123". Returns
    None if no leading MAJOR.MINOR pattern can be found.
    """
    if not version:
        return None
    text = str(version).strip()
    if text.startswith("v") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    match = _VERSION_PREFIX_RE.match(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _duckdb_version_supports_ducklake(version: Any) -> bool:
    """Return True if *version* is >= the DuckLake minimum DuckDB version (1.3)."""
    parsed = _parse_duckdb_major_minor(version)
    if parsed is None:
        return False
    return parsed >= _MIN_DUCKDB_VERSION_FOR_DUCKLAKE


class _DuckLakeCursorConnection:
    """Wrap a DuckDB connection so every cursor() defaults to the DuckLake catalog.

    DuckDB's ``.cursor()`` starts a fresh session whose current catalog is the
    base ``memory``/file catalog, NOT the ATTACHed DuckLake catalog — even though
    the parent connection ran ``USE lake``. Framework seams that validate/inspect
    via ``connection.cursor()`` (e.g. phase_tracking._validate_data_integrity's
    accessibility probe, and any row-count/integrity check) would then fail to
    resolve unqualified table names that live in ``lake.main``. Re-applying
    ``USE <catalog>`` to each new cursor makes unqualified names resolve to the
    DuckLake catalog uniformly, matching the parent connection.

    Everything else (``execute``/``executemany``/``close``/``commit``/``sql``/...)
    delegates to the parent connection via ``__getattr__``, so the query
    execution and plan-capture paths — which run on the parent that already has
    ``USE lake`` — are unchanged; only ``.cursor()`` is specialized.
    """

    def __init__(self, connection: Any, catalog: str = "lake") -> None:
        self._connection = connection
        self._ducklake_catalog = catalog

    def cursor(self) -> Any:
        cur = self._connection.cursor()
        # ``catalog`` is the fixed "lake" literal we control — no injection risk.
        cur.execute(f"USE {self._ducklake_catalog}")
        return cur

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _unwrap_duckdb_connection(connection: Any) -> Any:
    """Return the underlying raw DuckDB connection behind any BenchBox wrappers.

    Walks ``._connection`` through the DuckLake cursor wrapper and the dry-run
    ``DuckDBConnectionWrapper`` (which may be nested) until it reaches a
    non-wrapper connection.
    """
    conn = connection
    while isinstance(conn, (_DuckLakeCursorConnection, DuckDBConnectionWrapper)):
        conn = conn._connection
    return conn


class DuckLakeAdapter(DuckDBAdapter):
    """DuckLake platform adapter - DuckDB engine with an attached lakehouse catalog.

    Extends DuckDBAdapter by loading the ``ducklake`` extension and
    ``ATTACH``-ing a DuckLake catalog (DuckDB-file metadata + local Parquet
    ``DATA_PATH``) as the active catalog before schema creation / data
    loading / query execution. Because DuckLake reuses DuckDB's SQL dialect
    unchanged, every other DuckDBAdapter behavior (schema creation, data
    loading, query execution, plan capture, tuning) is inherited as-is.

    Requires a live DuckDB runtime >= 1.3 (the ``ducklake`` extension is not
    available on earlier DuckDB releases). This is enforced at connection
    time regardless of the driver version pinned in pyproject.toml.
    """

    # Declared explicitly (not just inherited from DuckDBAdapter) because
    # test_plan_capture_phase_eligibility.py requires every concrete
    # registered adapter to state this on its own class body. DuckLake reuses
    # DuckDBAdapter's EXPLAIN-based plan capture unchanged, so this mirrors
    # DuckDBAdapter's value.
    plan_capture_phase_eligible = True

    @property
    def platform_name(self) -> str:
        return "DuckLake"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add DuckLake-specific CLI arguments."""
        if not hasattr(parser, "add_argument_group"):
            return
        try:
            ducklake_group = parser.add_argument_group("DuckLake Arguments")
            ducklake_group.add_argument(
                "--ducklake-metadata-path",
                dest="ducklake_metadata_path",
                type=str,
                help="Path to the DuckLake catalog metadata file (.ducklake)",
            )
            ducklake_group.add_argument(
                "--ducklake-data-path",
                dest="ducklake_data_path",
                type=str,
                help="Path to the DuckLake Parquet data directory",
            )
        except argparse.ArgumentError as exc:
            # Don't hide a genuine argparse registration failure (e.g. an
            # option-string collision): surface it at debug level instead of
            # swallowing it silently.
            logger.debug("Failed to register DuckLake CLI arguments: %s", exc)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DuckLakeAdapter:
        """Create DuckLake adapter from unified configuration.

        Resolves ``metadata_path``/``data_path`` with precedence: explicit
        argparse-style keys (``ducklake_metadata_path``/``ducklake_data_path``)
        > normalized keys (``metadata_path``/``data_path``) > generated
        defaults under ``benchmark_runs/databases/``.
        """
        from benchbox.utils.database_naming import generate_database_filename
        from benchbox.utils.path_utils import get_benchmark_runs_databases_path

        adapter_config: dict[str, Any] = {}

        metadata_path = config.get("ducklake_metadata_path") or config.get("metadata_path")
        data_path = config.get("ducklake_data_path") or config.get("data_path")

        if not metadata_path or not data_path:
            if config.get("output_dir"):
                data_dir = get_benchmark_runs_databases_path(
                    config["benchmark"],
                    config["scale_factor"],
                    base_dir=Path(config["output_dir"]) / "databases",
                )
            else:
                data_dir = get_benchmark_runs_databases_path(config["benchmark"], config["scale_factor"])

            db_filename = generate_database_filename(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="ducklake",
                tuning_config=config.get("tuning_config"),
            )

            if not metadata_path:
                metadata_path = str(data_dir / db_filename)
            if not data_path:
                # Sibling "ducklake_data/" dir, namespaced per run (by the
                # generated filename stem) so concurrent benchmark/scale/tuning
                # combinations sharing the same databases dir don't collide.
                data_path = str(data_dir / "ducklake_data" / Path(db_filename).stem)

        adapter_config["metadata_path"] = metadata_path
        adapter_config["data_path"] = data_path

        # Pass through DuckDB-family configuration (base DuckDB connection
        # settings for the "shell" connection the DuckLake catalog attaches to).
        adapter_config["memory_limit"] = config.get("memory_limit", "4GB")
        adapter_config["force_recreate"] = config.get("force", False)
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]
        for key in [
            "driver_package",
            "driver_version",
            "driver_version_requested",
            "driver_version_resolved",
            "driver_version_actual",
            "driver_runtime_strategy",
            "driver_runtime_path",
            "driver_runtime_python_executable",
            "driver_auto_install",
            "driver_auto_install_used",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        metadata_path = config.get("metadata_path")
        data_path = config.get("data_path")
        if not metadata_path or not data_path:
            # Direct construction without from_config() (e.g. unit tests /
            # ad-hoc scripting). Fall back to a scratch location so the
            # adapter is still usable without requiring callers to compute
            # paths themselves.
            from benchbox.utils.path_utils import get_benchmark_runs_databases_path

            fallback_dir = get_benchmark_runs_databases_path("ducklake", 1.0)
            metadata_path = metadata_path or str(fallback_dir / "ducklake.ducklake")
            data_path = data_path or str(fallback_dir / "ducklake_data" / "default")

        self.metadata_path = Path(metadata_path)
        self.data_path = Path(data_path)
        # Directory creation is deliberately LAZY: __init__ (and from_config)
        # must not touch the filesystem, otherwise merely constructing an
        # adapter — e.g. in unit tests or `platforms list` — would leave stray
        # benchmark_runs/databases/ dirs behind. The parent dirs are created in
        # create_connection(), the only place that actually needs them on disk
        # (right before ATTACH).

    def get_target_dialect(self) -> str:
        """Get the SQL dialect for query translation.

        DuckLake reuses DuckDB's SQL dialect unchanged, inherited via the
        duckdb platform family (see platform_registry.py's ducklake entry).
        """
        return resolve_dialect_for_query_translation("ducklake")

    def handle_existing_database(self, **connection_config) -> None:
        """Force-recreate / reuse-detect against the on-disk DuckLake catalog.

        The base shell connection is ``:memory:``, so the inherited
        ``handle_existing_database`` (connection_lifecycle.py) early-returns for
        in-memory databases and never touches DuckLake's real persistence unit
        — the catalog metadata file (``metadata_path``) plus the Parquet
        ``DATA_PATH`` (``data_path``). Without this override ``--force`` would be
        a silent no-op and re-running the same benchmark/scale/tuning would
        ATTACH the already-populated ``lake`` catalog, so the inherited
        ``create_schema``'s plain ``CREATE TABLE`` (no ``IF NOT EXISTS``) would
        raise "table already exists".

        - force_recreate + catalog exists: delete metadata_path and clear
          data_path so ATTACH rebuilds a fresh catalog (database_was_reused=False).
        - no force + catalog exists: reuse it (database_was_reused=True). The
          runner then takes the reused-database phase path — schema creation and
          data loading are skipped and queries run against the existing catalog.
          Pass ``--force`` to wipe the catalog + data dir for a clean rebuild.
        """
        if self.dry_run:
            # Never mutate on-disk artifacts during a dry run.
            self.log_verbose("DuckLake catalog validation skipped (dry run mode)")
            return

        if not self.metadata_path.exists():
            self.log_very_verbose("DuckLake catalog does not exist yet - nothing to handle")
            return

        if self.force_recreate:
            self.log_verbose(f"Force recreate enabled - removing existing DuckLake catalog: {self.metadata_path}")
            self._reset_ducklake_catalog()
            self.database_was_reused = False
            return

        # Existing catalog, no force: reuse it. Setting database_was_reused=True
        # routes the runner down the reused-database phase path, so schema
        # creation and data loading are skipped and queries run against the
        # already-populated catalog. Pass --force for a clean rebuild instead.
        self.log_verbose(
            f"Existing DuckLake catalog found at {self.metadata_path} - reusing it (pass --force for a clean rebuild)"
        )
        self.database_was_reused = True

    def _reset_ducklake_catalog(self) -> None:
        """Delete the on-disk DuckLake catalog so a subsequent ATTACH rebuilds it.

        Removes the DuckDB-file catalog metadata file (and any sidecar files
        DuckDB writes next to it, e.g. a ``.wal``) and recursively clears the
        Parquet ``DATA_PATH`` directory.
        """
        # Remove the catalog metadata file plus any sidecars sharing its name
        # prefix (e.g. "<catalog>.ducklake.wal").
        for sidecar in sorted(self.metadata_path.parent.glob(self.metadata_path.name + "*")):
            if sidecar.is_file():
                try:
                    sidecar.unlink()
                except OSError as exc:
                    logger.debug("Could not remove DuckLake catalog file %s: %s", sidecar, exc)

        # Recursively clear the Parquet data directory contents.
        if self.data_path.exists():
            shutil.rmtree(self.data_path, ignore_errors=True)

    def create_connection(self, **connection_config) -> Any:
        """Create a DuckDB connection and attach the DuckLake catalog.

        Delegates to DuckDBAdapter.create_connection() for the base DuckDB
        connection/settings, then installs the ``ducklake`` extension and
        ATTACHes the DuckLake catalog as ``lake``, making it the active
        catalog via ``USE lake``. All subsequent DDL/DML issued by the
        inherited DuckDBAdapter methods (create_schema, load_data,
        execute_query, ...) is unqualified SQL, so it targets ``lake`` once
        attached (see w3 note on create_schema/load_data below).

        Note: even in dry-run / SQL-capture mode this runs a real
        INSTALL/LOAD/ATTACH, so a live DuckDB >= 1.3 runtime (and network
        access for the first INSTALL) is a deliberate prerequisite of dry-run
        mode — the attached ``lake`` catalog is what makes captured DDL/DML
        resolve against DuckLake rather than the base ``main`` catalog.
        """
        conn = super().create_connection(**connection_config)

        # DuckDBAdapter.create_connection() returns a DuckDBConnectionWrapper
        # when self.dry_run_mode is True (duckdb.py create_connection, near
        # the end) so that *benchmarked* SQL is captured instead of executed.
        # The INSTALL/LOAD/ATTACH/USE statements below are connection setup,
        # not benchmarked statements: they must run for real even in
        # dry-run mode, otherwise `USE lake` never happens and dry-run SQL
        # capture would reflect an unattached `main` catalog. Wrapper.execute
        # would intercept and capture them like ordinary queries, so unwrap
        # to the real underlying connection for setup; DuckDBConnectionWrapper
        # already delegates other attribute access transparently via
        # __getattr__, but .execute is explicitly overridden, hence the
        # explicit unwrap here rather than relying on that delegation.
        setup_conn = conn._connection if isinstance(conn, DuckDBConnectionWrapper) else conn

        live_version = self.driver_version_actual or getattr(self._duckdb_module, "__version__", None)
        if not _duckdb_version_supports_ducklake(live_version):
            # super().create_connection() already opened the base connection;
            # close it before raising so the guard-reject path doesn't leak it.
            try:
                setup_conn.close()
            except Exception:
                logger.debug("Failed to close base connection on DuckLake version-guard reject", exc_info=True)
            raise RuntimeError(
                "DuckLake requires DuckDB >= 1.3 (the 'ducklake' extension is not "
                f"available on earlier releases). Detected DuckDB version: "
                f"{live_version or 'unknown'}. Use a duckdb>=1.3 environment "
                "(e.g. `uv add 'duckdb>=1.3,<2.0'` or --driver-version 1.3.2)."
            )

        # Lazily create the catalog parent dir + Parquet DATA_PATH right before
        # ATTACH (the only place they must exist on disk). __init__/from_config
        # intentionally do not, to avoid stray dirs from adapter construction.
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.mkdir(parents=True, exist_ok=True)

        escaped_metadata_path = escape_sql_string_literal(str(self.metadata_path))
        escaped_data_path = escape_sql_string_literal(str(self.data_path))

        try:
            setup_conn.execute("INSTALL ducklake")
            setup_conn.execute("LOAD ducklake")
            setup_conn.execute(f"ATTACH 'ducklake:{escaped_metadata_path}' AS lake (DATA_PATH '{escaped_data_path}')")
            setup_conn.execute("USE lake")
        except Exception as e:
            try:
                setup_conn.close()
            except Exception:
                logger.debug("Failed to close base connection after DuckLake ATTACH failure", exc_info=True)
            raise RuntimeError(
                "Failed to initialize the DuckLake catalog (INSTALL/LOAD/ATTACH "
                "'ducklake' extension). DuckLake requires DuckDB >= 1.3; detected "
                f"DuckDB version: {live_version or 'unknown'}. "
                f"metadata_path={self.metadata_path}, data_path={self.data_path}. "
                f"Underlying error: {e}"
            ) from e

        # Wrap so that framework seams calling connection.cursor() (e.g.
        # phase_tracking._validate_data_integrity's accessibility probe) get a
        # cursor scoped to the DuckLake catalog. A fresh DuckDB cursor's current
        # catalog is the base memory/file catalog, not the ATTACHed lake, so
        # unqualified names in lake.main would otherwise fail to resolve. The
        # wrapper composes on top of either a raw connection or a dry-run
        # DuckDBConnectionWrapper; execute/close/etc. delegate to the parent
        # (which has USE lake), so only .cursor() is specialized.
        return _DuckLakeCursorConnection(conn)

    # w3: no create_schema/load_data override needed. DuckDBAdapter.create_schema
    # (duckdb.py) issues unqualified `CREATE TABLE {table}` and
    # base/data_loading.py's DataLoader issues unqualified `INSERT INTO {table}`
    # (and DuckDBParquetHandler/DuckDBNativeHandler follow the same pattern).
    # Neither qualifies statements with `main.`, so after `USE lake` in
    # create_connection() above, DuckDB resolves these unqualified names
    # against the current catalog/schema search path, i.e. `lake.main`, not
    # the base `main` catalog of the underlying :memory:/file connection.
    # Adding an override here would be redundant with inherited behavior.

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get DuckLake platform information."""
        platform_info = super().get_platform_info(connection)

        platform_info["platform_type"] = "ducklake"
        platform_info["platform_name"] = self.platform_name
        platform_info["catalog_backend"] = "duckdb"
        platform_info["metadata_path"] = str(self.metadata_path)
        platform_info["data_path"] = str(self.data_path)
        platform_info["configuration"]["catalog_backend"] = "duckdb"
        platform_info["configuration"]["metadata_path"] = str(self.metadata_path)
        platform_info["configuration"]["data_path"] = str(self.data_path)

        if connection is not None:
            # Unwrap both the DuckLake cursor wrapper and any dry-run
            # DuckDBConnectionWrapper so the probe runs on the real connection.
            probe_conn = _unwrap_duckdb_connection(connection)
            try:
                row = probe_conn.execute(
                    "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'ducklake'"
                ).fetchone()
                if row and row[0]:
                    platform_info["ducklake_extension_version"] = row[0]
            except Exception:
                logger.debug("Could not probe ducklake extension version", exc_info=True)

        return platform_info


__all__ = ["DuckLakeAdapter"]
