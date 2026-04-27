#!/usr/bin/env python3
"""Generate a CHANGELOG.md entry from conventional commits since the last tag.

Standalone CLI extracted from scripts/automate_release.py for the version-branch
release flow. Run on the develop branch to draft a `## [VERSION] - DATE` section
ahead of cutting the release branch with `make release-prepare`.

Behaviour mirrors the legacy automate_release.py:_build_raw_changelog,
_summarize_changelog_with_claude, and generate_changelog_entry helpers:
- Parses commits since the most recent v* tag (or all commits if no tag exists).
- Categorises conventional commits into Added (feat), Fixed (fix), and
  Changed (perf). Skips test/docs/chore/ci/build/refactor/style and
  non-conventional commits.
- If the Claude CLI is available, summarises the raw bullets into a
  compact, themed section (10-25 user-facing bullets). Falls back to
  raw commit messages otherwise.
- Inserts the new section into CHANGELOG.md before the first existing
  `## [` entry.

Usage:
    uv run python scripts/generate_changelog_entry.py --version 0.3.0
    uv run python scripts/generate_changelog_entry.py --version 0.3.0 \
        --release-date 2026-04-30 --since-tag v0.2.1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

CLAUDE_TIMEOUT_SECONDS = 120


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
    or the summarization fails.
    """
    if not added and not fixed and not changed:
        return None

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

Now summarize the following raw commits:

{raw_input}"""

    try:
        result = subprocess.run(
            ["claude", "--print", "--model", "sonnet", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
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

    if summary.startswith("```"):
        summary = "\n".join(summary.split("\n")[1:])
    if summary.endswith("```"):
        summary = "\n".join(summary.split("\n")[:-1])
    summary = summary.strip()

    print(f"  Claude summarized {len(added) + len(fixed) + len(changed)} commits into compact changelog")
    return f"## [{version}] - {release_date}\n\n{summary}\n"


def generate_changelog_entry(source: Path, version: str, release_date: str, since_tag: str | None = None) -> bool:
    """Generate a changelog entry from conventional commits since the last tag.

    Args:
        source: Source repository path.
        version: New version string (without leading 'v').
        release_date: Release date in YYYY-MM-DD format.
        since_tag: Tag to use as the lower bound (e.g. 'v0.2.1'). If None,
            the latest matching v* tag is auto-detected.

    Returns:
        True if changelog was updated, False otherwise.
    """
    print(f"\n  Auto-generating changelog entry for v{version}...")

    if since_tag is None:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=source,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("  Warning: No previous version tag found, using all commits")
            since_tag = None
        else:
            since_tag = result.stdout.strip()
            print(f"  Previous tag: {since_tag}")
    else:
        print(f"  Since tag: {since_tag}")

    log_range = f"{since_tag}..HEAD" if since_tag else "HEAD"
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

    added: list[str] = []
    fixed: list[str] = []
    changed: list[str] = []
    skipped_nonconventional = 0
    skip_prefixes = ("test", "docs", "chore", "ci", "build", "refactor", "style")

    for commit in commits:
        if ":" in commit:
            prefix = commit.split(":", 1)[0].strip().lower()
            bare_prefix = prefix.split("(", 1)[0].strip()
            message = commit.split(":", 1)[1].strip()

            if bare_prefix == "feat":
                added.append(message)
            elif bare_prefix == "fix":
                fixed.append(message)
            elif bare_prefix == "perf":
                changed.append(message)
            elif bare_prefix in skip_prefixes:
                continue
            else:
                skipped_nonconventional += 1
        else:
            skipped_nonconventional += 1

    if skipped_nonconventional > 0:
        print(f"  Skipped {skipped_nonconventional} non-conventional commit(s)")

    if not added and not fixed and not changed:
        print("  Warning: No user-facing changes found in commits")
        print("  Generating empty changelog section (please edit manually)")

    new_section = _summarize_changelog_with_claude(version, release_date, added, fixed, changed)
    if new_section is None:
        new_section = _build_raw_changelog(version, release_date, added, fixed, changed)

    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        print(f"  Error: {changelog} not found")
        return False

    content = changelog.read_text()
    insertion_marker = "\n## ["
    idx = content.find(insertion_marker)
    if idx == -1:
        content = content.rstrip() + "\n\n" + new_section
    else:
        content = content[:idx] + "\n" + new_section + content[idx:]

    changelog.write_text(content)
    print(f"  Updated {changelog}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a CHANGELOG.md entry from conventional commits since the last v* tag."
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Version string for the new entry (without leading 'v'), e.g. 0.3.0",
    )
    parser.add_argument(
        "--release-date",
        default=date.today().isoformat(),
        help="Release date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--since-tag",
        default=None,
        help="Lower-bound tag for commit range (default: auto-detect latest v* tag)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args()

    if not (args.source / ".git").exists():
        print(f"  Error: {args.source} is not a git repository", file=sys.stderr)
        return 1

    success = generate_changelog_entry(
        source=args.source,
        version=args.version,
        release_date=args.release_date,
        since_tag=args.since_tag,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
