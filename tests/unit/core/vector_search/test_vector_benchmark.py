"""Unit tests for the vector search benchmark module.

Covers:
  - Data generator (synthetic embedding generation, reproducibility)
  - Query manager (all 6 queries, dialect variants)
  - Schema DDL generation (dialect-specific embedding types)
  - Metrics utilities (recall@k, latency percentiles, QPS)
  - Benchmark class (construction, API surface)
  - Registry integration (benchmark discoverable via benchbox module)

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.core.query_catalog_base import QuerySkippedError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ALL_QUERY_IDS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------


class TestVectorSearchDataGenerator:
    """Tests for VectorSearchDataGenerator."""

    def test_imports(self):
        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        assert VectorSearchDataGenerator is not None

    def test_generate_vectors_creates_files(self, tmp_path):
        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        gen = VectorSearchDataGenerator(
            scale_factor=0.001,  # tiny - keeps test fast
            output_dir=tmp_path,
            dimensions=4,
            compression_enabled=False,
        )
        # Override base_vectors to make it truly tiny
        from benchbox.core.vector_search import generator as _gmod

        orig = _gmod.BASE_VECTORS
        _gmod.BASE_VECTORS = 10
        try:
            paths = gen._generate_local(tmp_path)
        finally:
            _gmod.BASE_VECTORS = orig

        assert "vectors" in paths
        assert "vector_queries" in paths

    def test_vectors_file_has_correct_rows(self, tmp_path):
        import numpy as np

        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        gen = VectorSearchDataGenerator(
            scale_factor=1.0,
            output_dir=tmp_path,
            dimensions=4,
            compression_enabled=False,
        )
        rng = np.random.default_rng(42)
        from benchbox.core.vector_search import generator as _gmod

        orig = _gmod.BASE_VECTORS
        _gmod.BASE_VECTORS = 5
        try:
            path = gen._generate_vectors(tmp_path, rng)
        finally:
            _gmod.BASE_VECTORS = orig

        assert path.exists()
        lines = path.read_text().splitlines()
        assert lines[0] == "id|embedding|category|doc_id"  # header
        assert len(lines) == 6  # 1 header + 5 data rows
        assert gen._manifest_row_counts["vectors"] == 5

    def test_query_vectors_fixed_count(self, tmp_path):
        import numpy as np

        from benchbox.core.vector_search.generator import (
            NUM_QUERY_VECTORS,
            VectorSearchDataGenerator,
        )

        gen = VectorSearchDataGenerator(
            scale_factor=1.0,
            output_dir=tmp_path,
            dimensions=8,
            compression_enabled=False,
        )
        rng = np.random.default_rng(43)
        path = gen._generate_query_vectors(tmp_path, rng)

        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == NUM_QUERY_VECTORS + 1  # +1 for header
        assert gen._manifest_row_counts["vector_queries"] == NUM_QUERY_VECTORS

    def test_reproducibility(self, tmp_path):
        """Two generators with the same seed produce identical files."""
        import numpy as np

        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        def _make_vectors(out_dir):
            gen = VectorSearchDataGenerator(
                scale_factor=1.0,
                output_dir=out_dir,
                dimensions=4,
                compression_enabled=False,
            )
            rng = np.random.default_rng(42)
            from benchbox.core.vector_search import generator as _gmod

            orig = _gmod.BASE_VECTORS
            _gmod.BASE_VECTORS = 5
            try:
                path = gen._generate_vectors(out_dir, rng)
            finally:
                _gmod.BASE_VECTORS = orig
            return path.read_text()

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        assert _make_vectors(dir_a) == _make_vectors(dir_b)

    def test_embedding_values_are_unit_normalised(self, tmp_path):
        """Each embedding row in the CSV should encode a unit vector."""
        import math

        import numpy as np

        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        dim = 8
        gen = VectorSearchDataGenerator(
            scale_factor=1.0,
            output_dir=tmp_path,
            dimensions=dim,
            compression_enabled=False,
        )
        rng = np.random.default_rng(42)
        from benchbox.core.vector_search import generator as _gmod

        orig = _gmod.BASE_VECTORS
        _gmod.BASE_VECTORS = 3
        try:
            path = gen._generate_vectors(tmp_path, rng)
        finally:
            _gmod.BASE_VECTORS = orig

        for line in path.read_text().splitlines()[1:]:
            emb_str = line.split("|")[1]  # e.g. [0.1,0.2,...]
            vals = [float(v) for v in emb_str.strip("[]").split(",")]
            norm = math.sqrt(sum(v * v for v in vals))
            assert abs(norm - 1.0) < 1e-4, f"Not unit-normalised: norm={norm}"

    def test_manifest_written(self, tmp_path):
        from benchbox.core.vector_search.generator import VectorSearchDataGenerator

        gen = VectorSearchDataGenerator(
            scale_factor=1.0,
            output_dir=tmp_path,
            dimensions=4,
            compression_enabled=False,
        )
        from benchbox.core.vector_search import generator as _gmod

        orig = _gmod.BASE_VECTORS
        _gmod.BASE_VECTORS = 3
        try:
            gen.generate_data()
        finally:
            _gmod.BASE_VECTORS = orig

        manifest = tmp_path / "_datagen_manifest.json"
        assert manifest.exists()


# ---------------------------------------------------------------------------
# Query manager tests
# ---------------------------------------------------------------------------


class TestVectorSearchQueryManager:
    """Tests for VectorSearchQueryManager."""

    def test_imports(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        assert VectorSearchQueryManager is not None

    def test_has_six_queries(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        assert len(mgr.get_all_queries()) == 6

    @pytest.mark.parametrize("qid", ALL_QUERY_IDS)
    def test_all_query_ids_available(self, qid):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query(qid)
        assert isinstance(sql, str)
        assert len(sql) > 20

    def test_invalid_query_id_raises(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        with pytest.raises(ValueError, match="Invalid query ID"):
            mgr.get_query("Q99")

    def test_default_sql_targets_duckdb(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        q1 = mgr.get_query("Q1")
        assert "array_cosine_similarity" in q1

    def test_postgresql_dialect(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q1", dialect="postgresql")
        assert "<=>" in sql
        assert "array_cosine_similarity" not in sql

    def test_clickhouse_dialect(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q1", dialect="clickhouse")
        assert "cosineDistance" in sql

    def test_doris_dialect(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q1", dialect="doris")
        assert "cosine_distance" in sql
        assert "array_cosine_similarity" not in sql
        assert "1 -" in sql

    def test_snowflake_dialect(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q1", dialect="snowflake")
        assert "VECTOR_COSINE_SIMILARITY" in sql

    def test_unsupported_dialect_falls_back_to_duckdb(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q1", dialect="bigquery")
        assert "array_cosine_similarity" in sql

    def test_get_all_queries_returns_six(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        queries = mgr.get_all_queries()
        assert set(queries.keys()) == set(ALL_QUERY_IDS)

    def test_get_all_queries_with_dialect(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        queries = mgr.get_all_queries(dialect="snowflake")
        for sql in queries.values():
            assert "array_cosine_similarity" not in sql

    def test_descriptions_present(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        for qid in ALL_QUERY_IDS:
            desc = mgr.get_description(qid)
            assert isinstance(desc, str) and desc

    def test_supported_dialects_includes_known_platforms(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        dialects = mgr.supported_dialects()
        assert "lakesail" in dialects
        assert "spark" in dialects
        assert "starrocks" in dialects
        assert "doris" in dialects
        assert "postgresql" in dialects
        assert "clickhouse" in dialects
        assert "snowflake" in dialects

    def test_lakesail_queries_use_spark_array_functions(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        queries = mgr.get_all_queries(dialect="lakesail")
        assert set(queries) == set(ALL_QUERY_IDS)
        assert all("array_cosine_similarity" not in sql for sql in queries.values())
        assert "zip_with" in queries["Q1"]
        assert "aggregate" in queries["Q1"]
        assert "sqrt" in queries["Q2"]

    def test_q3_has_category_filter(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q3")
        assert "category" in sql.lower()
        assert "WHERE" in sql

    def test_q4_has_limit_100(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q4")
        assert "LIMIT 100" in sql

    def test_q2_uses_l2_distance(self):
        from benchbox.core.vector_search.queries import VectorSearchQueryManager

        mgr = VectorSearchQueryManager()
        sql = mgr.get_query("Q2")
        assert "array_distance" in sql
        assert "ASC" in sql


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestVectorSearchSchema:
    """Tests for schema DDL generation."""

    def test_imports(self):
        from benchbox.core.vector_search.schema import TABLES, get_all_create_table_sql

        assert "vectors" in TABLES
        assert "vector_queries" in TABLES
        assert callable(get_all_create_table_sql)

    def test_duckdb_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("duckdb", 128) == "FLOAT[128]"
        assert get_embedding_type("duckdb", 768) == "FLOAT[768]"

    def test_postgresql_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("postgresql", 128) == "VECTOR(128)"

    def test_snowflake_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("snowflake", 1536) == "VECTOR(FLOAT, 1536)"

    def test_clickhouse_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("clickhouse", 128) == "Array(Float32)"

    def test_doris_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("doris", 128) == "ARRAY<FLOAT>"

    def test_spark_family_embedding_type(self):
        from benchbox.core.vector_search.schema import get_embedding_type

        assert get_embedding_type("lakesail", 128) == "ARRAY<FLOAT>"
        assert get_embedding_type("spark", 768) == "ARRAY<FLOAT>"

    def test_get_create_table_sql_vectors(self):
        from benchbox.core.vector_search.schema import get_create_table_sql

        sql = get_create_table_sql("vectors", dialect="duckdb", dimensions=128)
        assert "CREATE TABLE vectors" in sql
        assert "FLOAT[128]" in sql
        assert "category" in sql
        assert "doc_id" in sql

    def test_get_create_table_sql_unknown_raises(self):
        from benchbox.core.vector_search.schema import get_create_table_sql

        with pytest.raises(ValueError, match="Unknown table"):
            get_create_table_sql("nonexistent")

    def test_get_all_create_table_sql_contains_both_tables(self):
        from benchbox.core.vector_search.schema import get_all_create_table_sql

        ddl = get_all_create_table_sql(dialect="duckdb", dimensions=128)
        assert "CREATE TABLE vectors" in ddl
        assert "CREATE TABLE vector_queries" in ddl

    def test_get_create_table_sql_doris_uses_unsized_array(self):
        from benchbox.core.vector_search.schema import get_create_table_sql

        sql = get_create_table_sql("vectors", dialect="doris", dimensions=128)
        assert "ARRAY<FLOAT>" in sql
        assert "[128]" not in sql

    def test_get_create_table_sql_lakesail_uses_unsized_array(self):
        from benchbox.core.vector_search.schema import get_create_table_sql

        sql = get_create_table_sql("vectors", dialect="lakesail", dimensions=128)
        assert "ARRAY<FLOAT>" in sql
        assert "[128]" not in sql

    def test_ddl_dimensions_parameter(self):
        from benchbox.core.vector_search.schema import get_all_create_table_sql

        ddl_128 = get_all_create_table_sql(dimensions=128)
        ddl_768 = get_all_create_table_sql(dimensions=768)
        assert "FLOAT[128]" in ddl_128
        assert "FLOAT[768]" in ddl_768
        assert "FLOAT[128]" not in ddl_768


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestVectorSearchMetrics:
    """Tests for recall@k, latency percentiles, and QPS utilities."""

    def test_perfect_recall(self):
        from benchbox.core.vector_search.metrics import recall_at_k

        gt = [1, 2, 3, 4, 5]
        approx = [1, 2, 3, 4, 5]
        assert recall_at_k(gt, approx, k=5) == 1.0

    def test_zero_recall(self):
        from benchbox.core.vector_search.metrics import recall_at_k

        gt = [1, 2, 3]
        approx = [4, 5, 6]
        assert recall_at_k(gt, approx, k=3) == 0.0

    def test_partial_recall(self):
        from benchbox.core.vector_search.metrics import recall_at_k

        gt = [1, 2, 3, 4]
        approx = [1, 2, 10, 11]
        assert recall_at_k(gt, approx, k=4) == 0.5

    def test_recall_truncates_to_k(self):
        from benchbox.core.vector_search.metrics import recall_at_k

        # Only first k items from each list matter
        gt = [1, 2, 3, 100, 200]
        approx = [1, 2, 3, 99, 199]
        assert recall_at_k(gt, approx, k=3) == 1.0

    def test_recall_k_zero_returns_zero(self):
        from benchbox.core.vector_search.metrics import recall_at_k

        assert recall_at_k([1, 2, 3], [1, 2, 3], k=0) == 0.0

    def test_latency_percentiles_basic(self):
        from benchbox.core.vector_search.metrics import latency_percentiles

        lats = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = latency_percentiles(lats)
        assert "p50" in result and "p95" in result and "p99" in result
        assert result["p50"] <= result["p95"] <= result["p99"]

    def test_latency_percentiles_empty(self):
        from benchbox.core.vector_search.metrics import latency_percentiles

        result = latency_percentiles([])
        assert result == {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    def test_latency_percentiles_single_value(self):
        from benchbox.core.vector_search.metrics import latency_percentiles

        result = latency_percentiles([0.5])
        assert result["p50"] == 0.5
        assert result["p99"] == 0.5

    def test_qps_basic(self):
        from benchbox.core.vector_search.metrics import queries_per_second

        assert queries_per_second(100, 10.0) == pytest.approx(10.0)

    def test_qps_zero_elapsed(self):
        from benchbox.core.vector_search.metrics import queries_per_second

        assert queries_per_second(100, 0.0) == 0.0

    def test_mean_latency(self):
        from benchbox.core.vector_search.metrics import mean_latency

        assert mean_latency([0.1, 0.3]) == pytest.approx(0.2)

    def test_mean_latency_empty(self):
        from benchbox.core.vector_search.metrics import mean_latency

        assert mean_latency([]) == 0.0


# ---------------------------------------------------------------------------
# Benchmark class tests
# ---------------------------------------------------------------------------


class TestVectorSearchBenchmark:
    """Tests for VectorSearchBenchmark class construction and API."""

    def test_core_benchmark_imports(self):
        from benchbox.core.vector_search import VectorSearchBenchmark

        assert VectorSearchBenchmark is not None

    def test_construct_with_defaults(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert b.scale_factor == 0.01
        assert b.dimensions == 128

    def test_construct_custom_dimensions(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path, dimensions=768)
        assert b.dimensions == 768

    def test_get_query_returns_string(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        for qid in ALL_QUERY_IDS:
            sql = b.get_query(qid)
            assert isinstance(sql, str) and sql

    def test_get_query_params_raises(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        with pytest.raises(ValueError, match="static"):
            b.get_query("Q1", params={"k": 10})

    def test_get_all_queries_returns_six(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        queries = b.get_all_queries()
        assert len(queries) == 6
        assert set(queries.keys()) == set(ALL_QUERY_IDS)

    def test_get_queries_with_dialect(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        queries = b.get_queries(dialect="postgresql")
        assert "<=>" in queries["Q1"]

    def test_get_queries_with_doris_dialect(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        queries = b.get_queries(dialect="doris")
        assert "cosine_distance" in queries["Q1"]
        assert "l2_distance" in queries["Q2"]

    def test_get_queries_omits_version_gated_skip(self, tmp_path, monkeypatch):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        queries = b.get_queries(dialect="starrocks", platform_version="3.1")
        assert "Q2" not in queries

    def test_get_query_raises_for_version_gated_skip(self, tmp_path, monkeypatch):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        with pytest.raises(QuerySkippedError, match="Q2"):
            b.get_query("Q2", dialect="starrocks", platform_version="3.1")

    def test_non_pep440_engine_version_still_uses_variant(self, tmp_path, monkeypatch):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        sql = b.get_query("Q2", dialect="starrocks", platform_version="3.3.0-starrocks")
        assert "l2_distance" in sql

    def test_run_benchmark_marks_version_gated_skip(self, tmp_path, monkeypatch):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        results = b.run_benchmark(
            connection=object(),
            queries=["Q2"],
            dialect="starrocks",
            platform_version="3.1",
        )
        assert results["queries"]["Q2"]["status"] == "SKIPPED"
        assert "l2_distance requires StarRocks" in results["queries"]["Q2"]["skip_reason"]

    def test_get_create_tables_sql_duckdb(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        ddl = b.get_create_tables_sql(dialect="duckdb")
        assert "CREATE TABLE vectors" in ddl
        assert "FLOAT[128]" in ddl

    def test_get_schema_returns_tables_dict(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        b = VectorSearchBenchmark(scale_factor=0.01, output_dir=tmp_path)
        schema = b.get_schema()
        assert "vectors" in schema
        assert "vector_queries" in schema

    def test_invalid_scale_factor_raises(self, tmp_path):
        from benchbox.core.vector_search import VectorSearchBenchmark

        with pytest.raises((ValueError, Exception)):
            VectorSearchBenchmark(scale_factor=-1.0, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# Top-level wrapper tests
# ---------------------------------------------------------------------------


class TestVectorSearchWrapper:
    """Tests for the top-level VectorSearch wrapper class."""

    def test_wrapper_imports(self):
        from benchbox.vector_search import VectorSearch

        assert VectorSearch is not None

    def test_wrapper_instantiates(self, tmp_path):
        from benchbox.vector_search import VectorSearch

        b = VectorSearch(scale_factor=0.01, output_dir=tmp_path)
        assert b.scale_factor == 0.01

    def test_wrapper_get_query(self, tmp_path):
        from benchbox.vector_search import VectorSearch

        b = VectorSearch(scale_factor=0.01, output_dir=tmp_path)
        sql = b.get_query("Q1")
        assert "array_cosine_similarity" in sql

    def test_wrapper_get_all_queries(self, tmp_path):
        from benchbox.vector_search import VectorSearch

        b = VectorSearch(scale_factor=0.01, output_dir=tmp_path)
        assert len(b.get_all_queries()) == 6


# ---------------------------------------------------------------------------
# Registry integration tests
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    """Tests that vector_search is properly registered."""

    def test_benchmark_class_name_registered(self):
        from benchbox.core.benchmark_registry import BENCHMARK_CLASS_NAMES

        assert "vector_search" in BENCHMARK_CLASS_NAMES
        assert BENCHMARK_CLASS_NAMES["vector_search"] == "VectorSearch"

    def test_benchmark_metadata_registered(self):
        from benchbox.core.benchmark_registry import BENCHMARK_METADATA

        meta = BENCHMARK_METADATA.get("vector_search")
        assert meta is not None
        assert meta["category"] == "AI/ML"
        assert meta["num_queries"] == 6
        assert meta["min_scale"] == 0.01

    def test_get_benchmark_class_returns_class(self):
        from benchbox.core.benchmark_registry import get_benchmark_class

        cls = get_benchmark_class("vector_search")
        assert cls is not None

    def test_lazy_load_via_benchbox_module(self):
        import benchbox

        cls = benchbox.VectorSearch
        assert cls is not None

    def test_vector_search_in_category_list(self):
        from benchbox.core.benchmark_registry import get_benchmarks_by_category

        ai_ml = get_benchmarks_by_category("AI/ML")
        assert "vector_search" in ai_ml
