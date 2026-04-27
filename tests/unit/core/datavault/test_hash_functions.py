"""Unit tests for Data Vault hash functions.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib

import duckdb
import pytest

from benchbox.core.datavault.etl.hash_functions import (
    generate_hash_key,
    generate_hash_key_sql,
    generate_hashdiff,
    generate_hashdiff_sql,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGenerateHashKey:
    """Tests for generate_hash_key function."""

    def test_single_value(self):
        """Hash of single value should be deterministic."""
        result = generate_hash_key(1)
        assert len(result) == 32  # MD5 produces 32 hex chars
        assert result == generate_hash_key(1)  # Deterministic

    def test_multiple_values(self):
        """Hash of multiple values should be deterministic."""
        result = generate_hash_key(1, 2, 3)
        assert len(result) == 32
        assert result == generate_hash_key(1, 2, 3)

    def test_different_values_produce_different_hashes(self):
        """Different inputs should produce different hashes."""
        hash1 = generate_hash_key(1)
        hash2 = generate_hash_key(2)
        assert hash1 != hash2

    def test_order_matters(self):
        """Order of values should affect the hash."""
        hash1 = generate_hash_key(1, 2)
        hash2 = generate_hash_key(2, 1)
        assert hash1 != hash2

    def test_none_handling(self):
        """None values should be handled consistently."""
        result = generate_hash_key(None)
        assert len(result) == 32
        # None should produce same hash consistently
        assert result == generate_hash_key(None)

    def test_string_values(self):
        """String values should be hashed correctly."""
        result = generate_hash_key("test")
        assert len(result) == 32

    def test_sha1_algorithm_raises(self):
        """SHA-1 is rejected - not present in the supported algorithm set."""
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            generate_hash_key(1, algorithm="sha1")

    def test_sha256_algorithm_accepted(self):
        """SHA-256 is supported after VARCHAR(64) schema migration."""
        result = generate_hash_key(1, algorithm="sha256")
        assert len(result) == 64

    def test_unsupported_algorithm_raises(self):
        """Unsupported algorithm should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            generate_hash_key(1, algorithm="invalid")


class TestGenerateHashdiff:
    """Tests for generate_hashdiff function."""

    def test_hashdiff_same_as_hash_key(self):
        """HASHDIFF uses same logic as hash key."""
        attrs = ("John", "Doe", "123 Main St")
        hashdiff = generate_hashdiff(*attrs)
        hash_key = generate_hash_key(*attrs)
        assert hashdiff == hash_key

    def test_hashdiff_detects_changes(self):
        """Different attribute values should produce different HASHDIFF."""
        hashdiff1 = generate_hashdiff("John", "Doe")
        hashdiff2 = generate_hashdiff("Jane", "Doe")
        assert hashdiff1 != hashdiff2


class TestGenerateHashKeySql:
    """Tests for SQL hash key generation."""

    def test_single_column(self):
        """Single column should produce simple MD5 expression."""
        result = generate_hash_key_sql("c_custkey")
        assert "md5" in result
        assert "c_custkey" in result
        assert "CAST" in result
        assert "VARCHAR" in result

    def test_multiple_columns(self):
        """Multiple columns should be concatenated with delimiter."""
        result = generate_hash_key_sql("ps_partkey", "ps_suppkey")
        assert "md5" in result
        assert "ps_partkey" in result
        assert "ps_suppkey" in result
        assert "||" in result
        assert "'|'" in result

    def test_with_table_alias(self):
        """Table alias should be prefixed to columns."""
        result = generate_hash_key_sql("c_custkey", table_alias="c")
        assert "c.c_custkey" in result

    def test_sha256_algorithm_accepted(self):
        """SHA-256 is supported via DuckDB's built-in sha256() function."""
        result = generate_hash_key_sql("c_custkey", algorithm="sha256")
        assert "sha256" in result
        assert "c_custkey" in result

    def test_unsupported_algorithm_raises(self):
        """Algorithms outside md5/sha256 should raise ValueError."""
        with pytest.raises(ValueError, match="only supports"):
            generate_hash_key_sql("col", algorithm="sha1")


class TestGenerateHashdiffSql:
    """Tests for SQL HASHDIFF generation."""

    def test_hashdiff_uses_coalesce(self):
        """HASHDIFF SQL should use COALESCE for NULL handling."""
        result = generate_hashdiff_sql("c_name", "c_address")
        assert "COALESCE" in result
        assert "md5" in result
        assert "c_name" in result
        assert "c_address" in result

    def test_hashdiff_with_alias(self):
        """HASHDIFF SQL should support table alias."""
        result = generate_hashdiff_sql("c_name", table_alias="sc")
        assert "sc.c_name" in result

    def test_sha256_algorithm_accepted(self):
        """SHA-256 is supported via DuckDB's built-in sha256() function."""
        result = generate_hashdiff_sql("c_name", "c_address", algorithm="sha256")
        assert "sha256" in result
        assert "COALESCE" in result

    def test_unsupported_algorithm_raises(self):
        """Algorithms outside md5/sha256 should raise ValueError."""
        with pytest.raises(ValueError, match="only supports"):
            generate_hashdiff_sql("col", algorithm="sha1")


class TestSqlRoundTrip:
    """Execute generated SQL against DuckDB and verify parity with hashlib."""

    @pytest.fixture(scope="class")
    def conn(self):
        connection = duckdb.connect(":memory:")
        yield connection
        connection.close()

    @pytest.mark.parametrize(
        ("algorithm", "expected_len"),
        [("md5", 32), ("sha256", 64)],
    )
    def test_hash_key_sql_matches_hashlib(self, conn, algorithm, expected_len):
        """generate_hash_key_sql output must match hashlib for the same inputs."""
        expr = generate_hash_key_sql("c_custkey", algorithm=algorithm)
        sql_result = conn.execute(f"SELECT {expr} FROM (SELECT 42 AS c_custkey)").fetchone()[0]
        py_result = generate_hash_key(42, algorithm=algorithm)
        assert sql_result == py_result
        assert len(sql_result) == expected_len

    @pytest.mark.parametrize(
        ("algorithm", "expected_len"),
        [("md5", 32), ("sha256", 64)],
    )
    def test_hashdiff_sql_matches_hashlib(self, conn, algorithm, expected_len):
        """generate_hashdiff_sql output must match hashlib (NULL→'' via COALESCE)."""
        expr = generate_hashdiff_sql("c_name", "c_address", algorithm=algorithm)
        sql_result = conn.execute(
            f"SELECT {expr} FROM (SELECT 'John' AS c_name, '123 Main St' AS c_address)"
        ).fetchone()[0]
        py_result = hashlib.new(algorithm, b"John|123 Main St").hexdigest()
        assert sql_result == py_result
        assert len(sql_result) == expected_len

    def test_hashdiff_sql_null_handling(self, conn):
        """NULL attributes become empty string via COALESCE in SQL path."""
        expr = generate_hashdiff_sql("c_name", "c_address", algorithm="sha256")
        sql_result = conn.execute(
            f"SELECT {expr} FROM (SELECT 'John' AS c_name, CAST(NULL AS VARCHAR) AS c_address)"
        ).fetchone()[0]
        py_result = hashlib.sha256(b"John|").hexdigest()
        assert sql_result == py_result
