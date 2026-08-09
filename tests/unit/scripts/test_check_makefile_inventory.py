"""Contract tests for the modular Makefile inventory guard."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "make" / "check_makefile_inventory.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_makefile_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_make_contract(destination: Path) -> None:
    shutil.copy2(REPO_ROOT / "Makefile", destination / "Makefile")
    shutil.copytree(REPO_ROOT / "make", destination / "make")


def _run_make(root: Path, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_repository_inventory_matches_manifest() -> None:
    module = _load_module()

    assert module.compare_inventory(REPO_ROOT) == []
    assert module.validate_migration_proof(REPO_ROOT) == []


def test_checked_monolith_baseline_has_expected_contract() -> None:
    module = _load_module()
    baseline = module._load_inventory(REPO_ROOT / module.BASELINE_PATH)

    assert baseline["target_count"] == 198
    assert baseline["public_target_count"] == 195
    assert baseline["default_goal"] == "test"


def test_public_target_removal_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    _copy_make_contract(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    assert "test-fast:\n" in text
    makefile.write_text(text.replace("test-fast:\n", "test-fast-removed:\n", 1), encoding="utf-8")

    problems = module.compare_inventory(tmp_path)

    assert any("missing targets: test-fast" in problem for problem in problems)
    assert any("unexpected targets: test-fast-removed" in problem for problem in problems)


def test_required_include_removal_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    _copy_make_contract(tmp_path)
    (tmp_path / "make" / "help.mk").unlink()

    assert module.compare_inventory(tmp_path) == ["required Make include is missing: make/help.mk"]


def test_semantic_assignment_reorder_fails_and_changes_gnu_make_evaluation(tmp_path: Path) -> None:
    module = _load_module()
    _copy_make_contract(tmp_path)
    platform_makefile = tmp_path / "make" / "platform-tests.mk"
    original = "CONTAINER_ENGINE ?= docker\nCOMPOSE := $(CONTAINER_ENGINE) compose"
    reordered = "COMPOSE := $(CONTAINER_ENGINE) compose\nCONTAINER_ENGINE ?= docker"
    text = platform_makefile.read_text(encoding="utf-8")
    assert original in text

    before = _run_make(tmp_path, "-pn", "test")
    assert before.returncode == 0
    assert "COMPOSE := docker compose" in before.stdout.splitlines()

    platform_makefile.write_text(text.replace(original, reordered, 1), encoding="utf-8")
    after = _run_make(tmp_path, "-pn", "test")
    assert after.returncode == 0
    assert "COMPOSE :=  compose" in after.stdout.splitlines()

    problems = module.compare_inventory(tmp_path)
    assert "semantic_statements changed" in problems


def test_writer_blesses_intentional_future_target_without_rewriting_migration_proof(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _copy_make_contract(tmp_path)
    maintenance = tmp_path / "make" / "worktree-maintenance.mk"
    maintenance.write_text(
        maintenance.read_text(encoding="utf-8")
        + "\n.PHONY: future-contract-probe\nfuture-contract-probe:\n\t@echo future\n",
        encoding="utf-8",
    )
    baseline = tmp_path / module.BASELINE_PATH
    proof = tmp_path / module.MIGRATION_PROOF_PATH
    original_baseline = baseline.read_bytes()
    original_proof = proof.read_bytes()

    assert any("unexpected targets: future-contract-probe" in item for item in module.compare_inventory(tmp_path))
    result = module.main(["--root", str(tmp_path), "--write"])

    assert result == 0
    assert module.compare_inventory(tmp_path) == []
    assert baseline.read_bytes() == original_baseline
    assert proof.read_bytes() == original_proof


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        (("BENCHBOX_MAKEFILE_ROOT=/definitely/missing/", "-n", "help"), None),
        (
            ("-e", "-n", "help"),
            {**os.environ, "BENCHBOX_MAKEFILE_ROOT": "/definitely/missing/"},
        ),
    ],
)
def test_reserved_include_root_rejects_cli_and_environment_override(
    tmp_path: Path,
    arguments: tuple[str, ...],
    environment: dict[str, str] | None,
) -> None:
    _copy_make_contract(tmp_path)

    result = _run_make(tmp_path, *arguments, env=environment)

    assert result.returncode == 0, result.stderr
    assert "makefile-inventory-check" in result.stdout
    assert "/definitely/missing" not in result.stderr


def test_absolute_symlink_makefile_preserves_module_resolution(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _copy_make_contract(repository)
    invocation = tmp_path / "invocation"
    invocation.mkdir()
    makefile_link = invocation / "BenchBox.mk"
    makefile_link.symlink_to(repository / "Makefile")

    result = subprocess.run(
        ["make", "--no-print-directory", "-f", str(makefile_link), "-n", "help"],
        cwd=invocation,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "makefile-inventory-check" in result.stdout
