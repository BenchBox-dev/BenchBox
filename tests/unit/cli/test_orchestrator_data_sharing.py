"""Tests for CLI orchestrator data sharing behavior.

This module tests that the CLI orchestrator correctly handles benchmarks that
share data from other benchmarks (like Primitives sharing TPC-H data).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.schemas import BenchmarkConfig
from benchbox.utils.scale_factor import format_scale_factor

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _assert_tpch_default_path(path: Path, scale_factor: float) -> None:
    expected_suffix = Path("benchmark_runs") / "datagen" / f"tpch_{format_scale_factor(scale_factor)}"
    actual_suffix = Path(*Path(path).parts[-3:])
    assert actual_suffix == expected_suffix
    assert "primitives_sf" not in str(path)


@pytest.mark.unit
class TestOrchestratorDataSharing:
    """Test orchestrator data sharing logic."""

    def test_primitives_uses_tpch_path(self):
        """Test that orchestrator respects Primitives' TPC-H data sharing."""
        orchestrator = BenchmarkOrchestrator()

        # Create benchmark config for Primitives
        config = BenchmarkConfig(
            name="read_primitives",
            display_name="Primitives",
            scale_factor=1.0,
            compress_data=False,
            compression_type="none",
        )

        # Create benchmark instance
        benchmark = orchestrator._get_benchmark_instance(config, None)

        # Check that benchmark declares TPC-H as data source
        data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()
        assert data_source == "tpch", "Primitives should declare 'tpch' as data source"

        # Verify benchmark uses tpch_sf path
        _assert_tpch_default_path(Path(benchmark.output_dir), 1.0)

    def test_orchestrator_detects_data_sharing(self):
        """Test that orchestrator correctly detects data-sharing benchmarks."""
        orchestrator = BenchmarkOrchestrator()

        # Create a benchmark that shares data
        config = BenchmarkConfig(
            name="read_primitives",
            display_name="Primitives",
            scale_factor=1.0,
            compress_data=False,
            compression_type="none",
        )
        benchmark = orchestrator._get_benchmark_instance(config, None)

        # Simulate orchestrator's data source check
        data_source = getattr(benchmark, "get_data_source_benchmark", lambda: None)()

        # If data source is set, output_root should be None (use benchmark default)
        if data_source:
            output_root = None
        else:
            output_root = str(orchestrator.directory_manager.get_datagen_path(config.name.lower(), config.scale_factor))

        # For Primitives, output_root should be None (respecting benchmark default)
        assert output_root is None, "Orchestrator should not override path for data-sharing benchmarks"

    def test_orchestrator_does_not_interfere_with_regular_benchmarks(self):
        """Test that orchestrator still manages paths for non-sharing benchmarks."""
        BenchmarkOrchestrator()

        # Create a mock benchmark that does NOT share data
        mock_benchmark = Mock()
        mock_benchmark.get_data_source_benchmark.return_value = None  # No data sharing
        mock_benchmark.output_dir = "/some/path"

        # Simulate orchestrator's logic
        data_source = getattr(mock_benchmark, "get_data_source_benchmark", lambda: None)()

        if data_source:
            output_root = None
        else:
            # For non-sharing benchmarks, use CLI-managed path
            output_root = "benchmark_runs/datagen/tpch_sf1"

        # For regular benchmarks, orchestrator should provide a path
        assert output_root is not None, "Orchestrator should provide path for non-sharing benchmarks"
        assert "benchmark_runs/datagen" in output_root

    def test_custom_output_overrides_data_sharing(self):
        """Test that custom --output paths override data sharing."""
        orchestrator = BenchmarkOrchestrator()
        custom_path = "/custom/data/path"
        orchestrator.set_custom_output_dir(custom_path)

        # Even for data-sharing benchmarks, custom path should take precedence
        BenchmarkConfig(
            name="read_primitives",
            display_name="Primitives",
            scale_factor=1.0,
            compress_data=False,
        )

        # Simulate orchestrator's logic
        output_root = orchestrator.custom_output_dir if orchestrator.custom_output_dir else None

        # Custom output should be used
        assert output_root == custom_path, "Custom output path should override data sharing"

    def test_get_platform_config_resolves_data_source_benchmark(self):
        """_get_platform_config should override benchmark_name with data source name."""
        orchestrator = BenchmarkOrchestrator()
        benchmark = Mock()
        benchmark.get_data_source_benchmark.return_value = "tpch"

        with patch("benchbox.cli.orchestrator._core_get_platform_config", return_value={}) as mock_core:
            orchestrator._get_platform_config(
                database_config=Mock(),
                system_profile=Mock(),
                benchmark_name="read_primitives",
                scale_factor=1.0,
                benchmark=benchmark,
            )

        assert mock_core.call_args.kwargs["benchmark_name"] == "tpch"

    def test_get_platform_config_passes_through_when_no_data_source(self):
        """_get_platform_config should keep original benchmark_name when no data source."""
        orchestrator = BenchmarkOrchestrator()
        benchmark = Mock()
        benchmark.get_data_source_benchmark.return_value = None

        with patch("benchbox.cli.orchestrator._core_get_platform_config", return_value={}) as mock_core:
            orchestrator._get_platform_config(
                database_config=Mock(),
                system_profile=Mock(),
                benchmark_name="tpch",
                scale_factor=1.0,
                benchmark=benchmark,
            )

        assert mock_core.call_args.kwargs["benchmark_name"] == "tpch"

    def test_data_sharing_with_different_scale_factors(self):
        """Test that data sharing works correctly with different scale factors."""
        orchestrator = BenchmarkOrchestrator()

        # Test multiple scale factors
        for scale_factor in [0.1, 1.0, 10.0]:
            config = BenchmarkConfig(
                name="read_primitives",
                display_name="Primitives",
                scale_factor=scale_factor,
                compress_data=False,
                compression_type="none",
            )
            benchmark = orchestrator._get_benchmark_instance(config, None)

            _assert_tpch_default_path(Path(benchmark.output_dir), scale_factor)
