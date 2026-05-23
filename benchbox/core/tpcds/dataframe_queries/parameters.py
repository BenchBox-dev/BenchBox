"""TPC-DS query parameters for DataFrame implementations.

This module provides parameter definitions for TPC-DS queries. Unlike TPC-H
which has fixed parameters, TPC-DS parameters can vary based on scale factor
and stream. For DataFrame implementations, we use representative default
values that are valid across all scale factors.

The parameters are extracted from the TPC-DS specification and dsqgen output.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TPCDSParameters:
    """Parameters for a specific TPC-DS query.

    Each query has its own set of parameters that can be customized.
    Default values are provided for standard benchmark execution.
    """

    query_id: int
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value.

        Args:
            key: Parameter name
            default: Default value if not found

        Returns:
            Parameter value
        """
        return self.params.get(key, default)


# Default parameters for each TPC-DS query
# These are representative values extracted from the TPC-DS specification
# and are valid for SF >= 1


def _load_default_params() -> dict[int, dict[str, Any]]:
    with (Path(__file__).with_name("default_parameters.yaml")).open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("TPC-DS default parameters must be a mapping")
    return {int(query_id): params for query_id, params in payload.items()}


TPCDS_DEFAULT_PARAMS: dict[int, dict[str, Any]] = _load_default_params()


# Module-level parameter overrides. When set by the dataframe_runner before
# query execution, get_parameters() merges these into the defaults. This avoids
# changing the call signature that all 99 query functions depend on.
_parameter_overrides: dict[int, dict[str, Any]] | None = None


def set_parameter_overrides(overrides: dict[int, dict[str, Any]] | None) -> None:
    """Set parameter overrides for the current benchmark run.

    Called by the dataframe_runner before query execution to inject seed-derived
    parameters. Pass None to clear overrides and revert to static defaults.

    Args:
        overrides: Dict mapping query_id to param dict, or None to clear.
    """
    global _parameter_overrides
    _parameter_overrides = overrides


def get_parameters(query_id: int) -> TPCDSParameters:
    """Get parameters for a TPC-DS query.

    If parameter overrides are active (set via set_parameter_overrides),
    override values are merged on top of the defaults for the given query.
    This allows seed-derived parameters from dsqgen to flow into DataFrame
    queries without modifying any query function.

    Args:
        query_id: Query number (1-99)

    Returns:
        TPCDSParameters object with default or overridden values
    """
    params = dict(TPCDS_DEFAULT_PARAMS.get(query_id, {}))
    if _parameter_overrides is not None and query_id in _parameter_overrides:
        params.update(_parameter_overrides[query_id])
    return TPCDSParameters(query_id=query_id, params=params)


def get_all_parameters() -> dict[int, TPCDSParameters]:
    """Get all TPC-DS query parameters.

    Returns:
        Dictionary mapping query_id to TPCDSParameters
    """
    return {qid: get_parameters(qid) for qid in range(1, 100)}
