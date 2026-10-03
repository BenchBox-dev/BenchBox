# Copyright 2026 Joe Harris / BenchBox Project

# This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Optional, Union

from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

TablePaths = Path | list[Path]


class ReadPrimitivesDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        if output_dir is None:
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)
        self.output_dir = create_path_handler(output_dir)
        self.verbose = verbose

        self.tpch_generator = TPCHDataGenerator(
            scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs
        )

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str | list[str]]:

        def local_generate_func(output_dir: Path) -> dict[str, TablePaths]:
            return self._generate_data_local(output_dir, tables)

        result = self._handle_cloud_or_local_generation(
            self.output_dir,
            local_generate_func,
            verbose=self.verbose,
        )

        return {k: [str(path) for path in v] if isinstance(v, list) else str(v) for k, v in result.items()}

    def _generate_data_local(self, output_dir: Path, tables: Optional[list[str]] = None) -> dict[str, TablePaths]:
        self.tpch_generator.output_dir = output_dir

        table_paths = self.tpch_generator.generate()

        if tables is not None:
            filtered_paths = {k: v for k, v in table_paths.items() if k in tables}
            return filtered_paths

        return table_paths
