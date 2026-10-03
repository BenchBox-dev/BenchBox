from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TPCDSParameters:
    query_id: int
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


_PAIR_LIST_KEYS = {"hours", "quantity_ranges"}


def _normalize_param_value(key: str, value: Any) -> Any:
    if key in _PAIR_LIST_KEYS and isinstance(value, list):
        return [tuple(item) if isinstance(item, list) else item for item in value]
    return value


def _load_default_params() -> dict[int, dict[str, Any]]:
    with (Path(__file__).with_name("default_parameters.yaml")).open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("TPC-DS default parameters must be a mapping")
    return {
        int(query_id): {key: _normalize_param_value(key, value) for key, value in params.items()}
        for query_id, params in payload.items()
    }


TPCDS_DEFAULT_PARAMS: dict[int, dict[str, Any]] = _load_default_params()

_parameter_overrides: dict[int, dict[str, Any]] | None = None


def set_parameter_overrides(overrides: dict[int, dict[str, Any]] | None) -> None:
    global _parameter_overrides
    _parameter_overrides = overrides


@contextmanager
def parameter_overrides(overrides: dict[int, dict[str, Any]]) -> Iterator[None]:
    previous = _parameter_overrides
    set_parameter_overrides({**(previous or {}), **overrides})
    try:
        yield
    finally:
        set_parameter_overrides(previous)


def get_parameters(query_id: int) -> TPCDSParameters:
    params = dict(TPCDS_DEFAULT_PARAMS.get(query_id, {}))
    if _parameter_overrides is not None and query_id in _parameter_overrides:
        params.update(_parameter_overrides[query_id])
    return TPCDSParameters(query_id=query_id, params=params)


def get_all_parameters() -> dict[int, TPCDSParameters]:
    return {qid: get_parameters(qid) for qid in range(1, 100)}
