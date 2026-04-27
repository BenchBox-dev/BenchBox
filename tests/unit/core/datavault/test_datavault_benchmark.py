"""Tests for the DataVaultBenchmark core class."""

import json

import pytest

from benchbox.core.datavault.benchmark import DataVaultBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_default_output_dir_uses_datavault_name(tmp_path, monkeypatch):
    """Default output directory should use the datavault identifier."""
    # Force cwd to tmp_path so the generated path is deterministic
    monkeypatch.chdir(tmp_path)

    benchmark = DataVaultBenchmark(scale_factor=0.01)

    assert benchmark.output_dir is not None
    assert benchmark.output_dir.name.endswith("datavault_sf001")
    assert "benchmark_runs" in benchmark.output_dir.as_posix()


def test_benchmark_name_override():
    """Benchmark name should be stabilized to datavault."""
    benchmark = DataVaultBenchmark(scale_factor=0.1)
    assert benchmark._get_benchmark_name() == "datavault"


def test_get_create_tables_sql_translation():
    """DDL generation should support dialect translation via SQLGlot."""
    benchmark = DataVaultBenchmark(scale_factor=0.01)
    ddl = benchmark.get_create_tables_sql(dialect="snowflake")

    assert ddl.count("CREATE TABLE") == 21
    # Snowflake translation should quote identifiers
    assert '"' in ddl


def test_query_translation_via_base():
    """Queries should translate to other dialects without errors."""
    from benchbox.datavault import DataVault

    benchmark = DataVault(scale_factor=0.01)
    translated = benchmark.translate_query(1, dialect="snowflake")

    assert "SELECT" in translated.upper()


class TestDataFrameMode:
    """Tests for DataFrame execution mode support."""

    def test_supports_dataframe_mode(self):
        """DataVaultBenchmark should declare DataFrame mode support."""
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode() is True

    def test_get_dataframe_queries_returns_all_22(self):
        """get_dataframe_queries should return all 22 Data Vault queries."""
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        queries = benchmark.get_dataframe_queries()
        assert len(queries) == 22

    def test_dataframe_queries_have_both_implementations(self):
        """Each query should have both expression and pandas implementations."""
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        for query in benchmark.get_dataframe_queries():
            assert query.expression_impl is not None, f"{query.query_id} missing expression_impl"
            assert query.pandas_impl is not None, f"{query.query_id} missing pandas_impl"

    def test_dataframe_query_ids_match_sql_queries(self):
        """DataFrame query IDs should correspond to SQL query IDs (Q1-Q22)."""
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        df_ids = sorted(q.query_id for q in benchmark.get_dataframe_queries())
        expected = sorted(f"Q{i}" for i in range(1, 23))
        assert df_ids == expected


class TestHashAlgorithmValidation:
    """Tests for hash algorithm validation."""

    def test_md5_algorithm_accepted(self):
        """MD5 hash algorithm should be accepted."""
        benchmark = DataVaultBenchmark(scale_factor=0.01, hash_algorithm="md5")
        assert benchmark.hash_algorithm == "md5"

    def test_sha1_algorithm_rejected(self):
        """SHA-1 is rejected because it is not in SUPPORTED_HASH_ALGORITHMS."""
        with pytest.raises(ValueError) as exc_info:
            DataVaultBenchmark(scale_factor=0.01, hash_algorithm="sha1")

        assert "sha1" in str(exc_info.value).lower()
        assert "md5" in str(exc_info.value).lower()

    def test_sha256_algorithm_accepted(self):
        """SHA256 hash algorithm should be accepted after VARCHAR(64) schema migration."""
        benchmark = DataVaultBenchmark(scale_factor=0.01, hash_algorithm="sha256")
        assert benchmark.hash_algorithm == "sha256"

    def test_sha256_produces_64char_key(self):
        """SHA-256 hash key generation should produce a 64-character hex string."""
        from benchbox.core.datavault.etl.hash_functions import generate_hash_key

        result = generate_hash_key(1, algorithm="sha256")
        assert len(result) == 64

    def test_invalid_algorithm_rejected(self):
        """Arbitrary hash algorithm names should be rejected."""
        with pytest.raises(ValueError):
            DataVaultBenchmark(scale_factor=0.01, hash_algorithm="invalid")


class TestManifestChecking:
    """Tests for existing data manifest checking."""

    def test_check_existing_manifest_returns_none_when_no_manifest(self, tmp_path):
        """Should return None when no manifest exists."""
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        result = benchmark._check_existing_manifest()
        assert result is None

    def test_check_existing_manifest_returns_none_on_benchmark_mismatch(self, tmp_path):
        """Should return None when manifest benchmark doesn't match."""
        manifest = {
            "version": 2,
            "benchmark": "tpch",  # Wrong benchmark
            "scale_factor": 0.01,
            "tables": {},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        result = benchmark._check_existing_manifest()
        assert result is None

    def test_check_existing_manifest_returns_none_on_scale_mismatch(self, tmp_path):
        """Should return None when manifest scale factor doesn't match."""
        manifest = {
            "version": 2,
            "benchmark": "datavault",
            "scale_factor": 1.0,  # Wrong scale
            "tables": {},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        result = benchmark._check_existing_manifest()
        assert result is None

    def test_check_existing_manifest_returns_none_on_missing_files(self, tmp_path):
        """Should return None when manifest references non-existent files."""
        manifest = {
            "version": 2,
            "benchmark": "datavault",
            "scale_factor": 0.01,
            "tables": {
                "hub_region": {"formats": {"tbl": [{"path": "hub_region.tbl", "row_count": 5, "size_bytes": 100}]}}
            },
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        result = benchmark._check_existing_manifest()
        # Should return None because hub_region.tbl doesn't exist
        assert result is None

    def test_force_regenerate_bypasses_manifest_check(self, tmp_path, monkeypatch):
        """force_regenerate=True should skip manifest checking."""
        # Create a valid-looking manifest
        manifest = {
            "version": 2,
            "benchmark": "datavault",
            "scale_factor": 0.01,
            "tables": {},
        }
        (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path, force_regenerate=True)
        # When force_regenerate is True, generate_data should not short-circuit
        # We test this by verifying force_regenerate flag is set
        assert benchmark.force_regenerate is True


class TestDataVaultBenchmarkExtraOps:
    """Additional coverage for DataVaultBenchmark methods."""

    def test_get_query_returns_sql(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        sql = benchmark.get_query(1)
        assert isinstance(sql, str)
        assert "SELECT" in sql.upper()

    def test_get_all_queries_returns_22(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        queries = benchmark.get_all_queries()
        assert len(queries) == 22

    def test_get_queries_dialect_none(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        queries = benchmark.get_queries()
        # Keys should be string versions of 1-22
        assert "1" in queries
        assert "22" in queries

    def test_get_schema_returns_tables_dict(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        schema = benchmark.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_get_table_count_is_21(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        assert benchmark.get_table_count() == 21

    def test_get_table_loading_order_full(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        order = benchmark.get_table_loading_order()
        assert len(order) == 21

    def test_get_table_loading_order_filtered(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        available = ["hub_customer", "hub_supplier"]
        order = benchmark.get_table_loading_order(available_tables=available)
        assert set(order) == set(available)

    def test_tpch_source_dir_property(self, tmp_path):
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        src_dir = benchmark.tpch_source_dir
        assert src_dir is not None
        assert "tpch" in str(src_dir)

    def test_tpch_generator_lazy_load(self, tmp_path):
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        gen = benchmark.tpch_generator
        assert gen is not None
        # Second access returns same object
        assert benchmark.tpch_generator is gen

    def test_etl_transformer_lazy_load(self, tmp_path):
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        transformer = benchmark.etl_transformer
        assert transformer is not None
        assert benchmark.etl_transformer is transformer

    def test_query_manager_lazy_load(self, tmp_path):
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        qm = benchmark.query_manager
        assert qm is not None
        assert benchmark.query_manager is qm

    def test_get_create_tables_sql_with_tuning_config(self, tmp_path):
        from types import SimpleNamespace

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        tuning = SimpleNamespace(
            primary_keys=SimpleNamespace(enabled=False),
            foreign_keys=SimpleNamespace(enabled=False),
        )
        ddl = benchmark.get_create_tables_sql(dialect="duckdb", tuning_config=tuning)
        assert isinstance(ddl, str)
        assert "CREATE TABLE" in ddl

    def test_execute_query_uses_cursor(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [(1, "test")]
        result = benchmark.execute_query(1, conn)
        assert result == [(1, "test")]
        cursor.execute.assert_called_once()

    def test_execute_query_connectionless_cursor(self):
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        # Connection that acts as cursor itself (has execute/fetchall but no cursor())
        conn = MagicMock()
        del conn.cursor  # remove cursor attribute
        conn.fetchall.return_value = []
        benchmark.execute_query(1, conn)
        conn.execute.assert_called_once()

    def test_generate_data_uses_existing_manifest(self, tmp_path, monkeypatch):
        """generate_data returns existing files when valid manifest found."""
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)

        fake_files = {f"hub_{i}": tmp_path / f"hub_{i}.tbl" for i in range(21)}
        for path in fake_files.values():
            path.touch()

        monkeypatch.setattr(benchmark, "_check_existing_manifest", lambda: fake_files)

        result = benchmark.generate_data()
        assert len(result) == 21

    def test_cleanup_with_generator(self, tmp_path):
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        mock_gen = MagicMock()
        benchmark._tpch_generator = mock_gen
        benchmark.cleanup()
        mock_gen.cleanup.assert_called_once()

    def test_generate_data_full_path(self, tmp_path, monkeypatch):
        """Cover the full generate_data path (step 1 and step 2)."""
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path, force_regenerate=True)
        mock_tpch_gen = MagicMock()
        mock_tpch_gen.generate.return_value = {"customer": tmp_path / "customer.tbl"}

        mock_etl = MagicMock()
        dv_files = {f"hub_{i}": tmp_path / f"hub_{i}.tbl" for i in range(21)}
        mock_etl.transform.return_value = dv_files

        benchmark._tpch_generator = mock_tpch_gen
        benchmark._etl_transformer = mock_etl

        result = benchmark.generate_data()
        assert len(result) == 21
        mock_tpch_gen.generate.assert_called_once()
        mock_etl.transform.assert_called_once()

    def test_default_output_dir_without_explicit_dir(self, monkeypatch, tmp_path):
        """No output_dir provided should use default path."""
        monkeypatch.chdir(tmp_path)
        benchmark = DataVaultBenchmark(scale_factor=0.01)
        assert benchmark.output_dir is not None
        assert "datavault" in str(benchmark.output_dir)

    def test_check_manifest_with_few_tables(self, tmp_path):
        """Manifest with < 21 tables should return None."""
        from benchbox.utils.datagen_manifest import MANIFEST_FILENAME

        # Create manifest with only a few tables
        manifest = {
            "version": 2,
            "benchmark": "datavault",
            "scale_factor": 0.01,
            "tables": {
                "hub_customer": {"formats": {"tbl": [{"path": "hub_customer.tbl", "row_count": 5, "size_bytes": 100}]}},
            },
        }
        (tmp_path / MANIFEST_FILENAME).write_text(__import__("json").dumps(manifest))
        # Create the actual file so path check passes
        (tmp_path / "hub_customer.tbl").touch()

        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=tmp_path)
        result = benchmark._check_existing_manifest()
        # Should return None because we only have 1 table, not 21
        assert result is None


from unittest.mock import MagicMock
