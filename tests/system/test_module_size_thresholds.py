"""Guardrails for oversized runtime modules.

These checks ensure that the restructured runtime modules remain within the
expected size boundaries. When a module needs to exceed the default limit,
add an explicit entry to ``ALLOWLIST`` along with a short justification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.fast


# Default maximum number of lines for a module before the guardrails trigger.
MAX_LINES_DEFAULT = 1_200

# Modules that intentionally exceed the default.  The value is the bespoke limit
# for that path; keep the list small and well-commented.
ALLOWLIST = {
    Path(
        "benchbox/cli/commands/run.py"
    ): 2_550,  # CLI tuning + query subset + validation + visualization + help + compression + interactive wizard + post-run charts + driver_version/auto_install options + --publish flag
    Path("benchbox/core/tpcds/benchmark/runner.py"): 2_120,  # orchestrates all benchmark phases
    Path("benchbox/core/tpcdi/generator/data.py"): 1_600,  # generator coordination remains complex
}

# Runtime modules that we care about keeping trim.  Add new modules here when
# substantial refactors land or when new runtime-critical packages are created.
MODULE_PATHS = [
    Path("benchbox/cli/commands/run.py"),
    Path("benchbox/cli/app.py"),
    Path("benchbox/core/tpcds/benchmark/runner.py"),
    Path("benchbox/core/tpcds/generator/manager.py"),
    Path("benchbox/core/tpcdi/etl/pipeline.py"),
    Path("benchbox/core/tpcdi/generator/data.py"),
    Path("benchbox/platforms/clickhouse/adapter.py"),
]


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def test_runtime_modules_respect_size_limits() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = []

    for relative_path in MODULE_PATHS:
        full_path = repo_root / relative_path
        if not full_path.exists():
            raise AssertionError(f"Tracked module {relative_path} is missing; update the size guard list")

        line_count = _count_lines(full_path)
        limit = ALLOWLIST.get(relative_path, MAX_LINES_DEFAULT)

        if line_count > limit:
            violations.append((relative_path, line_count, limit))

    if violations:
        details = "\n".join(f"{path} has {lines} lines (limit {limit})" for path, lines, limit in violations)
        raise AssertionError(
            "Runtime module size guardrails tripped:\n"
            + details
            + "\nReduce the module size or update the allowlist with justification."
        )
