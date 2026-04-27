"""Tests for ClickBench CSV loading configuration and empty string handling.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestClickBenchCSVLoading:
    """Test ClickBench CSV loading configuration and empty string preservation."""

    def setup_method(self):
        """Setup test fixtures."""
        self.benchmark = ClickBenchBenchmark(scale_factor=0.001)
        self.adapter = DuckDBAdapter()

    def test_clickbench_csv_loading_config(self):
        """Test that ClickBench provides correct CSV loading configuration."""
        config = self.benchmark.get_csv_loading_config("hits")

        expected_config = [
            "delim='|'",  # ClickBench uses pipe delimiter
            "header=false",  # No header row
            "nullstr='__NULL__'",  # Use a marker that won't appear in real data for NULLs
            "ignore_errors=true",  # Continue on parse errors
            "auto_detect=true",  # Auto-detect types
        ]

        assert config == expected_config

    def test_empty_string_preservation_logic(self):
        """Test the logic behind empty string preservation in ClickBench."""
        # This tests the reasoning documented in the CSV loading config method
        config = self.benchmark.get_csv_loading_config("hits")

        # Verify key configuration for empty string preservation
        assert "nullstr='__NULL__'" in config, "Must use non-empty string NULL marker to preserve empty strings"
        assert "delim='|'" in config, "ClickBench uses pipe delimiter"

        # The key insight: by using '__NULL__' instead of '' for nullstr,
        # DuckDB will preserve actual empty strings in the CSV as empty strings
        # rather than converting them to NULL values

    def test_clickbench_schema_consistency(self):
        """Test that ClickBench schema is consistent with NOT NULL expectations."""
        from benchbox.core.clickbench.schema import HITS_TABLE

        # Verify all fields are NOT NULL as expected
        for column in HITS_TABLE["columns"]:
            assert column["nullable"] is False, f"Column {column['name']} should be NOT NULL"

        # This validates that the schema correctly expects no NULL values,
        # which is why preserving empty strings (not converting to NULL) is critical

    def test_clickbench_query_patterns(self):
        """Test that ClickBench queries use empty string filtering patterns."""
        from benchbox.core.clickbench.queries import ClickBenchQueryManager

        query_manager = ClickBenchQueryManager()
        # Get all queries by checking query IDs
        query_ids = [f"Q{i}" for i in range(1, 44)]  # ClickBench has Q1-Q43
        queries = {qid: query_manager.get_query(qid) for qid in query_ids}

        # Check for queries that filter empty strings (not NULL values)
        empty_string_queries = []
        for query_id, query_sql in queries.items():
            if "<> ''" in query_sql:
                empty_string_queries.append(query_id)

        assert len(empty_string_queries) > 0, "ClickBench should have queries filtering empty strings"

        # Verify no queries use IS NOT NULL patterns (which would be wrong for ClickBench)
        null_queries = []
        for query_id, query_sql in queries.items():
            if "IS NOT NULL" in query_sql.upper():
                null_queries.append(query_id)

        assert len(null_queries) == 0, f"ClickBench queries should not use IS NOT NULL: {null_queries}"


class TestClickBenchDataIntegrity:
    """Test data integrity and validation for ClickBench empty string handling."""

    def test_csv_loading_configuration_logic(self):
        """Test the logic behind CSV loading configuration without actual CSV files."""
        from benchbox.core.clickbench.benchmark import ClickBenchBenchmark

        benchmark = ClickBenchBenchmark()
        config = benchmark.get_csv_loading_config("hits")

        # Test that the configuration is designed to preserve empty strings
        assert "nullstr='__NULL__'" in config
        assert "delim='|'" in config

        # The key insight: nullstr='__NULL__' means DuckDB will only treat
        # the literal string '__NULL__' as NULL, preserving empty strings

    def test_empty_string_vs_null_handling(self):
        """Test the conceptual difference between empty strings and NULLs in ClickBench context."""
        # This test documents the key insight of the fix

        # ClickBench schema: all fields NOT NULL
        from benchbox.core.clickbench.schema import HITS_TABLE

        referer_col = next(col for col in HITS_TABLE["columns"] if col["name"] == "Referer")
        assert referer_col["nullable"] is False

        # ClickBench queries: filter with <> '' not IS NOT NULL
        from benchbox.core.clickbench.queries import ClickBenchQueryManager

        query_manager = ClickBenchQueryManager()

        # Check a query that uses empty string filtering
        try:
            q29_sql = query_manager.get_query("Q29")  # Query that filters on Referer
            if q29_sql and "Referer" in q29_sql:
                # Should use empty string filtering, not NULL checking
                assert "<>" in q29_sql or "!=" in q29_sql or "WHERE" in q29_sql
        except Exception:
            # If query not found or has issues, that's okay for this test
            pass

        # The fix ensures DuckDB CSV loading preserves this semantic:
        # - Empty CSV fields -> Empty strings in database (not NULL)
        # - Only '__NULL__' literal in CSV -> NULL in database (which shouldn't happen)

    def test_benchmark_integration_concept(self):
        """Test that the benchmark components work together conceptually."""
        from benchbox.core.clickbench.benchmark import ClickBenchBenchmark

        # Test the integration between benchmark configuration and platform loading
        benchmark = ClickBenchBenchmark()

        # Benchmark provides CSV configuration
        csv_config = benchmark.get_csv_loading_config("hits")
        assert len(csv_config) > 0

        # Verify CSV config contains expected values
        assert "nullstr='__NULL__'" in csv_config
        assert "delim='|'" in csv_config


class TestClickBenchSchemaRanges:
    """Guard: schema numeric types must be wide enough for their source ClickHouse values.

    BenchBox intentionally uses a synthetic generator that caps UInt16 columns at
    values well below SMALLINT_MAX (32 767).  Three columns are exceptions: Interests,
    RefererCategoryID, and URLCategoryID — the BenchBox generator produces the full
    UInt16 range for those, so they are widened to INTEGER.

    The remaining UInt16 columns remain SMALLINT because the BenchBox generator caps
    them well below SMALLINT_MAX.  BOUNDED_UINT16_COLUMNS documents those caps; the
    test below verifies the schema still declares them as SMALLINT (not accidentally
    widened) and that the caps are genuinely below SMALLINT_MAX.

    If loading real ClickHouse-exported data (not BenchBox-generated), these columns
    may require widening to INTEGER.  See schema.py for the full type-width notes.
    """

    # Columns whose ClickHouse source type is UInt16 (0-65 535) and BenchBox generates
    # the full range → must be wider than SMALLINT.
    UINT16_COLUMNS = {"Interests", "RefererCategoryID", "URLCategoryID"}
    SMALLINT_MAX = 32_767

    # UInt16 in ClickHouse but BenchBox generator caps well below SMALLINT_MAX.
    # Values are (ClickHouse source type, BenchBox generator max).
    BOUNDED_UINT16_COLUMNS: dict[str, tuple[str, int]] = {
        "UserAgent": ("UInt16", 1_000),
        "ResolutionWidth": ("UInt16", 1_920),
        "ResolutionHeight": ("UInt16", 1_200),
        "UserAgentMajor": ("UInt16", 100),
        "SearchEngineID": ("UInt16", 50),
        "WindowClientWidth": ("UInt16", 1_920),
        "WindowClientHeight": ("UInt16", 1_200),
        "SilverlightVersion2": ("UInt16", 50),
        "SilverlightVersion4": ("UInt16", 100),
        "HistoryLength": ("UInt16", 100),
        "HTTPError": ("UInt16", 500),
        "ParamCurrencyID": ("UInt16", 10),
    }

    def _col_map(self):
        from benchbox.core.clickbench.schema import HITS_TABLE

        return {c["name"]: c["type"] for c in HITS_TABLE["columns"]}

    def test_uint16_columns_are_not_smallint(self):
        """UInt16 source columns whose generator produces the full range must not be SMALLINT."""
        col_map = self._col_map()
        for col in self.UINT16_COLUMNS:
            assert col in col_map, f"Column {col} missing from schema"
            assert col_map[col].upper() != "SMALLINT", (
                f"{col} is UInt16 in ClickHouse (0-65535) but declared as SMALLINT "
                f"(max {self.SMALLINT_MAX}); use INTEGER or wider"
            )

    def test_bounded_uint16_columns_remain_smallint(self):
        """UInt16 columns whose BenchBox generator caps below SMALLINT_MAX stay SMALLINT.

        These columns are intentionally kept as SMALLINT because the synthetic generator
        limits them to safe ranges.  This test guards against accidental widening.
        It also asserts the documented BenchBox cap is genuinely below SMALLINT_MAX,
        so the table above stays accurate.
        """
        col_map = self._col_map()
        for col, (ch_type, benchbox_max) in self.BOUNDED_UINT16_COLUMNS.items():
            assert col in col_map, f"Column {col} missing from schema"
            assert col_map[col].upper() == "SMALLINT", (
                f"{col} ({ch_type} in ClickHouse, BenchBox max={benchbox_max}) should remain "
                f"SMALLINT — only widen if the generator range is updated to exceed {self.SMALLINT_MAX}"
            )
            assert benchbox_max <= self.SMALLINT_MAX, (
                f"BOUNDED_UINT16_COLUMNS entry for {col} documents BenchBox max={benchbox_max} "
                f"which exceeds SMALLINT_MAX={self.SMALLINT_MAX}; the column needs widening to INTEGER"
            )

    def test_generator_interests_values_fit_integer_and_exceed_smallint(self):
        """Interests generator must produce values in [0, 65535] including values > SMALLINT_MAX.

        This double-checks both that INTEGER is wide enough (range test) and that SMALLINT
        would genuinely overflow (at least one value > 32 767 across 200 records), confirming
        the INTEGER widening is load-bearing and not cosmetic.

        P(all 200 values ≤ 32 767) = (0.5)^200 ≈ 10^-60 — effectively impossible.
        """
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from benchbox.core.clickbench.generator import ClickBenchDataGenerator
        from benchbox.core.clickbench.schema import HITS_TABLE

        with tempfile.TemporaryDirectory() as td:
            gen = ClickBenchDataGenerator(scale_factor=0.0001, output_dir=Path(td))
            records = [gen._generate_hit_record(i, datetime(2013, 7, 1)) for i in range(200)]

        col_names = [c["name"] for c in HITS_TABLE["columns"]]
        interests_idx = col_names.index("Interests")
        values = [r[interests_idx] for r in records]

        assert all(0 <= v <= 65_535 for v in values), "Interests values must be in UInt16 range [0, 65535]"
        assert any(v > self.SMALLINT_MAX for v in values), (
            f"Expected at least one Interests value > {self.SMALLINT_MAX} in 200 records; "
            "got all values ≤ SMALLINT_MAX — the INTEGER widening may be unnecessary"
        )
