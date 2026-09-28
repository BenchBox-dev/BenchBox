"""Fail if a workflow file or process test exists that the ledger does not list.

Guardrail G3 backstop for the development loop modernization: every file in
the ledger's scope must appear in docs/development/dev-loop-property-ledger.md
so deletions cannot silently drop coverage. The ledger may list a file by
exact name or, for the large scripts directories, by an explicit
"Remaining ..." catch-all row that forces individual reclassification before
any deletion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "docs" / "development" / "dev-loop-property-ledger.md"

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOWS_TEST_DIR = REPO_ROOT / "tests" / "unit" / "workflows"
SCRIPTS_TEST_DIR = REPO_ROOT / "tests" / "unit" / "scripts"
RELEASE_TEST_DIR = REPO_ROOT / "tests" / "unit" / "release"
UNIT_DIR = REPO_ROOT / "tests" / "unit"
SCRIPTS_DIR = REPO_ROOT / "scripts"
PROJECT_SCRIPTS_DIR = REPO_ROOT / "_project" / "scripts"
HOOKS_FILE = REPO_ROOT / ".pre-commit-config.yaml"

# Files with an explicit "Remaining ..." catch-all row in the ledger: the row
# text names the directory so unlisted single files still resolve, while the
# row itself requires individual reclassification before any deletion.
CATCH_ALL_DIRS = ("scripts/*.py", "_project/scripts/*.py")


def _ledger_text() -> str:
    assert LEDGER.is_file(), f"ledger missing: {LEDGER}"
    return LEDGER.read_text(encoding="utf-8")


def _covered(name: str, text: str) -> bool:
    if name in text:
        return True
    return any(marker in text for marker in CATCH_ALL_DIRS)


def _workflow_files() -> list[str]:
    return sorted(p.name for p in WORKFLOW_DIR.glob("*.yml"))


def _test_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob("test_*.py"))


def test_ledger_lists_every_workflow() -> None:
    text = _ledger_text()
    missing = [name for name in _workflow_files() if name not in text]
    assert not missing, f"workflows missing from ledger: {missing}"


def test_ledger_lists_every_workflows_test() -> None:
    text = _ledger_text()
    missing = [name for name in _test_files(WORKFLOWS_TEST_DIR) if name not in text]
    assert not missing, f"tests/unit/workflows files missing from ledger: {missing}"


def test_ledger_lists_every_scripts_test() -> None:
    text = _ledger_text()
    missing = [name for name in _test_files(SCRIPTS_TEST_DIR) if name not in text]
    assert not missing, f"tests/unit/scripts files missing from ledger: {missing}"


def test_ledger_lists_every_release_test() -> None:
    text = _ledger_text()
    missing = [name for name in _test_files(RELEASE_TEST_DIR) if name not in text]
    assert not missing, f"tests/unit/release files missing from ledger: {missing}"


def test_ledger_lists_auto_merge_and_release_tests() -> None:
    text = _ledger_text()
    names = sorted(p.name for p in UNIT_DIR.glob("test_auto_merge_*.py"))
    names += sorted(p.name for p in UNIT_DIR.glob("test_release_*.py"))
    assert names, "expected auto-merge and release tests in tests/unit/"
    missing = [name for name in names if name not in text]
    assert not missing, f"auto-merge/release tests missing from ledger: {missing}"


def test_ledger_lists_every_script() -> None:
    text = _ledger_text()
    names = sorted(p.name for p in SCRIPTS_DIR.glob("*.py"))
    names += sorted(p.name for p in PROJECT_SCRIPTS_DIR.glob("*.py"))
    assert names, "expected scripts in scripts/ and _project/scripts/"
    missing = [name for name in names if not _covered(name, text)]
    assert not missing, f"scripts missing from ledger: {missing}"


def test_ledger_lists_every_pre_commit_hook() -> None:
    text = _ledger_text()
    hook_ids = re.findall(r"^\s*-\s*id:\s*(\S+)", HOOKS_FILE.read_text(encoding="utf-8"), re.M)
    assert hook_ids, "expected hooks in .pre-commit-config.yaml"
    missing = [hook for hook in dict.fromkeys(hook_ids) if hook not in text]
    assert not missing, f"pre-commit hooks missing from ledger: {missing}"


def test_ledger_records_keep_traps() -> None:
    text = _ledger_text()
    traps = [
        "detect_self_binding.py",
        "rp_scoped_check.py",
        "timing_audit.py",
        "timing_policy_check.py",
        "test_workflow_expression_contexts.py",
        "ruleset_drift_check.py",
        "validate_submission.py",
    ]
    missing = [name for name in traps if name not in text]
    assert not missing, f"KEEP traps missing from ledger: {missing}"
