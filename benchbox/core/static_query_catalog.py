"""Shared loader for static benchmark query catalogs."""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml


def load_static_query_catalog(package: str, catalog_filename: str = "query_catalog.yaml") -> dict[str, Any]:
    """Load an arbitrary static query catalog from a benchmark package."""
    payload = yaml.safe_load(resources.files(package).joinpath(catalog_filename).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Static query catalog {package}:{catalog_filename} must contain a mapping")
    return payload


__all__ = ["load_static_query_catalog"]
