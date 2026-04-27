"""Tests for bidirectional repository sync functions.

Tests the get_syncable_files(), compare_repos(), and apply_transform()
functions in benchbox/release/workflow.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import subprocess
from pathlib import Path

import pytest

from benchbox.release.workflow import (
    ALLOWED_ROOT_FILES,
    CLEANUP_PATTERNS,
    DOCS_DIR_EXCLUDES,
    FORBIDDEN_PATTERNS,
    GITIGNORE_PRIVATE_LINES,
    GITIGNORE_PRIVATE_SECTIONS,
    GLOBAL_EXCLUDES,
    PYPROJECT_PRIVATE_BLOCKS,
    TESTS_DIR_EXCLUDES,
    RepoComparison,
    _cleanup_unwanted_files,
    _restore_private_pyproject_lines,
    _strip_private_pyproject_lines,
    apply_transform,
    compare_repos,
    get_syncable_files,
    should_transform,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetSyncableFiles:
    """Test get_syncable_files() function."""

    def test_returns_set_of_paths(self, tmp_path: Path):
        """Test that get_syncable_files returns a set of Path objects."""
        # Create minimal structure
        (tmp_path / "README.md").write_text("# Test")
        result = get_syncable_files(tmp_path)
        assert isinstance(result, set)
        if result:
            assert all(isinstance(p, Path) for p in result)

    def test_includes_allowed_root_files(self, tmp_path: Path):
        """Test that files in ALLOWED_ROOT_FILES are included."""
        # Create a subset of allowed files
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "LICENSE").write_text("MIT License")
        (tmp_path / "pyproject.toml").write_text("[project]")

        result = get_syncable_files(tmp_path)

        assert Path("README.md") in result
        assert Path("LICENSE") in result
        assert Path("pyproject.toml") in result

    def test_excludes_global_patterns(self, tmp_path: Path):
        """Test that GLOBAL_EXCLUDES patterns are excluded."""
        # Create files that should be excluded
        (tmp_path / "benchbox").mkdir()
        (tmp_path / "benchbox" / "__pycache__").mkdir()
        (tmp_path / "benchbox" / "__pycache__" / "test.pyc").write_bytes(b"bytecode")
        (tmp_path / "benchbox" / "module.py").write_text("# module")
        (tmp_path / ".DS_Store").write_bytes(b"mac metadata")

        result = get_syncable_files(tmp_path)

        # Should include module.py but not __pycache__ contents or .DS_Store
        assert Path("benchbox/module.py") in result
        pycache_files = [p for p in result if "__pycache__" in str(p)]
        assert len(pycache_files) == 0, f"Found pycache files: {pycache_files}"
        assert Path(".DS_Store") not in result

    def test_excludes_docs_build_directory(self, tmp_path: Path):
        """Test that docs/_build is excluded."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "_build").mkdir()
        (tmp_path / "docs" / "_build" / "html").mkdir()
        (tmp_path / "docs" / "_build" / "html" / "index.html").write_text("<html>")
        (tmp_path / "docs" / "index.md").write_text("# Docs")

        result = get_syncable_files(tmp_path)

        # Should include docs/index.md but not docs/_build/*
        assert Path("docs/index.md") in result
        build_files = [p for p in result if "_build" in str(p)]
        assert len(build_files) == 0, f"Found build files: {build_files}"

    def test_excludes_claude_and_codex_directories(self, tmp_path: Path):
        """Test that .claude/ and .codex/ directories are fully excluded."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "skills").mkdir()
        (tmp_path / ".claude" / "skills" / "workflow.md").write_text("# workflow")
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "skills").mkdir()
        (tmp_path / ".codex" / "skills" / "task.md").write_text("# task")

        result = get_syncable_files(tmp_path)

        # Neither .claude nor .codex files should be included
        claude_files = [p for p in result if ".claude" in str(p)]
        codex_files = [p for p in result if ".codex" in str(p)]
        assert len(claude_files) == 0, f"Found .claude files: {claude_files}"
        assert len(codex_files) == 0, f"Found .codex files: {codex_files}"

    def test_excludes_forbidden_patterns(self, tmp_path: Path):
        """Test that FORBIDDEN_PATTERNS are excluded."""
        (tmp_path / "benchbox").mkdir()
        (tmp_path / "benchbox" / "data.dat").write_bytes(b"binary data")
        (tmp_path / "benchbox" / "table.tbl").write_bytes(b"table data")
        (tmp_path / "benchbox" / "module.py").write_text("# module")

        result = get_syncable_files(tmp_path)

        # Should include .py but not .dat or .tbl
        assert Path("benchbox/module.py") in result
        dat_files = [p for p in result if p.suffix == ".dat"]
        tbl_files = [p for p in result if p.suffix == ".tbl"]
        assert len(dat_files) == 0, f"Found .dat files: {dat_files}"
        assert len(tbl_files) == 0, f"Found .tbl files: {tbl_files}"

    def test_excludes_files_not_in_allowed_roots(self, tmp_path: Path):
        """Test that files not under ALLOWED_ROOT_FILES are excluded."""
        (tmp_path / "secret_stuff").mkdir()
        (tmp_path / "secret_stuff" / "data.py").write_text("# secret")
        (tmp_path / "benchbox").mkdir()
        (tmp_path / "benchbox" / "public.py").write_text("# public")

        result = get_syncable_files(tmp_path)

        # Should include benchbox/ but not secret_stuff/
        assert Path("benchbox/public.py") in result
        secret_files = [p for p in result if "secret" in str(p)]
        assert len(secret_files) == 0, f"Found secret files: {secret_files}"

    def test_excludes_tests_databases_directory(self, tmp_path: Path):
        """Test that tests/databases is excluded (gitignored in public repo)."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "databases").mkdir()
        (tmp_path / "tests" / "databases" / "create_test_db.py").write_text("# db script")
        (tmp_path / "tests" / "unit").mkdir()
        (tmp_path / "tests" / "unit" / "test_foo.py").write_text("# test")

        result = get_syncable_files(tmp_path)

        # Should include tests/unit but not tests/databases
        assert Path("tests/unit/test_foo.py") in result
        db_files = [p for p in result if "databases" in str(p)]
        assert len(db_files) == 0, f"Found database files: {db_files}"

    def test_excludes_hold_back_paths_across_repo_roots(self, tmp_path: Path):
        """Explorer hold-backs should be excluded from syncable files everywhere."""
        (tmp_path / "benchbox/release").mkdir(parents=True)
        (tmp_path / "benchbox/release/sync.py").write_text("# private\n")
        (tmp_path / "benchbox/core/explorer_pipeline").mkdir(parents=True)
        (tmp_path / "benchbox/core/explorer_pipeline/__init__.py").write_text("# private\n")
        (tmp_path / "benchbox/cli/commands").mkdir(parents=True)
        (tmp_path / "benchbox/cli/commands/explorer.py").write_text("# private\n")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts/prepare_release.py").write_text("# private\n")
        (tmp_path / "tests/unit/core/explorer_pipeline").mkdir(parents=True)
        (tmp_path / "tests/unit/core/explorer_pipeline/test_private.py").write_text("# private\n")
        (tmp_path / "tests/unit/release").mkdir(parents=True)
        (tmp_path / "tests/unit/release/test_workflow.py").write_text("# private\n")
        (tmp_path / "tests/unit/test_xdist_safety.py").write_text("# private\n")
        (tmp_path / "docs/development").mkdir(parents=True)
        (tmp_path / "docs/development/results-explorer-brand-ownership.md").write_text("# private\n")
        (tmp_path / "docs/development/results-explorer-browser-testing.md").write_text("# private\n")
        (tmp_path / ".github/workflows").mkdir(parents=True)
        (tmp_path / ".github/workflows/results-explorer-browser.yml").write_text("name: explorer\n")
        (tmp_path / "README.md").write_text("# public\n")

        result = get_syncable_files(tmp_path)

        assert Path("README.md") in result
        assert Path("benchbox/release/sync.py") not in result
        assert Path("benchbox/core/explorer_pipeline/__init__.py") not in result
        assert Path("benchbox/cli/commands/explorer.py") not in result
        assert Path("scripts/prepare_release.py") not in result
        assert Path("tests/unit/core/explorer_pipeline/test_private.py") not in result
        assert Path("tests/unit/release/test_workflow.py") not in result
        assert Path("tests/unit/test_xdist_safety.py") not in result
        assert Path("docs/development/results-explorer-brand-ownership.md") not in result
        assert Path("docs/development/results-explorer-browser-testing.md") not in result
        assert Path(".github/workflows/results-explorer-browser.yml") not in result


class TestCompareRepos:
    """Test compare_repos() function."""

    def test_detects_added_files(self, tmp_path: Path):
        """Test detection of files added in source."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Use files that are in ALLOWED_ROOT_FILES
        (source / "README.md").write_text("# Source")
        (source / "CONTRIBUTING.md").write_text("# Contributing")  # In ALLOWED_ROOT_FILES
        (target / "README.md").write_text("# Source")

        result = compare_repos(source, target, check_conflicts=False)

        assert Path("CONTRIBUTING.md") in result.added
        assert Path("README.md") not in result.added

    def test_detects_modified_files(self, tmp_path: Path):
        """Test detection of modified files."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "README.md").write_text("# Modified content")
        (target / "README.md").write_text("# Original content")

        result = compare_repos(source, target, check_conflicts=False)

        assert Path("README.md") in result.modified

    def test_detects_deleted_files(self, tmp_path: Path):
        """Test detection of files deleted from source."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Use files that are in ALLOWED_ROOT_FILES
        (source / "README.md").write_text("# Source")
        (target / "README.md").write_text("# Source")
        (target / "CONTRIBUTING.md").write_text("# Contributing")  # In ALLOWED_ROOT_FILES

        result = compare_repos(source, target, check_conflicts=False)

        assert Path("CONTRIBUTING.md") in result.deleted

    def test_detects_unchanged_files(self, tmp_path: Path):
        """Test detection of unchanged files."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "README.md").write_text("# Same content")
        (target / "README.md").write_text("# Same content")

        result = compare_repos(source, target, check_conflicts=False)

        assert Path("README.md") in result.unchanged
        assert Path("README.md") not in result.modified

    def test_has_changes_property(self, tmp_path: Path):
        """Test has_changes property."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "README.md").write_text("# Same")
        (target / "README.md").write_text("# Same")

        result = compare_repos(source, target, check_conflicts=False)
        assert not result.has_changes

        # Add a new file (must be in ALLOWED_ROOT_FILES)
        (source / "CONTRIBUTING.md").write_text("# Contributing")
        result = compare_repos(source, target, check_conflicts=False)
        assert result.has_changes

    def test_summary_method(self, tmp_path: Path):
        """Test summary() method returns correct description."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "README.md").write_text("# Same")
        (target / "README.md").write_text("# Same")

        result = compare_repos(source, target, check_conflicts=False)
        assert "No changes" in result.summary()

        # Add changes (must be in ALLOWED_ROOT_FILES)
        (source / "CONTRIBUTING.md").write_text("# Contributing")
        result = compare_repos(source, target, check_conflicts=False)
        assert "Added: 1 files" in result.summary()

    def test_handles_missing_target(self, tmp_path: Path):
        """Test handling when target doesn't exist."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        # target is NOT created

        (source / "README.md").write_text("# Source")

        result = compare_repos(source, target, check_conflicts=False)

        # All source files should be marked as added
        assert Path("README.md") in result.added
        assert len(result.deleted) == 0
        assert len(result.modified) == 0


class TestConflictDetection:
    """Test conflict detection using git history."""

    def _init_git_repo(self, path: Path) -> None:
        """Initialize a git repo and make initial commit."""
        subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)

    def _git_add_commit(self, path: Path, message: str) -> None:
        """Stage and commit all changes."""
        subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True, check=True)

    def test_detects_conflict_when_both_modified(self, tmp_path: Path):
        """Test conflict detection when file modified in both repos."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Initialize git repos with same initial content
        (source / "README.md").write_text("# Original")
        (target / "README.md").write_text("# Original")

        self._init_git_repo(source)
        self._init_git_repo(target)
        self._git_add_commit(source, "Initial")
        self._git_add_commit(target, "Initial")

        # Now modify both with different content
        (source / "README.md").write_text("# Modified in source")
        (target / "README.md").write_text("# Modified in target")

        result = compare_repos(source, target, check_conflicts=True)

        assert Path("README.md") in result.conflicts

    def test_no_conflict_when_only_source_modified(self, tmp_path: Path):
        """Test no conflict when only source is modified."""
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        # Initialize git repos with same initial content
        (source / "README.md").write_text("# Original")
        (target / "README.md").write_text("# Original")

        self._init_git_repo(source)
        self._init_git_repo(target)
        self._git_add_commit(source, "Initial")
        self._git_add_commit(target, "Initial")

        # Only modify source
        (source / "README.md").write_text("# Modified in source")

        result = compare_repos(source, target, check_conflicts=True)

        assert Path("README.md") in result.modified
        assert Path("README.md") not in result.conflicts


class TestApplyTransform:
    """Test apply_transform() function."""

    def test_push_transform_applies_substitutions(self):
        """Test that push direction applies public substitutions."""
        content = 'email = "joeharris76@gmail.com"'
        result = apply_transform(content, "push")
        assert "joe@benchbox.dev" in result
        assert "joeharris76@gmail.com" not in result

    def test_pull_transform_reverses_substitutions(self):
        """Test that pull direction reverses substitutions."""
        content = 'email = "joe@benchbox.dev"'
        result = apply_transform(content, "pull")
        assert "joeharris76@gmail.com" in result
        assert "joe@benchbox.dev" not in result

    def test_round_trip_transformation(self):
        """Test that push then pull returns original content."""
        original = 'email = "joeharris76@gmail.com"'
        pushed = apply_transform(original, "push")
        pulled = apply_transform(pushed, "pull")
        assert pulled == original

    def test_no_transform_for_unrelated_content(self):
        """Test that unrelated content is unchanged."""
        content = "def hello():\n    print('hello')"
        push_result = apply_transform(content, "push")
        pull_result = apply_transform(content, "pull")
        assert push_result == content
        assert pull_result == content

    def test_invalid_direction_raises_error(self):
        """Test that invalid direction raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="Invalid direction"):
            apply_transform("content", "invalid")

        with pytest.raises(ValueError, match="must be 'push' or 'pull'"):
            apply_transform("content", "")

    def test_cli_init_push_and_pull_transform(self):
        """CLI registry transforms should strip and restore explorer wiring."""
        content = """from .df_tuning import df_tuning_group
from .download_answers import download_answers
from .explorer import explorer_group
from .export import export

COMMANDS = (
    df_tuning_group,  # Deprecated: hidden, kept for backwards compatibility
    download_answers,
    explorer_group,
    export,
)

__all__ = [
    "df_tuning_group",
    "download_answers",
    "explorer_group",
    "export",
]
"""
        pushed = apply_transform(content, "push", Path("benchbox/cli/commands/__init__.py"))
        assert "from .explorer import explorer_group" not in pushed
        assert "    explorer_group," not in pushed
        assert '"explorer_group"' not in pushed

        pulled = apply_transform(pushed, "pull", Path("benchbox/cli/commands/__init__.py"))
        assert "from .explorer import explorer_group" in pulled
        assert "    explorer_group," in pulled
        assert '"explorer_group"' in pulled

    def test_test_workflow_push_and_pull_transform(self):
        """Public test workflow should guard the parity job when explorer is absent."""
        content = """name: Tests

jobs:
  parity:
    runs-on: ubuntu-latest
    steps:
      - run: npm ci
        working-directory: results-explorer

  test:
    runs-on: ubuntu-latest
    steps:
      - run: uv run -- python -m pytest -m fast -q
"""
        pushed = apply_transform(content, "push", Path(".github/workflows/test.yml"))
        assert "if: ${{ hashFiles('results-explorer/package.json') != '' }}" in pushed

        pulled = apply_transform(pushed, "pull", Path(".github/workflows/test.yml"))
        assert "if: ${{ hashFiles('results-explorer/package.json') != '' }}" not in pulled

    def test_pytest_ini_push_and_pull_transform(self):
        """Public pytest configs should drop the private xdist safety plugin line."""
        content = """[pytest]
addopts =
    -p _benchbox_pytest_xdist_safety
    --strict-markers
"""
        pushed = apply_transform(content, "push", Path("pytest.ini"))
        assert "_benchbox_pytest_xdist_safety" not in pushed

        pulled = apply_transform(pushed, "pull", Path("pytest.ini"))
        assert "_benchbox_pytest_xdist_safety" in pulled


class TestPyprojectPrivateLines:
    """Test stripping/restoring private-only pyproject.toml lines."""

    # Minimal pyproject.toml fragment that includes all three private blocks.
    PRIVATE_CONTENT = """\
[tool.setuptools.packages.find]
include = ["benchbox*"]
exclude = [
    "benchmark_runs",
    "benchmark_runs.*",
    # benchbox.release contains internal release tooling \u2014 never ship in the default wheel.
    "benchbox.release",
    "benchbox.release.*",
    # benchbox.experimental is intentionally INCLUDED in the default wheel (Option A, Beta contract).
]

[tool.ruff.lint.pylint]
max-complexity = 20
allowed-complexity = [
    "benchbox/cli/commands/export.py:export",                          # 22
    "benchbox/release/sync.py:cmd_pull",                               # 25 \u2014 auditable safety-check workflow
    "benchbox/release/sync.py:cmd_push",                               # 22 \u2014 mirror of cmd_pull
    "benchbox/cli/commands/shell.py:_launch_sqlite_shell",             # 16
    "benchbox/platforms/snowflake.py:apply_table_tunings",            # 13
    "benchbox/release/content_validation.py:_is_example_line",        # 13 \u2014 heuristic classifier must combine marker, table, bullet, and blockquote context
    "benchbox/utils/execution_manager.py:execute_power_runs",         # 13
]
"""

    PUBLIC_EXPECTED_LINES = [
        "benchmark_runs.*",
        "# benchbox.experimental",
        "benchbox/cli/commands/export.py:export",
        "benchbox/cli/commands/shell.py:_launch_sqlite_shell",
        "benchbox/platforms/snowflake.py:apply_table_tunings",
        "benchbox/utils/execution_manager.py:execute_power_runs",
    ]

    ABSENT_IN_PUBLIC = [
        "benchbox.release",
        "benchbox/release/sync.py",
        "benchbox/release/content_validation.py",
    ]

    def test_strip_removes_all_private_lines(self):
        """Push direction removes every benchbox.release reference."""
        result = _strip_private_pyproject_lines(self.PRIVATE_CONTENT)
        for fragment in self.ABSENT_IN_PUBLIC:
            assert fragment not in result, f"'{fragment}' should be stripped"

    def test_strip_preserves_public_lines(self):
        """Push direction keeps all non-private lines."""
        result = _strip_private_pyproject_lines(self.PRIVATE_CONTENT)
        for fragment in self.PUBLIC_EXPECTED_LINES:
            assert fragment in result, f"'{fragment}' should be preserved"

    def test_restore_inserts_after_anchors(self):
        """Pull direction restores private lines in the correct positions."""
        stripped = _strip_private_pyproject_lines(self.PRIVATE_CONTENT)
        restored = _restore_private_pyproject_lines(stripped)
        for _anchor, block in PYPROJECT_PRIVATE_BLOCKS:
            for line in block:
                assert line.strip() in restored, f"'{line.strip()}' should be restored"

    def test_round_trip_preserves_content(self):
        """Strip then restore is a no-op on content with the private lines."""
        stripped = _strip_private_pyproject_lines(self.PRIVATE_CONTENT)
        restored = _restore_private_pyproject_lines(stripped)
        # All original lines present (order preserved)
        for line in self.PRIVATE_CONTENT.splitlines():
            if line.strip():
                assert line.strip() in restored

    def test_restore_is_idempotent(self):
        """Restoring content that already has private lines does not duplicate."""
        restored = _restore_private_pyproject_lines(self.PRIVATE_CONTENT)
        for _anchor, block in PYPROJECT_PRIVATE_BLOCKS:
            for line in block:
                assert restored.count(line.strip()) == 1

    def test_apply_transform_push_strips_private_lines(self):
        """apply_transform(push) strips private pyproject lines."""
        result = apply_transform(self.PRIVATE_CONTENT, "push")
        for fragment in self.ABSENT_IN_PUBLIC:
            assert fragment not in result

    def test_apply_transform_pull_restores_private_lines(self):
        """apply_transform(pull) restores private pyproject lines."""
        pushed = apply_transform(self.PRIVATE_CONTENT, "push")
        pulled = apply_transform(pushed, "pull")
        for _anchor, block in PYPROJECT_PRIVATE_BLOCKS:
            for line in block:
                assert line.strip() in pulled

    def test_private_blocks_anchors_exist_in_pyproject(self):
        """Every anchor in PYPROJECT_PRIVATE_BLOCKS must exist in pyproject.toml."""
        pyproject = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
        for anchor, _block in PYPROJECT_PRIVATE_BLOCKS:
            assert anchor in pyproject, f"Anchor '{anchor}' not found in pyproject.toml"

    def test_private_blocks_lines_exist_in_pyproject(self):
        """Every private line in PYPROJECT_PRIVATE_BLOCKS must exist in pyproject.toml."""
        pyproject = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
        for _anchor, block in PYPROJECT_PRIVATE_BLOCKS:
            for line in block:
                assert line.strip() in pyproject, f"Private line not found: {line.strip()}"


class TestGitignoreTransform:
    """Test gitignore transformation for sync."""

    def test_gitignore_push_removes_private_sections(self):
        """Test that push removes private-only sections from gitignore."""
        gitignore_content = """# Python
__pycache__/
*.pyc

# Exclude everything in _project/ except TODO files
_project/*
!_project/specs/
!_project/TODO/

# Virtual Environments
venv/
.venv/

# Firebolt data and core data directories
/firebolt-data
/firebolt-core-data

# IDE specific
.idea/
"""
        result = apply_transform(gitignore_content, "push", Path(".gitignore"))

        # Should keep Python and Virtual Environments sections
        assert "__pycache__/" in result
        assert "venv/" in result
        assert ".idea/" in result

        # Should remove _project section
        assert "_project/*" not in result
        assert "!_project/specs/" not in result

        # Should remove Firebolt section
        assert "/firebolt-data" not in result
        assert "/firebolt-core-data" not in result

    def test_gitignore_push_removes_private_lines(self):
        """Test that push removes individual private-only lines."""
        gitignore_content = """# Python
__pycache__/
.mcp.json
_sources/join-order-benchmark/
*.pyc
"""
        result = apply_transform(gitignore_content, "push", Path(".gitignore"))

        # Should keep normal patterns
        assert "__pycache__/" in result
        assert "*.pyc" in result

        # Should remove private lines
        assert ".mcp.json" not in result
        assert "_sources/join-order-benchmark/" not in result

    def test_gitignore_pull_unchanged(self):
        """Test that pull returns gitignore unchanged."""
        gitignore_content = """# Public gitignore
__pycache__/
*.pyc
"""
        result = apply_transform(gitignore_content, "pull", Path(".gitignore"))
        assert result == gitignore_content

    def test_gitignore_removes_consecutive_blank_lines(self):
        """Test that consecutive blank lines are cleaned up."""
        gitignore_content = """# Python
__pycache__/

# Exclude everything in _project/
_project/*


# IDE specific
.idea/
"""
        result = apply_transform(gitignore_content, "push", Path(".gitignore"))

        # Should not have multiple consecutive blank lines
        assert "\n\n\n" not in result

    def test_should_transform_includes_gitignore(self):
        """Test that should_transform returns True for .gitignore."""
        assert should_transform(Path(".gitignore"))
        assert should_transform(Path("some/path/.gitignore"))

    def test_gitignore_private_sections_defined(self):
        """Test that GITIGNORE_PRIVATE_SECTIONS is properly defined."""
        assert len(GITIGNORE_PRIVATE_SECTIONS) > 0
        # Check for key sections
        section_texts = " ".join(GITIGNORE_PRIVATE_SECTIONS)
        assert "_project" in section_texts.lower()
        assert "firebolt" in section_texts.lower()

    def test_gitignore_private_lines_defined(self):
        """Test that GITIGNORE_PRIVATE_LINES is properly defined."""
        assert len(GITIGNORE_PRIVATE_LINES) > 0
        assert ".mcp.json" in GITIGNORE_PRIVATE_LINES


class TestShouldTransform:
    """Test should_transform() function."""

    def test_pyproject_should_transform(self):
        """Test that pyproject.toml needs transform."""
        assert should_transform(Path("pyproject.toml"))
        assert should_transform(Path("some/path/pyproject.toml"))
        assert should_transform(Path("pytest.ini"))
        assert should_transform(Path("pytest-ci.ini"))
        assert should_transform(Path("benchbox/cli/commands/__init__.py"))
        assert should_transform(Path(".github/workflows/test.yml"))

    def test_other_files_should_not_transform(self):
        """Test that other files don't need transform."""
        assert not should_transform(Path("README.md"))
        assert not should_transform(Path("benchbox/__init__.py"))
        assert not should_transform(Path("tests/test_foo.py"))


class TestExclusionConstants:
    """Test that exclusion constants are properly defined."""

    def test_allowed_root_files_not_empty(self):
        """Test that ALLOWED_ROOT_FILES is defined and not empty."""
        assert len(ALLOWED_ROOT_FILES) > 0
        assert "README.md" in ALLOWED_ROOT_FILES
        assert "benchbox" in ALLOWED_ROOT_FILES

    def test_global_excludes_includes_pycache(self):
        """Test that GLOBAL_EXCLUDES includes __pycache__."""
        assert "__pycache__" in GLOBAL_EXCLUDES

    def test_docs_excludes_includes_build(self):
        """Test that DOCS_DIR_EXCLUDES includes _build."""
        assert "_build" in DOCS_DIR_EXCLUDES

    def test_claude_and_codex_not_in_allowed_roots(self):
        """Test that .claude, .codex, CLAUDE.md, AGENTS.md are excluded from public release."""
        assert ".claude" not in ALLOWED_ROOT_FILES
        assert ".codex" not in ALLOWED_ROOT_FILES
        assert "CLAUDE.md" not in ALLOWED_ROOT_FILES
        assert "AGENTS.md" not in ALLOWED_ROOT_FILES

    def test_forbidden_patterns_includes_data_files(self):
        """Test that FORBIDDEN_PATTERNS includes data file extensions."""
        assert "*.dat" in FORBIDDEN_PATTERNS
        assert "*.tbl" in FORBIDDEN_PATTERNS

    def test_tests_excludes_includes_databases(self):
        """Test that TESTS_DIR_EXCLUDES includes databases."""
        assert "databases" in TESTS_DIR_EXCLUDES


class TestSymlinkHandling:
    """Test symlink handling in sync functions."""

    def test_symlinks_are_skipped_in_syncable_files(self, tmp_path: Path):
        """Test that symlinks are not included in syncable files.

        Symlinks could point outside the repo or create cycles, so they
        should be skipped to avoid security issues and infinite loops.
        """
        import os

        # Create a regular file
        (tmp_path / "benchbox").mkdir()
        (tmp_path / "benchbox" / "real_file.py").write_text("# real")

        # Create a symlink
        symlink_path = tmp_path / "benchbox" / "link_to_file.py"
        try:
            os.symlink(tmp_path / "benchbox" / "real_file.py", symlink_path)
        except OSError:
            # Skip test on systems that don't support symlinks (e.g., some Windows configs)
            import pytest

            pytest.skip("Symlinks not supported on this system")

        result = get_syncable_files(tmp_path)

        # Real file should be included
        assert Path("benchbox/real_file.py") in result
        # Symlink should be skipped (it's not a regular file)
        assert Path("benchbox/link_to_file.py") not in result

    def test_directory_symlinks_are_not_followed(self, tmp_path: Path):
        """Test that directory symlinks are not followed (avoids cycles)."""
        import os

        # Create a directory with a file
        (tmp_path / "benchbox").mkdir()
        (tmp_path / "benchbox" / "subdir").mkdir()
        (tmp_path / "benchbox" / "subdir" / "file.py").write_text("# file")

        # Create a symlink to the parent (would create a cycle)
        symlink_dir = tmp_path / "benchbox" / "cycle_link"
        try:
            os.symlink(tmp_path / "benchbox", symlink_dir)
        except OSError:
            import pytest

            pytest.skip("Symlinks not supported on this system")

        result = get_syncable_files(tmp_path)

        # Real file should be included
        assert Path("benchbox/subdir/file.py") in result
        # Files through symlink should not be included
        cycle_files = [p for p in result if "cycle_link" in str(p)]
        assert len(cycle_files) == 0, f"Found files through symlink: {cycle_files}"


class TestRepoComparisonClass:
    """Test RepoComparison class directly."""

    def test_initialization(self):
        """Test RepoComparison can be initialized."""
        comparison = RepoComparison(
            added={Path("a.py")},
            modified={Path("b.py")},
            deleted={Path("c.py")},
            conflicts={Path("d.py")},
            unchanged={Path("e.py")},
        )

        assert Path("a.py") in comparison.added
        assert Path("b.py") in comparison.modified
        assert Path("c.py") in comparison.deleted
        assert Path("d.py") in comparison.conflicts
        assert Path("e.py") in comparison.unchanged

    def test_has_changes_with_added(self):
        """Test has_changes is True when files are added."""
        comparison = RepoComparison(
            added={Path("a.py")},
            modified=set(),
            deleted=set(),
            conflicts=set(),
            unchanged=set(),
        )
        assert comparison.has_changes

    def test_has_changes_with_deleted(self):
        """Test has_changes is True when files are deleted."""
        comparison = RepoComparison(
            added=set(),
            modified=set(),
            deleted={Path("a.py")},
            conflicts=set(),
            unchanged=set(),
        )
        assert comparison.has_changes

    def test_has_conflicts_property(self):
        """Test has_conflicts property."""
        comparison = RepoComparison(
            added=set(),
            modified=set(),
            deleted=set(),
            conflicts={Path("a.py")},
            unchanged=set(),
        )
        assert comparison.has_conflicts

        comparison_no_conflict = RepoComparison(
            added=set(),
            modified=set(),
            deleted=set(),
            conflicts=set(),
            unchanged=set(),
        )
        assert not comparison_no_conflict.has_conflicts


class TestCleanupUnwantedFiles:
    """Test _cleanup_unwanted_files() function."""

    def test_removes_venv_directory(self, tmp_path: Path):
        """Test that .venv directory is removed."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("test")

        _cleanup_unwanted_files(tmp_path)

        assert not venv.exists()

    def test_removes_ruff_cache(self, tmp_path: Path):
        """Test that .ruff_cache directory is removed."""
        ruff = tmp_path / ".ruff_cache"
        ruff.mkdir()
        (ruff / "cache.json").write_text("{}")

        _cleanup_unwanted_files(tmp_path)

        assert not ruff.exists()

    def test_preserves_dist_directory(self, tmp_path: Path):
        """Test that dist directory is preserved for no-clean release targets."""
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "package.whl").write_text("fake wheel")

        _cleanup_unwanted_files(tmp_path)

        assert dist.exists()

    def test_preserves_egg_info(self, tmp_path: Path):
        """Test that benchbox.egg-info is preserved for no-clean release targets."""
        egg = tmp_path / "benchbox.egg-info"
        egg.mkdir()
        (egg / "PKG-INFO").write_text("test")

        _cleanup_unwanted_files(tmp_path)

        assert egg.exists()

    def test_preserves_allowed_files(self, tmp_path: Path):
        """Test that allowed files are not removed."""
        # Create files that should be preserved
        readme = tmp_path / "README.md"
        readme.write_text("# Test")
        benchbox = tmp_path / "benchbox"
        benchbox.mkdir()
        (benchbox / "__init__.py").write_text("# init")

        # Create file that should be removed
        venv = tmp_path / ".venv"
        venv.mkdir()

        _cleanup_unwanted_files(tmp_path)

        # Allowed files still exist
        assert readme.exists()
        assert benchbox.exists()
        # Unwanted file removed
        assert not venv.exists()

    def test_cleanup_patterns_are_comprehensive(self):
        """Test that CLEANUP_PATTERNS includes common dev artifacts."""
        expected_patterns = {
            ".venv",
            "venv",
            ".ruff_cache",
            "*.egg-info",
            "node_modules",
            ".mypy_cache",
            ".pytest_cache",
            "__pycache__",
            ".coverage",
            "htmlcov",
            ".tox",
            ".nox",
            "dist",
            "build",
            # Note: 'landing' is NOT in cleanup patterns because it's in
            # ALLOWED_ROOT_FILES for GitHub Pages marketing site
            # Always rebuilt from whitelist to prevent stale accumulation
            "_sources",
            "_project",
            "benchmark_runs",
            ".claude",
            ".codex",
        }
        assert set(CLEANUP_PATTERNS) == expected_patterns

    def test_handles_nonexistent_target(self, tmp_path: Path):
        """Test that cleanup handles non-existent target gracefully."""
        nonexistent = tmp_path / "does_not_exist"
        # Should not raise
        _cleanup_unwanted_files(nonexistent)
