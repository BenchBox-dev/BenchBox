from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

DATA_GENERATION_VERSION = 1


_BENCHMARK_SPECS_FILES: dict[str, tuple[str, ...]] = {
    "tpch": ("benchbox/core/tpch/generator_specs.yaml",),
    "tpch_skew": (
        "benchbox/core/tpch/generator_specs.yaml",
        "benchbox/core/tpch_skew/generator_specs.yaml",
    ),
    "tsbs_devops": ("benchbox/core/tsbs_devops/generator_specs.yaml",),
    "tsbs": ("benchbox/core/tsbs_devops/generator_specs.yaml",),
}

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _spec_files_for(benchmark: str | None) -> list[Path]:
    if not benchmark:
        return []
    return [_PACKAGE_ROOT / rel for rel in _BENCHMARK_SPECS_FILES.get(str(benchmark).lower(), ())]


def compute_base_constants_hash(benchmark: str | None = None) -> str:

    digest = hashlib.sha256(f"datagen-v{DATA_GENERATION_VERSION}".encode())
    for path in _spec_files_for(benchmark):
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()


def current_datagen_stamp(benchmark: str | None = None) -> dict[str, Any]:

    return {
        "data_generation_version": DATA_GENERATION_VERSION,
        "base_constants_hash": compute_base_constants_hash(benchmark),
    }


def compute_datagen_identity_hash(benchmark: str | None, configuration: Mapping[str, Any] | None = None) -> str:

    payload = {
        "base_constants_hash": compute_base_constants_hash(benchmark),
        "configuration": dict(configuration) if configuration is not None else None,
        "data_generation_version": DATA_GENERATION_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def manifest_datagen_is_current(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> bool:

    if not isinstance(manifest, Mapping):
        return False
    if manifest.get("data_generation_version") != DATA_GENERATION_VERSION:
        return False
    expected = compute_base_constants_hash(benchmark if benchmark is not None else manifest.get("benchmark"))
    return manifest.get("base_constants_hash") == expected


def describe_datagen_staleness(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> str | None:

    if manifest_datagen_is_current(manifest, benchmark):
        return None
    if not isinstance(manifest, Mapping):
        return "datagen manifest is missing or unreadable"
    if manifest.get("data_generation_version") != DATA_GENERATION_VERSION:
        if "data_generation_version" not in manifest:
            return (
                "this dataset predates version stamping and is treated as stale; "
                "it regenerates once to establish provenance"
            )
        return (
            f"datagen version {manifest.get('data_generation_version')!r} "
            f"does not match current version {DATA_GENERATION_VERSION}"
        )
    return "datagen base constants changed since this data was generated"
