"""Unit tests for TPC-H streams and permutation functionality.

Tests the TPC-H specification compliant permutation matrix and stream generation
to ensure correct query ordering and parameter handling.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.tpch.streams import TPCHStreamRunner, TPCHStreams

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHPermutationMatrix:
    """Test TPC-H permutation matrix compliance."""

    def test_permutation_matrix_exists(self):
        """Test that the permutation matrix is properly defined."""
        assert hasattr(TPCHStreams, "PERMUTATION_MATRIX")
        matrix = TPCHStreams.PERMUTATION_MATRIX

        # Should have 41 permutations as per TPC-H specification
        assert len(matrix) == 41

        # Each permutation should have 22 queries
        for i, permutation in enumerate(matrix):
            assert len(permutation) == 22, f"Permutation {i} has {len(permutation)} queries, expected 22"

    def test_permutation_matrix_values(self):
        """Test that permutation matrix contains valid query IDs."""
        matrix = TPCHStreams.PERMUTATION_MATRIX

        for i, permutation in enumerate(matrix):
            # Each permutation should contain queries 1-22 exactly once
            query_set = set(permutation)
            expected_queries = set(range(1, 23))

            assert query_set == expected_queries, f"Permutation {i} missing or has extra queries"

            # No duplicate queries in a permutation
            assert len(permutation) == len(query_set), f"Permutation {i} has duplicate queries"

    def test_permutation_matrix_uniqueness(self):
        """Test that all permutations are unique."""
        matrix = TPCHStreams.PERMUTATION_MATRIX
        unique_permutations = {tuple(perm) for perm in matrix}

        assert len(unique_permutations) == 41, "Some permutations are duplicates"

    def test_permutation_retrieval(self):
        """Test _get_stream_permutation method."""
        streams = TPCHStreams(num_streams=1)

        # Test first few permutations
        perm_0 = streams._get_stream_permutation(0)
        perm_1 = streams._get_stream_permutation(1)
        perm_40 = streams._get_stream_permutation(40)

        # Should match matrix exactly
        assert perm_0 == TPCHStreams.PERMUTATION_MATRIX[0]
        assert perm_1 == TPCHStreams.PERMUTATION_MATRIX[1]
        assert perm_40 == TPCHStreams.PERMUTATION_MATRIX[40]

        # Test wrapping (stream 41 should use permutation 0)
        perm_41 = streams._get_stream_permutation(41)
        assert perm_41 == TPCHStreams.PERMUTATION_MATRIX[0]

        # Test more wrapping
        perm_82 = streams._get_stream_permutation(82)  # 82 % 41 = 0
        assert perm_82 == TPCHStreams.PERMUTATION_MATRIX[0]

        perm_43 = streams._get_stream_permutation(43)  # 43 % 41 = 2
        assert perm_43 == TPCHStreams.PERMUTATION_MATRIX[2]


class TestTPCHStreamsInitialization:
    """Test TPC-H streams initialization and configuration."""

    def test_default_initialization(self):
        """Test default TPCHStreams initialization."""
        streams = TPCHStreams()

        assert streams.num_streams == 1
        assert streams.scale_factor == 1.0
        assert streams.rng_seed == 1
        assert not streams.verbose
        assert streams.query_count == 22

    def test_custom_initialization(self):
        """Test TPCHStreams with custom parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            streams = TPCHStreams(
                num_streams=5,
                scale_factor=10.0,
                output_dir=output_dir,
                rng_seed=42,
                verbose=True,
            )

            assert streams.num_streams == 5
            assert streams.scale_factor == 10.0
            assert streams.output_dir == output_dir
            assert streams.rng_seed == 42
            assert streams.verbose

    def test_tools_path_detection(self):
        """Test that TPC-H tools path is detected."""
        streams = TPCHStreams()

        # Should have a tools path set
        assert hasattr(streams, "tpch_tools_path")
        assert streams.tpch_tools_path is not None

        # Path should be a Path object
        assert isinstance(streams.tpch_tools_path, Path)


class TestTPCHStreamGeneration:
    """Test TPC-H stream generation functionality."""

    @pytest.fixture
    def mock_streams(self):
        """Create a TPCHStreams instance with mocked compilation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            streams = TPCHStreams(
                num_streams=2,
                scale_factor=1.0,
                output_dir=output_dir,
                rng_seed=12345,
                verbose=False,
            )
            yield streams

    def test_stream_info_structure(self, mock_streams):
        """Test get_stream_info returns correct structure."""
        stream_info = mock_streams.get_stream_info(0)

        required_fields = [
            "stream_id",
            "query_order",
            "scale_factor",
            "rng_seed",
            "query_count",
            "output_file",
            "permutation_index",
        ]

        for field in required_fields:
            assert field in stream_info, f"Missing field: {field}"

        # Verify field types and values
        assert stream_info["stream_id"] == 0
        assert isinstance(stream_info["query_order"], list)
        assert len(stream_info["query_order"]) == 22
        assert stream_info["scale_factor"] == 1.0
        assert stream_info["rng_seed"] == 12345  # base seed + stream_id
        assert stream_info["query_count"] == 22
        assert isinstance(stream_info["output_file"], Path)
        assert stream_info["permutation_index"] == 0  # 0 % 41 = 0

    def test_multiple_stream_info(self, mock_streams):
        """Test get_stream_info for multiple streams."""
        stream_0_info = mock_streams.get_stream_info(0)
        stream_1_info = mock_streams.get_stream_info(1)

        # Different stream IDs
        assert stream_0_info["stream_id"] == 0
        assert stream_1_info["stream_id"] == 1

        # Different RNG seeds
        assert stream_0_info["rng_seed"] == 12345  # base + 0
        assert stream_1_info["rng_seed"] == 12346  # base + 1

        # Different permutations
        assert stream_0_info["query_order"] != stream_1_info["query_order"]

        # Different permutation indices
        assert stream_0_info["permutation_index"] == 0
        assert stream_1_info["permutation_index"] == 1

    def test_all_streams_info(self, mock_streams):
        """Test get_all_streams_info method."""
        all_info = mock_streams.get_all_streams_info()

        assert len(all_info) == 2  # num_streams = 2
        assert all_info[0]["stream_id"] == 0
        assert all_info[1]["stream_id"] == 1

        # Verify all streams have different query orders
        order_0 = all_info[0]["query_order"]
        order_1 = all_info[1]["query_order"]
        assert order_0 != order_1

    def test_invalid_stream_id(self, mock_streams):
        """Test error handling for invalid stream IDs."""
        # Stream ID beyond num_streams should raise error
        with pytest.raises(ValueError, match="Invalid stream ID: 5. Max streams: 2"):
            mock_streams.get_stream_info(5)

        # Note: The current TPC-H implementation doesn't validate negative stream IDs
        # It just uses modulo arithmetic, so negative IDs won't raise an error
        # This is actually consistent with the specification behavior


class TestTPCHStreamPermutationCompliance:
    """Test TPC-H specification compliance for stream permutations."""

    def test_stream_permutation_deterministic(self):
        """Test that permutations are deterministic for same stream ID."""
        # Create two different instances
        streams1 = TPCHStreams(num_streams=5, rng_seed=42)
        streams2 = TPCHStreams(num_streams=5, rng_seed=42)

        for stream_id in range(5):
            order1 = streams1.get_stream_info(stream_id)["query_order"]
            order2 = streams2.get_stream_info(stream_id)["query_order"]

            assert order1 == order2, f"Stream {stream_id} permutation not deterministic"

    def test_stream_permutation_different_for_different_streams(self):
        """Test that different streams have different permutations."""
        streams = TPCHStreams(num_streams=10)

        permutations = []
        for stream_id in range(10):
            order = tuple(streams.get_stream_info(stream_id)["query_order"])
            permutations.append(order)

        # All permutations should be unique
        unique_permutations = set(permutations)
        assert len(unique_permutations) == 10, "Some streams have identical permutations"

    def test_permutation_wrapping_behavior(self):
        """Test correct wrapping behavior when stream_id >= 41."""
        streams = TPCHStreams(num_streams=100)

        # Test that stream 0 and stream 41 have same permutation
        order_0 = streams.get_stream_info(0)["query_order"]
        order_41 = streams.get_stream_info(41)["query_order"]
        assert order_0 == order_41

        # Test that stream 1 and stream 42 have same permutation
        order_1 = streams.get_stream_info(1)["query_order"]
        order_42 = streams.get_stream_info(42)["query_order"]
        assert order_1 == order_42

        # Test that stream 40 and stream 81 have same permutation
        order_40 = streams.get_stream_info(40)["query_order"]
        order_81 = streams.get_stream_info(81)["query_order"]
        assert order_40 == order_81

    def test_specification_permutation_values(self):
        """Test that our permutations match TPC-H specification examples."""
        streams = TPCHStreams(num_streams=2)  # Need at least 2 streams to test stream 1

        # Get first permutation
        order_0 = streams.get_stream_info(0)["query_order"]

        # Should match the first row in PERMUTATION_MATRIX
        expected_0 = [
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
        assert order_0 == expected_0

        # Test second permutation
        order_1 = streams.get_stream_info(1)["query_order"]
        expected_1 = [
            21,
            3,
            18,
            5,
            11,
            7,
            6,
            20,
            17,
            12,
            16,
            15,
            13,
            10,
            2,
            8,
            14,
            19,
            9,
            22,
            1,
            4,
        ]
        assert order_1 == expected_1


class TestTPCHStreamQueryGeneration:
    """Test TPC-H stream query generation and compilation."""

    @pytest.fixture
    def mock_qgen_compilation(self):
        """Mock qgen compilation for testing."""
        with patch("benchbox.core.tpch.streams.TPCHStreams._compile_qgen") as mock_compile:
            with patch("benchbox.core.tpch.streams.TPCHStreams._generate_stream_queries_qgen") as mock_gen_qgen:
                # Mock successful compilation
                mock_qgen_path = Path("/mock/qgen")
                mock_compile.return_value = mock_qgen_path

                # Mock successful query generation
                mock_stream_file = Path("/mock/stream_0.sql")
                mock_gen_qgen.return_value = mock_stream_file

                yield {
                    "compile": mock_compile,
                    "gen_qgen": mock_gen_qgen,
                    "qgen_path": mock_qgen_path,
                    "stream_file": mock_stream_file,
                }

    def test_generate_streams_with_qgen(self, mock_qgen_compilation):
        """Test stream generation using qgen binary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            streams = TPCHStreams(num_streams=2, output_dir=output_dir, verbose=False)

            # Generate streams
            result = streams.generate_streams()

            # Should have attempted compilation
            mock_qgen_compilation["compile"].assert_called_once()

            # Should have used qgen for generation
            assert mock_qgen_compilation["gen_qgen"].call_count == 2  # 2 streams

            # Should return list of stream files
            assert len(result) == 2
            assert all(isinstance(f, Path) for f in result)

    def test_generate_streams_fails_without_qgen(self, mock_qgen_compilation):
        """Test stream generation fails when qgen compilation fails."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            streams = TPCHStreams(num_streams=1, output_dir=output_dir, verbose=False)

            # Mock compilation failure
            mock_qgen_compilation["compile"].side_effect = RuntimeError("qgen compilation failed")

            # Generate streams should raise RuntimeError
            with pytest.raises(RuntimeError, match="TPC-H streams generation requires qgen compilation"):
                streams.generate_streams()

            # Should have attempted compilation
            mock_qgen_compilation["compile"].assert_called_once()

            # Should not have used qgen for generation since compilation failed
            assert mock_qgen_compilation["gen_qgen"].call_count == 0


class TestTPCHStreamRunner:
    """Test TPC-H stream runner functionality."""

    def test_stream_runner_initialization(self):
        """Test TPCHStreamRunner initialization."""
        runner = TPCHStreamRunner(connection_string="sqlite:///test.db", dialect="sqlite", verbose=True)

        assert runner.connection_string == "sqlite:///test.db"
        assert runner.dialect == "sqlite"
        assert runner.verbose

    def test_stream_runner_methods_raise_not_implemented(self):
        """run_stream/run_concurrent_streams never fake success; they always raise NotImplementedError.

        These methods used to "handle" a missing file by returning a
        success=False dict, and an empty stream list by returning a
        success=True dict -- both computed from counting comment lines rather
        than running any SQL. That fake-success stub is retired: both methods
        now raise NotImplementedError unconditionally.
        """
        runner = TPCHStreamRunner("connection_string")

        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            runner.run_stream(Path("/fake/stream.sql"), 1)

        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            runner.run_concurrent_streams([])


class TestTPCHStreamsIntegration:
    """Integration tests for TPC-H streams functionality."""

    def test_stream_generation_full_workflow(self):
        """Test complete stream generation workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            # Create streams manager
            streams = TPCHStreams(
                num_streams=3,
                scale_factor=0.01,  # Small scale for testing
                output_dir=output_dir,
                rng_seed=999,
                verbose=False,
            )

            # Test stream info before generation
            for i in range(3):
                info = streams.get_stream_info(i)
                assert info["stream_id"] == i
                assert len(info["query_order"]) == 22
                assert info["rng_seed"] == 999 + i

                # Verify query order is a valid permutation
                query_set = set(info["query_order"])
                expected_queries = set(range(1, 23))
                assert query_set == expected_queries

            # Verify different streams have different permutations
            all_info = streams.get_all_streams_info()
            assert len(all_info) == 3

            orders = [info["query_order"] for info in all_info]
            unique_orders = {tuple(order) for order in orders}
            assert len(unique_orders) == 3, "All streams should have unique permutations"

    def test_permutation_spec_compliance_sample(self):
        """Test a sample of permutations for specification compliance."""
        streams = TPCHStreams(num_streams=41)  # Test all 41 permutations

        # Test that we get exactly the specification permutations
        for stream_id in range(41):
            actual_order = streams.get_stream_info(stream_id)["query_order"]
            expected_order = TPCHStreams.PERMUTATION_MATRIX[stream_id]

            assert actual_order == expected_order, f"Stream {stream_id} permutation doesn't match specification"
