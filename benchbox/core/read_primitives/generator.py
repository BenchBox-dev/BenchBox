"""Read Primitives benchmark data generator.

This module provides TPC-H data generation for the Read Primitives benchmark
by reusing the official TPC-H data generator module entirely.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Optional, Union

from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

# Type for table path results (single file or sharded)
TablePaths = Path | list[Path]


class ReadPrimitivesDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for Read Primitives benchmark data using TPC-H data generator."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the Read Primitives data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
            output_dir: Directory to write generated data files
            verbose: Whether to print verbose output during generation
            **kwargs: Additional arguments including compression options
        """
        # Initialize compression mixin
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        if output_dir is None:
            # Read Primitives uses the canonical TPC-H dataset location
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)
        self.output_dir = create_path_handler(output_dir)
        self.verbose = verbose

        # Use TPC-H data generator directly and pass compression parameters
        self.tpch_generator = TPCHDataGenerator(
            scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs
        )

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str | list[str]]:
        """Generate Read Primitives data files using TPC-H data generator.

        Args:
            tables: Optional list of table names to generate. If None, generates all tables.

        Returns:
            Dictionary mapping table names to a file path or an ordered list of shard paths.
        """

        # Use centralized cloud/local generation handler
        def local_generate_func(output_dir: Path) -> dict[str, TablePaths]:
            return self._generate_data_local(output_dir, tables)

        result = self._handle_cloud_or_local_generation(
            self.output_dir,
            local_generate_func,
            verbose=self.verbose,
        )

        # Note: We intentionally do NOT rewrite the manifest here.
        # The manifest should remain as "benchmark": "tpch" because Read Primitives
        # shares TPC-H data. Validation engines should accept TPC-H manifests
        # for Read Primitives benchmarks since they use the same data.

        # Preserve shard boundaries while converting paths for platform consumers.
        # Stringifying a whole list produces a repr rather than usable file paths.
        return {k: [str(path) for path in v] if isinstance(v, list) else str(v) for k, v in result.items()}

    def _generate_data_local(self, output_dir: Path, tables: Optional[list[str]] = None) -> dict[str, TablePaths]:
        """Generate Read Primitives data files locally using TPC-H data generator."""
        # Configure the TPC-H generator's output directory to match ours
        self.tpch_generator.output_dir = output_dir

        # Use TPC-H generator to create all tables
        table_paths = self.tpch_generator.generate()

        # Filter results if specific tables were requested
        if tables is not None:
            filtered_paths = {k: v for k, v in table_paths.items() if k in tables}
            return filtered_paths

        return table_paths
