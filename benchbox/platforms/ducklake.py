"""DuckLake platform adapter for BenchBox benchmarking.

DuckLake is an open lakehouse table format shipped as a DuckDB extension.
Table DATA lives as Parquet on local disk or object storage; catalog
METADATA lives in a SQL database (DuckDB/SQLite/Postgres). It reuses
DuckDB's execution engine and SQL dialect unchanged:

    INSTALL ducklake; LOAD ducklake;
    ATTACH 'ducklake:<metadata_path>' AS lake (DATA_PATH '<data_path>');
    USE lake;

Catalog metadata backend is selected via the ``catalog`` platform option
(``duckdb`` default, ``sqlite``, or ``postgres``); DATA_PATH may be a local
directory or an ``s3://`` URI. See ``create_connection()`` for the per-backend
ATTACH string construction and the S3 secret setup.

For the ``postgres`` catalog backend, the target PostgreSQL DATABASE must
already exist - this adapter does not run ``CREATE DATABASE``.

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
from benchbox.utils.cloud_storage import get_cloud_path_info, is_cloud_path

from .duckdb import DuckDBAdapter, DuckDBConnectionWrapper
from .postgresql import _build_postgres_connection_kwargs

logger = logging.getLogger(__name__)

# Supported DuckLake catalog metadata backends. MySQL is deliberately excluded
# - DuckLake's own docs flag it as not recommended (compatibility issues).
_VALID_CATALOGS: tuple[str, ...] = ("duckdb", "sqlite", "postgres")

# Stable, idempotent secret name so reconnects/CREATE OR REPLACE don't
# accumulate anonymous secrets.
_S3_SECRET_NAME = "benchbox_ducklake_s3"


def _libpq_quote_value(value: str) -> str:
    """Quote/escape one libpq ``keyword=value`` component for a connection string.

    Per libpq rules, a value is wrapped in single quotes when it is empty or
    contains whitespace; backslashes and single quotes inside a quoted value
    are backslash-escaped. The composed connection string is embedded, as-is,
    inside DuckLake's single-quoted ``ducklake:postgres:...`` ATTACH literal by
    the caller, which then runs the whole string through
    ``escape_sql_string_literal()`` for the outer SQL literal - libpq's
    backslash-escaping and SQL's quote-doubling use different escape
    characters, so the two compose safely without double-unescaping.
    """
    if value == "" or any(ch.isspace() for ch in value) or "'" in value or "\\" in value:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return value


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
                help="Path to the DuckLake Parquet data directory (local path or s3:// URI)",
            )
            ducklake_group.add_argument(
                "--ducklake-catalog",
                dest="ducklake_catalog",
                type=str,
                choices=_VALID_CATALOGS,
                help="DuckLake catalog backend: duckdb, sqlite, or postgres (default: duckdb). "
                "The --platform-option catalog=... form is the primary interface; PostgreSQL "
                "catalog connection params (pg_host/pg_port/pg_database/pg_user/pg_password) and "
                "S3 credentials (s3_key_id/s3_secret/s3_region) are only available via "
                "--platform-option.",
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

        ``catalog``/PostgreSQL/S3 options are resolved via ``_resolve_option()``
        (see that helper's docstring for why: DuckLake has no registered
        ``PlatformHookRegistry`` config builder, so ``--platform-option`` values
        land only in ``config["options"]``, not as flat top-level keys).
        """
        from benchbox.utils.database_naming import generate_database_filename
        from benchbox.utils.path_utils import get_benchmark_runs_databases_path

        def _resolve_option(key: str, default: Any = None) -> Any:
            """Resolve a platform option from either the flat or nested config shape.

            Direct programmatic construction (tests, scripts, MCP tool calls)
            passes a flat dict, e.g. ``from_config({"catalog": "sqlite", ...})``.
            The real CLI ``--platform-option catalog=sqlite`` path instead
            builds a ``DatabaseConfig`` via ``PlatformHookRegistry`` whose
            *default* builder (DuckLake registers no custom one - see the "Wiring"
            note in ducklake-catalog-storage-backends.yaml) nests all
            ``--platform-option`` values under ``config["options"]`` rather than
            promoting them to top-level fields (unlike PG-family adapters, which
            use ``make_platform_config_builder``'s ``platform_fields`` promotion).
            Checking both shapes here - rather than adding a config builder -
            keeps both call paths working without pulling in credential-manager
            machinery this adapter doesn't need.
            """
            if key in config and config[key] is not None:
                return config[key]
            return (config.get("options") or {}).get(key, default)

        adapter_config: dict[str, Any] = {}

        metadata_path = config.get("ducklake_metadata_path") or _resolve_option("metadata_path")
        data_path = config.get("ducklake_data_path") or _resolve_option("data_path")

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
        # "force" (flat) is the legacy config_utils.py build_config() shape;
        # "force_recreate" (flat or nested in config["options"]) is what the
        # real --force CLI flag actually threads through as via the modern
        # PlatformHookRegistry default config builder (see _resolve_option's
        # docstring above for why nested lookups are needed at all). Check
        # both so a real --force request is never silently dropped to False.
        adapter_config["force_recreate"] = bool(config.get("force") or _resolve_option("force_recreate", False))
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

        # Catalog backend selection + PG/S3 connection params (w1-w3). The
        # argparse-style --ducklake-catalog key takes precedence over the
        # --platform-option catalog=... form, matching the metadata_path/
        # data_path precedence above.
        catalog = config.get("ducklake_catalog") or _resolve_option("catalog")
        if catalog is not None:
            adapter_config["catalog"] = catalog

        for key in ("pg_host", "pg_port", "pg_database", "pg_user", "pg_password"):
            value = _resolve_option(key)
            if value is not None:
                adapter_config[key] = value

        for key in ("s3_key_id", "s3_secret", "s3_region"):
            value = _resolve_option(key)
            if value is not None:
                adapter_config[key] = value

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

        self.catalog = self._validate_catalog(config.get("catalog", "duckdb"))

        self.metadata_path = Path(metadata_path)
        if self.catalog == "sqlite" and self.metadata_path.suffix == ".ducklake":
            # DuckLake's `ducklake:sqlite:<path>` ATTACH form expects a .sqlite
            # metadata file, not the DuckDB-file catalog's .ducklake extension.
            # The swap is UNCONDITIONAL for a .ducklake suffix under the sqlite
            # catalog: it rewrites both the default-derived filename AND an
            # explicitly-passed metadata_path that happens to end in .ducklake
            # (e.g. --ducklake-metadata-path .../x.ducklake with catalog=sqlite).
            # Any other suffix (including an explicit .sqlite) is honored as-is.
            self.metadata_path = self.metadata_path.with_suffix(".sqlite")

        # DATA_PATH may be a local directory or a cloud URI (s3:// for now).
        # Cloud paths must NOT go through Path() - it mangles "s3://bucket/x"
        # into "s3:/bucket/x" by collapsing the double slash - so keep cloud
        # data_path as a plain string and only wrap local paths in Path().
        self._data_path_is_cloud = is_cloud_path(str(data_path))
        self.data_path = str(data_path) if self._data_path_is_cloud else Path(data_path)
        # Directory creation is deliberately LAZY: __init__ (and from_config)
        # must not touch the filesystem, otherwise merely constructing an
        # adapter — e.g. in unit tests or `platforms list` — would leave stray
        # benchmark_runs/databases/ dirs behind. The parent dirs are created in
        # create_connection(), the only place that actually needs them on disk
        # (right before ATTACH), and only for backends/paths that need them
        # (skipped for the postgres catalog's metadata_path and for cloud
        # data_path - see create_connection()).

        # PostgreSQL catalog connection params (only meaningful when
        # catalog == "postgres"). Host/port/username/password defaulting
        # reuses the shared PG-family helper (_build_postgres_connection_kwargs)
        # so this doesn't duplicate PG arg-parsing/defaulting logic; only the
        # catalog DATABASE name gets a DuckLake-specific default below, since
        # the catalog DB is an operator-provisioned concern independent of
        # benchmark identity (unlike PG-family adapters' per-benchmark
        # database naming) - DuckLake's postgres ATTACH does not CREATE
        # DATABASE, so this name must already exist on the target server.
        self.pg_host: str | None = None
        self.pg_port: int | None = None
        self.pg_user: str | None = None
        self.pg_password: str | None = None
        self.pg_database: str | None = None
        if self.catalog == "postgres":
            pg_overrides = {
                key: value
                for key, value in (
                    ("host", config.get("pg_host")),
                    ("port", config.get("pg_port")),
                    ("username", config.get("pg_user")),
                    ("password", config.get("pg_password")),
                )
                if value is not None
            }
            pg_conn = _build_postgres_connection_kwargs(pg_overrides)
            self.pg_host = pg_conn["host"]
            self.pg_port = int(pg_conn["port"])
            self.pg_user = pg_conn["username"]
            self.pg_password = pg_conn["password"]
            self.pg_database = config.get("pg_database") or "ducklake_catalog"

        # S3 / cloud DATA_PATH credentials (only meaningful when data_path is
        # a cloud URI). Left None to use DuckDB's credential_chain provider
        # (env vars / profile / IMDS) unless explicit keys are supplied.
        self.s3_key_id = config.get("s3_key_id")
        self.s3_secret = config.get("s3_secret")
        self.s3_region = config.get("s3_region")

    @staticmethod
    def _validate_catalog(catalog: Any) -> str:
        """Validate and normalize the ``catalog`` platform option.

        Accepts ``duckdb`` (default), ``sqlite``, ``postgres``. Raises
        ``ValueError`` for anything else, including ``mysql`` - DuckLake's own
        docs flag it as not recommended, so BenchBox does not support it.
        """
        normalized = str(catalog or "duckdb").strip().lower()
        if normalized not in _VALID_CATALOGS:
            raise ValueError(
                f"Unsupported DuckLake catalog backend: {catalog!r}. Supported values: {', '.join(_VALID_CATALOGS)}."
            )
        return normalized

    def _build_postgres_connstring(self) -> str:
        """Build the libpq-style keyword/value string for the postgres catalog ATTACH.

        Produces ``dbname=... host=... user=... password=... port=...``
        (omitting any component that is unset), individually libpq-quoted via
        ``_libpq_quote_value()``. The caller embeds this, as-is, into the
        DuckLake ATTACH literal.
        """
        components: list[tuple[str, Any]] = [
            ("dbname", self.pg_database),
            ("host", self.pg_host),
            ("user", self.pg_user),
            ("password", self.pg_password),
            ("port", self.pg_port),
        ]
        parts = [f"{key}={_libpq_quote_value(str(value))}" for key, value in components if value not in (None, "")]
        return " ".join(parts)

    def _build_catalog_attach_target(self) -> str:
        """Build the string that follows ``ducklake:`` in the ATTACH literal.

        Per-backend forms:
          - duckdb (default): the bare metadata_path (unchanged from the MVP
            adapter's ``ducklake:<metadata_path>``).
          - sqlite: ``sqlite:<metadata_path>`` (metadata_path is already
            resolved to a ``.sqlite`` file by ``__init__`` for the
            default-derived-filename case).
          - postgres: ``postgres:<libpq connection string>``.

        A pure function of already-resolved instance state (no I/O), so it is
        unit-testable directly against a constructed adapter without a live
        DuckDB connection.
        """
        if self.catalog == "duckdb":
            return str(self.metadata_path)
        if self.catalog == "sqlite":
            return f"sqlite:{self.metadata_path}"
        if self.catalog == "postgres":
            return f"postgres:{self._build_postgres_connstring()}"
        # Unreachable: _validate_catalog() already rejects anything else.
        raise ValueError(f"Unsupported DuckLake catalog backend: {self.catalog!r}")  # pragma: no cover

    def _build_s3_secret_sql(self) -> str:
        """Build the ``CREATE OR REPLACE SECRET`` statement for S3 DATA_PATH access.

        Defaults to the ``credential_chain`` provider (DuckDB's httpfs
        extension then discovers credentials the same way the AWS CLI does -
        env vars, shared profile, IMDS, etc. - so no credentials are required
        for local/CI runs against a bucket reachable via ambient AWS auth).
        Uses explicit ``KEY_ID``/``SECRET``/``REGION`` only when both
        ``s3_key_id`` and ``s3_secret`` were supplied via ``--platform-option``.
        ``CREATE OR REPLACE`` keeps this idempotent across reconnects.
        """
        if self.s3_key_id and self.s3_secret:
            parts = [
                f"KEY_ID '{escape_sql_string_literal(self.s3_key_id)}'",
                f"SECRET '{escape_sql_string_literal(self.s3_secret)}'",
            ]
            if self.s3_region:
                parts.append(f"REGION '{escape_sql_string_literal(self.s3_region)}'")
            return f"CREATE OR REPLACE SECRET {_S3_SECRET_NAME} (TYPE s3, {', '.join(parts)})"
        return f"CREATE OR REPLACE SECRET {_S3_SECRET_NAME} (TYPE s3, PROVIDER credential_chain)"

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

        Known limitation (postgres catalog): this reuse/force detection is keyed
        off the local ``metadata_path`` file, which only exists for the
        duckdb/sqlite catalog backends. For ``catalog == "postgres"`` the
        catalog metadata lives entirely server-side, so this always takes the
        "does not exist yet" branch (fresh-run assumption) regardless of
        whether the target PostgreSQL database already has DuckLake tables in
        it, and ``--force`` does not clear a postgres-backed catalog. Re-running
        against a populated PostgreSQL catalog can therefore hit "table already
        exists" from the inherited plain ``CREATE TABLE``; use a fresh/dedicated
        ``pg_database`` per run until this gets proper remote-catalog detection.
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

        Removes the DuckDB-file/sqlite catalog metadata file (and any sidecar
        files DuckDB writes next to it, e.g. a ``.wal``) and recursively clears
        the Parquet ``DATA_PATH`` directory when it is local. Cloud (e.g. s3://)
        DATA_PATH is left untouched - clearing a bucket prefix is out of scope
        here; see ``create_connection()``'s S3 secret handling for the cloud
        DATA_PATH path.
        """
        # Remove the catalog metadata file plus any sidecars sharing its name
        # prefix (e.g. "<catalog>.ducklake.wal"). Only reachable when
        # metadata_path.exists() was already True (checked by the caller,
        # handle_existing_database), which for a local duckdb/sqlite catalog
        # implies its parent dir exists too.
        for sidecar in sorted(self.metadata_path.parent.glob(self.metadata_path.name + "*")):
            if sidecar.is_file():
                try:
                    sidecar.unlink()
                except OSError as exc:
                    logger.debug("Could not remove DuckLake catalog file %s: %s", sidecar, exc)

        # Recursively clear the Parquet data directory contents (local only).
        if not self._data_path_is_cloud and self.data_path.exists():
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
        # Skipped for backends/paths that have nothing local to create: the
        # postgres catalog has no metadata_path file, and a cloud data_path
        # (s3://...) is not a local mkdir target.
        if self.catalog in ("duckdb", "sqlite"):
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._data_path_is_cloud:
            self.data_path.mkdir(parents=True, exist_ok=True)

        data_path_is_cloud = self._data_path_is_cloud
        if data_path_is_cloud:
            cloud_info = get_cloud_path_info(str(self.data_path))
            self.log_verbose(
                f"DuckLake DATA_PATH is a cloud path: {cloud_info['provider']} bucket "
                f"'{cloud_info['bucket']}' (credential_chain provider unless s3_key_id/"
                f"s3_secret were supplied)"
            )
        escaped_data_path = escape_sql_string_literal(str(self.data_path))

        try:
            setup_conn.execute("INSTALL ducklake")
            setup_conn.execute("LOAD ducklake")

            # Catalog-backend-specific extension (tolerant INSTALL/LOAD idiom,
            # mirrors duckdb.py's _try_delta_scan/_try_iceberg_scan). No extra
            # extension is needed for the default duckdb-file catalog.
            if self.catalog == "sqlite":
                setup_conn.execute("INSTALL sqlite")
                setup_conn.execute("LOAD sqlite")
            elif self.catalog == "postgres":
                setup_conn.execute("INSTALL postgres")
                setup_conn.execute("LOAD postgres")
                self.log_verbose(
                    f"DuckLake postgres catalog: host={self.pg_host} port={self.pg_port} "
                    f"database={self.pg_database} (must already exist - DuckLake does not "
                    "CREATE DATABASE)"
                )

            # Cloud DATA_PATH: httpfs + an S3 secret, created BEFORE ATTACH so
            # the ATTACH's initial catalog/DATA_PATH validation can already
            # reach the bucket. Local runs never touch this branch, so no S3
            # credentials are required for the default/local path.
            if data_path_is_cloud:
                setup_conn.execute("INSTALL httpfs")
                setup_conn.execute("LOAD httpfs")
                try:
                    setup_conn.execute(self._build_s3_secret_sql())
                except Exception as secret_exc:
                    # Redact: never let explicit key/secret material reach an
                    # exception message or log line.
                    using_explicit_creds = bool(self.s3_key_id and self.s3_secret)
                    raise RuntimeError(
                        "Failed to create the DuckDB S3 secret for DuckLake DATA_PATH "
                        f"(provider={'explicit key/secret' if using_explicit_creds else 'credential_chain'}). "
                        f"Underlying error type: {type(secret_exc).__name__}."
                        + ("" if using_explicit_creds else f" Underlying error: {secret_exc}")
                    ) from None

            attach_target = self._build_catalog_attach_target()
            escaped_attach_target = escape_sql_string_literal(attach_target)
            setup_conn.execute(f"ATTACH 'ducklake:{escaped_attach_target}' AS lake (DATA_PATH '{escaped_data_path}')")
            setup_conn.execute("USE lake")
        except Exception as e:
            try:
                setup_conn.close()
            except Exception:
                logger.debug("Failed to close base connection after DuckLake ATTACH failure", exc_info=True)
            raise RuntimeError(
                "Failed to initialize the DuckLake catalog (INSTALL/LOAD/ATTACH "
                f"'ducklake' extension, catalog={self.catalog}). DuckLake requires "
                f"DuckDB >= 1.3; detected DuckDB version: {live_version or 'unknown'}. "
                f"metadata_path={self.metadata_path if self.catalog != 'postgres' else '(postgres catalog - N/A)'}, "
                f"data_path={self.data_path}. Underlying error: {e}"
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
        platform_info["catalog_backend"] = self.catalog
        platform_info["metadata_path"] = str(self.metadata_path)
        platform_info["data_path"] = str(self.data_path)
        platform_info["data_path_is_cloud"] = self._data_path_is_cloud
        platform_info["configuration"]["catalog_backend"] = self.catalog
        platform_info["configuration"]["metadata_path"] = str(self.metadata_path)
        platform_info["configuration"]["data_path"] = str(self.data_path)
        platform_info["configuration"]["data_path_is_cloud"] = self._data_path_is_cloud
        if self.catalog == "postgres":
            platform_info["configuration"]["pg_host"] = self.pg_host
            platform_info["configuration"]["pg_port"] = self.pg_port
            platform_info["configuration"]["pg_database"] = self.pg_database
            # Deliberately not exposing pg_user/pg_password here.

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
