# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from pathlib import Path

from benchbox.core.comparison.types import (
    PlatformType,
    UnifiedPlatformResult,
)

logger = logging.getLogger(__name__)


class UnifiedComparisonPlotter:
    def __init__(
        self,
        results: list[UnifiedPlatformResult],
        theme: str = "light",
    ):
        if not results:
            raise ValueError("No results provided for visualization")
        self.results = results
        self.theme = theme
        self.platform_type = results[0].platform_type if results else PlatformType.SQL

    def generate_charts(self, output_dir: str | Path, **kwargs: object) -> dict[str, Path]:
        from benchbox.core.visualization.chart_generator import (
            generate_comparison_charts,
            normalized_from_unified,
        )

        normalized = normalized_from_unified(self.results)
        return generate_comparison_charts(normalized, output_dir, theme=self.theme)


__all__ = ["UnifiedComparisonPlotter"]
