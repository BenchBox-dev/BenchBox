"""Static guardrails for centralized runtime output control.

Design: ratchet pattern
-----------------------
* The global scan covers every .py file under benchbox/ automatically -
  no manual per-file lists to forget to update.
* _PRINT_ALLOWLIST: files that legitimately construct or use print() directly
  (only the output implementation itself).
* _PENDING_MIGRATION: files with pre-existing print() usage that have not yet
  been migrated to emit().  This set must only ever SHRINK.  A companion test
  enforces that: if you migrate a file, you must remove it from this set or
  the test suite fails.
* New files are covered automatically.  Any new file with raw print() that
  is not in _PENDING_MIGRATION causes an immediate test failure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHBOX_ROOT = REPO_ROOT / "benchbox"

# The output implementation itself is allowed to construct Console() directly.
_PRINT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "benchbox/utils/printing.py",
    }
)

# Pre-existing files with raw print() that have not yet been migrated to
# emit().  When a file here is migrated, remove it from this set - the
# companion test `test_pending_migration_set_contains_no_stale_entries` will
# fail if you forget.
_PENDING_MIGRATION: frozenset[str] = frozenset(
    {
        # Docstring examples in publishing module - pre-existing, not new violations
        "benchbox/core/publishing/__init__.py",
        "benchbox/core/publishing/bundle_publisher.py",
        # Equivalence-report __main__ entrypoints (make *-equivalence-report):
        # pre-existing raw print() report output, surfaced when the medium tier
        # got its first CI consumer (develop-post-merge run 28706929881; see
        # medium-tier-red-disposition-and-promotion). Migration to emit() is a
        # follow-up; cross_surface.py is a CODEOWNERS soundness path, so that
        # migration belongs in a reviewed comparator PR, not this test-only
        # disposition.
        "benchbox/core/equivalence/cross_surface.py",
        "benchbox/core/tpchavoc/dataframe_equivalence.py",
        "benchbox/core/tpchavoc/equivalence.py",
    }
)

# raw print( that is not a method call (e.g. not console.print, self.print)
_RAW_PRINT = re.compile(r"(?<![\w.])print\(")

# module-level `console = Console(...)` - the specific CLI anti-pattern being
# guarded.  Word-boundary anchor prevents matches on `string_console`, `self.console`, etc.
_CONSOLE_SINGLETON = re.compile(r"\bconsole\s*=\s*Console\(")


def _benchbox_runtime_files() -> list[Path]:
    """All .py files under benchbox/, excluding test files."""
    return [p for p in BENCHBOX_ROOT.rglob("*.py") if "test" not in p.name]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_no_new_raw_print_in_benchbox_runtime() -> None:
    """No NEW benchbox runtime file may use raw print() - use emit() instead.

    Files in _PENDING_MIGRATION are pre-existing and exempt until migrated.
    Files in _PRINT_ALLOWLIST are permanently exempt (output implementation).
    Any file outside both sets that contains raw print() is a regression.
    """
    _exempt = _PRINT_ALLOWLIST | _PENDING_MIGRATION
    offenders: list[str] = []
    for path in _benchbox_runtime_files():
        rel = _rel(path)
        if rel in _exempt:
            continue
        if _RAW_PRINT.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, (
        "Raw print() introduced in files not in _PENDING_MIGRATION"
        " (use emit() instead, or add to _PENDING_MIGRATION if pre-existing):\n"
        + "\n".join(f"  {f}" for f in sorted(offenders))
    )


def test_pending_migration_set_contains_no_stale_entries() -> None:
    """_PENDING_MIGRATION must only contain files that still have raw print().

    When a file is migrated to emit(), remove it from _PENDING_MIGRATION.
    This test fails if you forget, keeping the set honest and always shrinking.
    """
    stale: list[str] = []
    for rel in sorted(_PENDING_MIGRATION):
        path = REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel}  (file no longer exists)")
            continue
        if not _RAW_PRINT.search(path.read_text(encoding="utf-8")):
            stale.append(f"{rel}  (no longer uses raw print - remove from _PENDING_MIGRATION)")
    assert not stale, "Stale entries in _PENDING_MIGRATION:\n" + "\n".join(f"  {s}" for s in stale)


def test_cli_commands_do_not_use_direct_console_singletons() -> None:
    """CLI command files must use the shared console proxy, not Console() singletons.

    Scans all files under benchbox/cli/commands/ so new command modules are
    covered automatically without manual list updates.
    """
    offenders: list[str] = []
    cli_commands_root = BENCHBOX_ROOT / "cli" / "commands"
    for path in cli_commands_root.rglob("*.py"):
        if "test" in path.name:
            continue
        if _CONSOLE_SINGLETON.search(path.read_text(encoding="utf-8")):
            offenders.append(_rel(path))
    assert not offenders, (
        "Direct Console() singleton detected in CLI commands"
        " (import console from benchbox.cli.shared instead):\n" + "\n".join(f"  {f}" for f in sorted(offenders))
    )
