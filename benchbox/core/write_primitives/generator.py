# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from benchbox.core.primitives.generator_base import PrimitivesDataGeneratorBase


class WritePrimitivesDataGenerator(PrimitivesDataGeneratorBase):
    _benchmark_name = "write_primitives"
    _display_name = "Write Primitives"
    _auxiliary_dir = "write_primitives_auxiliary"
    _logger_name = "benchbox.core.write_primitives.generator"


__all__ = ["WritePrimitivesDataGenerator"]
