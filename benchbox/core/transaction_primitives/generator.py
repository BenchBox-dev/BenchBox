# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from pathlib import Path

from benchbox.core.primitives import generator_base as _generator_base
from benchbox.core.primitives.generator_base import PrimitivesDataGeneratorBase

DataGenerationManifest = _generator_base.DataGenerationManifest
resolve_compression_metadata = _generator_base.resolve_compression_metadata


class TransactionPrimitivesDataGenerator(PrimitivesDataGeneratorBase):
    _benchmark_name = "transaction_primitives"
    _display_name = "Transaction Primitives"
    _auxiliary_dir = "transaction_primitives_auxiliary"
    _logger_name = "benchbox.core.transaction_primitives.generator"

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        _generator_base.DataGenerationManifest = DataGenerationManifest
        _generator_base.resolve_compression_metadata = resolve_compression_metadata
        super()._write_manifest(table_paths)


__all__ = [
    "TransactionPrimitivesDataGenerator",
    "DataGenerationManifest",
    "resolve_compression_metadata",
]
