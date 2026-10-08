# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator

if TYPE_CHECKING:
    from benchbox.core.tuning.ddl_generator import TuningClauses
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)


class PgDuckDBDDLGenerator(PostgreSQLDDLGenerator):
    @property
    def platform_name(self) -> str:
        return "pg_duckdb"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        clauses = super().generate_tuning_clauses(table_tuning, platform_opts)

        clauses.post_create_statements = [
            stmt for stmt in clauses.post_create_statements if not stmt.upper().startswith("CLUSTER")
        ]

        return clauses


__all__ = [
    "PgDuckDBDDLGenerator",
]
