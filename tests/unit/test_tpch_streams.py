"""Tests for TPC-H stream execution functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path

import pytest

from benchbox.core.tpch.streams import TPCHStreamRunner, TPCHStreams

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHStreamRunner:
    """Test TPC-H stream execution methods.

    NOTE: ``TPCHStreamRunner.run_stream``/``run_concurrent_streams`` used to
    "execute" a stream by counting ``-- Query`` comment lines in the stream
    file and reporting every query as successful, regardless of whether the
    file (or the queries in it) were real -- it never connected to a database
    despite accepting a ``connection_string``. The tests below previously
    asserted that fake success (e.g. a stream file was read, and
    ``result["success"] is True``/``queries_executed == 2`` was asserted from
    comment-counting alone, with no real database involved). Both methods now
    raise ``NotImplementedError`` unconditionally so they can never again
    silently report fake success; see
    ``benchbox.core.tpch.throughput_test.TPCHThroughputTest`` for the real,
    spec-compliant execution path.
    """

    @pytest.fixture
    def stream_runner(self):
        """Create a stream runner for testing."""
        return TPCHStreamRunner(connection_string="test://localhost", dialect="standard", verbose=False)

    @pytest.fixture
    def mock_stream_file(self):
        """Create a mock stream file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, encoding="utf-8") as f:
            f.write("""-- TPC-H Stream 0
-- Query 14 (Stream 0, Position 1)
SELECT 1;

-- Query 2 (Stream 0, Position 2)
SELECT 2;
""")
            return Path(f.name)

    def test_run_stream_raises_not_implemented(self, stream_runner, mock_stream_file):
        """run_stream never executes SQL; it always raises NotImplementedError."""
        try:
            with pytest.raises(NotImplementedError, match="does not execute SQL"):
                stream_runner.run_stream(mock_stream_file, stream_id=0)
        finally:
            mock_stream_file.unlink()

    def test_run_stream_raises_not_implemented_even_for_missing_file(self, stream_runner):
        """run_stream raises NotImplementedError regardless of whether the file exists."""
        nonexistent_file = Path("/tmp/nonexistent_stream.sql")
        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            stream_runner.run_stream(nonexistent_file, stream_id=0)

    def test_run_concurrent_streams_raises_not_implemented(self, stream_runner, mock_stream_file):
        """run_concurrent_streams never executes SQL; it always raises NotImplementedError."""
        try:
            with pytest.raises(NotImplementedError, match="does not execute SQL"):
                stream_runner.run_concurrent_streams([mock_stream_file])
        finally:
            mock_stream_file.unlink()

    def test_run_concurrent_streams_raises_not_implemented_for_empty_list(self, stream_runner):
        """run_concurrent_streams raises unconditionally, even with no streams."""
        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            stream_runner.run_concurrent_streams([])


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
