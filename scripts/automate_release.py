#!/usr/bin/env python3
"""Fully automated BenchBox release process with timestamp normalization.

This script orchestrates the complete release workflow:
1. Calculate most recent whole hour timestamp
2. Run pre-flight checks (changelog, git status, version)
3. Run content validation (em-dash/en-dash checks in docs and blog)
4. Run CI validation (lint, format, type check, tests)
5. Prepare curated public tree
6. Run size safety check
7. Commit and squash into single release commit
8. Build packages from squashed commit (with SOURCE_DATE_EPOCH)
9. Verify artifacts and run smoke tests
10. Tag squashed commit and archive artifacts

Packages are built AFTER the code is committed and squashed, ensuring the
source fingerprint matches between the committed tree and the wheel contents.

All file timestamps are normalized to the most recent whole hour UTC,
ensuring no trace of actual creation/modification times in released artifacts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import from benchbox and sibling scripts
sys.path.insert(0, str(Path(__file__).parent.parent))
from finalize_release import archive_release_artifacts, git_tag_with_timestamp
from update_version import (
    DOCUMENTATION_PATHS,
    update_landing_page_version,
    update_release_marker,
    update_version_in_init,
    update_version_in_pyproject,
)

from benchbox.release.content_validation import check_content_for_release
from benchbox.release.workflow import (
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_MAX_TOTAL_SIZE_MB,
    calculate_release_timestamp,
    check_release_size,
)


def parse_timestamp(timestamp_str: str) -> tuple[int, str, str]:
    """Parse a timestamp string into release timestamp formats.

    Args:
        timestamp_str: Timestamp in git format (e.g., "2026-01-16 13:00:00 -0500")

    Returns:
        tuple[int, str, str]: (unix_timestamp, iso_format, git_format)

    Raises:
        ValueError: If timestamp cannot be parsed
    """
    # Try git format: "YYYY-MM-DD HH:MM:SS +/-HHMM"
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        # Try without timezone (assume UTC)
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise ValueError(
                f"Cannot parse timestamp '{timestamp_str}'. "
                "Expected format: 'YYYY-MM-DD HH:MM:SS -0500' or 'YYYY-MM-DD HH:MM:SS'"
            ) from e

    unix_ts = int(dt.timestamp())
    iso_fmt = dt.isoformat()
    git_fmt = dt.strftime("%Y-%m-%d %H:%M:%S %z")

    return unix_ts, iso_fmt, git_fmt


def get_head_sha(repo_path: Path) -> str:
    """Get the current HEAD commit SHA of a git repository.

    Args:
        repo_path: Path to the git repository

    Returns:
        Full SHA hex string of HEAD

    Raises:
        RuntimeError: If git command fails
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get HEAD SHA for {repo_path}: {result.stderr}")
    return result.stdout.strip()


def confirm_or_exit(message: str, auto_continue: bool = False) -> None:
    """Prompt user for confirmation or exit.

    Args:
        message: Confirmation message to display
        auto_continue: If True, skip prompt and continue automatically

    Raises:
        SystemExit: If user does not confirm
    """
    if auto_continue:
        print(f"\n{message} [auto-continuing]")
        return
    response = input(f"\n{message} (y/N): ").strip().lower()
    if response not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)


def bump_version(source: Path, version: str) -> bool:
    """Bump version across all project files using update_version functions.

    Args:
        source: Source repository path
        version: New version string

    Returns:
        True if all updates succeeded, False otherwise
    """
    print(f"\n  Auto-bumping version to {version}...")
    success = True

    if not update_version_in_init(version):
        success = False
    if not update_version_in_pyproject(version):
        success = False

    for doc_path in DOCUMENTATION_PATHS:
        full_path = source / doc_path
        if not update_release_marker(full_path, version):
            success = False

    if not update_landing_page_version(version):
        success = False

    return success


def _build_raw_changelog(
    version: str, release_date: str, added: list[str], fixed: list[str], changed: list[str]
) -> str:
    """Build a raw changelog section from commit message lists (fallback)."""
    lines = [f"## [{version}] - {release_date}", ""]
    if added:
        lines.append("### Added")
        lines.append("")
        for msg in added:
            lines.append(f"- {msg}")
        lines.append("")
    if fixed:
        lines.append("### Fixed")
        lines.append("")
        for msg in fixed:
            lines.append(f"- {msg}")
        lines.append("")
    if changed:
        lines.append("### Changed")
        lines.append("")
        for msg in changed:
            lines.append(f"- {msg}")
        lines.append("")
    if not added and not fixed and not changed:
        lines.append("### Added")
        lines.append("")
        lines.append("- (no user-facing changes detected -- please edit manually)")
        lines.append("")
    return "\n".join(lines)


def _summarize_changelog_with_claude(
    version: str, release_date: str, added: list[str], fixed: list[str], changed: list[str]
) -> str | None:
    """Use Claude Code CLI to summarize raw commits into a compact changelog.

    Returns the summarized changelog section, or None if claude is unavailable
    or the summarization fails. The caller should fall back to the raw format.
    """
    if not added and not fixed and not changed:
        return None

    # Build the raw input for Claude to summarize
    raw_parts: list[str] = []
    if added:
        raw_parts.append("### Added")
        raw_parts.extend(f"- {msg}" for msg in added)
    if fixed:
        raw_parts.append("### Fixed")
        raw_parts.extend(f"- {msg}" for msg in fixed)
    if changed:
        raw_parts.append("### Changed")
        raw_parts.extend(f"- {msg}" for msg in changed)
    raw_input = "\n".join(raw_parts)

    prompt = f"""\
Summarize these raw commit messages into a compact changelog entry for version {version}.

RULES:
- Output ONLY the markdown body (### Added, ### Fixed, ### Changed sections). Do NOT include
  the ## [version] header line - the caller adds that.
- Group related commits into single thematic bullets. Hundreds of raw commits should become
  10-25 well-written bullets total across all sections.
- Major features get **bold lead-ins** with a dash separator and a 1-2 sentence description
  that explains the user impact, e.g.:
  **DataFrame mode for all benchmarks** - Complete DataFrame query implementations across all
  22 benchmarks including TPC-DS (99 queries), TPC-H (22 queries), SSB, ClickBench, and more.
- Minor items can be plain single-line bullets without bold.
- Omit internal refactors, TODO management, CI tweaks, and commit noise.
- Use Keep a Changelog conventions (Added/Fixed/Changed).
- Preserve technical accuracy - mention specific counts, platform names, and query IDs where
  they add value.
- Wrap lines at 100 characters with 2-space continuation indent.
- Do NOT add any preamble, explanation, or commentary - output the markdown sections only.

Here is an example of the desired style from the previous release:

### Fixed

- **Critical: TPC-H/TPC-DS query templates missing from wheel distribution** - BenchBox installed
  from PyPI via wheel could not run TPC-H or TPC-DS benchmarks because query template files were
  stored outside the package tree and excluded from wheels. Templates are now bundled inside
  `benchbox/_binaries/*/templates/` with a resolution utility that checks the bundled location
  first and falls back to `_sources/` for development installs.
- **dsqgen path buffer overflow** - TPC-DS query generation could fail on systems with long temp
  directory paths (e.g., macOS `/var/folders/...`) due to dsqgen's internal 80-char path buffer.
  Fixed by using short symlinks in the temp directory.
- Python 3.10 compatibility for CLI, version utilities, and `tomllib` imports
- Windows CI test failures and cross-platform compatibility issues

### Added

- MCP server: 7 new tools (`get_query_details`, `detect_regressions`, `get_performance_trends`,
  `aggregate_results`, `get_query_plan`, `export_results`, `export_summary`) and 2 prompts
- GitHub Actions PyPI publishing with trusted publishers
- Release automation: `--push`, `--auto-continue`, CI validation integration, bidirectional sync

### Changed

- Minimum Python version explicitly documented as 3.10
- MCP server refactored to use public API instead of CLI internals
- Benchmark metadata centralized into single registry

---

Now summarize the following raw commits:

{raw_input}"""

    try:
        result = subprocess.run(
            ["claude", "--print", "--model", "sonnet", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        print("  Claude CLI not found, falling back to raw changelog")
        return None
    except subprocess.TimeoutExpired:
        print("  Claude CLI timed out, falling back to raw changelog")
        return None

    if result.returncode != 0:
        print(f"  Claude CLI failed (exit {result.returncode}), falling back to raw changelog")
        return None

    summary = result.stdout.strip()
    if not summary or "### " not in summary:
        print("  Claude CLI returned invalid output, falling back to raw changelog")
        return None

    # Strip any leading ``` fences Claude might add
    if summary.startswith("```"):
        summary = "\n".join(summary.split("\n")[1:])
    if summary.endswith("```"):
        summary = "\n".join(summary.split("\n")[:-1])
    summary = summary.strip()

    print(f"  Claude summarized {len(added) + len(fixed) + len(changed)} commits into compact changelog")
    return f"## [{version}] - {release_date}\n\n{summary}\n"


def generate_changelog_entry(source: Path, version: str, release_date: str) -> bool:
    """Generate a changelog entry from conventional commits since the last tag.

    Parses commits since the previous version tag and categorizes them into
    Keep a Changelog sections (Added, Fixed, Changed). Non-user-facing commit
    types (test, docs, chore, ci, build, refactor, style) are skipped.

    When the Claude CLI is available, raw commits are summarized into a compact,
    human-readable changelog (10-25 themed bullets). Falls back to raw commit
    messages if Claude is unavailable or fails.

    Args:
        source: Source repository path
        version: New version string
        release_date: Release date in YYYY-MM-DD format

    Returns:
        True if changelog was updated, False otherwise
    """
    print(f"\n  Auto-generating changelog entry for v{version}...")

    # Find previous version tag
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
        cwd=source,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  Warning: No previous version tag found, using all commits")
        prev_tag = None
    else:
        prev_tag = result.stdout.strip()
        print(f"  Previous tag: {prev_tag}")

    # Collect commits since previous tag
    log_range = f"{prev_tag}..HEAD" if prev_tag else "HEAD"
    result = subprocess.run(
        ["git", "log", "--format=%s", log_range],
        cwd=source,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Error: Failed to get git log: {result.stderr}")
        return False

    commits = [line for line in result.stdout.strip().split("\n") if line.strip()]
    if not commits:
        print("  Warning: No commits found since last tag")
        return False

    # Parse conventional commits into categories
    added: list[str] = []
    fixed: list[str] = []
    changed: list[str] = []
    skipped_conventional = 0
    skipped_nonconventional = 0

    skip_prefixes = ("test", "docs", "chore", "ci", "build", "refactor", "style")

    for commit in commits:
        # Match conventional commit: type(scope): message  or  type: message
        # Use colon-after-word to identify conventional commits
        if ":" in commit:
            prefix = commit.split(":", 1)[0].strip().lower()
            # Strip optional scope: feat(core) -> feat
            bare_prefix = prefix.split("(", 1)[0].strip()
            message = commit.split(":", 1)[1].strip()

            if bare_prefix == "feat":
                added.append(message)
            elif bare_prefix == "fix":
                fixed.append(message)
            elif bare_prefix == "perf":
                changed.append(message)
            elif bare_prefix in skip_prefixes:
                skipped_conventional += 1
            else:
                # Has a colon but unrecognized prefix -- treat as non-conventional
                skipped_nonconventional += 1
        else:
            skipped_nonconventional += 1

    if skipped_nonconventional > 0:
        print(f"  Skipped {skipped_nonconventional} non-conventional commit(s)")

    if not added and not fixed and not changed:
        print("  Warning: No user-facing changes found in commits")
        print("  Generating empty changelog section (please edit manually)")

    # Build changelog section -- use Claude to summarize if available
    new_section = _summarize_changelog_with_claude(version, release_date, added, fixed, changed)
    if new_section is None:
        new_section = _build_raw_changelog(version, release_date, added, fixed, changed)

    # Insert into CHANGELOG.md after header, before first existing ## [ entry
    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        print(f"  Error: {changelog} not found")
        return False

    content = changelog.read_text()

    # Find insertion point: before the first existing "## [" line
    insertion_marker = "\n## ["
    idx = content.find(insertion_marker)
    if idx == -1:
        # No existing entries, append after header
        content = content.rstrip() + "\n\n" + new_section
    else:
        content = content[:idx] + "\n" + new_section + content[idx:]

    changelog.write_text(content)
    print(f"  Updated {changelog}")
    return True


def run_pre_flight_checks(source: Path, version: str, release_date: str, auto_continue: bool = False) -> bool:
    """Run pre-flight validation checks, auto-fixing version and changelog.

    Args:
        source: Source repository path
        version: Version string
        release_date: Release date in YYYY-MM-DD format
        auto_continue: If True, skip confirmation prompts

    Returns:
        True if all checks pass, False otherwise
    """
    print("\n" + "=" * 60)
    print("Pre-Flight Checks")
    print("=" * 60)

    # Check 1: Version string format (hard fail)
    if not version.replace(".", "").replace("-", "").replace("_", "").isalnum():
        print(f"❌ Invalid version format: {version}")
        return False
    print(f"✓ Version format valid: {version}")

    # Check 2: Version consistency -- auto-bump if mismatched
    try:
        import re

        init_text = (source / "benchbox" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
        if not match:
            raise ValueError("Could not parse __version__ from benchbox/__init__.py")
        source_version = match.group(1)

        if source_version != version:
            print(f"⚠️  Version mismatch: source={source_version}, release={version}")
            if not bump_version(source, version):
                print("❌ Version bump failed")
                return False
            print(f"✓ Version bumped to {version}")
        else:
            print(f"✓ Version matches source: {version}")
            # Ensure landing page badge is current even when version was pre-bumped
            if not update_landing_page_version(version):
                print("⚠️  Warning: Landing page version badge not updated")
            else:
                print("✓ Landing page version badge is current")
    except Exception as e:
        print(f"⚠️  Warning: Could not verify source version: {e}")
        confirm_or_exit("Continue without version verification?", auto_continue)

    # Check 3: Changelog entry -- auto-generate if missing
    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        print("❌ CHANGELOG.md not found")
        return False

    changelog_text = changelog.read_text()
    if f"## [{version}]" not in changelog_text and f"## {version}" not in changelog_text:
        print(f"⚠️  CHANGELOG.md missing entry for v{version}")
        if not generate_changelog_entry(source, version, release_date):
            print("❌ Changelog generation failed")
            return False
        print(f"✓ Changelog entry generated for v{version}")
    else:
        print(f"✓ CHANGELOG.md has entry for v{version}")

    # Check 4: Git status (warn about uncommitted changes, which now includes bump/changelog)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=source,
        capture_output=True,
        text=True,
    )

    if result.stdout.strip():
        print("⚠️  Warning: Main repository has uncommitted changes:")
        for line in result.stdout.strip().split("\n")[:10]:
            print(f"     {line}")
        confirm_or_exit("Continue anyway?", auto_continue)
    else:
        print("✓ Main repository is clean")

    print("\n✅ Pre-flight checks passed")
    return True


def run_step(script: str, args: list[str], description: str, check: bool = True) -> bool:
    """Run a release step script.

    Args:
        script: Script name (e.g., "prepare_release.py")
        args: Command-line arguments for the script
        description: Human-readable description
        check: Whether to raise on non-zero exit

    Returns:
        True if successful, False otherwise
    """
    print("\n" + "=" * 60)
    print(description)
    print("=" * 60)
    print(f"Running: {script} {' '.join(str(a) for a in args)}\n")

    script_path = Path(__file__).parent / script
    result = subprocess.run(
        [sys.executable, str(script_path)] + args,
        check=False,
    )

    if result.returncode != 0:
        print(f"\n❌ {description} failed")
        if check:
            sys.exit(1)
        return False

    print(f"\n✓ {description} complete")
    return True


def run_size_check(target: Path) -> bool:
    """Run release size safety check.

    Args:
        target: Path to the release directory

    Returns:
        True if all checks passed, False otherwise
    """
    print("\n" + "=" * 60)
    print("Release Size Safety Check")
    print("=" * 60)

    passed, violations, total_size_mb = check_release_size(target)

    print(f"\nTotal release size: {total_size_mb:.1f} MB")
    print(f"Limits: {DEFAULT_MAX_FILE_SIZE_MB} MB per file, {DEFAULT_MAX_TOTAL_SIZE_MB} MB total")

    if passed:
        print("\n✓ All size checks passed")
        return True
    else:
        print(f"\n❌ Found {len(violations)} violation(s):\n")
        for v in violations:
            print(f"  • {v}")
        print("\nRelease aborted. Please fix the violations and try again.")
        return False


def run_ci_checks(source: Path) -> bool:
    """Run CI validation checks (lint, type check, tests).

    These are the same checks that run in GitHub Actions. Running them
    locally before release ensures the code is in a releasable state.

    Args:
        source: Source repository path

    Returns:
        True if all checks pass, False otherwise
    """
    print("\n" + "=" * 60)
    print("CI Validation Checks")
    print("=" * 60)
    print("Running the same checks as GitHub Actions...")
    print("(equivalent to: make ci-lint && make ci-test)\n")

    checks = [
        ("Lint check (ruff)", ["uv", "run", "ruff", "check", "."]),
        ("Format check (ruff)", ["uv", "run", "ruff", "format", "--check", "."]),
        ("Type check (ty)", ["uv", "run", "ty", "check"]),
        (
            "Fast tests with coverage",
            [
                "uv",
                "run",
                "--",
                "python",
                "-m",
                "pytest",
                "tests",
                "-m",
                "fast and not (slow or stress or resource_heavy or live_integration)",
                "--tb=short",
                "-p",
                "pytest_cov",  # Override pytest.ini's -p no:cov
                "--cov=benchbox",
                "--cov-report=term-missing",
                "--cov-fail-under=70",
                # Exclude PySpark tests - CI runs these separately with Java
                "--ignore=tests/unit/platforms/dataframe/test_pyspark_df.py",
                "--ignore=tests/unit/platforms/pyspark",
            ],
        ),
    ]

    for description, cmd in checks:
        print(f"• {description}...", end=" ", flush=True)
        result = subprocess.run(
            cmd,
            cwd=source,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("❌ FAILED")
            print(f"\nCommand: {' '.join(cmd)}")
            if result.stdout.strip():
                # Show last 20 lines of output
                lines = result.stdout.strip().split("\n")
                if len(lines) > 20:
                    print(f"... ({len(lines) - 20} lines omitted)")
                    lines = lines[-20:]
                print("\n".join(lines))
            if result.stderr.strip():
                print(result.stderr.strip())
            print(f"\n❌ CI check '{description}' failed")
            print("Fix the issues above before releasing, or use --skip-ci to bypass.")
            return False
        print("✓")

    print("\n✅ All CI checks passed")
    return True


def _initial_release_commit_message(version: str) -> str:
    """Generate the commit message for the first public release.

    Args:
        version: Release version string

    Returns:
        Formatted commit message
    """
    return f"""Initial release v{version}

BenchBox: SQL benchmarking framework for OLAP databases.

Features:
- TPC-H, TPC-DS, SSB, ClickBench benchmarks
- DuckDB, SQLite, PostgreSQL, Snowflake, Databricks platforms
- DataFrame support (Polars, Pandas, DuckDB, DataFusion)
- MCP server for AI agent integration
- Comprehensive validation and result analysis

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"""


def _incremental_release_commit_message(version: str) -> str:
    """Generate the commit message for an incremental release.

    Args:
        version: Release version string

    Returns:
        Formatted commit message
    """
    return f"""Incremental release v{version}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"""


def _find_squash_anchor(target: Path) -> str | None:
    """Find the commit to squash onto for an incremental release.

    Looks for the most recent version tag reachable from HEAD. This is
    preferred over origin/main because intermediate commits (e.g. CI fixes
    pushed between releases) should be squashed into the release commit,
    not preserved as separate parents.

    Falls back to origin/main if no version tags exist, and returns None
    if neither anchor is available (initial release).

    Args:
        target: Path to the git repository

    Returns:
        The anchor ref string, or None for initial releases.
    """
    # Prefer the most recent version tag
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        tag = result.stdout.strip()
        print(f"  Squash anchor: {tag} (previous version tag)")
        return tag

    # Fall back to origin/main
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  Squash anchor: origin/main (no version tags found)")
        return "origin/main"

    return None


def squash_commits(target: Path, version: str, git_timestamp: str) -> bool:
    """Squash new commits into a single release commit with normalized timestamp.

    For initial releases (no tags or remote): collapses all commits into one
    with the full feature-list message.

    For incremental releases: squashes all commits since the previous version
    tag into one commit. This ensures intermediate commits (e.g. CI fixes
    pushed between releases) are absorbed into the release commit rather than
    cluttering the public history. Falls back to origin/main if no tags exist.

    Args:
        target: Path to the public repository
        version: Release version string
        git_timestamp: Git-formatted timestamp (YYYY-MM-DD HH:MM:SS +0000)

    Returns:
        True if successful, False otherwise
    """
    print("\n" + "=" * 60)
    print("Squashing commits into single release commit...")
    print("=" * 60)

    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = git_timestamp
    env["GIT_COMMITTER_DATE"] = git_timestamp
    # Public release tree has no .pre-commit-config.yaml; silence the hook if present
    env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"

    anchor = _find_squash_anchor(target)

    try:
        if anchor is None:
            # Initial release: squash all commits
            commit_message = _initial_release_commit_message(version)
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=target,
                capture_output=True,
                text=True,
                check=True,
            )
            commit_count = int(result.stdout.strip())

            if commit_count > 1:
                print(f"  Initial release: squashing all {commit_count} commits...")
                subprocess.run(
                    ["git", "reset", "--soft", f"HEAD~{commit_count - 1}"],
                    cwd=target,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "--amend", "-m", commit_message],
                    cwd=target,
                    env=env,
                    check=True,
                )
            else:
                print("  Initial release: amending single commit...")
                subprocess.run(
                    ["git", "commit", "--amend", "-m", commit_message],
                    cwd=target,
                    env=env,
                    check=True,
                )
        else:
            # Incremental release: squash all commits since anchor (tag or origin/main)
            commit_message = _incremental_release_commit_message(version)
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{anchor}..HEAD"],
                cwd=target,
                capture_output=True,
                text=True,
                check=True,
            )
            new_commits = int(result.stdout.strip())

            if new_commits == 0:
                print(f"  No new commits since {anchor}, nothing to squash")
                return True
            elif new_commits == 1:
                print("  Incremental release: amending commit message...")
                subprocess.run(
                    ["git", "commit", "--amend", "-m", commit_message],
                    cwd=target,
                    env=env,
                    check=True,
                )
            else:
                print(f"  Incremental release: squashing {new_commits} commits since {anchor}...")
                subprocess.run(
                    ["git", "reset", "--soft", anchor],
                    cwd=target,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", commit_message],
                    cwd=target,
                    env=env,
                    check=True,
                )

        print("✓ Squash complete")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Squash failed: {e}")
        return False


def push_release(target: Path, version: str) -> bool:
    """Push release commit and tag to remote.

    Args:
        target: Path to the public repository
        version: Release version string

    Returns:
        True if successful, False otherwise
    """
    print("\n" + "=" * 60)
    print("Pushing to remote...")
    print("=" * 60)

    try:
        print("  Pushing main branch (force)...")
        subprocess.run(
            ["git", "push", "--force", "origin", "main"],
            cwd=target,
            check=True,
        )
        print(f"  Pushing tag v{version}...")
        subprocess.run(
            ["git", "push", "--force", "origin", f"v{version}"],
            cwd=target,
            check=True,
        )

        print("✅ Push complete!")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Push failed: {e}")
        return False


def display_summary(
    version: str,
    timestamp_info: tuple[int, str, str],
    public_path: Path,
):
    """Display release summary.

    Args:
        version: Release version
        timestamp_info: (unix_ts, iso_fmt, git_fmt) tuple
        public_path: Path to public repository
    """
    unix_ts, iso_fmt, git_fmt = timestamp_info

    print("\n" + "=" * 60)
    print("RELEASE SUMMARY")
    print("=" * 60)
    print(f"\nVersion: {version}")
    print(f"Timestamp: {iso_fmt}")
    print(f"Unix: {unix_ts}")
    print(f"Git: {git_fmt}")
    print(f"\nPublic Repository: {public_path}")
    print(f"Distribution: {public_path / 'dist'}")

    # Show built artifacts
    dist_dir = public_path / "dist"
    if dist_dir.exists():
        print("\nArtifacts:")
        for artifact in sorted(dist_dir.glob("*")):
            if artifact.suffix in (".whl", ".gz"):
                size_mb = artifact.stat().st_size / (1024 * 1024)
                print(f"  - {artifact.name} ({size_mb:.2f} MB)")

    print("\n" + "=" * 60)


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        type=str,
        required=True,
        help="Release version (e.g., 0.1.0)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("../BenchBox-public"),
        help="Target directory for public release (default: ../BenchBox-public)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Source repository (default: current directory)",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip pre-flight validation checks",
    )
    parser.add_argument(
        "--skip-ci",
        action="store_true",
        help="Skip CI validation (lint, tests, type checking)",
    )
    parser.add_argument(
        "--skip-content-check",
        action="store_true",
        help="Skip content validation (em-dash/en-dash checks in docs and blog)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip smoke tests",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Skip artifact archiving",
    )
    parser.add_argument(
        "--force-tag",
        action="store_true",
        help="Overwrite existing git tag if it exists",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push release commit and tag to remote",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--auto-continue",
        "-y",
        action="store_true",
        help="Automatically continue after each successful step (no confirmation prompts)",
    )
    parser.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help=(
            "Use a specific timestamp instead of most recent whole hour. "
            "Format: 'YYYY-MM-DD HH:MM:SS -0500' (git format with timezone)"
        ),
    )

    args = parser.parse_args()

    # Resolve paths
    source = args.source.resolve()
    target = args.target.resolve()
    version = args.version

    # Safety check: target must not be inside source repository
    try:
        target.relative_to(source)
        # If we get here, target is inside source - this is an error
        print("❌ Target directory cannot be inside source repository")
        print(f"   Source: {source}")
        print(f"   Target: {target}")
        print("\n   Use a path outside the repo, e.g.: --target ../BenchBox-public")
        return 1
    except ValueError:
        # target is not inside source - this is what we want
        pass

    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
        print(f"Version: {version}")
        print(f"Source: {source}")
        print(f"Target: {target}")
        return 0

    # Get timestamp: use provided or calculate most recent whole hour
    if args.timestamp:
        try:
            unix_ts, iso_fmt, git_fmt = parse_timestamp(args.timestamp)
            timestamp_source = "provided"
        except ValueError as e:
            print(f"❌ {e}")
            return 1
    else:
        unix_ts, iso_fmt, git_fmt = calculate_release_timestamp()
        timestamp_source = "most recent whole hour"

    print("=" * 60)
    print("BenchBox Automated Release")
    print("=" * 60)
    print(f"Version: {version}")
    print(f"Timestamp: {iso_fmt} ({timestamp_source})")
    print(f"  Unix: {unix_ts}")
    print(f"  Git: {git_fmt}")
    print(f"Source: {source}")
    print(f"Target: {target}")
    print("=" * 60)

    # Confirm before starting
    confirm_or_exit(f"Proceed with release v{version}?", args.auto_continue)

    # Extract release date from timestamp for changelog generation
    release_date = iso_fmt[:10]

    # Step 1: Pre-flight checks
    if not args.skip_preflight:
        if not run_pre_flight_checks(source, version, release_date, args.auto_continue):
            print("\n❌ Pre-flight checks failed")
            return 1
        confirm_or_exit("Pre-flight checks passed. Continue?", args.auto_continue)

    # Step 2: Content validation (docs and blog)
    if not args.skip_content_check:
        if not check_content_for_release(source, args.auto_continue):
            print("\n❌ Content validation failed")
            print("Use --skip-content-check to bypass (not recommended)")
            return 1
        confirm_or_exit("Content validation passed. Continue?", args.auto_continue)
    else:
        print("\n⚠️  Content validation skipped (--skip-content-check)")

    # Step 3: CI validation (lint, type check, tests)
    if not args.skip_ci:
        if not run_ci_checks(source):
            print("\n❌ CI validation failed")
            print("Use --skip-ci to bypass (not recommended)")
            return 1
        confirm_or_exit("CI checks passed. Continue?", args.auto_continue)
    else:
        print("\n⚠️  CI validation skipped (--skip-ci)")

    # Record dev repo HEAD for drift detection
    sync_start_sha = get_head_sha(source)

    # Step 4: Prepare public tree
    # Note: _sources extras (compilation, patches, answers) are now in the whitelist
    # in workflow.py's _SOURCES_INCLUDE_PATHS, ensuring deterministic builds
    run_step(
        "prepare_release.py",
        [
            str(target),
            "--source",
            str(source),
            "--version",
            version,
            "--init-git",
            "--timestamp",
            str(unix_ts),
            "--no-clean",  # Safe: _sources is in CLEANUP_PATTERNS, always rebuilt from whitelist
        ],
        "Step 4/8: Preparing Public Tree",
    )

    # Step 5: Size safety check
    if not run_size_check(target):
        return 1

    # Step 6: Commit and squash (before build, so packages are built from committed state)
    # 6a: Commit the prepared tree
    run_step(
        "finalize_release.py",
        [
            str(target),
            "--version",
            version,
            "--git-timestamp",
            git_fmt,
            "--skip-tag",
            "--skip-archive",
            "--skip-fingerprint",
        ],
        "Step 6/8: Committing Public Tree",
    )

    # 6b: Squash into single release commit with normalized timestamp
    if not squash_commits(target, version, git_fmt):
        print("\n❌ Squash failed")
        return 1

    # Step 7: Build packages (from squashed commit state)
    run_step(
        "build_release.py",
        [str(target), "--timestamp", str(unix_ts)],
        "Step 7/8: Building Packages",
    )

    # Step 8: Verify and smoke test
    verify_args = [str(target)]
    if args.skip_tests:
        verify_args.append("--skip-smoke-tests")
    if args.verbose:
        verify_args.append("--verbose")

    run_step(
        "verify_release.py",
        verify_args,
        "Step 8/8: Verifying Artifacts & Running Smoke Tests",
    )

    # Verify dev repo hasn't changed since sync
    current_sha = get_head_sha(source)
    if current_sha != sync_start_sha:
        print(f"\n❌ Dev repo changed during release: {sync_start_sha[:12]} → {current_sha[:12]}")
        print("New commits landed after sync. Re-run release to include them.")
        return 1

    # Post-verify: Tag the squashed commit
    if not git_tag_with_timestamp(target, f"v{version}", git_fmt, force=args.force_tag):
        print("\n❌ Tagging failed")
        return 1

    # Archive artifacts (to private repo)
    if not args.skip_archive:
        archive_base = source / "release" / "archive"
        dist_dir = target / "dist"
        wheels = list(dist_dir.glob("*.whl"))
        sdists = list(dist_dir.glob("*.tar.gz"))
        if wheels and sdists:
            archive_release_artifacts(version, wheels[0], sdists[0], archive_base)
        else:
            print("\n⚠️  Artifacts not found in dist/, skipping archive")

    # Display summary
    display_summary(version, (unix_ts, iso_fmt, git_fmt), target)

    # Push if requested (just push, squash already done)
    if args.push:
        confirm_or_exit("Push release to remote?", args.auto_continue)
        if not push_release(target, version):
            print("\n❌ Push failed")
            return 1
        print("\n✅ Release automation complete!")
        print("\nThe release has been pushed. Remaining steps:")
        print(f"  1. Upload to PyPI: twine upload {target}/dist/benchbox-{version}*")
        print("  2. Sync fixes back to private repo:")
        print(f"     cd {source} && git push private main")
    else:
        print("\n✅ Release automation complete!")
        print("\nThe release is ready to publish manually:")
        print(f"  1. Review: cd {target} && git log --format=fuller")
        print(f"  2. Push: git push origin main && git push origin v{version}")
        print(f"  3. Upload to PyPI: twine upload dist/benchbox-{version}*")
        print("  4. Sync fixes back to private repo:")
        print(f"     cd {source} && git push private main")

    return 0


if __name__ == "__main__":
    sys.exit(main())
