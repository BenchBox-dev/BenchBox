"""Tests to ensure consistent error handling between TPC-H and TPC-DS benchmarks.

This module validates that both benchmarks handle errors in the same way,
with consistent exception types and messages for invalid inputs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest import mock

import pytest

from benchbox.tpcds import TPCDS
from benchbox.tpch import TPCH

pytestmark = pytest.mark.fast


class TestErrorHandlingConsistency:
    """Test that TPC-H and TPC-DS handle errors consistently."""

    def test_invalid_scale_factor_type_consistency(self):
        """Test that both benchmarks raise TypeError for invalid scale_factor types."""
        # Test string instead of number
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCH(scale_factor="invalid")

        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCDS(scale_factor="invalid")

        # Test None instead of number
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCH(scale_factor=None)

        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCDS(scale_factor=None)

    def test_invalid_scale_factor_value_consistency(self):
        """Test that both benchmarks raise ValueError for invalid scale_factor values."""
        # Test zero
        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCH(scale_factor=0)

        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCDS(scale_factor=0)

        # Test negative
        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCH(scale_factor=-1.0)

        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCDS(scale_factor=-1.0)

    def test_invalid_query_id_type_consistency(self):
        """Test that both benchmarks raise TypeError for invalid query_id types."""
        tpch = TPCH()
        tpcds = TPCDS()

        # Test string instead of int
        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpch.get_query("invalid")

        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpcds.get_query("invalid")

        # Test float instead of int
        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpch.get_query(1.5)

        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpcds.get_query(1.5)

        # Test None
        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpch.get_query(None)

        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpcds.get_query(None)

    def test_invalid_query_id_range_consistency(self):
        """Test that both benchmarks raise ValueError for out-of-range query_ids."""
        tpch = TPCH()
        tpcds = TPCDS()

        # Test query_id = 0 (below range)
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            tpch.get_query(0)

        with pytest.raises(ValueError, match="Query ID must be 1-99"):
            tpcds.get_query(0)

        # Test query_id above range
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            tpch.get_query(23)

        with pytest.raises(ValueError, match="Query ID must be 1-99"):
            tpcds.get_query(100)

        # Test very large query_id
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            tpch.get_query(9999)

        with pytest.raises(ValueError, match="Query ID must be 1-99"):
            tpcds.get_query(9999)

    def test_invalid_seed_type_consistency(self):
        """Test that both benchmarks raise TypeError for invalid seed types."""
        tpch = TPCH()
        tpcds = TPCDS()

        # Test string instead of int
        with pytest.raises(TypeError, match="seed must be an integer"):
            tpch.get_query(1, seed="invalid")

        with pytest.raises(TypeError, match="seed must be an integer"):
            tpcds.get_query(1, seed="invalid")

        # Test float instead of int
        with pytest.raises(TypeError, match="seed must be an integer"):
            tpch.get_query(1, seed=1.5)

        with pytest.raises(TypeError, match="seed must be an integer"):
            tpcds.get_query(1, seed=1.5)

    def test_invalid_scale_factor_in_get_query_consistency(self):
        """Test that both benchmarks validate scale_factor in get_query method."""
        tpch = TPCH()
        tpcds = TPCDS()

        # Test invalid type
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            tpch.get_query(1, scale_factor="invalid")

        with pytest.raises(TypeError, match="scale_factor must be a number"):
            tpcds.get_query(1, scale_factor="invalid")

        # Test zero value
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            tpch.get_query(1, scale_factor=0)

        with pytest.raises(ValueError, match="scale_factor must be positive"):
            tpcds.get_query(1, scale_factor=0)

        # Test negative value
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            tpch.get_query(1, scale_factor=-1.0)

        with pytest.raises(ValueError, match="scale_factor must be positive"):
            tpcds.get_query(1, scale_factor=-1.0)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_valid_inputs_accepted_consistently(self, mock_dbgen_build):
        """Test that both benchmarks accept valid inputs without raising errors."""
        mock_dbgen_build.return_value = Path("/tmp/dbgen")

        # Test valid initialization
        tpch = TPCH(scale_factor=1.0)
        tpcds = TPCDS(scale_factor=1.0)

        assert tpch.scale_factor == 1.0
        assert tpcds.scale_factor == 1.0

        # Test valid scale factors
        tpch_sf = TPCH(scale_factor=0.1)
        tpcds_sf = TPCDS(scale_factor=1.0)

        assert tpch_sf.scale_factor == 0.1
        assert tpcds_sf.scale_factor == 1.0

        # Test that valid query_id ranges are accepted (we won't actually call get_query
        # as it requires the underlying tools, but we can test the validation passes)
        # This would be tested in integration tests


class TestErrorMessageFormats:
    """Test that error messages follow consistent patterns."""

    def test_type_error_message_format(self):
        """Test that TypeError messages follow consistent format."""
        with pytest.raises(TypeError) as exc_info:
            TPCH(scale_factor="invalid")

        error_msg = str(exc_info.value)
        assert "scale_factor must be a number, got str" in error_msg

        with pytest.raises(TypeError) as exc_info:
            TPCDS(scale_factor="invalid")

        error_msg = str(exc_info.value)
        assert "scale_factor must be a number, got str" in error_msg

    def test_value_error_message_format(self):
        """Test that ValueError messages follow consistent format."""
        with pytest.raises(ValueError) as exc_info:
            TPCH(scale_factor=-1.0)

        error_msg = str(exc_info.value)
        assert "Scale factor must be positive" in error_msg

        with pytest.raises(ValueError) as exc_info:
            TPCDS(scale_factor=-1.0)

        error_msg = str(exc_info.value)
        assert "Scale factor must be positive" in error_msg

    def test_query_id_error_message_format(self):
        """Test that query_id error messages show correct ranges."""
        tpch = TPCH()
        tpcds = TPCDS()

        with pytest.raises(ValueError) as exc_info:
            tpch.get_query(100)

        error_msg = str(exc_info.value)
        assert "Query ID must be 1-22, got 100" in error_msg

        with pytest.raises(ValueError) as exc_info:
            tpcds.get_query(200)

        error_msg = str(exc_info.value)
        assert "Query ID must be 1-99, got 200" in error_msg
