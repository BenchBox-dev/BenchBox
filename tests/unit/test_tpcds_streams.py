"""Tests for TPC-DS stream execution functionality.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.benchmark.runner import TPCDSBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def fake_tpcds_stream_environment(monkeypatch):  # noqa: C901
    """Stub TPC-DS stream dependencies so tests run without compiled binaries."""

    class FakeQuery:
        def __init__(self, stream_id, position, query_id, variant=None, sql="SELECT 1"):
            self.stream_id = stream_id
            self.position = position
            self.query_id = query_id
            self.variant = variant
            self.sql = sql

    class FakeStreamManager:
        def __init__(self, num_streams, base_seed):
            self.num_streams = num_streams
            self.base_seed = base_seed

        def generate_streams(self):
            streams = {}
            for stream_id in range(self.num_streams):
                streams[stream_id] = [
                    FakeQuery(stream_id, 0, 1, sql=f"SELECT {stream_id + 1}"),
                    FakeQuery(stream_id, 1, 2, variant="a", sql=f"SELECT {stream_id + 2}"),
                ]
            return streams

    def _fake_create_standard_streams(query_manager, num_streams, base_seed):
        return FakeStreamManager(num_streams, base_seed)

    monkeypatch.setattr("benchbox.core.tpcds.streams.create_standard_streams", _fake_create_standard_streams)

    class FakeDSQGen:
        def generate(self, query_id, **_):
            return f"SELECT {query_id}"

        def generate_with_parameters(self, query_id, parameters, **_):
            return f"SELECT {query_id} /* params:{parameters} */"

        def get_query_variations(self, query_id):
            return [str(query_id)]

        def validate_query_id(self, query_id):
            try:
                value = int(query_id)
            except (TypeError, ValueError):
                return False
            return 1 <= value <= 99

    class FakeQueryManager:
        def __init__(self):
            self.dsqgen = FakeDSQGen()

        def get_query(self, query_id, **_):
            return f"SELECT {query_id}"

        def get_all_queries(self, **_):
            return {1: "SELECT 1", 2: "SELECT 2"}

    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", lambda: FakeQueryManager())

    class FakeDataGenerator:
        def __init__(self, scale_factor=1.0, parallel=1, output_dir=None, **kwargs):
            self.scale_factor = scale_factor
            self.parallel = parallel
            self.output_dir = Path(output_dir) if output_dir else Path.cwd()
            self.kwargs = kwargs
            self.generated = False

        def generate(self):
            self.generated = True
            return {
                "store_sales": self.output_dir / "store_sales.dat",
                "store_returns": self.output_dir / "store_returns.dat",
            }

    monkeypatch.setattr(
        "benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator",
        lambda *args, **kwargs: FakeDataGenerator(*args, **kwargs),
    )

    class FakeCTools:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def get_tools_info(self):
            return {"dsqgen_available": False, "templates_available": False, "available_tools": []}

    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", FakeCTools)

    fake_module = types.ModuleType("benchbox.core.tpcds.benchmark.streams")
    fake_module.create_standard_streams = _fake_create_standard_streams
    monkeypatch.setitem(sys.modules, "benchbox.core.tpcds.benchmark.streams", fake_module)

    class FakeValidationEngine:
        def validate(self, *_args, **_kwargs):
            return {"status": "skipped"}

    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.DataValidationEngine", FakeValidationEngine)
    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.DatabaseValidationEngine", FakeValidationEngine)


class TestTPCDSStreamGeneration:
    """Test TPC-DS stream generation methods."""

    @pytest.fixture
    def tpcds_benchmark(self):
        """Create a TPC-DS benchmark for testing."""
        benchmark = TPCDSBenchmark(
            scale_factor=1.0,  # Default scale for consistency
            verbose=False,
        )
        benchmark.verbose = False
        return benchmark

    def test_generate_streams_basic_functionality(self, tpcds_benchmark):
        """Test basic stream generation functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            streams_dir = Path(temp_dir) / "streams"

            stream_files = tpcds_benchmark.generate_streams(num_streams=2, rng_seed=42, streams_output_dir=streams_dir)

            # Verify stream files were created
            assert len(stream_files) == 2
            assert all(isinstance(f, Path) for f in stream_files)
            assert all(f.exists() for f in stream_files)

            # Verify stream files have expected names
            expected_names = {"stream_0.sql", "stream_1.sql"}
            actual_names = {f.name for f in stream_files}
            assert actual_names == expected_names

            # Verify stream files have content
            for stream_file in stream_files:
                content = stream_file.read_text()
                assert "TPC-DS Stream" in content
                assert "Scale Factor: 1.0" in content
                assert "RNG Seed: 42" in content
                assert "-- Query" in content

    def test_generate_streams_default_parameters(self, tpcds_benchmark):
        """Test stream generation with default parameters."""
        stream_files = tpcds_benchmark.generate_streams()

        # Should generate 1 stream by default
        assert len(stream_files) == 1
        assert all(f.exists() for f in stream_files)

        # Verify content with default seed
        content = stream_files[0].read_text()
        assert "RNG Seed: 42" in content  # Default seed

    def test_generate_streams_creates_directory(self, tpcds_benchmark):
        """Test that stream generation creates output directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nonexistent_dir = Path(temp_dir) / "nonexistent" / "streams"
            assert not nonexistent_dir.exists()

            stream_files = tpcds_benchmark.generate_streams(num_streams=1, streams_output_dir=nonexistent_dir)

            assert nonexistent_dir.exists()
            assert len(stream_files) == 1
            assert stream_files[0].exists()

    def test_get_stream_info_basic_functionality(self, tpcds_benchmark):
        """Test basic stream info functionality."""
        stream_info = tpcds_benchmark.get_stream_info(0)

        # Verify result structure
        assert isinstance(stream_info, dict)
        assert stream_info["stream_id"] == 0
        assert stream_info["scale_factor"] == 1.0
        assert "query_count" in stream_info
        assert "unique_query_count" in stream_info
        assert "rng_seed" in stream_info
        assert "parameter_seed" in stream_info
        assert "query_list" in stream_info
        assert "permutation_mode" in stream_info

        # Verify values make sense
        assert stream_info["query_count"] > 0
        assert stream_info["unique_query_count"] > 0
        assert stream_info["rng_seed"] == 42  # stream 0 with default base seed
        assert stream_info["parameter_seed"] == 1042  # base seed + 1000
        assert stream_info["permutation_mode"] == "tpcds_standard"
        assert isinstance(stream_info["query_list"], list)

    def test_get_stream_info_different_streams(self, tpcds_benchmark):
        """Test that different streams have different info."""
        stream_0_info = tpcds_benchmark.get_stream_info(0)
        stream_1_info = tpcds_benchmark.get_stream_info(1)

        # Stream IDs should be different
        assert stream_0_info["stream_id"] == 0
        assert stream_1_info["stream_id"] == 1

        # Seeds should be different
        assert stream_0_info["rng_seed"] != stream_1_info["rng_seed"]
        assert stream_0_info["parameter_seed"] != stream_1_info["parameter_seed"]

        # Query lists might be different (due to different permutations)
        # This depends on the permutation algorithm, but we can at least check they exist
        assert len(stream_0_info["query_list"]) > 0
        assert len(stream_1_info["query_list"]) > 0

    def test_get_stream_info_invalid_stream_id(self, tpcds_benchmark):
        """Test get_stream_info with large but reasonable stream ID."""
        # This should work for any reasonable stream ID since we create it on demand
        # Use 10 instead of 999 to avoid performance issues
        stream_info = tpcds_benchmark.get_stream_info(10)
        assert stream_info["stream_id"] == 10


class TestTPCDSStreamExecution:
    """Test TPC-DS stream execution methods."""

    @pytest.fixture
    def tpcds_benchmark(self):
        """Create a TPC-DS benchmark for testing."""
        benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)
        benchmark.verbose = False
        return benchmark

    @pytest.fixture
    def mock_stream_files(self):
        """Create mock stream files for testing."""
        stream_files = []
        for i in range(2):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
                f.write(f"""-- TPC-DS Stream {i}
-- Scale Factor: 0.01
-- RNG Seed: 42
-- Generated using TPC-DS query manager

-- Query 1 (Stream {i}, Position 1)
SELECT COUNT(*) FROM CUSTOMER LIMIT 1;

-- Query 2 (Stream {i}, Position 2)
SELECT COUNT(*) FROM ITEM LIMIT 1;
""")
                stream_files.append(Path(f.name))
        return stream_files

    def test_run_streams_basic_functionality(self, tpcds_benchmark, mock_stream_files):
        """Test basic stream execution functionality."""

        mock_connection = Mock()
        result = tpcds_benchmark.run_streams(
            connection=mock_connection,
            stream_files=mock_stream_files,
            concurrent=False,  # Use sequential execution for simplicity
        )

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

        # Verify basic execution worked
        assert result["num_streams"] == 2
        assert result["streams_executed"] == 2
        # Use >= 0 for cross-platform compatibility (Windows timer resolution)
        assert result["total_duration"] >= 0

        # Clean up
        for stream_file in mock_stream_files:
            stream_file.unlink()

    def test_run_streams_nonexistent_files(self, tpcds_benchmark):
        """Test stream execution with nonexistent files."""

        nonexistent_files = [
            Path("/tmp/nonexistent_stream_1.sql"),
            Path("/tmp/nonexistent_stream_2.sql"),
        ]
        mock_connection = Mock()

        result = tpcds_benchmark.run_streams(
            connection=mock_connection, stream_files=nonexistent_files, concurrent=False
        )

        # Should handle errors gracefully
        assert not result["success"]
        assert len(result["errors"]) > 0
        assert all("not found" in error for error in result["errors"])

        # Should still have proper structure
        assert result["streams_executed"] == 2
        assert result["streams_successful"] == 0
        assert result["streams_failed"] == 2

    def test_run_streams_generates_streams_when_none_provided(self, tpcds_benchmark):
        """Test that run_streams generates streams when none are provided."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Set benchmark output directory to temp directory
            tpcds_benchmark.output_dir = Path(temp_dir)
            mock_connection = Mock()

            result = tpcds_benchmark.run_streams(connection=mock_connection, concurrent=False)

            # Should have generated and executed streams
            assert result["streams_executed"] == 2  # Default num_streams
            assert "stream_results" in result
            assert len(result["stream_results"]) == 2

    def test_run_streams_concurrent_execution_disabled(self, tpcds_benchmark, mock_stream_files):
        """Test concurrent stream execution when concurrent queries are disabled."""

        # Mock the ConcurrentQueryExecutor to be disabled
        with patch("benchbox.utils.execution_manager.ConcurrentQueryExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor.config = {"enabled": False}
            mock_executor_class.return_value = mock_executor
            mock_connection = Mock()

            result = tpcds_benchmark.run_streams(
                connection=mock_connection,
                stream_files=mock_stream_files,
                concurrent=True,  # Request concurrent but it will fallback to sequential
            )

            # Should still work with sequential execution
            assert result["streams_executed"] == 2
            assert "stream_results" in result

        # Clean up
        for stream_file in mock_stream_files:
            stream_file.unlink()

    def test_run_streams_single_stream(self, tpcds_benchmark, mock_stream_files):
        """Test execution with single stream."""

        single_stream = [mock_stream_files[0]]
        mock_connection = Mock()

        result = tpcds_benchmark.run_streams(connection=mock_connection, stream_files=single_stream, concurrent=False)

        # Should handle single stream correctly
        assert result["num_streams"] == 1
        assert result["streams_executed"] == 1
        assert len(result["stream_results"]) == 1

        # Clean up
        single_stream[0].unlink()


class TestTPCDSStreamsIntegration:
    """Integration tests for TPC-DS streams functionality."""

    def test_stream_generation_and_info_integration(self):
        """Test integration between stream generation and info retrieval."""
        tpcds_benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)
        tpcds_benchmark.verbose = False

        with tempfile.TemporaryDirectory() as temp_dir:
            streams_dir = Path(temp_dir) / "streams"

            # Generate streams
            tpcds_benchmark.generate_streams(num_streams=2, rng_seed=123, streams_output_dir=streams_dir)

            # Get stream info
            stream_0_info = tpcds_benchmark.get_stream_info(0)
            stream_1_info = tpcds_benchmark.get_stream_info(1)

            # Verify consistency
            assert stream_0_info["scale_factor"] == tpcds_benchmark.scale_factor
            assert stream_1_info["scale_factor"] == tpcds_benchmark.scale_factor

            # Verify streams have different characteristics
            assert stream_0_info["stream_id"] != stream_1_info["stream_id"]
            assert stream_0_info["rng_seed"] != stream_1_info["rng_seed"]

    def test_stream_info_contains_valid_tpcds_queries(self):
        """Test that stream info contains valid TPC-DS query IDs."""
        tpcds_benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)
        stream_info = tpcds_benchmark.get_stream_info(0)

        # Parse query IDs from query list
        query_ids = set()
        for query_str in stream_info["query_list"]:
            # Extract numeric part (e.g., "14a" -> 14, "23" -> 23)
            numeric_part = "".join(c for c in query_str if c.isdigit())
            if numeric_part:
                query_ids.add(int(numeric_part))

        # Should contain valid TPC-DS query IDs (1-99)
        assert all(1 <= qid <= 99 for qid in query_ids)
        assert len(query_ids) > 0

    def test_multiple_streams_have_different_characteristics(self):
        """Test that multiple streams have different query orderings."""
        tpcds_benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)
        tpcds_benchmark.verbose = False

        stream_0_info = tpcds_benchmark.get_stream_info(0)
        stream_1_info = tpcds_benchmark.get_stream_info(1)
        stream_2_info = tpcds_benchmark.get_stream_info(2)

        # All should have the same number of queries
        assert stream_0_info["query_count"] == stream_1_info["query_count"]
        assert stream_1_info["query_count"] == stream_2_info["query_count"]

        # But different seeds should result in different query orderings
        # Note: this depends on the permutation algorithm, but at minimum they should have different seeds
        assert stream_0_info["rng_seed"] != stream_1_info["rng_seed"]
        assert stream_1_info["rng_seed"] != stream_2_info["rng_seed"]
        assert stream_0_info["rng_seed"] != stream_2_info["rng_seed"]
