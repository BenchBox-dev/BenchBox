from __future__ import annotations

from pathlib import Path

import yaml

from benchbox.core.tpchavoc.variant_base import StaticSQLVariant


def load_variants(module_file: str) -> dict[int, StaticSQLVariant]:
    specs_path = Path(module_file).with_suffix(".yaml")
    with specs_path.open(encoding="utf-8") as handle:
        specs = yaml.safe_load(handle) or {}
    return {
        int(entry["id"]): StaticSQLVariant(int(entry["id"]), entry["description"], entry["sql"])
        for entry in specs["variants"]
    }
