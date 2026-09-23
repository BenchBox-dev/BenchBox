"""Data-generation versioning for stale-datagen detection.

Changing data-generation base constants (for example the ``base_row_counts``
in a ``generator_specs.yaml``) silently invalidates comparisons between data
generated before and after the change. This module versions the generation
inputs so cached datagen directories can be recognized as stale:

- ``DATA_GENERATION_VERSION`` marks the generation-logic generation. Bump it
  whenever the generator code changes incompatibly.
- ``compute_base_constants_hash`` fingerprints the base-constant inputs for a
  benchmark, so editing a specs file is detected even without a version bump.

Datagen manifests stamp both values; the runner treats a manifest whose stamp
differs from current as invalid and regenerates (the automatic equivalent of
``--force`` datagen). ``BenchmarkResults.data_generation_version`` records the
version that produced a result so old and new results are not silently
compared.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

# Generation-logic generation. Bump on incompatible generator changes.
DATA_GENERATION_VERSION = 1

# Benchmark slug (as stored lowercased in datagen manifests) to the
# base-constant files that determine its generated data.
_BENCHMARK_SPECS_FILES: dict[str, tuple[str, ...]] = {
    "tpch": ("benchbox/core/tpch/generator_specs.yaml",),
    "tpch_skew": ("benchbox/core/tpch_skew/generator_specs.yaml",),
    "tsbs_devops": ("benchbox/core/tsbs_devops/generator_specs.yaml",),
    "tsbs": ("benchbox/core/tsbs_devops/generator_specs.yaml",),
}

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _spec_files_for(benchmark: str | None) -> list[Path]:
    if not benchmark:
        return []
    return [_PACKAGE_ROOT / rel for rel in _BENCHMARK_SPECS_FILES.get(str(benchmark).lower(), ())]


def compute_base_constants_hash(benchmark: str | None = None) -> str:
    """Return the hex fingerprint of the base constants for a benchmark.

    Falls back to the version marker alone when a benchmark has no
    registered specs files, so unmapped benchmarks still get a stable stamp.
    """
    digest = hashlib.sha256(f"datagen-v{DATA_GENERATION_VERSION}".encode())
    for path in _spec_files_for(benchmark):
        try:
            digest.update(path.read_bytes())
        except OSError:
            # Installed layouts may omit spec files; the version marker
            # still distinguishes logic generations.
            continue
    return digest.hexdigest()


def current_datagen_stamp(benchmark: str | None = None) -> dict[str, Any]:
    """Return the stamp written into freshly generated manifests."""
    return {
        "data_generation_version": DATA_GENERATION_VERSION,
        "base_constants_hash": compute_base_constants_hash(benchmark),
    }


def manifest_datagen_is_current(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> bool:
    """Return whether a manifest's datagen stamp matches current inputs."""
    if not isinstance(manifest, Mapping):
        return False
    if manifest.get("data_generation_version") != DATA_GENERATION_VERSION:
        return False
    expected = compute_base_constants_hash(benchmark if benchmark is not None else manifest.get("benchmark"))
    return manifest.get("base_constants_hash") == expected


def describe_datagen_staleness(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> str | None:
    """Explain why a manifest is datagen-stale, or None when current."""
    if manifest_datagen_is_current(manifest, benchmark):
        return None
    if not isinstance(manifest, Mapping):
        return "datagen manifest is missing or unreadable"
    if manifest.get("data_generation_version") != DATA_GENERATION_VERSION:
        return (
            f"datagen version {manifest.get('data_generation_version')!r} "
            f"does not match current version {DATA_GENERATION_VERSION}"
        )
    return "datagen base constants changed since this data was generated"
