# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from benchbox.core.tuning.ddl_generator import TuningClauses
from benchbox.core.tuning.generators.postgresql import PostgreSQLDDLGenerator

if TYPE_CHECKING:
    from benchbox.core.tuning.ddl_generator import ColumnDefinition
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)


class PgMooncakeDDLGenerator(PostgreSQLDDLGenerator):
    @property
    def platform_name(self) -> str:
        return "pg_mooncake"

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        return TuningClauses()

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses,
        schema: str | None = None,
    ) -> str:
        return super().generate_create_table_ddl(table_name, columns, tuning, schema)

    def generate_partition_children(
        self,
        parent_table: str,
        columns,
        tuning: TuningClauses,
        table_tuning: TableTuning | None = None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
        schema: str | None = None,
    ) -> list[str]:
        return []


__all__ = [
    "PgMooncakeDDLGenerator",
]
