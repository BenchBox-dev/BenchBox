"""Static guardrails for centralized runtime output control.

Design: ratchet pattern
-----------------------
* The global scan covers every .py file under benchbox/ automatically -
  no manual per-file lists to forget to update.
* _PRINT_ALLOWLIST: files that legitimately construct or use print() directly
  (only the output implementation itself).
* _PENDING_MIGRATION: files with pre-existing print() usage that have not yet
  been migrated to emit(), mapped to the exact count of raw print() call sites
  they are exempt for.  This is a COUNT-pinned ratchet, not a file-level
  exemption: a file's raw-print count may only ever decrease (migration) or
  stay the same, never increase.  Adding a new print() call to an exempted
  file raises its actual count above the pinned value and fails
  test_no_new_raw_print_in_benchbox_runtime, exactly like introducing raw
  print() in a brand new file - the exemption only covers the print() calls
  that already existed when the file was added here, not the file itself.
* New files are covered automatically.  Any new file with raw print() that
  is not in _PENDING_MIGRATION causes an immediate test failure.
"""

from __future__ import annotations

import re
import sys
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
# emit(), mapped to their exact current raw-print call count.  When a file is
# migrated (count drops), update or remove its entry - the companion test
# `test_pending_migration_set_contains_no_stale_entries` will fail if you
# forget to tighten a lowered count. A NEW print() call anywhere in one of
# these files raises its actual count above the pinned value here, which
# `test_no_new_raw_print_in_benchbox_runtime` treats as a fresh violation -
# the exemption covers only the call sites counted below, not the whole file.
_PENDING_MIGRATION: dict[str, int] = {
    # Docstring examples in publishing module - pre-existing, not new violations
    "benchbox/core/publishing/__init__.py": 2,
    "benchbox/core/publishing/bundle_publisher.py": 1,
    # Equivalence-report __main__ entrypoints (make *-equivalence-report):
    # pre-existing raw print() report output, surfaced when the medium tier
    # got its first CI consumer (develop-post-merge run 28706929881; see
    # medium-tier-red-disposition-and-promotion). Migration to emit() is a
    # follow-up; cross_surface.py is a CODEOWNERS soundness path, so that
    # migration belongs in a reviewed comparator PR, not this test-only
    # disposition.
    "benchbox/core/equivalence/cross_surface.py": 18,
    "benchbox/core/tpchavoc/dataframe_equivalence.py": 8,
    "benchbox/core/tpchavoc/equivalence.py": 12,
}

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
    """No NEW raw print() call site may appear in benchbox runtime - use emit().

    Files in _PRINT_ALLOWLIST are permanently exempt (output implementation).
    Files in _PENDING_MIGRATION are exempt ONLY up to their pinned call count -
    a file's actual raw-print count exceeding its pinned value is a fresh
    violation, exactly like raw print() in a brand new file. This is a
    count-pinned ratchet, not a file-level exemption, so a new print() call
    added to an already-exempted file still fails here.
    """
    offenders: list[str] = []
    for path in _benchbox_runtime_files():
        rel = _rel(path)
        if rel in _PRINT_ALLOWLIST:
            continue
        actual_count = len(_RAW_PRINT.findall(path.read_text(encoding="utf-8")))
        allowed_count = _PENDING_MIGRATION.get(rel, 0)
        if actual_count > allowed_count:
            offenders.append(f"{rel}  (found {actual_count}, pinned to {allowed_count})")
    assert not offenders, (
        "Raw print() count increased beyond what _PENDING_MIGRATION pins"
        " (use emit() instead, or raise the pinned count only if the addition is pre-existing):\n"
        + "\n".join(f"  {f}" for f in sorted(offenders))
    )


def test_new_print_in_an_exempted_file_still_fails(tmp_path, monkeypatch) -> None:
    """Regression: the exemption is count-pinned, not file-level.

    A file already in _PENDING_MIGRATION with a NEW print() call added (raising
    its actual count above the pinned value) must still be reported as an
    offender - the exemption must not silently cover every future print() in
    that file.
    """
    fake_root = tmp_path / "benchbox"
    fake_file = fake_root / "core" / "equivalence" / "cross_surface.py"
    fake_file.parent.mkdir(parents=True)
    pinned_count = _PENDING_MIGRATION["benchbox/core/equivalence/cross_surface.py"]
    # One MORE print() call than the pinned count.
    fake_file.write_text("\n".join("print('x')" for _ in range(pinned_count + 1)), encoding="utf-8")

    monkeypatch.setattr(sys.modules[__name__], "BENCHBOX_ROOT", fake_root)
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)

    offenders: list[str] = []
    for path in _benchbox_runtime_files():
        rel = _rel(path)
        if rel in _PRINT_ALLOWLIST:
            continue
        actual_count = len(_RAW_PRINT.findall(path.read_text(encoding="utf-8")))
        allowed_count = _PENDING_MIGRATION.get(rel, 0)
        if actual_count > allowed_count:
            offenders.append(rel)
    assert offenders == ["benchbox/core/equivalence/cross_surface.py"]


def test_pending_migration_set_contains_no_stale_entries() -> None:
    """_PENDING_MIGRATION's pinned counts must match reality, and only shrink.

    A pinned count that no longer matches the file's actual raw-print count
    (file fully migrated to 0, or partially migrated so the pinned count is
    now too loose) must be corrected or removed. This test fails if you
    forget, keeping the ratchet honest and always shrinking.
    """
    stale: list[str] = []
    for rel, allowed_count in sorted(_PENDING_MIGRATION.items()):
        path = REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel}  (file no longer exists)")
            continue
        actual_count = len(_RAW_PRINT.findall(path.read_text(encoding="utf-8")))
        if actual_count == 0:
            stale.append(f"{rel}  (no longer uses raw print - remove from _PENDING_MIGRATION)")
        elif actual_count < allowed_count:
            stale.append(f"{rel}  (pinned to {allowed_count} but only {actual_count} remain - lower the pinned count)")
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
