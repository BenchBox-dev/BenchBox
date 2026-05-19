"""Regression tests for quiet kwarg handling across all benchmarks.

This module ensures that all benchmark classes can accept quiet=True as a kwarg
without triggering a "got multiple values for keyword argument 'quiet'" error.

This is a regression test for the bug fixed in commits c562e05d and the
comprehensive fix that followed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Check for optional dependencies
try:
    import pandas

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class TestQuietKwargHandling:
    """Test that all benchmarks correctly handle quiet kwarg."""

    def test_tpch_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: TPCHBenchmark should accept quiet=True without error."""
        from benchbox.core.tpch import TPCHBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = TPCHBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "tpch",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_tpcds_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: TPCDSBenchmark should accept quiet=True without error."""
        from benchbox.core.tpcds import TPCDSBenchmark

        # TPC-DS initialization now defers file checks or uses fake implementations
        # Should not raise TypeError about duplicate kwarg
        benchmark = TPCDSBenchmark(
            scale_factor=1.0,
            output_dir=tmp_path / "tpcds",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_ssb_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: SSBBenchmark should accept quiet=True without error."""
        from benchbox.core.ssb import SSBBenchmark

        # Should not raise TypeError about duplicate kwarg
        # Pass compression_type="none" to avoid zstd dependency
        benchmark = SSBBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "ssb",
            quiet=True,
            compress_data=False,
            compression_type="none",
        )
        assert benchmark.quiet is True

    def test_h2odb_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: H2OBenchmark should accept quiet=True without error."""
        from benchbox.core.h2odb import H2OBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = H2OBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "h2odb",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_amplab_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: AMPLabBenchmark should accept quiet=True without error."""
        from benchbox.core.amplab import AMPLabBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = AMPLabBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "amplab",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_clickbench_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: ClickBenchBenchmark should accept quiet=True without error."""
        from benchbox.core.clickbench import ClickBenchBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = ClickBenchBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "clickbench",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_write_primitives_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: WritePrimitivesBenchmark should accept quiet=True without error."""
        from benchbox.core.write_primitives.benchmark import WritePrimitivesBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = WritePrimitivesBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "write_primitives",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_read_primitives_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: ReadPrimitivesBenchmark should accept quiet=True without error."""
        from benchbox.core.read_primitives import ReadPrimitivesBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = ReadPrimitivesBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "read_primitives",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_joinorder_synthetic_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: JoinOrderSyntheticBenchmark should accept quiet=True without error."""
        from benchbox.core.joinorder_synthetic import JoinOrderSyntheticBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = JoinOrderSyntheticBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "joinorder_synthetic",
            quiet=True,
        )
        assert benchmark.quiet is True

    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas not installed (required for TPCDI)")
    def test_tpcdi_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: TPCDIBenchmark should accept quiet=True without error."""
        from benchbox.core.tpcdi import TPCDIBenchmark

        # TPC-DI may have initialization issues, but we're testing that it doesn't
        # fail with duplicate kwarg error during the kwargs handling phase
        try:
            benchmark = TPCDIBenchmark(
                scale_factor=0.01,
                output_dir=tmp_path / "tpcdi",
                quiet=True,
            )
            # If successful, verify quiet is set
            assert benchmark.quiet is True
        except (NameError, ImportError, FileNotFoundError):
            # These errors are acceptable - they occur after kwargs handling
            # The important thing is we don't get TypeError about duplicate kwarg
            pass

    def test_coffeeshop_benchmark_accepts_quiet_kwarg(self, tmp_path):
        """Regression test: CoffeeShopBenchmark should accept quiet=True without error."""
        from benchbox.core.coffeeshop import CoffeeShopBenchmark

        # Should not raise TypeError about duplicate kwarg
        benchmark = CoffeeShopBenchmark(
            scale_factor=0.001,
            output_dir=tmp_path / "coffeeshop",
            quiet=True,
        )
        assert benchmark.quiet is True

    def test_quiet_propagates_to_data_generator(self, tmp_path):
        """Test that quiet flag propagates correctly to data generators."""
        from benchbox.core.tpch import TPCHBenchmark

        benchmark = TPCHBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "tpch",
            quiet=True,
        )

        # Verify quiet is set on benchmark
        assert benchmark.quiet is True

        # Verify quiet is set on data generator
        assert benchmark.data_generator.quiet is True

    def test_quiet_false_by_default(self, tmp_path):
        """Test that quiet defaults to False when not specified."""
        from benchbox.core.tpch import TPCHBenchmark

        benchmark = TPCHBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "tpch",
        )

        assert benchmark.quiet is False

    def test_multiple_benchmarks_with_quiet(self, tmp_path):
        """Test that multiple benchmarks can be instantiated with quiet=True."""
        from benchbox.core.h2odb import H2OBenchmark
        from benchbox.core.ssb import SSBBenchmark
        from benchbox.core.tpch import TPCHBenchmark

        # Should not raise any errors
        # SSB needs explicit compression_type to avoid zstd dependency
        tpch = TPCHBenchmark(scale_factor=0.01, output_dir=tmp_path / "tpch", quiet=True)
        ssb = SSBBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "ssb",
            quiet=True,
            compress_data=False,
            compression_type="none",
        )
        h2o = H2OBenchmark(scale_factor=0.01, output_dir=tmp_path / "h2o", quiet=True)

        assert tpch.quiet is True
        assert ssb.quiet is True
        assert h2o.quiet is True

    def test_quiet_with_other_kwargs(self, tmp_path):
        """Test that quiet works correctly when combined with other kwargs."""
        from benchbox.core.tpch import TPCHBenchmark

        benchmark = TPCHBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "tpch",
            quiet=True,
            verbose=2,  # Test interaction with verbose
            parallel=1,
            force_regenerate=False,
            compress_data=False,
            compression_type="none",
        )

        assert benchmark.quiet is True
        # When quiet=True, verbose is suppressed, so verbose_level becomes 0
        # This is the expected behavior from VerbosityMixin
        assert benchmark.verbose_level == 0
        assert benchmark.parallel == 1
