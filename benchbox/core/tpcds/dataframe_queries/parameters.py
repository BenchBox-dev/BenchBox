"""TPC-DS query parameters for DataFrame implementations.

Default parameter values are loaded from ``default_params.yaml``. They are
representative values extracted from the TPC-DS specification and dsqgen output
and are valid for SF >= 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TPCDSParameters:
    """Parameters for a specific TPC-DS query."""

    query_id: int
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value."""
        return self.params.get(key, default)


_PAIR_LIST_KEYS = {"hours", "quantity_ranges"}


def _normalize_param_value(key: str, value: Any) -> Any:
    if key in _PAIR_LIST_KEYS and isinstance(value, list):
        return [tuple(item) if isinstance(item, list) else item for item in value]
    return value


def _load_default_params() -> dict[int, dict[str, Any]]:
    with (Path(__file__).with_name("default_params.yaml")).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return {
        int(query_id): {key: _normalize_param_value(key, value) for key, value in params.items()}
        for query_id, params in raw["default_params"].items()
    }


TPCDS_DEFAULT_PARAMS: dict[int, dict[str, Any]] = _load_default_params()

# Module-level parameter overrides. When set by the dataframe_runner before
# query execution, get_parameters() merges these into the defaults. This avoids
# changing the call signature that all 99 query functions depend on.
_parameter_overrides: dict[int, dict[str, Any]] | None = None


def set_parameter_overrides(overrides: dict[int, dict[str, Any]] | None) -> None:
    """Set parameter overrides for the current benchmark run."""
    global _parameter_overrides
    _parameter_overrides = overrides


def get_parameters(query_id: int) -> TPCDSParameters:
    """Get parameters for a TPC-DS query."""
    params = dict(TPCDS_DEFAULT_PARAMS.get(query_id, {}))
    if _parameter_overrides is not None and query_id in _parameter_overrides:
        params.update(_parameter_overrides[query_id])
    return TPCDSParameters(query_id=query_id, params=params)


def get_all_parameters() -> dict[int, TPCDSParameters]:
    """Get all TPC-DS query parameters."""
    return {qid: get_parameters(qid) for qid in range(1, 100)}
