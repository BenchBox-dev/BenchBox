# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


def validate_effective_layout(config: UnifiedTuningConfiguration) -> list[str]:
    errors: list[str] = []
    try:
        config.platform_optimizations.__post_init__()
    except ValueError as exc:
        errors.append(str(exc))

    strategy = config.platform_optimizations.databricks_clustering_strategy
    liquid_requested = (
        strategy in {"liquid_clustering", "liquid_clustering_auto"}
        or config.platform_optimizations.liquid_clustering_enabled
        or bool(config.platform_optimizations.liquid_clustering_columns)
        or config.platform_optimizations.physical_rendering_id in {"databricks_liquid_manual", "databricks_liquid_auto"}
    )
    if not liquid_requested:
        return errors

    partitioned_tables = sorted(
        table_name for table_name, table_tuning in config.table_tunings.items() if table_tuning.partitioning
    )
    if partitioned_tables:
        errors.append(
            "Databricks Liquid Clustering is incompatible with per-table partitioning; "
            f"move partition columns to Liquid clustering intent or use databricks_z_order. Tables: "
            f"{', '.join(partitioned_tables)}"
        )

    distributed_tables = sorted(
        table_name for table_name, table_tuning in config.table_tunings.items() if table_tuning.distribution
    )
    if distributed_tables:
        errors.append(
            "Databricks Liquid Clustering has no user-managed distribution key; "
            f"fold distribution candidates into clustering intent or use databricks_z_order. Tables: "
            f"{', '.join(distributed_tables)}"
        )

    if strategy == "liquid_clustering":
        oversized_tables = sorted(
            table_name
            for table_name, table_tuning in config.table_tunings.items()
            if table_tuning.clustering and len(table_tuning.clustering) > 4
        )
        if oversized_tables:
            errors.append(
                "Databricks manual Liquid Clustering supports at most four clustering keys per table; "
                f"use databricks_liquid_auto or reduce clustering columns. Tables: {', '.join(oversized_tables)}"
            )

    return errors


__all__ = ["validate_effective_layout"]
