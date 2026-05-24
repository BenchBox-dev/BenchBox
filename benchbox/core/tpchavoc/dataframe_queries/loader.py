"""YAML loader for TPC-Havoc DataFrame variant registries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

VariantImpl = Callable[..., Any]


def load_variant_specs(
    module_file: str, namespace: dict[str, Any]
) -> tuple[list[tuple[VariantImpl, VariantImpl]], list[str]]:
    """Load variant implementation pairs and descriptions from YAML next to a module."""
    with Path(module_file).with_suffix(".yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    pairs: list[tuple[VariantImpl, VariantImpl]] = []
    descriptions: list[str] = []
    for entry in payload["variants"]:
        pairs.append((namespace[entry["expression_impl"]], namespace[entry["pandas_impl"]]))
        descriptions.append(entry["description"])
    return pairs, descriptions
