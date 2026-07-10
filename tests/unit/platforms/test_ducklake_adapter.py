"""Unit tests for the DuckLake platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.config_inheritance import resolve_dialect_for_query_translation
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms.base.data_loading import escape_sql_string_literal
from benchbox.platforms.ducklake import (
    DuckLakeAdapter,
    _duckdb_version_supports_ducklake,
    _libpq_quote_value,
    _parse_duckdb_major_minor,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDuckLakeVersionGuard:
    """Test the DuckDB >= 1.3 runtime version parser/guard used by DuckLake."""

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("1.3.2", (1, 3)),
            ("1.4.0", (1, 4)),
            ("1.2.0", (1, 2)),
            ("v1.3.2", (1, 3)),
            ("1.3", (1, 3)),
            ("1.4.0-dev123", (1, 4)),
        ],
    )
    def test_parse_major_minor(self, version, expected):
        assert _parse_duckdb_major_minor(version) == expected

    @pytest.mark.parametrize("bad_version", [None, "", "not-a-version", "v"])
    def test_parse_major_minor_rejects_unparseable(self, bad_version):
        assert _parse_duckdb_major_minor(bad_version) is None

    @pytest.mark.parametrize(
        "version,supported",
        [
            ("1.2.0", False),
            ("1.2.9", False),
            ("1.3.0", True),
            ("1.3.2", True),
            ("1.4.0", True),
            ("v1.3.2", True),
            ("0.10.0", False),
            (None, False),
            ("garbage", False),
        ],
    )
    def test_meets_minimum_version(self, version, supported):
        assert _duckdb_version_supports_ducklake(version) is supported


class TestDuckLakeFromConfig:
    """Test DuckLakeAdapter.from_config() path resolution."""

    def test_resolves_default_paths_under_benchmark_runs(self, tmp_path):
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(tmp_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path.suffix == ".ducklake"
        assert str(adapter.metadata_path).startswith(str(tmp_path))
        assert adapter.data_path.name != ""
        # Data path is a sibling "ducklake_data" dir alongside the metadata db.
        assert "ducklake_data" in adapter.data_path.parts
        # from_config resolves paths only; directory creation is lazy (deferred
        # to create_connection), so nothing is written to disk here.
        assert not adapter.metadata_path.parent.exists()
        assert not adapter.data_path.exists()

    def test_honors_explicit_argparse_style_keys(self, tmp_path):
        metadata_path = tmp_path / "custom" / "catalog.ducklake"
        data_path = tmp_path / "custom" / "data"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "ducklake_metadata_path": str(metadata_path),
            "ducklake_data_path": str(data_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path

    def test_honors_explicit_normalized_keys(self, tmp_path):
        metadata_path = tmp_path / "normalized" / "catalog.ducklake"
        data_path = tmp_path / "normalized" / "data"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "metadata_path": str(metadata_path),
            "data_path": str(data_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path

    def test_argparse_style_key_takes_precedence_over_normalized(self, tmp_path):
        preferred = tmp_path / "preferred.ducklake"
        ignored = tmp_path / "ignored.ducklake"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "ducklake_metadata_path": str(preferred),
            "metadata_path": str(ignored),
            "ducklake_data_path": str(tmp_path / "data"),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == preferred


class TestDuckLakeAdapterBasics:
    """Test basic adapter properties and construction."""

    def test_platform_name(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.platform_name == "DuckLake"

    def test_target_dialect_is_duckdb(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.get_target_dialect() == "duckdb"
        assert resolve_dialect_for_query_translation("ducklake") == "duckdb"

    def test_init_does_not_create_directories(self, tmp_path):
        # Directory creation is lazy (deferred to create_connection): merely
        # constructing an adapter must not touch the filesystem.
        metadata_path = tmp_path / "nested" / "catalog.ducklake"
        data_path = tmp_path / "nested" / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path
        # No eager mkdir: neither the parent nor the data dir should exist yet.
        assert not metadata_path.parent.exists()
        assert not data_path.exists()

    def test_constructs_with_fallback_paths_without_touching_disk(self, tmp_path, monkeypatch):
        # Direct construction without metadata_path/data_path should not raise
        # and must not write real dirs. Redirect the fallback root into tmp_path
        # and assert nothing is created on disk by construction alone.
        import benchbox.utils.path_utils as path_utils

        monkeypatch.setattr(
            path_utils,
            "get_benchmark_runs_databases_path",
            lambda *args, **kwargs: tmp_path / "fallback",
        )

        adapter = DuckLakeAdapter()
        assert adapter.metadata_path.suffix == ".ducklake"
        assert str(adapter.metadata_path).startswith(str(tmp_path))
        # Lazy: construction created nothing on disk.
        assert not (tmp_path / "fallback").exists()

    def test_create_connection_rejects_old_duckdb_version(self, tmp_path, monkeypatch):
        # No live INSTALL/ATTACH: the guard is patched to reject before any
        # network call, so this stays in the hermetic fast lane.
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        # DuckDBAdapter.create_connection() re-detects the live version from
        # the real connection (SELECT version()) and overwrites
        # driver_version_actual, so pre-seeding that attribute wouldn't stick.
        # Patch the version-support predicate itself to exercise the
        # create_connection wiring (guard runs, raises before INSTALL/ATTACH)
        # without needing to actually downgrade the installed duckdb package.
        import benchbox.platforms.ducklake as ducklake_module

        monkeypatch.setattr(ducklake_module, "_duckdb_version_supports_ducklake", lambda version: False)

        with pytest.raises(RuntimeError, match=r"DuckDB >= 1\.3"):
            adapter.create_connection()


class TestDuckLakeCatalogValidation:
    """Test the ``catalog`` platform option validation (w1)."""

    def test_default_catalog_is_duckdb(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.catalog == "duckdb"

    @pytest.mark.parametrize("catalog", ["duckdb", "sqlite", "postgres"])
    def test_valid_catalogs_accepted(self, tmp_path, catalog):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog=catalog,
        )
        assert adapter.catalog == catalog

    @pytest.mark.parametrize("catalog", ["mysql", "not-a-catalog", "DUCKDB!"])
    def test_invalid_catalog_raises(self, tmp_path, catalog):
        with pytest.raises(ValueError, match="Unsupported DuckLake catalog backend"):
            DuckLakeAdapter(
                metadata_path=str(tmp_path / "catalog.ducklake"),
                data_path=str(tmp_path / "data"),
                catalog=catalog,
            )

    def test_empty_string_catalog_defaults_to_duckdb(self, tmp_path):
        # An empty/falsy catalog value is treated as "unset" (same as
        # omitting the option entirely), not as an invalid value.
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="",
        )
        assert adapter.catalog == "duckdb"

    def test_catalog_is_case_insensitive(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="SQLite",
        )
        assert adapter.catalog == "sqlite"


class TestDuckLakeSqliteCatalog:
    """Test sqlite catalog metadata-path resolution and ATTACH target (w1)."""

    def test_default_derived_ducklake_suffix_swapped_to_sqlite(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="sqlite",
        )
        assert adapter.metadata_path == tmp_path / "catalog.sqlite"

    def test_explicit_sqlite_suffix_left_alone(self, tmp_path):
        explicit = tmp_path / "custom_name.sqlite"
        adapter = DuckLakeAdapter(
            metadata_path=str(explicit),
            data_path=str(tmp_path / "data"),
            catalog="sqlite",
        )
        assert adapter.metadata_path == explicit

    def test_duckdb_catalog_keeps_ducklake_suffix(self, tmp_path):
        # Regression: the suffix swap must only apply to catalog="sqlite".
        explicit = tmp_path / "catalog.ducklake"
        adapter = DuckLakeAdapter(
            metadata_path=str(explicit),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.metadata_path == explicit


class TestDuckLakeAttachTargetBuilder:
    """Unit-test the per-backend ATTACH-string builder directly (w1/w2)."""

    def test_duckdb_attach_target_is_bare_metadata_path(self, tmp_path):
        metadata_path = tmp_path / "catalog.ducklake"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(tmp_path / "data"))
        assert adapter._build_catalog_attach_target() == str(metadata_path)

    def test_sqlite_attach_target_has_sqlite_prefix(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="sqlite",
        )
        target = adapter._build_catalog_attach_target()
        assert target == f"sqlite:{tmp_path / 'catalog.sqlite'}"

    def test_postgres_attach_target_uses_pg_params(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
            pg_host="pg.example.com",
            pg_port=5433,
            pg_database="mydb",
            pg_user="alice",
            pg_password="s3cr3t",
        )
        target = adapter._build_catalog_attach_target()
        assert target == "postgres:dbname=mydb host=pg.example.com user=alice password=s3cr3t port=5433"

    def test_postgres_attach_target_applies_defaults(self, tmp_path):
        # No pg_* options supplied: host/port/user default via the shared
        # PG-family helper; database defaults to the DuckLake-specific name.
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
        )
        assert adapter.pg_host == "localhost"
        assert adapter.pg_port == 5432
        assert adapter.pg_user == "postgres"
        assert adapter.pg_password is None
        assert adapter.pg_database == "ducklake_catalog"
        target = adapter._build_catalog_attach_target()
        assert target == "postgres:dbname=ducklake_catalog host=localhost user=postgres port=5432"

    def test_postgres_connstring_quotes_values_with_spaces(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
            pg_database="my db",
            pg_password="pa'ss",
        )
        connstring = adapter._build_postgres_connstring()
        assert "dbname='my db'" in connstring
        # Embedded single quote is backslash-escaped per libpq quoting rules.
        assert r"password='pa\'ss'" in connstring


class TestLibpqQuoteValue:
    """Directly unit-test the libpq component quoter (w2 soundness)."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Simple values with no whitespace/quote/backslash pass through bare.
            ("localhost", "localhost"),
            ("5432", "5432"),
            ("my_db-1", "my_db-1"),
            # Empty value must be quoted (bare `keyword=` is a libpq syntax error).
            ("", "''"),
            # Whitespace triggers quoting.
            ("my db", "'my db'"),
            ("a\tb", "'a\tb'"),
            # A single quote inside is backslash-escaped AND the value is wrapped.
            ("pa'ss", r"'pa\'ss'"),
            # A backslash inside is doubled AND the value is wrapped.
            ("a\\b", r"'a\\b'"),
            # Both together: backslash doubled, quote escaped, order preserved.
            ("a\\'b", r"'a\\\'b'"),
        ],
    )
    def test_quotes_components_per_libpq_rules(self, value, expected):
        assert _libpq_quote_value(value) == expected


class TestDuckLakePostgresAttachInjection:
    """Adversarial coverage: a malicious PG password/param cannot break out of
    either the libpq value or the outer single-quoted SQL string literal (w2).

    The final ATTACH literal DuckDB executes is
    ``'ducklake:<escape_sql_string_literal(attach_target)>'``, so these tests
    assert the FULLY-escaped literal (libpq quoting THEN SQL quote-doubling),
    not just the intermediate connstring - i.e. the exact composition the
    reviewer asked to pin down.
    """

    def _final_attach_literal(self, adapter):
        """Reproduce create_connection()'s exact escaping of the ATTACH target.

        Mirrors: escaped = escape_sql_string_literal(attach_target);
                 sql = f"ATTACH 'ducklake:{escaped}' AS lake (...)".
        Returns the single-quoted literal ``'ducklake:...'`` (including the
        surrounding quotes) so balance/breakout can be asserted directly.
        """
        target = adapter._build_catalog_attach_target()
        return "'ducklake:" + escape_sql_string_literal(target) + "'"

    @pytest.mark.parametrize(
        "malicious_password",
        [
            "pass'word",
            "x' OR sslmode=disable",
            "'; DROP TABLE lineitem; --",
            "a' host='evil.example.com",
        ],
    )
    def test_malicious_password_stays_inside_the_literal(self, tmp_path, malicious_password):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
            pg_database="benchdb",
            pg_user="alice",
            pg_password=malicious_password,
        )
        literal = self._final_attach_literal(adapter)

        # 1. The literal is a single balanced SQL string: it starts and ends
        #    with a quote, and every interior quote is doubled ('') - so the
        #    count of standalone (odd-run) quotes is zero. Strip the outer pair,
        #    then every remaining ' must be part of a '' pair.
        assert literal.startswith("'") and literal.endswith("'")
        interior = literal[1:-1]
        # After SQL escaping, every single quote in the interior is doubled.
        # Removing all '' pairs must leave NO stray single quote behind - that
        # is exactly the property that prevents breaking out of the literal.
        assert "'" not in interior.replace("''", "")

        # 2. The malicious payload's own quote/keyword material did not create a
        #    real libpq keyword boundary: the connstring keeps password=... as
        #    a single quoted value, so no injected `host=`/`sslmode=` keyword
        #    escaped into the connection string as an unquoted token.
        connstring = adapter._build_postgres_connstring()
        # The user/db we set are the only bare keyword tokens; the payload sits
        # inside the quoted password value.
        assert connstring.count("password=") == 1
        assert connstring.startswith("dbname=benchdb host=") or "dbname=benchdb" in connstring
        # The password value is single-quoted (payload contains a quote/space),
        # so its content is contained, not a run of bare keyword=value tokens.
        assert "password='" in connstring

    def test_backslash_in_password_survives_both_escaping_layers(self, tmp_path):
        # A backslash is libpq-doubled (\\) then passes through
        # escape_sql_string_literal (which only doubles single quotes),
        # so the final literal keeps the doubled backslash and stays balanced.
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
            pg_database="benchdb",
            pg_password="a\\b'c",
        )
        connstring = adapter._build_postgres_connstring()
        # libpq layer: backslash doubled, quote escaped, whole value wrapped.
        assert r"password='a\\b\'c'" in connstring

        literal = self._final_attach_literal(adapter)
        # Outer SQL layer only doubles single quotes; balance still holds.
        assert literal.startswith("'") and literal.endswith("'")
        assert "'" not in literal[1:-1].replace("''", "")


class TestDuckLakeFromConfigCatalogOptions:
    """Test from_config() resolves catalog/pg_*/s3_* from both config shapes (w1-w3).

    The real CLI --platform-option path nests values under config["options"]
    (DuckLake has no registered PlatformHookRegistry config builder to promote
    them to flat top-level keys - see from_config()'s _resolve_option
    docstring), so both shapes must be exercised.
    """

    def test_resolves_catalog_from_flat_config(self, tmp_path):
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(tmp_path),
            "catalog": "sqlite",
        }
        adapter = DuckLakeAdapter.from_config(config)
        assert adapter.catalog == "sqlite"

    def test_resolves_catalog_from_nested_options(self, tmp_path):
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(tmp_path),
            "options": {"catalog": "postgres", "pg_host": "dbhost", "pg_port": 5433},
        }
        adapter = DuckLakeAdapter.from_config(config)
        assert adapter.catalog == "postgres"
        assert adapter.pg_host == "dbhost"
        assert adapter.pg_port == 5433

    def test_no_catalog_option_defaults_to_duckdb(self, tmp_path):
        config = {"benchmark": "tpch", "scale_factor": 0.01, "output_dir": str(tmp_path)}
        adapter = DuckLakeAdapter.from_config(config)
        assert adapter.catalog == "duckdb"

    def test_resolves_s3_creds_from_nested_options(self, tmp_path):
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(tmp_path),
            "options": {"s3_key_id": "AKIA...", "s3_secret": "shh", "s3_region": "us-east-1"},
        }
        adapter = DuckLakeAdapter.from_config(config)
        assert adapter.s3_key_id == "AKIA..."
        assert adapter.s3_secret == "shh"
        assert adapter.s3_region == "us-east-1"


class TestDuckLakeS3Routing:
    """Test S3/cloud DATA_PATH routing and secret-SQL construction (w3)."""

    def test_cloud_data_path_detected(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
        )
        assert adapter._data_path_is_cloud is True
        # Path() would have mangled "s3://" to "s3:/" - assert it did not.
        assert str(adapter.data_path) == "s3://my-bucket/bench/"

    def test_local_data_path_not_flagged_cloud(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter._data_path_is_cloud is False

    def test_cloud_data_path_skips_local_mkdir_on_connect(self, tmp_path, monkeypatch):
        # Regression: create_connection() must not attempt Path.mkdir() on a
        # cloud data_path (a plain str has no .mkdir()). Stub out the base
        # DuckDBAdapter.create_connection() (the super() call, which would
        # otherwise open a real DuckDB connection) so this stays hermetic;
        # the real installed duckdb module/version satisfies the >=1.3 guard.
        from benchbox.platforms.duckdb import DuckDBAdapter

        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
        )

        class _StubSetupConn:
            def __init__(self):
                self.executed: list[str] = []

            def execute(self, sql):
                self.executed.append(sql)
                if sql.startswith("ATTACH"):
                    # Stop before USE lake / the return wrapper - we only care
                    # that mkdir was never attempted and the SQL sequence up
                    # to ATTACH is sane.
                    raise RuntimeError("stop-after-attach (test stub)")
                return self

            def close(self):
                pass

        stub_conn = _StubSetupConn()
        monkeypatch.setattr(DuckDBAdapter, "create_connection", lambda self, **_: stub_conn)

        with pytest.raises(RuntimeError, match="Failed to initialize the DuckLake catalog"):
            adapter.create_connection()

        # data_path is a bare string (no mkdir attempted/possible - it would
        # have raised AttributeError before reaching the SQL sequence below),
        # and the executed SQL sequence installed httpfs + created a
        # credential_chain secret before ATTACH.
        assert any("INSTALL httpfs" in sql for sql in stub_conn.executed)
        assert any("CREATE OR REPLACE SECRET" in sql and "credential_chain" in sql for sql in stub_conn.executed)
        assert any(sql.startswith("ATTACH") for sql in stub_conn.executed)

    def test_s3_secret_sql_defaults_to_credential_chain(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
        )
        sql = adapter._build_s3_secret_sql()
        assert "PROVIDER credential_chain" in sql
        assert "KEY_ID" not in sql

    def test_s3_secret_sql_uses_explicit_keys_when_provided(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
            s3_key_id="AKIAEXAMPLE",
            s3_secret="topsecret",
            s3_region="us-west-2",
        )
        sql = adapter._build_s3_secret_sql()
        assert "KEY_ID 'AKIAEXAMPLE'" in sql
        assert "SECRET 'topsecret'" in sql
        assert "REGION 'us-west-2'" in sql
        assert "credential_chain" not in sql

    def test_s3_secret_sql_omits_key_id_form_without_both_creds(self, tmp_path):
        # Only one of key_id/secret supplied - falls back to credential_chain
        # rather than sending a half-formed KEY_ID/SECRET pair.
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
            s3_key_id="AKIAEXAMPLE",
        )
        sql = adapter._build_s3_secret_sql()
        assert "PROVIDER credential_chain" in sql

    def test_s3_secret_sql_is_idempotent_create_or_replace(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path="s3://my-bucket/bench/",
        )
        assert adapter._build_s3_secret_sql().startswith("CREATE OR REPLACE SECRET ")


class TestDuckLakeRegistration:
    """Test DuckLake platform is properly registered."""

    def test_platform_registered_in_registry(self):
        caps = PlatformRegistry.get_platform_capabilities("ducklake")
        assert caps is not None
        assert caps.supports_sql is True
        assert caps.supports_dataframe is False

    def test_inherits_from_duckdb(self):
        caps = PlatformRegistry.get_platform_capabilities("ducklake")
        assert caps.inherits_from == "duckdb"
        assert caps.platform_family == "duckdb"

    def test_platform_appears_in_available_platforms(self):
        available = PlatformRegistry.get_available_platforms()
        assert "ducklake" in available

    def test_support_status_is_experimental(self):
        assert PlatformRegistry.get_platform_support_status("ducklake") == "experimental"

    def test_adapter_class_resolves(self):
        adapter_class = PlatformRegistry.get_adapter_class("ducklake")
        assert adapter_class is DuckLakeAdapter

    def test_appears_in_list_available_platforms(self):
        from benchbox.platforms import list_available_platforms

        platforms = list_available_platforms()
        assert "ducklake" in platforms
        assert platforms["ducklake"] is True

    def test_lazy_export_resolves_adapter(self):
        import benchbox.platforms as platforms_module

        assert platforms_module.DuckLakeAdapter is DuckLakeAdapter
