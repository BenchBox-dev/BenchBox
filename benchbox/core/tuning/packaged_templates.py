"""Packaged tuning templates shipped with the installed benchbox package.

`benchbox/cli/tuning_resolver.py:get_tuning_template_paths` auto-discovers
`<platform>/<benchmark>_tuned.yaml` templates relative to `$BENCHBOX_TUNING_PATH`
and the current working directory (`examples/tunings/` in a repo checkout).
Both of those tiers require either an environment variable or running from a
directory that has its own template tree - neither holds for a plain
`pip install benchbox` run from an arbitrary directory.

This module ships copies of the templates under
`benchbox/core/tuning/templates/<platform>/<benchmark>_tuned.yaml`, following
the same "plain path relative to this module's file" pattern used by
`benchbox/core/tuning/workload_profiles.py:PROFILE_ROOT` for the checked-in
`profiles/tpc.yaml` logical profile - no `importlib.resources` indirection is
needed since the files live inside the `benchbox` package tree and are picked
up by the existing `include-package-data` + `MANIFEST.in`
`recursive-include benchbox *.yaml` packaging configuration.

`examples/tunings/<platform>/<benchmark>_tuned.yaml` remains the dev-time
source of truth; see `templates/README.md` for the sync contract enforced by
`tests/unit/cli/test_tuning_resolution.py::TestPackagedTemplatesParity`.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"


def packaged_template_path(platform: str, benchmark: str) -> Path:
    """Build the candidate packaged-template path for platform/benchmark.

    This does not check whether the file exists - callers check that
    themselves (`Path.exists()`), matching how the other discovery tiers in
    `get_tuning_template_paths` are built as candidates first and checked
    later, so a search-order list can be assembled before any filesystem
    access happens.

    Args:
        platform: Platform name (e.g. 'duckdb', 'databricks')
        benchmark: Benchmark name (e.g. 'tpch', 'tpcds')

    Returns:
        The packaged-template path for this platform/benchmark (may not exist)
    """
    return TEMPLATES_ROOT / platform.lower() / f"{benchmark.lower()}_tuned.yaml"


def list_packaged_templates(
    platform: str | None = None,
    benchmark: str | None = None,
) -> dict[str, list[Path]]:
    """List packaged tuning templates, optionally filtered.

    Used by `list_available_tuning_templates` (and therefore `tuning list`)
    as the last-resort tier when no cwd-relative `examples/tunings/`
    directory is present - mirroring the packaged tier in
    `get_tuning_template_paths`.

    Args:
        platform: Filter to specific platform (optional)
        benchmark: Filter to specific benchmark (optional)

    Returns:
        Dictionary mapping platform names to list of available template paths
    """
    templates: dict[str, list[Path]] = {}

    if not TEMPLATES_ROOT.exists():
        return templates

    for platform_dir in sorted(TEMPLATES_ROOT.iterdir()):
        if not platform_dir.is_dir():
            continue

        platform_name = platform_dir.name
        if platform and platform.lower() != platform_name.lower():
            continue

        platform_templates = []
        for template_file in sorted(platform_dir.glob("*.yaml")):
            if benchmark and not template_file.stem.lower().startswith(benchmark.lower()):
                continue
            platform_templates.append(template_file)

        if platform_templates:
            templates[platform_name] = platform_templates

    return templates
