"""Static guard: no hardcoded ``Path.cwd()/"benchmark_runs"`` datagen defaults.

Work item w3 of the ``benchmark-output-root-regression-guard`` task.

PR #759 made the BaseBenchmark datagen default env-aware: constructors must
resolve their output root through ``get_benchmark_runs_datagen_path`` (which
honors ``BENCHBOX_OUTPUT_DIR``) instead of hardcoding a cwd-local
``benchmark_runs`` path. A new benchmark that reintroduces the hardcoded
pattern silently brings back the original bug — generated data lands under the
worktree instead of the configured shared root — and nothing else catches it.

This guard scans the source files of every *registered* benchmark (class
module plus adjacent generator/downloader modules) for the pattern and fails
with fix guidance when it appears outside the documented exception list.

Scan targets are derived from the registered classes' ``__module__`` via the
benchmark loader, NOT from a ``benchbox/core/**/benchmark.py`` glob, so
benchmarks living in non-standard files (e.g. TPCDSBenchmark in
``benchbox/core/tpcds/benchmark/runner.py``) and future additions are covered
automatically.
"""

from __future__ import annotations

import inspect
import re
import textwrap
from pathlib import Path
from typing import NamedTuple

import pytest

from benchbox.core.benchmark_loader import get_benchmark_class
from benchbox.core.benchmark_registry import get_all_benchmarks

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Matches e.g. ``Path.cwd() / "benchmark_runs"``, ``Path.cwd()/'benchmark_runs'``,
# and prefixed string literals like ``Path.cwd() / r"benchmark_runs"``.
_HARDCODED_PATTERN = re.compile(r"""Path\.cwd\(\)\s*/\s*[rRbBuUfF]{0,2}["']benchmark_runs["']""")

#: Documented exceptions, keyed by repo-relative POSIX path. Each occurrence is
#: an intentional non-default use (a fallback or probe), not a constructor
#: datagen default, so it cannot cause BENCHBOX_OUTPUT_DIR to be ignored at
#: benchmark construction. Additions to this list require the same scrutiny:
#: if the occurrence is a constructor/generator *default*, fix it to use
#: ``get_benchmark_runs_datagen_path`` instead of excepting it here.
_ALLOWED_OCCURRENCES: dict[str, str] = {
    "benchbox/core/write_primitives/benchmark.py": (
        "Multi-root probe list used to LOCATE existing TPC-H .tbl fixtures; "
        "one historical candidate root among several, not an output default."
    ),
    "benchbox/core/datavault/benchmark.py": (
        "Defensive fallback inside the tpch_source_dir property, taken only "
        "when output_dir is None — unreachable in practice because "
        "BaseBenchmark.__init__ always resolves output_dir first."
    ),
    "benchbox/core/joinorder_synthetic/generator.py": (
        "Standalone-use default inside the generator for direct construction "
        "without an output_dir. The benchmark always passes its (env-aware) "
        "output_dir through, so construction via the registry honors "
        "BENCHBOX_OUTPUT_DIR; covered by the registry-wide propagation test."
    ),
}


def _is_allowed(rel_path: str) -> bool:
    # Normalize separators so the POSIX-style keys match on every OS.
    return rel_path.replace("\\", "/") in _ALLOWED_OCCURRENCES


class _ScanTarget(NamedTuple):
    benchmark_id: str
    source_file: Path
    rel_path: str


def _collect_scan_targets() -> list[_ScanTarget]:
    """Resolve scan targets from the registry: class modules + generator modules."""
    repo_root = Path(__file__).resolve().parents[3]
    seen: set[Path] = set()
    targets: list[_ScanTarget] = []

    def _add(source: Path, benchmark_id: str) -> None:
        source = source.resolve()
        if source in seen or not source.is_file():
            return
        seen.add(source)
        try:
            rel = source.relative_to(repo_root)
        except ValueError:
            rel = source
        targets.append(_ScanTarget(benchmark_id, source, rel.as_posix()))

    for benchmark_id in sorted(get_all_benchmarks()):
        benchmark_class = get_benchmark_class(benchmark_id)
        class_file = Path(inspect.getfile(benchmark_class))
        _add(class_file, benchmark_id)

        # Hardcoded defaults frequently live in the generator/downloader the
        # constructor builds, not the benchmark class itself — scan those too.
        package_dir = repo_root / "benchbox" / "core" / benchmark_id
        for directory in {class_file.parent, package_dir}:
            if not directory.is_dir():
                continue
            for name in ("generator.py", "downloader.py"):
                _add(directory / name, benchmark_id)
            for sub in ("generator", "downloader"):
                sub_dir = directory / sub
                if sub_dir.is_dir():
                    for module in sorted(sub_dir.glob("*.py")):
                        _add(module, benchmark_id)

    return targets


_SCAN_TARGETS = _collect_scan_targets()


def test_scan_targets_cover_every_registered_benchmark() -> None:
    """Every registry id contributes at least one scanned source file."""
    covered = {target.benchmark_id for target in _SCAN_TARGETS}
    missing = sorted(set(get_all_benchmarks()) - covered)
    assert not missing, f"No scan targets resolved for: {missing}"


def test_no_hardcoded_cwd_benchmark_runs_defaults() -> None:
    """Benchmark sources must not hardcode cwd-local benchmark_runs defaults."""
    violations: list[str] = []

    for target in _SCAN_TARGETS:
        if _is_allowed(target.rel_path):
            continue
        source = target.source_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), start=1):
            if _HARDCODED_PATTERN.search(line):
                violations.append(f"  {target.rel_path}:{lineno}: {line.strip()}")

    if violations:
        guidance = textwrap.dedent(
            """
            Hardcoded Path.cwd()/"benchmark_runs" found in benchmark sources.

            These defaults ignore BENCHBOX_OUTPUT_DIR and write generated data
            under the active worktree instead of the configured output root.

            Fix: resolve the default through
                benchbox.utils.path_utils.get_benchmark_runs_datagen_path(name, sf)
            (or rely on BaseBenchmark's env-aware default by passing
            output_dir=None). If the occurrence is intentionally NOT a datagen
            default, add it to _ALLOWED_OCCURRENCES in this module with an
            explanation.

            Offending lines:
            """
        )
        pytest.fail(guidance + "\n".join(violations))


def test_guard_pattern_catches_the_regression_shape() -> None:
    """The regex matches the realistic spellings of the regression."""
    for snippet in (
        'self.output_dir = Path.cwd() / "benchmark_runs" / "datagen" / name',
        "output_dir = Path.cwd()/'benchmark_runs'/'datagen'",
        'default = Path.cwd()  /  "benchmark_runs"',
        'default = Path.cwd() / r"benchmark_runs"',
    ):
        assert _HARDCODED_PATTERN.search(snippet), snippet
    assert not _HARDCODED_PATTERN.search("output_dir = get_benchmark_runs_datagen_path(name, scale_factor)")
