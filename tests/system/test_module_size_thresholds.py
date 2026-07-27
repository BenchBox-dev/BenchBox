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

# Headroom added on top of every ALLOWLIST entry before it is enforced as a
# limit. Convention: when adding or updating an ALLOWLIST entry, record the
# module's actual line count at the time of the change (not a pre-inflated
# number) -- the enforced limit is computed as that value + ALLOWLIST_HEADROOM
# below. Without this, an exact-fit entry retrips the guardrail on the very
# next PR that adds even a single line to the file (this happened twice
# during the 2026-07 tuning remediation batch; see
# tuning-residual-cleanups-20260716 w3). This headroom applies only to
# explicit ALLOWLIST entries -- it intentionally does not loosen
# MAX_LINES_DEFAULT, so the guardrail still fails promptly on real unbounded
# growth of allowlisted modules and on any non-allowlisted module.
ALLOWLIST_HEADROOM = 25

# Modules that intentionally exceed the default.  The value is the module's
# documented line count (see ALLOWLIST_HEADROOM above for how the enforced
# limit is derived); keep the list small and well-commented.
ALLOWLIST = {
    Path(
        "benchbox/cli/commands/run.py"
    ): 3_105,  # CLI tuning + query subset + validation + visualization + help + compression + interactive wizard + post-run charts + driver_version/auto_install options + --publish flag + --benchmark-option + --iterations + explicit utf-8 encoding + run() McCabe 285 → <18 extraction helpers + benchmark-aware --scale defaulting (PR #351 review follow-up) + --strict-translation fail-closed policy + liquid_clustering_auto strategy wiring + propagate show_query_plans to interactive database_config + first-class --analyze-plans/--no-analyze-plans flag (canonical plan-capture knob) + --normalize-plan-literals flag (PR #939) + statistics phase CLI token + interactive wizard phase-name default (track2-joinorder-stats-phase) + --funding/--result-source provenance disclosure options + --stats-reset/--stats-per-table-timing controls + -df suffix dataframe-mode inference (PR #1042) + --dry-run OUTPUT_DIR flag-guard callback wiring (validation logic itself was relocated to ValidationRules.validate_dry_run_output_dir in benchbox/cli/exceptions.py; only the one-line callback= reference remains here, +1 line) + ADR-002 canonical tuning-mode vocabulary + tuned-fallback honesty wiring (PR #1182) + deployment-aware interactive credential/output ordering and one-time platform-option prompt (PR review follow-up); re-baselined 2026-07-27, headroom applied via ALLOWLIST_HEADROOM
    Path(
        "benchbox/core/tpcds/benchmark/runner.py"
    ): 2_059,  # orchestrates all benchmark phases (re-baselined 2026-07-16)
    Path(
        "benchbox/core/tpcdi/generator/data.py"
    ): 317,  # generator coordination remains complex (re-baselined 2026-07-16)
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


def _allowlist_snippet(path: Path, line_count: int) -> str:
    """Ready-to-paste ALLOWLIST entry for a module that just tripped the guard.

    No regen mode exists for this guard (guards-fix never edits allowlists,
    per policy) -- the fix is always a human-reviewed hand edit, so the
    failure prints the exact entry to paste.
    """
    return f'    Path(\n        "{path.as_posix()}"\n    ): {line_count},  # <justification -- why this module must exceed the default>'


def test_runtime_modules_respect_size_limits() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = []

    for relative_path in MODULE_PATHS:
        full_path = repo_root / relative_path
        if not full_path.exists():
            raise AssertionError(f"Tracked module {relative_path} is missing; update the size guard list")

        line_count = _count_lines(full_path)
        if relative_path in ALLOWLIST:
            limit = ALLOWLIST[relative_path] + ALLOWLIST_HEADROOM
        else:
            limit = MAX_LINES_DEFAULT

        if line_count > limit:
            violations.append((relative_path, line_count, limit))

    if violations:
        details = "\n".join(f"{path} has {lines} lines (limit {limit})" for path, lines, limit in violations)
        snippets = "\n".join(_allowlist_snippet(path, lines) for path, lines, _limit in violations)
        raise AssertionError(
            "Runtime module size guardrails tripped:\n"
            + details
            + "\nReduce the module size, or -- if the size is justified -- paste this into "
            "ALLOWLIST in tests/system/test_module_size_thresholds.py with a real "
            "justification (ALLOWLIST_HEADROOM is added automatically on top; no `make "
            "guards-fix` regen exists for this guard, it is always a reviewed hand edit):\n" + snippets
        )


def test_allowlist_headroom_applies_only_to_allowlisted_entries() -> None:
    """Pin the w3 headroom convention: ALLOWLIST entries get a small buffer
    above their documented line count so a routine one-line edit doesn't
    immediately retrip the guardrail, while MAX_LINES_DEFAULT (used for every
    module not in ALLOWLIST) stays untouched."""
    sample_path = next(iter(ALLOWLIST))
    documented_lines = ALLOWLIST[sample_path]

    assert documented_lines + ALLOWLIST_HEADROOM > documented_lines
    assert ALLOWLIST_HEADROOM < MAX_LINES_DEFAULT, "headroom must stay small relative to the default budget"

    # A module not in ALLOWLIST must never receive the headroom bump.
    untracked_path = Path("benchbox/cli/app.py")
    assert untracked_path not in ALLOWLIST
    effective_limit = (
        ALLOWLIST[untracked_path] + ALLOWLIST_HEADROOM if untracked_path in ALLOWLIST else MAX_LINES_DEFAULT
    )
    assert effective_limit == MAX_LINES_DEFAULT
