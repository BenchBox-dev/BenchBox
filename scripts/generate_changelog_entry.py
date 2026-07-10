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
  raw commit messages otherwise. Summarization is skipped inside a
  Claude Code session unless BENCHBOX_CHANGELOG_SUMMARIZE=1, because the
  nested CLI call blocks (see the 2026-07-09 amendment of
  _project/decisions/single-repo-migration.md).
- Inserts the new section into CHANGELOG.md before the first existing
  `## [` entry, or leaves an existing section for that version alone so
  an interrupted `make release-cut` can be re-run.

Usage:
    uv run python scripts/generate_changelog_entry.py --version 0.3.0
    uv run python scripts/generate_changelog_entry.py --version 0.3.0 \
        --release-date 2026-04-30 --since-tag v0.2.1
    uv run python scripts/generate_changelog_entry.py --version 0.3.1 \
        --since-ref origin/main
    uv run python scripts/generate_changelog_entry.py --version 0.3.1 \
        --check-curation
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path

CLAUDE_TIMEOUT_SECONDS = 120

# Set by the Claude Code CLI in every session it spawns. Shelling out to a
# nested `claude` from inside one stalls (the v0.3.1 cut hung here twice), so
# summarization defaults off when any of these are present.
_NESTED_CLAUDE_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

# Curation gate. `_build_raw_changelog` emits verbatim commit subjects, which
# keep their squash-merge PR suffix (e.g. "... (#1086)"); the Claude summary
# and any hand-curated section do not. That suffix is the precise signal; the
# bullet ceiling is a backstop for drafts written by other means.
#
# The ceiling is set from evidence, not the prompt's 10-25 target: the largest
# genuinely hand-curated section shipped so far is 0.2.1 at 39 bullets, while
# the raw origin/main..HEAD delta at v0.3.1 was 231 conventional commits. 60
# separates the two with room to spare.
MAX_CURATED_BULLETS = 60
RAW_PLACEHOLDER = "(no user-facing changes detected -- please edit manually)"
_PR_SUFFIX_RE = re.compile(r"\(#\d+\)\s*$")
_BULLET_RE = re.compile(r"^\s*- \S")

# Matches a dated released-version CHANGELOG.md header, e.g. "## [0.3.0] - 2026-05-16".
# Deliberately does not match "## [Unreleased]" (no version number) or an
# undated "## [X.Y.Z]" header, since a dated header is this repo's convention
# for a section that claims to be released (see CHANGELOG.md's own entries).
_CHANGELOG_VERSION_HEADER_RE = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - ", re.MULTILINE)

# Matches a release-cut branch name, e.g. "v0.3.1" or "v0.3.1-rc1". Mirrors
# the HEAD_REF regex in .github/workflows/validate-main-pr.yml so the two
# checks agree on what counts as an in-progress release branch.
_RELEASE_BRANCH_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(-[A-Za-z0-9.+-]+)?$")


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


def summarize_skip_reason(env: dict[str, str] | None = None) -> str | None:
    """Return why Claude summarization is skipped, or None to run it.

    `BENCHBOX_CHANGELOG_SUMMARIZE` decides explicitly in both directions. With
    it unset, summarization runs only outside a Claude Code session: a nested
    `claude --print` blocks until the timeout, which is how `make release-cut`
    stalled during the v0.3.1 cut.
    """
    env = os.environ if env is None else env
    flag = env.get("BENCHBOX_CHANGELOG_SUMMARIZE", "").strip().lower()
    if flag in _FALSE_VALUES:
        return "BENCHBOX_CHANGELOG_SUMMARIZE opts out"
    if flag in _TRUE_VALUES:
        return None
    nested = next((name for name in _NESTED_CLAUDE_ENV_VARS if env.get(name)), None)
    if nested:
        return f"already inside a Claude Code session ({nested} set); set BENCHBOX_CHANGELOG_SUMMARIZE=1 to force"
    return None


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    """SIGKILL the child's whole process group, falling back to the child alone."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - Windows
            proc.kill()
    except (ProcessLookupError, PermissionError):  # pragma: no cover - already reaped
        proc.kill()


def _run_claude_cli(prompt: str) -> subprocess.CompletedProcess[str]:
    """Run `claude --print` under a timeout that reaps the entire child tree.

    `subprocess.run(timeout=...)` kills only the direct child, then re-waits on
    the captured pipes; a surviving grandchild holding stdout open blocks that
    wait forever, which is what left an orphaned `claude` tree behind the
    stalled v0.3.1 cut. Running the child in its own process group lets the
    timeout path kill every pipe holder. stdin is closed so the CLI can never
    block waiting for input it will not get.
    """
    with subprocess.Popen(
        ["claude", "--print", "--model", "sonnet", "-p", prompt],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=CLAUDE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            proc.communicate()
            raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _summarize_changelog_with_claude(
    version: str, release_date: str, added: list[str], fixed: list[str], changed: list[str]
) -> str | None:
    """Use Claude Code CLI to summarize raw commits into a compact changelog.

    Returns the summarized changelog section, or None if summarization is
    skipped, claude is unavailable, or the summarization fails.
    """
    if not added and not fixed and not changed:
        return None

    skip_reason = summarize_skip_reason()
    if skip_reason is not None:
        print(f"  Skipping Claude summarization: {skip_reason}")
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
        result = _run_claude_cli(prompt)
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


def released_versions_in_changelog(changelog_text: str) -> list[str]:
    """Return the X.Y.Z versions of every dated '## [X.Y.Z] - <date>' header.

    Excludes '## [Unreleased]', which is not a released-version claim.
    """
    return [m.group("version") for m in _CHANGELOG_VERSION_HEADER_RE.finditer(changelog_text)]


def section_body(changelog_text: str, version: str) -> str | None:
    """Return the body of `## [version] - <date>`, or None when absent."""
    header = re.search(rf"^## \[{re.escape(version)}\] - .*$", changelog_text, re.MULTILINE)
    if header is None:
        return None
    rest = changelog_text[header.end() :]
    following = re.search(r"^## \[", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


def has_changelog_section(source: Path, version: str) -> bool:
    """True when CHANGELOG.md carries a dated section for `version`."""
    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        return False
    return section_body(changelog.read_text(encoding="utf-8"), version) is not None


def check_changelog_curation(source: Path, version: str) -> tuple[bool, list[str]]:
    """Return (ok, problems) for the drafted `version` section.

    `release-cut` generates a section from every conventional commit in the
    `origin/main..HEAD` patch delta, which for a `main` that lags `develop` is
    a raw dump of hundreds of commit subjects. The old gate only refused to
    skip curation when `EDITOR` was unset *and* stdin was not a TTY, so
    `EDITOR=true` waved the raw dump through. This checks the text instead.
    """
    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        return False, [f"{changelog} not found"]

    body = section_body(changelog.read_text(encoding="utf-8"), version)
    if body is None:
        return False, [f"no '## [{version}] - <date>' section found in CHANGELOG.md"]

    bullets = [line.strip() for line in body.splitlines() if _BULLET_RE.match(line)]
    problems: list[str] = []
    if not bullets:
        problems.append("section contains no bullets")
    if RAW_PLACEHOLDER in body:
        problems.append("section still carries the generator's manual-edit placeholder")
    raw_bullets = [b for b in bullets if _PR_SUFFIX_RE.search(b)]
    if raw_bullets:
        problems.append(
            f"{len(raw_bullets)} bullet(s) are verbatim commit subjects "
            f"(trailing PR number), e.g. {raw_bullets[0][:70]!r}"
        )
    if len(bullets) > MAX_CURATED_BULLETS:
        problems.append(f"{len(bullets)} bullets exceeds the {MAX_CURATED_BULLETS}-bullet curated ceiling")
    return (not problems), problems


def existing_tags(source: Path) -> set[str]:
    """Return the set of vX.Y.Z tag names visible to this checkout.

    Prefers local tags (`git tag -l`), which is what
    `_resolve_log_range`'s `git describe --tags` above also relies on.
    Falls back to `git ls-remote --tags origin` when no local tags are
    present (e.g. a shallow or tag-less local clone) so the guard doesn't
    silently pass for lack of local tag data.
    """
    local = _run_git(source, "tag", "-l", "v*")
    tags = {line.strip() for line in local.stdout.splitlines() if line.strip()}
    if tags:
        return tags
    remote = _run_git(source, "ls-remote", "--tags", "origin", "refs/tags/v*")
    for line in remote.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        ref = line.rsplit("\t", 1)[-1]
        name = ref.rsplit("/", 1)[-1]
        if name and not name.endswith("^{}"):
            tags.add(name)
    return tags


def find_untagged_changelog_versions(
    changelog_text: str,
    tags: set[str],
    *,
    current_branch: str | None = None,
) -> list[str]:
    """Return dated CHANGELOG.md versions with no matching vX.Y.Z git tag.

    `make release-cut` legitimately drafts a dated section for the version
    being cut before its tag exists (the tag is pushed later, by
    `release-finalize`, after squash-merge to main). So when
    `current_branch` matches the release-branch shape recognised by
    `.github/workflows/validate-main-pr.yml` (`vX.Y.Z[-suffix]`), the one
    untagged version matching that branch's own version number is exempt.

    Every other untagged dated section is flagged - in particular, any
    untagged section found while on `develop`/`main` (current_branch does
    not match the release-branch shape at all) is always flagged
    regardless of version number. This is what would have caught the
    `[0.3.1] - 2026-05-30` accounting drift: that section was committed to
    `develop` directly, never on a `v0.3.1` release branch, and no
    `v0.3.1` tag was ever pushed.
    """
    untagged = [v for v in released_versions_in_changelog(changelog_text) if f"v{v}" not in tags]
    if not untagged:
        return []
    branch_match = _RELEASE_BRANCH_RE.match(current_branch) if current_branch else None
    if branch_match:
        drafted_version = branch_match.group("version")
        untagged = [v for v in untagged if v != drafted_version]
    return untagged


def _current_branch(source: Path) -> str | None:
    result = _run_git(source, "rev-parse", "--abbrev-ref", "HEAD")
    branch = result.stdout.strip()
    if result.returncode == 0 and branch and branch != "HEAD":
        return branch
    # PR CI checks out a detached merge ref; fall back to the PR head ref so
    # the release-branch exemption in the tag-claim guard still applies.
    env_branch = os.environ.get("GITHUB_HEAD_REF", "").strip()
    return env_branch or None


def check_tag_claims(source: Path) -> tuple[bool, list[str]]:
    """Return (ok, untagged_versions) for CHANGELOG.md's tag-claim guard."""
    changelog_path = source / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8")
    tags = existing_tags(source)
    branch = _current_branch(source)
    untagged = find_untagged_changelog_versions(text, tags, current_branch=branch)
    return (not untagged, untagged)


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


def _commits_since_ref(source: Path, since_ref: str) -> list[tuple[str, str]] | None:
    result = _run_git(source, "log", "--format=%H%x00%s%x00", f"{since_ref}..HEAD")
    if result.returncode != 0:
        print(f"  Error: Failed to get git log: {result.stderr}")
        return None
    parts = [part for part in result.stdout.split("\0") if part]
    return [
        (commit_hash.strip(), subject.strip())
        for commit_hash, subject in zip(parts[0::2], parts[1::2], strict=False)
        if commit_hash.strip()
    ]


def _patch_delta_commit_subjects(source: Path, since_ref: str) -> list[str] | None:
    """Return subjects for commits that contribute to the current patch delta.

    `since_ref..HEAD` is ancestry-based. After a squash release to `main`, old
    develop commits are not ancestors of `main`, so ancestry would re-list them.
    Filtering through the actual tree diff keeps the changelog tied to the
    unreleased patch instead.
    """
    commits = _commits_since_ref(source, since_ref)
    if commits is None:
        return None
    if not commits:
        return []

    try:
        entries = _diff_name_status(source, since_ref)
    except subprocess.CalledProcessError as exc:
        print(f"  Error: Failed to diff {since_ref}..HEAD: {exc.stderr}")
        return None

    patch_paths = {path for _status, path in entries}
    if not patch_paths:
        return []

    tree_entry_cache: dict[tuple[str, str], str | None] = {}

    def tree_entry(ref: str, path: str) -> str | None:
        key = (ref, path)
        if key not in tree_entry_cache:
            tree_entry_cache[key] = _tree_entry_at(source, ref, path)
        return tree_entry_cache[key]

    target_entries = {path: tree_entry("HEAD", path) for path in patch_paths}
    base_entries = {path: tree_entry(since_ref, path) for path in patch_paths}
    unresolved_paths = {path for path in patch_paths if target_entries[path] != base_entries[path]}

    patch_commits: set[str] = set()
    for commit_hash, subject in commits:
        if not unresolved_paths:
            break
        result = _run_git(source, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit_hash)
        if result.returncode != 0:
            continue
        candidate_paths = {part for part in result.stdout.split("\0") if part}
        relevant_paths = candidate_paths & unresolved_paths
        parent_ref = f"{commit_hash}^"
        contributing_paths = [
            path
            for path in relevant_paths
            if tree_entry(commit_hash, path) == target_entries[path]
            and tree_entry(parent_ref, path) != target_entries[path]
        ]
        if not contributing_paths:
            continue
        if _conventional_changelog_subject(subject):
            patch_commits.add(commit_hash)
        for path in contributing_paths:
            target_entries[path] = tree_entry(parent_ref, path)
            if target_entries[path] == base_entries[path]:
                unresolved_paths.remove(path)

    if not patch_commits:
        return []

    return [subject for commit_hash, subject in commits if commit_hash in patch_commits]


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

    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        print(f"  Error: {changelog} not found")
        return False

    # An interrupted `make release-cut` leaves the drafted section in place.
    # Re-running the cut must not append a second one, and must not discard a
    # hand-curated section the operator wrote between the two runs.
    if section_body(changelog.read_text(encoding="utf-8"), version) is not None:
        print(f"  CHANGELOG.md already has a [{version}] section; leaving it untouched")
        return True

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
        "--check-tag-claims",
        action="store_true",
        help=(
            "Check CHANGELOG.md for dated released-version sections with no matching "
            "vX.Y.Z git tag, then exit (skips entry generation; --version not required)."
        ),
    )
    parser.add_argument(
        "--check-curation",
        action="store_true",
        help=(
            "Check that the '## [VERSION]' section has been hand-curated (no raw commit "
            "subjects, no placeholder, at most "
            f"{MAX_CURATED_BULLETS} bullets), then exit. Requires --version. "
            "Override with RELEASE_ALLOW_RAW_CHANGELOG=1."
        ),
    )
    parser.add_argument(
        "--version",
        default=None,
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

    if args.check_tag_claims:
        ok, untagged = check_tag_claims(args.source)
        if not ok:
            print("  CHANGELOG.md claims released version(s) with no matching git tag:")
            for version in untagged:
                print(f"    - {version} (expected tag v{version})")
            return 1
        print("  CHANGELOG.md tag-claim guard: OK")
        return 0

    if not args.version:
        parser.error("--version is required unless --check-tag-claims is set")

    if args.check_curation:
        ok, problems = check_changelog_curation(args.source, args.version)
        if ok:
            print(f"  CHANGELOG.md curation guard: OK ([{args.version}] section looks hand-curated)")
            return 0
        print(f"  CHANGELOG.md section [{args.version}] does not look hand-curated:")
        for problem in problems:
            print(f"    - {problem}")
        # The override forgives an uncurated section, not a missing one: with no
        # section at all there is nothing to accept, and the cut would fail later.
        if has_changelog_section(args.source, args.version) and (
            os.environ.get("RELEASE_ALLOW_RAW_CHANGELOG", "").strip().lower() in _TRUE_VALUES
        ):
            print("  RELEASE_ALLOW_RAW_CHANGELOG is set; accepting the section as-is")
            return 0
        print()
        print(f"  Edit the [{args.version}] section in CHANGELOG.md, then re-run the cut:")
        print(f"    make release-cut VERSION={args.version}")
        print("  To accept the raw draft deliberately: RELEASE_ALLOW_RAW_CHANGELOG=1 make release-cut ...")
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
