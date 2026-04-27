"""Tests for TPC-H stream execution functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpch.streams import TPCHStreamRunner, TPCHStreams

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHStreamRunner:
    """Test TPC-H stream execution methods."""

    @pytest.fixture
    def stream_runner(self):
        """Create a stream runner for testing."""
        return TPCHStreamRunner(connection_string="test://localhost", dialect="standard", verbose=False)

    @pytest.fixture
    def mock_stream_file(self):
        """Create a mock stream file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
            f.write("""-- TPC-H Stream 0
-- Scale Factor: 0.01
-- RNG Seed: 1
-- Query Order (Permuted): [14, 2, 9, 20, 6, 17, 18, 8, 21, 13, 3, 22, 16, 4, 11, 15, 1, 10, 19, 5, 7, 12]
-- Generated using TPC-H qgen tool
-- Compliant with TPC-H specification

-- Query 14 (Stream 0, Position 1)
SELECT 100.00 * SUM(CASE
    WHEN P_TYPE LIKE 'PROMO%'
    THEN L_EXTENDEDPRICE * (1 - L_DISCOUNT)
    ELSE 0
END) / SUM(L_EXTENDEDPRICE * (1 - L_DISCOUNT)) AS PROMO_REVENUE
FROM LINEITEM, PART
WHERE L_PARTKEY = P_PARTKEY
  AND L_SHIPDATE >= DATE '1995-09-01'
  AND L_SHIPDATE < DATE '1995-09-01' + INTERVAL '1' MONTH;

-- Query 2 (Stream 0, Position 2)
SELECT S_ACCTBAL, S_NAME, N_NAME, P_PARTKEY, P_MFGR, S_ADDRESS, S_PHONE, S_COMMENT
FROM PART, SUPPLIER, PARTSUPP, NATION, REGION
WHERE P_PARTKEY = PS_PARTKEY
  AND S_SUPPKEY = PS_SUPPKEY
  AND P_SIZE = 15
  AND P_TYPE LIKE '%BRASS'
  AND S_NATIONKEY = N_NATIONKEY
  AND N_REGIONKEY = R_REGIONKEY
  AND R_NAME = 'EUROPE'
  AND PS_SUPPLYCOST = (
    SELECT MIN(PS_SUPPLYCOST)
    FROM PARTSUPP, SUPPLIER, NATION, REGION
    WHERE P_PARTKEY = PS_PARTKEY
      AND S_SUPPKEY = PS_SUPPKEY
      AND S_NATIONKEY = N_NATIONKEY
      AND N_REGIONKEY = R_REGIONKEY
      AND R_NAME = 'EUROPE')
ORDER BY S_ACCTBAL DESC, N_NAME, S_NAME, P_PARTKEY;

""")
            return Path(f.name)

    def test_run_stream_basic_functionality(self, stream_runner, mock_stream_file):
        """Test basic stream execution functionality."""
        result = stream_runner.run_stream(mock_stream_file, stream_id=0)

        # Verify result structure
        assert isinstance(result, dict)
        assert result["stream_id"] == 0
        assert result["stream_file"] == str(mock_stream_file)
        assert "start_time" in result
        assert "end_time" in result
        assert "duration" in result
        assert "queries_executed" in result
        assert "queries_successful" in result
        assert "queries_failed" in result
        assert "success" in result
        assert "error" in result
        assert "query_results" in result

        # Verify basic execution worked
        assert result["success"] is True
        assert result["error"] is None
        assert result["queries_executed"] == 2  # Two queries in mock file
        assert result["queries_successful"] == 2
        assert result["queries_failed"] == 0
        # Use >= 0 for cross-platform compatibility (Windows timer resolution)
        assert result["duration"] >= 0

        # Clean up
        mock_stream_file.unlink()

    def test_run_stream_nonexistent_file(self, stream_runner):
        """Test stream execution with nonexistent file."""
        nonexistent_file = Path("/tmp/nonexistent_stream.sql")
        result = stream_runner.run_stream(nonexistent_file, stream_id=0)

        # Should handle error gracefully
        assert result["success"] is False
        assert result["error"] is not None
        assert "not found" in result["error"]
        assert result["queries_executed"] == 0
        assert result["queries_successful"] == 0

    def test_run_concurrent_streams_basic_functionality(self, stream_runner, mock_stream_file):
        """Test concurrent stream execution."""
        # Create multiple mock stream files
        stream_files = []
        for i in range(2):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
                f.write(f"""-- TPC-H Stream {i}
-- Query 1 (Stream {i}, Position 1)
SELECT * FROM REGION LIMIT 1;

-- Query 2 (Stream {i}, Position 2)
SELECT * FROM NATION LIMIT 1;
""")
                stream_files.append(Path(f.name))

        try:
            # Mock the ConcurrentQueryExecutor to avoid actual concurrent execution
            with patch("benchbox.utils.execution_manager.ConcurrentQueryExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                # Mock the execute_concurrent_queries method
                mock_result = Mock()
                mock_result.stream_results = [
                    {"success": True, "queries_executed": 2, "queries_successful": 2},
                    {"success": True, "queries_executed": 2, "queries_successful": 2},
                ]
                mock_result.queries_executed = 4
                mock_result.queries_successful = 4
                mock_result.queries_failed = 0
                mock_result.success = True
                mock_result.errors = []
                mock_executor.execute_concurrent_queries.return_value = mock_result
                mock_executor.config = {"enabled": False}

                result = stream_runner.run_concurrent_streams(stream_files)

                # Verify result structure
                assert isinstance(result, dict)
                assert "start_time" in result
                assert "end_time" in result
                assert "total_duration" in result
                assert "num_streams" in result
                assert "streams_executed" in result
                assert "streams_successful" in result
                assert "streams_failed" in result
                assert "total_queries_executed" in result
                assert "total_queries_successful" in result
                assert "total_queries_failed" in result
                assert "success" in result
                assert "errors" in result
                assert "stream_results" in result

                # Verify execution worked
                assert result["success"] is True
                assert result["num_streams"] == 2
                assert result["streams_executed"] == 2
                assert result["streams_successful"] == 2
                assert result["streams_failed"] == 0
                assert result["total_queries_executed"] == 4
                assert result["total_queries_successful"] == 4
                assert result["total_queries_failed"] == 0
                # Use >= 0 for cross-platform compatibility (Windows timer resolution)
                assert result["total_duration"] >= 0

                # Verify ConcurrentQueryExecutor was called properly
                mock_executor_class.assert_called_once()
                mock_executor.execute_concurrent_queries.assert_called_once()

        finally:
            # Clean up
            for stream_file in stream_files:
                stream_file.unlink()

    def test_run_concurrent_streams_empty_list(self, stream_runner):
        """Test concurrent stream execution with empty stream list."""
        result = stream_runner.run_concurrent_streams([])

        # Should handle empty list gracefully
        assert result["num_streams"] == 0
        assert result["streams_executed"] == 0
        # Use >= 0 for cross-platform compatibility (Windows timer resolution)
        assert result["total_duration"] >= 0


class TestTPCHStreamsIntegration:
    """Integration tests for TPC-H streams functionality."""

    def test_stream_generation_and_execution_integration(self):
        """Test integration between stream generation and execution."""
        # This test is more of an integration test that would require
        # actual TPC-H binaries, so we'll keep it simple for now

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            # Create a streams manager
            streams_manager = TPCHStreams(num_streams=1, scale_factor=0.01, output_dir=output_dir, verbose=False)

            # Test stream info functionality
            stream_info = streams_manager.get_stream_info(0)

            assert stream_info["stream_id"] == 0
            assert stream_info["scale_factor"] == 0.01
            assert stream_info["query_count"] == 22
            assert stream_info["rng_seed"] == 1
            assert len(stream_info["query_order"]) == 22

            # Verify permutation matrix is working
            assert stream_info["query_order"] == [
                14,
                2,
                9,
                20,
                6,
                17,
                18,
                8,
                21,
                13,
                3,
                22,
                16,
                4,
                11,
                15,
                1,
                10,
                19,
                5,
                7,
                12,
            ]
            assert stream_info["permutation_index"] == 0

    def test_multiple_streams_have_different_permutations(self):
        """Test that different streams have different query permutations."""
        streams_manager = TPCHStreams(num_streams=3, scale_factor=1.0)

        stream_0_info = streams_manager.get_stream_info(0)
        stream_1_info = streams_manager.get_stream_info(1)
        stream_2_info = streams_manager.get_stream_info(2)

        # Verify each stream has different permutation
        assert stream_0_info["query_order"] != stream_1_info["query_order"]
        assert stream_1_info["query_order"] != stream_2_info["query_order"]
        assert stream_0_info["query_order"] != stream_2_info["query_order"]

        # Verify all have same number of queries
        assert len(stream_0_info["query_order"]) == 22
        assert len(stream_1_info["query_order"]) == 22
        assert len(stream_2_info["query_order"]) == 22

        # Verify all contain the same queries (just different order)
        assert set(stream_0_info["query_order"]) == set(range(1, 23))
        assert set(stream_1_info["query_order"]) == set(range(1, 23))
        assert set(stream_2_info["query_order"]) == set(range(1, 23))
