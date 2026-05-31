#!/usr/bin/env python3
"""Generate a CHANGELOG.md entry from conventional commits since a release boundary.

Standalone CLI extracted from scripts/automate_release.py for the version-branch
release flow. Run on the develop branch to draft a `## [VERSION] - DATE` section
ahead of cutting the release branch with `make release-prepare`.

Behaviour mirrors the legacy automate_release.py:_build_raw_changelog,
_summarize_changelog_with_claude, and generate_changelog_entry helpers:
- Parses commits since an explicit lower-bound ref, or since the most recent
  v* tag when no lower-bound ref is supplied.
- For explicit refs, derives commit subjects from the actual tree patch so a
  squash-merged release on `main` does not re-list already released commits.
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
    uv run python scripts/generate_changelog_entry.py --version 0.3.1 \
        --since-ref origin/main
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

CLAUDE_TIMEOUT_SECONDS = 120


def _run_git(source: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=source,
        capture_output=True,
        text=True,
        check=check,
    )


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


def _resolve_log_range(source: Path, since_ref: str | None, since_tag: str | None) -> str | None:
    """Return the git log range for changelog generation."""
    if since_ref is not None:
        print(f"  Since ref: {since_ref}")
        return f"{since_ref}..HEAD"

    if since_tag is None:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=source,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("  Warning: No previous version tag found, using all commits")
            return None
        since_tag = result.stdout.strip()
        print(f"  Previous tag: {since_tag}")
    else:
        print(f"  Since tag: {since_tag}")

    return f"{since_tag}..HEAD"


def _diff_name_status(source: Path, since_ref: str) -> list[tuple[str, str]]:
    result = _run_git(source, "diff", "--name-status", "-z", since_ref, "HEAD", check=True)
    parts = result.stdout.split("\0")
    entries: list[tuple[str, str]] = []
    idx = 0
    while idx < len(parts) - 1:
        status = parts[idx]
        idx += 1
        if not status:
            continue
        if status.startswith(("R", "C")):
            if idx + 1 >= len(parts):
                break
            old_path = parts[idx]
            new_path = parts[idx + 1]
            idx += 2
            entries.append((status[0], new_path or old_path))
            continue
        path = parts[idx]
        idx += 1
        if path:
            entries.append((status[0], path))
    return entries


def _tree_entry_at(source: Path, ref: str, path: str) -> str | None:
    result = _run_git(source, "ls-tree", "-z", ref, "--", path)
    if result.returncode != 0:
        return None
    entry = result.stdout.split("\0", 1)[0]
    if not entry:
        return None
    metadata, _separator, _entry_path = entry.partition("\t")
    return metadata


def _conventional_changelog_subject(subject: str) -> bool:
    if ":" not in subject:
        return False
    prefix = subject.split(":", 1)[0].strip().lower()
    bare_prefix = prefix.split("(", 1)[0].strip()
    return bare_prefix in {"feat", "fix", "perf"}


def _candidate_changelog_commits(source: Path, since_ref: str) -> list[tuple[str, str]] | None:
    result = _run_git(source, "log", "--format=%H%x00%s%x00", f"{since_ref}..HEAD")
    if result.returncode != 0:
        print(f"  Error: Failed to get git log: {result.stderr}")
        return None
    parts = [part for part in result.stdout.split("\0") if part]
    return [
        (commit_hash.strip(), subject.strip())
        for commit_hash, subject in zip(parts[0::2], parts[1::2], strict=False)
        if commit_hash.strip() and _conventional_changelog_subject(subject)
    ]


def _patch_delta_commit_subjects(source: Path, since_ref: str) -> list[str] | None:
    """Return subjects for commits that contribute to the current patch delta.

    `since_ref..HEAD` is ancestry-based. After a squash release to `main`, old
    develop commits are not ancestors of `main`, so ancestry would re-list them.
    Filtering through the actual tree diff keeps the changelog tied to the
    unreleased patch instead.
    """
    candidates = _candidate_changelog_commits(source, since_ref)
    if candidates is None:
        return None
    if not candidates:
        return []

    try:
        entries = _diff_name_status(source, since_ref)
    except subprocess.CalledProcessError as exc:
        print(f"  Error: Failed to diff {since_ref}..HEAD: {exc.stderr}")
        return None

    patch_paths = {path for _status, path in entries}
    if not patch_paths:
        return []

    patch_commits: set[str] = set()
    for commit_hash, _subject in candidates:
        result = _run_git(source, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit_hash)
        if result.returncode != 0:
            continue
        candidate_paths = {part for part in result.stdout.split("\0") if part}
        relevant_paths = candidate_paths & patch_paths
        if any(
            _tree_entry_at(source, commit_hash, path) != _tree_entry_at(source, since_ref, path)
            for path in relevant_paths
        ):
            patch_commits.add(commit_hash)

    if not patch_commits:
        return []

    return [subject for commit_hash, subject in candidates if commit_hash in patch_commits]


def generate_changelog_entry(
    source: Path,
    version: str,
    release_date: str,
    since_tag: str | None = None,
    since_ref: str | None = None,
) -> bool:
    """Generate a changelog entry from conventional commits.

    Args:
        source: Source repository path.
        version: New version string (without leading 'v').
        release_date: Release date in YYYY-MM-DD format.
        since_tag: Tag to use as the lower bound (e.g. 'v0.2.1'). Ignored
            when since_ref is set. If neither is set, the latest matching v*
            tag is auto-detected.
        since_ref: Ref to use as the lower bound (e.g. 'origin/main'). This is
            the release-branch flow default because `develop` is intentionally
            not tagged after releases.

    Returns:
        True if changelog was updated, False otherwise.
    """
    print(f"\n  Auto-generating changelog entry for v{version}...")
    if since_ref is not None:
        print(f"  Since ref: {since_ref} (patch delta)")
        commits = _patch_delta_commit_subjects(source, since_ref)
        if commits is None:
            return False
    else:
        log_range = _resolve_log_range(source, since_ref=since_ref, since_tag=since_tag) or "HEAD"
        result = _run_git(source, "log", "--format=%s", log_range)
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
        description="Generate a CHANGELOG.md entry from conventional commits since a release boundary."
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
        help="Lower-bound tag for commit range (default: auto-detect latest v* tag unless --since-ref is set)",
    )
    parser.add_argument(
        "--since-ref",
        default=None,
        help="Lower-bound ref for commit range, e.g. origin/main. Overrides --since-tag.",
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
        since_ref=args.since_ref,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
