"""Regression: benchmark_registry / benchmark_specs load their YAML lazily.

PR #590 loaded the migrated YAML eagerly at module scope, putting file I/O +
parse on the import-critical path (benchmark_registry is imported by
benchmark_loader). This test pins the lazy+cached behavior -- the payload must
not be loaded until a public symbol is first accessed -- so the eager load
cannot silently return.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _run(code: str) -> list[str]:
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return result.stdout.strip().splitlines()


@pytest.mark.fast
def test_catalogs_load_lazily_not_at_import() -> None:
    # Fresh interpreter: importing the modules must NOT populate the cache
    # (misses == 0); first access of a public symbol triggers exactly one load.
    lines = _run(
        "import benchbox.core.benchmark_registry as r;"
        "import benchbox.core.results.benchmark_specs as s;"
        "print(r._registry.cache_info().misses, s._specs.cache_info().misses);"
        "r.BENCHMARK_METADATA;"
        "s.BENCHMARK_SPECS;"
        "print(r._registry.cache_info().misses, s._specs.cache_info().misses)"
    )
    assert lines == ["0 0", "1 1"]


@pytest.mark.fast
def test_unknown_attribute_still_raises_attribute_error() -> None:
    import benchbox.core.benchmark_registry as r
    import benchbox.core.results.benchmark_specs as s

    with pytest.raises(AttributeError):
        r.DOES_NOT_EXIST  # noqa: B018
    with pytest.raises(AttributeError):
        s.DOES_NOT_EXIST  # noqa: B018
