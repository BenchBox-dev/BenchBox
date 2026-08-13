"""Tests for the release curation-drift guard's Makefile parsing."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_release_curation.py"

spec = importlib.util.spec_from_file_location("check_release_curation", SCRIPT_PATH)
check_release_curation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_release_curation)

CURATED_PROJECT_DEPENDENT_TESTS = {
    "tests/unit/scripts/test_check_complexity.py",
}
RELEASE_SAFE_PROJECT_TESTS = {
    "tests/unit/scripts/test_check_makefile_inventory.py",
    "tests/unit/core/test_platform_registry_behavioral.py",
}


def _write_makefile(tmp_path: Path, recipe_lines: list[str]) -> Path:
    makefile = tmp_path / "Makefile"
    body = "\n".join(f"\t{line}" for line in recipe_lines)
    makefile.write_text(f"release-cut:\n{body}\n\nother-target:\n\techo hi\n", encoding="utf-8")
    return makefile


def test_parse_curation_list_handles_ignore_unmatch(tmp_path):
    """--ignore-unmatch must not be swallowed into the parsed path set."""
    makefile = _write_makefile(
        tmp_path,
        [
            "git rm -rf --ignore-unmatch _project _blog",
            "git rm -f --ignore-unmatch .mcp.json todo.config.yaml",
            "git add pyproject.toml",
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project", "_blog", ".mcp.json", "todo.config.yaml"}


def test_parse_curation_list_handles_legacy_prefixed_lines(tmp_path):
    """Pre---ignore-unmatch form (`-git rm -rf <paths>`) still parses."""
    makefile = _write_makefile(
        tmp_path,
        [
            "-git rm -rf _project",
            "-git rm -f .mcp.json",
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project", ".mcp.json"}


def test_parse_curation_list_ignores_non_rm_lines(tmp_path):
    """git ls-files guard lines and other commands contribute no paths."""
    makefile = _write_makefile(
        tmp_path,
        [
            "git rm -rf --ignore-unmatch _project",
            "@LEFTOVER=$$(git ls-files _project _blog); \\",
            'if [ -n "$$LEFTOVER" ]; then exit 1; fi',
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project"}


def test_real_makefile_curation_list_parses_to_paths_only():
    """Against the repo Makefile: every parsed entry is a path, never a flag."""
    paths = check_release_curation.parse_curation_list(REPO_ROOT / "Makefile")
    assert paths, "expected a non-empty curation list from the repo Makefile"
    flags = {p for p in paths if p.startswith("-")}
    assert not flags, f"parser leaked flags into the curation list: {sorted(flags)}"


def test_release_make_runtime_is_main_only_not_curated() -> None:
    main_only = check_release_curation.parse_main_only_allowlist(
        REPO_ROOT / "_project" / "decisions" / "single-repo-migration.md"
    )
    curated = check_release_curation.parse_curation_list(REPO_ROOT / "Makefile")

    assert "make" in main_only
    assert "make" not in curated


def test_curated_preview_release_paths_are_shipped_and_deferred_workflows_are_curated() -> None:
    main_only = check_release_curation.parse_main_only_allowlist(
        REPO_ROOT / "_project" / "decisions" / "single-repo-migration.md"
    )
    curated = check_release_curation.parse_curation_list(REPO_ROOT / "Makefile")

    assert main_only >= check_release_curation.REQUIRED_RELEASE_PATHS
    assert check_release_curation.REQUIRED_RELEASE_PATHS.isdisjoint(curated)
    assert curated >= check_release_curation.REQUIRED_CURATED_PATHS


def _copy_curated_make_runtime(destination: Path) -> None:
    shutil.copy2(REPO_ROOT / "Makefile", destination / "Makefile")
    shutil.copytree(REPO_ROOT / "make", destination / "make")


def test_curated_release_make_runtime_executes_help_and_inventory(tmp_path: Path) -> None:
    _copy_curated_make_runtime(tmp_path)

    help_result = subprocess.run(
        ["make", "--no-print-directory", "help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    inventory_result = subprocess.run(
        ["make", "--no-print-directory", "makefile-inventory-check"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "makefile-inventory-check" in help_result.stdout
    assert inventory_result.returncode == 0, inventory_result.stderr
    assert "Makefile inventory OK: 188 targets, 184 public, default=test" in inventory_result.stdout


@pytest.mark.parametrize(
    "target",
    ["complexity-check", "platform-manifest-check", "blind-spots-list"],
)
def test_curated_release_development_targets_fail_with_explicit_policy(tmp_path: Path, target: str) -> None:
    _copy_curated_make_runtime(tmp_path)

    result = subprocess.run(
        ["make", "--no-print-directory", target],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires the BenchBox development tree" in result.stderr
    assert "No such file or directory" not in result.stderr


def test_every_project_dependent_make_recipe_is_declared_development_only(tmp_path: Path) -> None:
    assert check_release_curation.development_tree_target_findings(REPO_ROOT) == []

    _copy_curated_make_runtime(tmp_path)
    with (tmp_path / "make" / "documentation.mk").open("a", encoding="utf-8") as stream:
        stream.write("\nforgotten-project-target:\n\tpython _project/scripts/forgotten.py\n")

    assert check_release_curation.development_tree_target_findings(tmp_path) == [
        "Make target 'forgotten-project-target' references _project/ but is not declared development-only"
    ]


def test_curated_release_make_runtime_fails_closed_when_module_is_omitted(tmp_path: Path) -> None:
    _copy_curated_make_runtime(tmp_path)
    (tmp_path / "make" / "help.mk").unlink()

    result = subprocess.run(
        ["make", "--no-print-directory", "help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "make/help.mk" in result.stderr
    assert "No such file or directory" in result.stderr


def test_curated_release_removes_dangling_project_test_and_runs_retained_tests(
    tmp_path: Path,
) -> None:
    curated = check_release_curation.parse_curation_list(REPO_ROOT / "Makefile")
    assert curated >= CURATED_PROJECT_DEPENDENT_TESTS
    assert curated.isdisjoint(RELEASE_SAFE_PROJECT_TESTS)

    _copy_curated_make_runtime(tmp_path)
    shutil.copytree(REPO_ROOT / "benchbox", tmp_path / "benchbox")
    retained_tests = []
    for relative in sorted(RELEASE_SAFE_PROJECT_TESTS):
        retained_test = tmp_path / relative
        retained_test.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, retained_test)
        retained_tests.append(str(retained_test))

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *retained_tests],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout
    assert "2 skipped" in result.stdout
