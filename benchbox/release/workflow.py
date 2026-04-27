"""Release preparation workflow utilities.

These helpers construct a curated copy of the repository suitable for public
publication. They trim held-back features, remove development artefacts, and
apply sanitized documentation so the public artefact only exposes supported
benchmarks and platforms.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

# HOLD_BACK_PATHS: paths that must NEVER appear on the public repo
# (joeharris76/BenchBox), on either the main or develop branch.
#
# Under the two-branch model (see _project/decisions/single-repo-migration.md):
# - develop carries the full dev tree (everything except per-user agent configs).
# - main carries only the released-code subset.
# - Per-user agent configs and credentials never reach either branch.
#
# The previous list (release scripts, explorer code, release-tooling tests,
# explorer docs) is moot under the new model: those paths now live on develop
# as ordinary dev content. The release-prepare Makefile target curates the
# develop → release-branch tree separately by removing develop-only paths
# (_project/, _blog/, agent configs, dev-tooling root files).
HOLD_BACK_PATHS: Sequence[str] = (
    ".claude",  # per-user agent config (Claude Code workspace)
    ".codex",  # per-user agent config (Codex)
    ".gemini",  # per-user agent config (Gemini)
    # Specific secrets / .env files belong here if introduced.
)

CLI_INIT_PRIVATE_BLOCKS: Sequence[tuple[str, tuple[str, ...]]] = (
    (
        "from .download_answers import download_answers",
        ("from .explorer import explorer_group",),
    ),
    (
        "    df_tuning_group,  # Deprecated: hidden, kept for backwards compatibility",
        ("    explorer_group,",),
    ),
    (
        '    "df_tuning_group",',
        ('    "explorer_group",',),
    ),
)

TEST_WORKFLOW_PARITY_GUARD = "    if: ${{ hashFiles('results-explorer/package.json') != '' }}"

PYTEST_PRIVATE_BLOCKS: Sequence[tuple[str, tuple[str, ...]]] = (
    (
        "addopts =",
        ("    -p _benchbox_pytest_xdist_safety",),
    ),
)

# ALLOWED_ROOT_FILES: top-level entries that are part of the public dev tree.
#
# Under the two-branch model, the develop branch on public carries this full
# list plus the develop-only additions below (_project/, _blog/, agent
# instructions, dev tooling). The release-prepare flow curates develop's tree
# down to just the items listed here when cutting the release branch for main.
ALLOWED_ROOT_FILES: Sequence[str] = (
    # Released-code essentials (kept on main and develop)
    ".gitignore",  # Synced with transformation to remove private-only patterns
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "COPYRIGHT.md",
    "DISCLAIMER.md",
    "LICENSE",
    "pyproject.toml",
    "MANIFEST.in",
    "README.md",
    "scripts",
    "benchbox",
    "tests",
    "docs",
    "examples",
    "pytest.ini",
    "pytest-ci.ini",
    "Makefile",
    "uv.lock",
    # GitHub configuration (workflows, issue templates, PR templates)
    ".github",
    # Precompiled TPC binaries for data generation
    "_binaries",
    # TPC source templates for query generation (queries/*.sql, variants/*.sql)
    "_sources",
    # CI/Linting configuration
    ".codespell-ignore.txt",
    # Landing page for GitHub Pages (index.html, style.css, etc.)
    "landing",
    # Develop-only entries (curated out at release-prepare time):
    # - _project/, _blog/: maintainer scaffolding (TODO/DONE/decisions, blog drafts/published).
    # - CLAUDE.md, AGENTS.md, GEMINI.md: agent instructions; project-wide.
    # - .pre-commit-config.yaml, _benchbox_pytest_xdist_safety.py: dev tooling.
    # - todo.config.yaml, skill-sync.yaml, skill-sync.lock: TODO/skill-sync configs.
    # - .coveragerc_core, .dockerignore, .env.example, .mcp.json: meta-files.
    "_project",
    "_blog",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    ".pre-commit-config.yaml",
    "_benchbox_pytest_xdist_safety.py",
    "todo.config.yaml",
    "skill-sync.yaml",
    "skill-sync.lock",
    ".coveragerc_core",
    ".dockerignore",
    ".env.example",
    ".mcp.json",
)

# Files to exclude when copying docs directory
DOCS_DIR_EXCLUDES: Sequence[str] = (
    "_build",  # Built documentation (68MB+)
    "_tags",  # Generated tag pages
    "site",  # Alternative build output
)

# Files to exclude when copying tests directory
TESTS_DIR_EXCLUDES: Sequence[str] = (
    "databases",  # Test database creation scripts (gitignored in public repo)
)

# Specific paths to include from _sources directory (whitelist approach)
# The _sources directory contains build artifacts and data files that should not
# be included in releases. Only query templates needed for qgen/dsqgen are included.
_SOURCES_INCLUDE_PATHS: Sequence[str] = (
    # Top-level documentation
    "README.md",
    # Compilation infrastructure (for users who need to build from source)
    "compilation",
    # TPC-H query templates (required for qgen)
    "tpc-h/dbgen/queries",  # 22 SQL template files
    "tpc-h/dbgen/variants",  # 5 variant SQL files
    "tpc-h/dbgen/dists.dss",  # Distribution specifications for qgen
    # TPC-H answer files (for validation tests)
    "tpc-h/dbgen/answers",
    # TPC-H patch documentation
    "tpc-h/PATCHES.md",
    "tpc-h/stdout-support.patch",
    # TPC-DS query templates (required for dsqgen)
    "tpc-ds/query_templates",  # Template files (*.tpl, *.lst)
    "tpc-ds/query_variants",  # Variant template files (*.tpl)
    # TPC-DS answer sets (for validation tests)
    "tpc-ds/answer_sets",
    # TPC-DS patch documentation
    "tpc-ds/PATCHES.md",
    "tpc-ds/stdout-support.patch",
)

# Global patterns to exclude from all directories
GLOBAL_EXCLUDES: Sequence[str] = (
    "__pycache__",
    "*.pyc",
    ".DS_Store",
)

# Directories/files that should be REMOVED from target if they exist
# These are development/build artifacts that should never be in releases
# Applied when --no-clean is used to preserve the target directory
CLEANUP_PATTERNS: Sequence[str] = (
    ".venv",  # Python virtual environment (can be 1GB+)
    "venv",  # Alternative venv name
    ".ruff_cache",  # Ruff linter cache
    "*.egg-info",  # Python package metadata
    "node_modules",  # Node.js dependencies
    ".mypy_cache",  # Mypy type checker cache
    ".pytest_cache",  # Pytest cache
    "__pycache__",  # Python bytecode cache
    ".coverage",  # Coverage data
    "htmlcov",  # Coverage HTML reports
    ".tox",  # Tox environments
    ".nox",  # Nox environments
    "dist",  # Build output (created fresh by build step)
    "build",  # Build output
    "_sources",  # Always rebuild from whitelist to prevent stale accumulation
    "_project",  # Development-only working files
    "benchmark_runs",  # Execution outputs (should never be in releases)
    ".claude",  # Claude Code configuration (private dev workflows)
    ".codex",  # Codex configuration (private dev workflows)
)


# pyproject.toml transformations for public release
# Maps private values to public values
PYPROJECT_SUBSTITUTIONS: dict[str, str] = {
    # Use public contact email instead of personal
    "joeharris76@gmail.com": "joe@benchbox.dev",
}

# Lines in pyproject.toml that exist only in the private repo because
# benchbox.release is held back from public via HOLD_BACK_PATHS.
# Each tuple: (anchor_line_stripped, lines_to_insert_after_anchor).
# On push/release: lines are stripped.  On pull: lines are restored after anchor.
PYPROJECT_PRIVATE_BLOCKS: Sequence[tuple[str, tuple[str, ...]]] = (
    (
        '"benchmark_runs.*",',
        (
            "    # benchbox.release contains internal release tooling \u2014 never ship in the default wheel.",
            '    "benchbox.release",',
            '    "benchbox.release.*",',
        ),
    ),
    (
        '"benchbox/cli/commands/export.py:export",',
        (
            '    "benchbox/release/sync.py:cmd_pull",                               # 25 \u2014 auditable safety-check workflow',
            '    "benchbox/release/sync.py:cmd_push",                               # 22 \u2014 mirror of cmd_pull',
        ),
    ),
    (
        '"benchbox/platforms/snowflake.py:apply_table_tunings",',
        (
            '    "benchbox/release/content_validation.py:_is_example_line",        # 13 \u2014 heuristic classifier must combine marker, table, bullet, and blockquote context',
        ),
    ),
)

# Gitignore sections to remove when syncing to public repo
# These are private-only patterns that don't apply to public users
# Sections are identified by their comment headers (removes until next section or EOF)
GITIGNORE_PRIVATE_SECTIONS: Sequence[str] = (
    "# Exclude everything in _project/",
    "# Firebolt data and core data directories",
)

# Individual gitignore lines to remove (exact match after stripping whitespace)
GITIGNORE_PRIVATE_LINES: Sequence[str] = (
    "_sources/join-order-benchmark/",
    ".mcp.json",
)


def _resolve_source_path(source: Path, relative: str) -> Path:
    path = source / relative
    if not path.exists():
        raise FileNotFoundError(f"Required file '{relative}' not found in {source}")
    return path


def calculate_release_timestamp() -> tuple[int, str, str]:
    """Calculate the most recent whole hour in UTC.

    This ensures all release artifacts have consistent, predictable timestamps
    that don't reveal the exact creation time. The current UTC time is truncated
    to the top of the hour.

    Returns:
        tuple[int, str, str]: (unix_timestamp, iso_format, git_format)
            - unix_timestamp: Seconds since epoch (for SOURCE_DATE_EPOCH and os.utime)
            - iso_format: ISO 8601 format (YYYY-MM-DDTHH:MM:SS+00:00)
            - git_format: Git-compatible format (YYYY-MM-DD HH:MM:SS +0000)

    Example:
        If now is 2025-01-07T14:37:22 UTC, this returns:
        - 2025-01-07T14:00:00 UTC (truncated to the hour)
    """
    now = datetime.now(timezone.utc)
    truncated = now.replace(minute=0, second=0, microsecond=0)

    # Generate all three formats
    unix_ts = int(truncated.timestamp())
    iso_fmt = truncated.isoformat()
    git_fmt = truncated.strftime("%Y-%m-%d %H:%M:%S %z")

    return unix_ts, iso_fmt, git_fmt


def _copy_with_excludes(src: Path, dest: Path, excludes: Iterable[str]) -> None:
    patterns = tuple(excludes)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*patterns))


def _cleanup_unwanted_files(target: Path) -> None:
    """Remove unwanted development/build artifacts from target directory.

    This is called when --no-clean is used to preserve existing files,
    but we still need to remove files that should never be in releases.

    Args:
        target: Target directory to clean up
    """
    import fnmatch

    if not target.exists():
        return

    preserve = {"dist", "build", "benchbox.egg-info"}
    for entry in target.iterdir():
        name = entry.name
        if name in preserve:
            continue
        should_remove = False

        for pattern in CLEANUP_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                should_remove = True
                break

        if should_remove:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()


def _sanitize_target_root(target: Path) -> None:
    """Remove stale root entries that are not part of the curated release tree."""
    if not target.exists():
        return

    preserve = set(ALLOWED_ROOT_FILES) | {".git", "dist", "build", "benchbox.egg-info"}
    for entry in target.iterdir():
        if entry.name in preserve:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _copy_sources_selective(source: Path, target: Path) -> None:
    """Selectively copy only whitelisted paths from _sources directory.

    The _sources directory contains many build artifacts, object files, and data
    files that should not be included in releases. This function copies only the
    specific template directories needed for query generation.

    Args:
        source: Source _sources directory
        target: Target _sources directory in release tree
    """
    for include_path in _SOURCES_INCLUDE_PATHS:
        src_path = source / include_path
        dest_path = target / include_path

        if not src_path.exists():
            continue

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_file():
            shutil.copy2(src_path, dest_path)
        elif src_path.is_dir():
            # Copy directory with global excludes only
            _copy_with_excludes(src_path, dest_path, GLOBAL_EXCLUDES)


def _normalize_timestamps(path: Path, timestamp: int) -> None:
    """Normalize all file timestamps to a specific unix timestamp.

    This recursively sets modification and access times for all files and
    directories to the provided timestamp, ensuring no trace of actual
    creation/modification times remains in the release artifacts.

    Args:
        path: Root directory to normalize
        timestamp: Unix timestamp (seconds since epoch) to set for all files
    """
    for entry in path.rglob("*"):
        if entry.exists():
            os.utime(entry, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def _apply_transformed_gitignore(source: Path, target: Path) -> None:
    """Read, transform, and write .gitignore for public release.

    Removes private-only sections and patterns from the gitignore file.

    Args:
        source: Source repository root containing .gitignore
        target: Target directory where transformed file will be written
    """
    source_file = source / ".gitignore"
    if not source_file.exists():
        return  # No gitignore to transform

    content = source_file.read_text(encoding="utf-8")
    transformed = apply_transform(content, "push", Path(".gitignore"))
    (target / ".gitignore").write_text(transformed, encoding="utf-8")


def _apply_transformed_cli_init(source: Path, target: Path) -> None:
    relative_path = Path("benchbox/cli/commands/__init__.py")
    source_file = source / relative_path
    if not source_file.exists():
        return

    transformed = apply_transform(source_file.read_text(encoding="utf-8"), "push", relative_path)
    target_file = target / relative_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(transformed, encoding="utf-8")


def _apply_transformed_test_workflow(source: Path, target: Path) -> None:
    relative_path = Path(".github/workflows/test.yml")
    source_file = source / relative_path
    if not source_file.exists():
        return

    transformed = apply_transform(source_file.read_text(encoding="utf-8"), "push", relative_path)
    target_file = target / relative_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(transformed, encoding="utf-8")


def _apply_transformed_pytest_config(source: Path, target: Path, relative_path: Path) -> None:
    source_file = source / relative_path
    if not source_file.exists():
        return

    transformed = apply_transform(source_file.read_text(encoding="utf-8"), "push", relative_path)
    target_file = target / relative_path
    target_file.write_text(transformed, encoding="utf-8")


def _initialize_git_repo(target: Path) -> None:
    subprocess.run(["git", "init"], cwd=target, check=True)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)


def _copy_root_files(source: Path, target: Path, allowed: Sequence[str]) -> None:
    for item in allowed:
        src_path = source / item
        if not src_path.exists():
            continue
        dest_path = target / item
        if src_path.is_dir():
            # Handle _sources specially - use whitelist instead of blacklist
            if item == "_sources":
                _copy_sources_selective(src_path, dest_path)
                continue
            # Build exclusion list: global excludes + directory-specific excludes
            excludes: list[str] = list(GLOBAL_EXCLUDES)
            if item == "benchbox":
                excludes.extend(HOLD_BACK_PATHS)
            elif item == "docs":
                excludes.extend(DOCS_DIR_EXCLUDES)
            _copy_with_excludes(src_path, dest_path, excludes)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)


def _strip_private_block_lines(content: str, blocks: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    """Remove private-only lines identified by the provided block definitions."""
    private_lines: set[str] = set()
    for _anchor, lines in blocks:
        for line in lines:
            private_lines.add(line.strip())

    if not any(line.strip() in private_lines for line in content.splitlines()):
        return content

    ends_with_newline = content.endswith("\n")
    result_lines = [line for line in content.splitlines() if line.strip() not in private_lines]
    result = "\n".join(result_lines)
    if ends_with_newline:
        result += "\n"
    return result


def _restore_private_block_lines(content: str, blocks: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    """Restore private-only lines after their anchors when missing."""
    lines = content.splitlines()
    changed = False
    for anchor, block in blocks:
        if any(block[0].strip() == line.strip() for line in lines):
            continue
        for i, line in enumerate(lines):
            if anchor in line:
                for j, insert_line in enumerate(block):
                    lines.insert(i + 1 + j, insert_line)
                changed = True
                break
    if not changed:
        return content
    result = "\n".join(lines)
    if content.endswith("\n"):
        result += "\n"
    return result


def _strip_private_pyproject_lines(content: str) -> str:
    """Remove private-only lines from pyproject.toml content.

    Lines are identified by membership in PYPROJECT_PRIVATE_BLOCKS.
    Returns content unchanged if no private lines are present.
    """
    return _strip_private_block_lines(content, PYPROJECT_PRIVATE_BLOCKS)


def _restore_private_pyproject_lines(content: str) -> str:
    """Restore private-only lines into pyproject.toml content.

    Each block is inserted after its anchor line if the lines are missing.
    Returns content unchanged if all private lines are already present.
    """
    return _restore_private_block_lines(content, PYPROJECT_PRIVATE_BLOCKS)


def _transform_cli_init(content: str, direction: str) -> str:
    """Transform benchbox.cli.commands.__init__ for public/private sync."""
    if direction == "push":
        return _strip_private_block_lines(content, CLI_INIT_PRIVATE_BLOCKS)
    return _restore_private_block_lines(content, CLI_INIT_PRIVATE_BLOCKS)


def _transform_test_workflow(content: str, direction: str) -> str:
    """Guard the parity job in public copies when results-explorer is absent."""
    lines = content.splitlines()
    result_lines: list[str] = []
    in_parity_job = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            in_parity_job = stripped == "parity:"

        if in_parity_job and direction == "pull" and line == TEST_WORKFLOW_PARITY_GUARD:
            continue

        result_lines.append(line)

        if in_parity_job and direction == "push" and line == "    runs-on: ubuntu-latest":
            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line != TEST_WORKFLOW_PARITY_GUARD:
                result_lines.append(TEST_WORKFLOW_PARITY_GUARD)

    result = "\n".join(result_lines)
    if content.endswith("\n"):
        result += "\n"
    return result


def _transform_pytest_ini(content: str, direction: str) -> str:
    """Remove private-only pytest plugin wiring from public copies."""
    if direction == "push":
        return _strip_private_block_lines(content, PYTEST_PRIVATE_BLOCKS)
    return _restore_private_block_lines(content, PYTEST_PRIVATE_BLOCKS)


def _transform_pyproject(content: str) -> str:
    """Transform pyproject.toml content for public release.

    Strips private-only lines (benchbox.release references) and applies
    substitutions (e.g., email addresses). This eliminates the need for a
    separate public pyproject.toml file, ensuring tool configs stay in sync.

    Args:
        content: Original pyproject.toml content

    Returns:
        Transformed content suitable for public release
    """
    result = content

    # Strip lines that only exist in private repo
    result = _strip_private_pyproject_lines(result)

    # Apply all configured substitutions
    for private_val, public_val in PYPROJECT_SUBSTITUTIONS.items():
        result = result.replace(private_val, public_val)

    return result


def _apply_transformed_pyproject(source: Path, target: Path) -> None:
    """Read, transform, and write pyproject.toml for public release.

    Args:
        source: Source repository root containing pyproject.toml
        target: Target directory where transformed file will be written
    """
    source_file = source / "pyproject.toml"
    if not source_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {source}")

    content = source_file.read_text(encoding="utf-8")
    transformed = apply_transform(content, "push", Path("pyproject.toml"))
    (target / "pyproject.toml").write_text(transformed, encoding="utf-8")


def prepare_public_release(
    *,
    source: Path,
    target: Path,
    version: str,
    clean: bool = True,
    init_git: bool = False,
    extra_root_files: Sequence[str] | None = None,
    timestamp: int | None = None,
) -> None:
    """Create a curated copy of the repository for public release.

    Args:
        source: Root of the private repository.
        target: Output directory for the public-ready tree.
        version: Version string used for logging/tagging.
        clean: Remove the target directory before copying.
        init_git: Initialize a fresh git repository and stage files.
        extra_root_files: Additional paths (relative to source) to include.
        timestamp: Unix timestamp for normalizing file times. If None, uses
            the most recent whole hour UTC.
    """

    if not source.is_dir():
        raise ValueError(f"Source directory '{source}' does not exist")

    if clean and target.exists():
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)

    # Even when not cleaning the entire target, remove unwanted artifacts
    # that should never be in releases (e.g., .venv, .ruff_cache, etc.)
    if not clean:
        _cleanup_unwanted_files(target)
        _sanitize_target_root(target)

    root_files: list[str] = list(ALLOWED_ROOT_FILES)
    if extra_root_files:
        for extra in extra_root_files:
            _resolve_source_path(source, extra)
        root_files.extend(extra_root_files)

    _copy_root_files(source, target, root_files)

    # Ensure hold-back paths are definitely absent post-copy.
    for pattern in HOLD_BACK_PATHS:
        candidates = [target / pattern]
        if "/" not in pattern:
            candidates.append(target / "benchbox" / pattern)
        for path in candidates:
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    # Note: No longer applying sanitized README - public releases use the full README.md
    # Transform pyproject.toml in-place (substitutes email, keeps all tool configs in sync)
    _apply_transformed_pyproject(source, target)
    # Transform .gitignore in-place (removes private-only sections)
    _apply_transformed_gitignore(source, target)
    # Strip explorer-only CLI wiring from the public command registry.
    _apply_transformed_cli_init(source, target)
    # Guard the parity job when the explorer sources are held back.
    _apply_transformed_test_workflow(source, target)
    # Remove private-only pytest plugin wiring from public test configs.
    _apply_transformed_pytest_config(source, target, Path("pytest.ini"))
    _apply_transformed_pytest_config(source, target, Path("pytest-ci.ini"))

    # Calculate or use provided timestamp for normalization
    if timestamp is None:
        timestamp, _, _ = calculate_release_timestamp()

    _normalize_timestamps(target, timestamp)

    (target / "RELEASE_VERSION").write_text(version + "\n", encoding="utf-8")

    if init_git:
        _initialize_git_repo(target)


# Default size limits for release safety checks
DEFAULT_MAX_FILE_SIZE_MB = 10  # Individual file limit
DEFAULT_MAX_TOTAL_SIZE_MB = 100  # Total release size limit (excluding .git)

# File patterns that are never allowed in releases (generated data, etc.)
FORBIDDEN_PATTERNS: Sequence[str] = (
    "*.dat",  # TPC generated data files
    "*.tbl",  # TPC table files
    "*.csv",  # Data files (except explicitly allowed)
    "*.parquet",  # Data files
    "*.db",  # Database files
    "*.duckdb",  # DuckDB files
)

# Paths exempt from forbidden pattern checks (relative to release root)
# These are intentional sample/example data files
ALLOWED_DATA_PATHS: Sequence[str] = (
    "benchbox/data/coffeeshop",  # Sample data for examples
    "benchbox/core/flightdata/reference_data",  # Runtime airline/airport lookup tables
    "docs/development",  # Development-time survey and inventory CSVs
)


class ReleaseSizeViolation:
    """Represents a file size violation in the release."""

    def __init__(self, path: Path, size_bytes: int, reason: str):
        self.path = path
        self.size_bytes = size_bytes
        self.size_mb = size_bytes / (1024 * 1024)
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.path}: {self.size_mb:.2f} MB ({self.reason})"


def check_release_size(
    target: Path,
    *,
    max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB,
    max_total_size_mb: float = DEFAULT_MAX_TOTAL_SIZE_MB,
    check_forbidden_patterns: bool = True,
) -> tuple[bool, list[ReleaseSizeViolation], float]:
    """Check release directory for size violations and forbidden files.

    Args:
        target: Release directory to check
        max_file_size_mb: Maximum allowed size for individual files (MB)
        max_total_size_mb: Maximum allowed total size (MB)
        check_forbidden_patterns: Whether to check for forbidden file patterns

    Returns:
        tuple of (passed, violations, total_size_mb):
            - passed: True if all checks passed
            - violations: List of ReleaseSizeViolation objects
            - total_size_mb: Total size of release in MB
    """
    import fnmatch

    violations: list[ReleaseSizeViolation] = []
    total_size = 0
    max_file_bytes = max_file_size_mb * 1024 * 1024

    for entry in target.rglob("*"):
        # Skip .git directory
        if ".git" in entry.parts:
            continue

        if not entry.is_file():
            continue

        size = entry.stat().st_size
        total_size += size
        rel_path = entry.relative_to(target)

        # Check forbidden patterns (skip files in allowed data paths)
        if check_forbidden_patterns:
            rel_path_str = rel_path.as_posix()
            in_allowed_path = any(rel_path_str.startswith(allowed) for allowed in ALLOWED_DATA_PATHS)
            if not in_allowed_path:
                for pattern in FORBIDDEN_PATTERNS:
                    if fnmatch.fnmatch(entry.name, pattern):
                        violations.append(ReleaseSizeViolation(rel_path, size, f"forbidden pattern: {pattern}"))
                        break

        # Check individual file size
        if size > max_file_bytes:
            violations.append(ReleaseSizeViolation(rel_path, size, f"exceeds {max_file_size_mb}MB limit"))

    total_size_mb = total_size / (1024 * 1024)

    # Check total size
    if total_size_mb > max_total_size_mb:
        violations.insert(
            0,
            ReleaseSizeViolation(
                Path("."), int(total_size), f"total size {total_size_mb:.1f}MB exceeds {max_total_size_mb}MB limit"
            ),
        )

    passed = len(violations) == 0
    return passed, violations, total_size_mb


def _should_exclude_file(rel_path: Path, root_item: str) -> bool:
    """Check if a file should be excluded based on path and patterns.

    Args:
        rel_path: Path relative to repo root
        root_item: The root directory/file being processed (e.g., "docs", ".claude")

    Returns:
        True if the file should be excluded
    """
    import fnmatch

    parts = rel_path.parts
    name = rel_path.name

    # Check global excludes
    if _matches_global_excludes(name, parts, fnmatch):
        return True

    if _matches_hold_back_paths(rel_path):
        return True

    # Check directory-specific excludes
    if _matches_dir_specific_excludes(rel_path, root_item, name, parts):
        return True

    # Check forbidden patterns (data files that shouldn't be synced)
    rel_path_str = rel_path.as_posix()
    in_allowed_path = any(rel_path_str.startswith(allowed) for allowed in ALLOWED_DATA_PATHS)
    if not in_allowed_path:
        for pattern in FORBIDDEN_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True

    return False


def _matches_hold_back_paths(rel_path: Path) -> bool:
    """Check whether a relative path is held back from the public tree."""
    rel_str = rel_path.as_posix()
    for exclude in HOLD_BACK_PATHS:
        if rel_str.startswith(exclude) or exclude in rel_path.parts:
            return True
    return False


def _normalize_transform_path(file_path: Path) -> str:
    """Normalize a possibly prefixed relative path for transform dispatch."""
    normalized = file_path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _matches_global_excludes(name: str, parts: tuple, fnmatch) -> bool:
    """Check if a file matches any global exclude pattern."""
    for pattern in GLOBAL_EXCLUDES:
        if fnmatch.fnmatch(name, pattern):
            return True
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _matches_dir_specific_excludes(rel_path: Path, root_item: str, name: str, parts: tuple) -> bool:
    """Check directory-specific exclude lists based on root_item."""
    _dir_excludes = {
        "docs": DOCS_DIR_EXCLUDES,
        "tests": TESTS_DIR_EXCLUDES,
    }

    excludes = _dir_excludes.get(root_item)
    if excludes is not None:
        for exclude in excludes:
            if name == exclude or exclude in parts:
                return True
    elif root_item == "benchbox":
        rel_str = str(rel_path)
        for exclude in HOLD_BACK_PATHS:
            if rel_str.startswith(exclude) or exclude in parts:
                return True

    return False


def _get_sources_syncable_files(sources_path: Path, repo_root: Path) -> set[Path]:
    """Get syncable files from _sources using whitelist approach.

    Only files under _SOURCES_INCLUDE_PATHS are included.

    Args:
        sources_path: Path to _sources directory
        repo_root: Root directory of the repository

    Returns:
        Set of relative paths (from repo root) for files to sync
    """
    syncable: set[Path] = set()

    for include_path in _SOURCES_INCLUDE_PATHS:
        src_path = sources_path / include_path

        if not src_path.exists():
            continue

        if src_path.is_file() and not src_path.is_symlink():
            rel_path = src_path.relative_to(repo_root)
            syncable.add(rel_path)
        elif src_path.is_dir() and not src_path.is_symlink():
            for file_path in src_path.rglob("*"):
                if file_path.is_symlink():
                    continue
                if not file_path.is_file():
                    continue
                # Check global excludes only
                if any(file_path.name == excl or file_path.match(excl) for excl in GLOBAL_EXCLUDES):
                    continue
                rel_path = file_path.relative_to(repo_root)
                syncable.add(rel_path)

    return syncable


def get_syncable_files(repo_root: Path) -> set[Path]:
    """Get all files that should be synced between private and public repos.

    Uses ALLOWED_ROOT_FILES to determine which top-level items to include,
    then applies GLOBAL_EXCLUDES, directory-specific excludes (DOCS_DIR_EXCLUDES,
    TESTS_DIR_EXCLUDES), HOLD_BACK_PATHS, and FORBIDDEN_PATTERNS to filter files.

    The _sources directory uses a whitelist approach via _SOURCES_INCLUDE_PATHS
    since it contains many build artifacts that should not be synced.

    Symlinks are explicitly excluded to prevent:
    - Security issues from links pointing outside the repo
    - Infinite loops from circular symlinks
    - Inconsistent behavior across platforms

    Args:
        repo_root: Root directory of the repository

    Returns:
        Set of relative paths (from repo root) that should be synced
    """
    syncable: set[Path] = set()

    for root_item in ALLOWED_ROOT_FILES:
        item_path = repo_root / root_item
        if not item_path.exists():
            continue

        if item_path.is_file() and not item_path.is_symlink():
            # Single file at root level (not a symlink)
            syncable.add(Path(root_item))
        elif item_path.is_dir() and not item_path.is_symlink():
            # Handle _sources specially - use whitelist approach
            if root_item == "_sources":
                syncable.update(_get_sources_syncable_files(item_path, repo_root))
                continue
            # Directory - enumerate all files (skip symlinks)
            for file_path in item_path.rglob("*"):
                # Skip symlinks (both file and directory symlinks)
                if file_path.is_symlink():
                    continue
                if not file_path.is_file():
                    continue
                rel_path = file_path.relative_to(repo_root)
                if not _should_exclude_file(rel_path, root_item):
                    syncable.add(rel_path)

    return syncable


class RepoComparison:
    """Result of comparing two repositories."""

    def __init__(
        self,
        added: set[Path],
        modified: set[Path],
        deleted: set[Path],
        conflicts: set[Path],
        unchanged: set[Path],
    ):
        self.added = added  # In source, not in target
        self.modified = modified  # Differ between repos, only source changed
        self.deleted = deleted  # In target, not in source
        self.conflicts = conflicts  # Modified in both repos
        self.unchanged = unchanged  # Same content in both repos

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def summary(self) -> str:
        lines = []
        if self.added:
            lines.append(f"Added: {len(self.added)} files")
        if self.modified:
            lines.append(f"Modified: {len(self.modified)} files")
        if self.deleted:
            lines.append(f"Deleted: {len(self.deleted)} files")
        if self.conflicts:
            lines.append(f"Conflicts: {len(self.conflicts)} files")
        if not lines:
            lines.append("No changes")
        return ", ".join(lines)


def _get_file_hash(file_path: Path) -> str:
    """Get SHA256 hash of a file's contents."""
    import hashlib

    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_source_fingerprint(package_dir: Path) -> str:
    """Compute deterministic SHA256 fingerprint over all .py files in a package.

    Walks all .py files under the given directory, sorted by relative path,
    and produces a single hash combining each file's path and content hash.
    This fingerprint is independent of timestamps, permissions, or metadata.

    Args:
        package_dir: Path to the package directory (e.g., repo_root / "benchbox")

    Returns:
        Hex-encoded SHA256 fingerprint string
    """
    import hashlib

    combined = hashlib.sha256()
    for py_file in sorted(package_dir.rglob("*.py")):
        rel = py_file.relative_to(package_dir).as_posix()
        content_hash = hashlib.sha256(py_file.read_bytes()).hexdigest()
        combined.update(f"{rel}:{content_hash}\n".encode())
    return combined.hexdigest()


def _get_git_committed_hash(repo_path: Path, rel_path: Path) -> str | None:
    """Get the git blob hash for a file at HEAD.

    Returns None if the file is not tracked or repo has no commits.
    """
    try:
        result = subprocess.run(
            ["git", "ls-tree", "HEAD", str(rel_path)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            # Format: <mode> <type> <hash>\t<filename>
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                return parts[2]
    except subprocess.CalledProcessError:
        pass
    return None


def _get_git_working_hash(file_path: Path) -> str | None:
    """Get the git blob hash for a file's current working copy content.

    Uses git hash-object to compute what the blob hash would be for the file.
    """
    try:
        result = subprocess.run(
            ["git", "hash-object", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() if result.stdout.strip() else None
    except subprocess.CalledProcessError:
        return None


def compare_repos(
    source: Path,
    target: Path,
    *,
    check_conflicts: bool = True,
) -> RepoComparison:
    """Compare syncable files between source and target repositories.

    Detects:
    - Added: Files in source but not in target
    - Modified: Files that differ between repos
    - Deleted: Files in target but not in source (among syncable files)
    - Conflicts: Files modified in both repos (requires git)

    Args:
        source: Source repository root (e.g., private repo)
        target: Target repository root (e.g., public repo)
        check_conflicts: Whether to check for conflicts using git history

    Returns:
        RepoComparison with categorized file sets
    """
    source_files = get_syncable_files(source)
    # Use get_syncable_files for target too - this applies all the same exclusions
    target_files = get_syncable_files(target) if target.exists() else set()

    added: set[Path] = set()
    modified: set[Path] = set()
    deleted: set[Path] = set()
    conflicts: set[Path] = set()
    unchanged: set[Path] = set()

    # Files in source
    for rel_path in source_files:
        source_path = source / rel_path
        target_path = target / rel_path

        if not target_path.exists():
            added.add(rel_path)
        else:
            # Compare content
            source_hash = _get_file_hash(source_path)
            target_hash = _get_file_hash(target_path)

            if source_hash == target_hash:
                unchanged.add(rel_path)
            else:
                # Check for conflict (both modified from git baseline)
                if check_conflicts:
                    source_committed = _get_git_committed_hash(source, rel_path)
                    target_committed = _get_git_committed_hash(target, rel_path)

                    # Conflict if:
                    # - Both have git history
                    # - Target's committed version differs from current target
                    # - Source's committed version differs from current source
                    if source_committed and target_committed:
                        source_working = _get_git_working_hash(source_path)
                        target_working = _get_git_working_hash(target_path)
                        source_changed = source_committed != source_working
                        target_changed = target_committed != target_working
                        if source_changed and target_changed:
                            conflicts.add(rel_path)
                            continue

                modified.add(rel_path)

    # Files only in target (deleted from source)
    # Since both source_files and target_files use get_syncable_files(),
    # all exclusions are already applied
    for rel_path in target_files:
        if rel_path not in source_files:
            deleted.add(rel_path)

    return RepoComparison(
        added=added,
        modified=modified,
        deleted=deleted,
        conflicts=conflicts,
        unchanged=unchanged,
    )


def _transform_gitignore(content: str, direction: str) -> str:
    """Transform .gitignore content for sync.

    For push (private→public): Removes private-only sections and lines.
    For pull (public→private): Returns content unchanged (private patterns
    should be manually maintained in private repo).

    Args:
        content: .gitignore file content
        direction: "push" or "pull"

    Returns:
        Transformed content
    """
    if direction == "pull":
        # Don't modify gitignore on pull - private patterns are manually maintained
        return content

    # Push direction: remove private-only sections
    lines = content.split("\n")
    result_lines: list[str] = []
    skip_until_next_section = False

    for line in lines:
        stripped = line.strip()

        # Check if this line starts a section to skip
        for section_header in GITIGNORE_PRIVATE_SECTIONS:
            if stripped.startswith(section_header):
                skip_until_next_section = True
                break

        # Check if we've hit a new section (comment starting with #)
        # A new section header must: have text after #, not be a private section marker
        is_new_section = (
            skip_until_next_section
            and stripped.startswith("#")
            and len(stripped) > 1
            and stripped[1:].strip()
            and not any(stripped.startswith(s) for s in GITIGNORE_PRIVATE_SECTIONS)
        )
        if is_new_section:
            skip_until_next_section = False

        if skip_until_next_section:
            continue

        # Check if this is an individual line to remove
        if stripped in GITIGNORE_PRIVATE_LINES:
            continue

        result_lines.append(line)

    # Clean up multiple consecutive blank lines
    cleaned_lines: list[str] = []
    prev_blank = False
    for line in result_lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        cleaned_lines.append(line)
        prev_blank = is_blank

    # Remove trailing blank lines
    while cleaned_lines and not cleaned_lines[-1].strip():
        cleaned_lines.pop()

    return "\n".join(cleaned_lines) + "\n"


def apply_transform(content: str, direction: str, file_path: Path | None = None) -> str:
    """Apply transformations to file content for sync.

    Args:
        content: File content to transform
        direction: "push" (private→public) or "pull" (public→private)
        file_path: Optional path to determine file-specific transforms

    Returns:
        Transformed content

    Raises:
        ValueError: If direction is not "push" or "pull"
    """
    if direction not in ("push", "pull"):
        raise ValueError(f"Invalid direction '{direction}': must be 'push' or 'pull'")

    normalized_path = _normalize_transform_path(file_path) if file_path is not None else None

    # File-specific transforms
    if normalized_path is not None and normalized_path.endswith(".gitignore"):
        return _transform_gitignore(content, direction)
    if normalized_path is not None and normalized_path.endswith("benchbox/cli/commands/__init__.py"):
        return _transform_cli_init(content, direction)
    if normalized_path is not None and normalized_path.endswith(".github/workflows/test.yml"):
        return _transform_test_workflow(content, direction)
    if normalized_path in {"pytest.ini", "pytest-ci.ini"}:
        return _transform_pytest_ini(content, direction)

    # pyproject.toml: substitutions + private-only line handling
    result = content

    if direction == "push":
        # Strip private-only lines and apply substitutions for public
        result = _strip_private_pyproject_lines(result)
        for private_val, public_val in PYPROJECT_SUBSTITUTIONS.items():
            result = result.replace(private_val, public_val)
    else:  # direction == "pull"
        # Reverse substitutions and restore private-only lines
        for private_val, public_val in PYPROJECT_SUBSTITUTIONS.items():
            result = result.replace(public_val, private_val)
        result = _restore_private_pyproject_lines(result)

    return result


def should_transform(rel_path: Path) -> bool:
    """Check if a file should have transforms applied.

    Args:
        rel_path: Relative path from repo root

    Returns:
        True if transforms should be applied
    """
    normalized_path = _normalize_transform_path(rel_path)
    return (
        normalized_path.endswith("pyproject.toml")
        or normalized_path.endswith(".gitignore")
        or normalized_path.endswith("benchbox/cli/commands/__init__.py")
        or normalized_path.endswith(".github/workflows/test.yml")
        or normalized_path in {"pytest.ini", "pytest-ci.ini"}
    )


__all__ = [
    "prepare_public_release",
    "calculate_release_timestamp",
    "check_release_size",
    "compute_source_fingerprint",
    "ReleaseSizeViolation",
    "DEFAULT_MAX_FILE_SIZE_MB",
    "DEFAULT_MAX_TOTAL_SIZE_MB",
    "get_syncable_files",
    "compare_repos",
    "RepoComparison",
    "apply_transform",
    "should_transform",
    "PYPROJECT_PRIVATE_BLOCKS",
]
