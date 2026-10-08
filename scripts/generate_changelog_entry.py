#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

CLAUDE_TIMEOUT_SECONDS = 120

_NESTED_CLAUDE_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

MAX_CURATED_BULLETS = 45
MAX_CURATED_LINES = 160
RAW_PLACEHOLDER = "(no user-facing changes detected -- please edit manually)"
_PR_SUFFIX_RE = re.compile(r"\(#\d+\)\s*$")
_BULLET_RE = re.compile(r"^\s*- \S")

_CHANGELOG_VERSION_HEADER_RE = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - ", re.MULTILINE)

_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*["\'](?P<version>[^"\']+)["\']', re.MULTILINE)
_STABLE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PYPI_RELEASE_URL = "https://pypi.org/pypi/benchbox/json"

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
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover
            proc.kill()
    except (ProcessLookupError, PermissionError):  # pragma: no cover
        proc.kill()


def _run_claude_cli(prompt: str) -> subprocess.CompletedProcess[str]:
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
    return [m.group("version") for m in _CHANGELOG_VERSION_HEADER_RE.finditer(changelog_text)]


def section_body(changelog_text: str, version: str) -> str | None:
    header = re.search(rf"^## \[{re.escape(version)}\] - .*$", changelog_text, re.MULTILINE)
    if header is None:
        return None
    rest = changelog_text[header.end() :]
    following = re.search(r"^## \[", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


def has_changelog_section(source: Path, version: str) -> bool:
    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        return False
    return section_body(changelog.read_text(encoding="utf-8"), version) is not None


def curated_section_from_file(path: Path, version: str, release_date: str) -> tuple[str | None, str | None]:
    try:
        body = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return None, f"cannot read curated section file {path}: {exc}"
    if not body:
        return None, f"curated section file {path} is empty"
    if re.search(r"^## ", body, re.MULTILINE):
        return None, f"curated section file {path} must hold the section body only, without a '## ' version header"
    return f"## [{version}] - {release_date}\n\n{body}\n", None


def _insert_section(content: str, new_section: str) -> str:
    first_release = re.search(r"^## \[\d", content, re.MULTILINE)
    if first_release is None:
        return content.rstrip() + "\n\n" + new_section
    return content[: first_release.start()] + new_section + "\n" + content[first_release.start() :]


def _replace_section(content: str, version: str, new_section: str) -> str:
    header = re.search(rf"^## \[{re.escape(version)}\] - .*$", content, re.MULTILINE)
    assert header is not None
    following = re.search(r"^## \[", content[header.end() :], re.MULTILINE)
    end = header.end() + following.start() if following else len(content)
    return content[: header.start()] + new_section + ("\n" if following else "") + content[end:]


def _write_curated_section(changelog: Path, version: str, release_date: str, section_file: Path) -> bool:
    new_section, error = curated_section_from_file(section_file, version, release_date)
    if new_section is None:
        print(f"  Error: {error}")
        return False
    content = changelog.read_text(encoding="utf-8")
    if section_body(content, version) is None:
        content = _insert_section(content, new_section)
        print(f"  Wrote the [{version}] section from {section_file}")
    else:
        content = _replace_section(content, version, new_section)
        print(f"  Replaced the existing [{version}] section with {section_file}")
    changelog.write_text(content, encoding="utf-8")
    return True


def check_changelog_curation(source: Path, version: str) -> tuple[bool, list[str]]:
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
    body_lines = len(body.splitlines())
    if body_lines > MAX_CURATED_LINES:
        problems.append(f"{body_lines} lines exceeds the {MAX_CURATED_LINES}-line curated ceiling")
    return (not problems), problems


def curated_section_body(source: Path, version: str) -> tuple[str | None, list[str]]:
    ok, problems = check_changelog_curation(source, version)
    if not ok:
        return None, problems
    body = section_body((source / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    if body is None or not body.strip():
        return None, ["section body is empty"]
    return body.strip(), []


def existing_tags(source: Path) -> set[str]:
    local = _run_git(source, "tag", "-l", "v*")
    if local.returncode != 0:
        raise RuntimeError(f"could not inspect local release tags: {local.stderr.strip() or 'git tag failed'}")
    tags = {line.strip() for line in local.stdout.splitlines() if line.strip()}

    shallow = _run_git(source, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        raise RuntimeError(f"could not inspect checkout depth: {shallow.stderr.strip() or 'git rev-parse failed'}")
    is_shallow = shallow.stdout.strip() == "true"
    if tags and not is_shallow:
        return tags

    remote = _run_git(source, "ls-remote", "--tags", "origin", "refs/tags/v*")
    if remote.returncode != 0:
        reason = remote.stderr.strip() or "git ls-remote failed"
        raise RuntimeError(f"could not discover release tags from origin: {reason}")
    for line in remote.stdout.splitlines():
        ref = line.strip().rsplit("\t", 1)[-1]
        name = ref.rsplit("/", 1)[-1]
        if name and not name.endswith("^{}"):
            tags.add(name)
    if not tags:
        raise RuntimeError("no release tags were discovered locally or on origin")
    return tags


def find_untagged_changelog_versions(
    changelog_text: str,
    tags: set[str],
    *,
    current_branch: str | None = None,
) -> list[str]:
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
    env_branch = os.environ.get("GITHUB_HEAD_REF", "").strip()
    return env_branch or None


def check_tag_claims(source: Path) -> tuple[bool, list[str]]:
    changelog_path = source / "CHANGELOG.md"
    text = changelog_path.read_text(encoding="utf-8")
    tags = existing_tags(source)
    branch = _current_branch(source)
    untagged = find_untagged_changelog_versions(text, tags, current_branch=branch)
    return (not untagged, untagged)


def latest_published_version() -> str:
    try:
        with urllib.request.urlopen(_PYPI_RELEASE_URL, timeout=15) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read published BenchBox version from PyPI: {exc}") from exc

    version = payload.get("info", {}).get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not _STABLE_VERSION_RE.fullmatch(version):
        raise RuntimeError(f"PyPI returned an invalid stable BenchBox version: {version!r}")
    return version


def find_release_accounting_errors(
    changelog_text: str,
    tags: set[str],
    *,
    published_version: str,
    pyproject_version: str | None,
    current_branch: str | None = None,
) -> list[str]:
    if not _STABLE_VERSION_RE.fullmatch(published_version):
        return [f"published version {published_version!r} is not a stable X.Y.Z version"]
    tag = f"v{published_version}"

    errors: list[str] = []
    if tag not in tags:
        errors.append(f"published PyPI version {published_version} has no visible git tag {tag}")

    if published_version not in released_versions_in_changelog(changelog_text):
        errors.append(f"CHANGELOG.md has no dated [{published_version}] section for published version {tag}")

    expected_compare = f"[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/{tag}...HEAD"
    if expected_compare not in changelog_text:
        errors.append(f"CHANGELOG.md [Unreleased] comparison does not start at {tag}")

    branch_match = _RELEASE_BRANCH_RE.fullmatch(current_branch) if current_branch else None
    expected_project_version = branch_match.group("version") if branch_match else published_version
    if pyproject_version != expected_project_version:
        expectation = f"release branch v{expected_project_version}" if branch_match else f"published PyPI version {tag}"
        errors.append(f"pyproject.toml version {pyproject_version!r} does not match {expectation}")

    return errors


def check_release_accounting(source: Path, published_version: str) -> tuple[bool, list[str]]:
    changelog_text = (source / "CHANGELOG.md").read_text(encoding="utf-8")
    pyproject_text = (source / "pyproject.toml").read_text(encoding="utf-8")
    version_match = _PYPROJECT_VERSION_RE.search(pyproject_text)
    pyproject_version = version_match.group("version") if version_match else None
    errors = find_release_accounting_errors(
        changelog_text,
        existing_tags(source),
        published_version=published_version,
        pyproject_version=pyproject_version,
        current_branch=_current_branch(source),
    )
    return (not errors, errors)


def update_github_release_notes(source: Path, version: str, body: str) -> None:
    tag = f"v{version}"
    notes_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as notes_file:
            notes_file.write(body.strip() + "\n")
            notes_path = Path(notes_file.name)
        result = subprocess.run(
            ["gh", "release", "edit", tag, "--notes-file", str(notes_path)],
            cwd=source,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            reason = result.stderr.strip() or result.stdout.strip() or "gh release edit failed"
            raise RuntimeError(f"could not update GitHub Release {tag}: {reason}")
    finally:
        if notes_path is not None:
            notes_path.unlink(missing_ok=True)


def _publishable_body_or_report(source: Path, version: str) -> str | None:
    body, problems = curated_section_body(source, version)
    if body is not None:
        return body
    print(f"  Error: CHANGELOG.md section [{version}] is not publishable:", file=sys.stderr)
    for problem in problems:
        print(f"    - {problem}", file=sys.stderr)
    return None


def _run_release_accounting_check(source: Path) -> int:
    try:
        published_version = latest_published_version()
        ok, errors = check_release_accounting(source, published_version)
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1
    if not ok:
        print(f"  Repository accounting does not match published PyPI version v{published_version}:")
        for error in errors:
            print(f"    - {error}")
        return 1
    print(f"  Published-release accounting guard: OK (PyPI v{published_version})")
    return 0


def _run_release_notes_sync(source: Path, version: str) -> int:
    body = _publishable_body_or_report(source, version)
    if body is None:
        return 1
    try:
        update_github_release_notes(source, version, body)
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 1
    print(f"  Updated GitHub Release v{version} from curated CHANGELOG.md notes")
    return 0


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
    section_file: Path | None = None,
) -> bool:
    print(f"\n  Auto-generating changelog entry for v{version}...")

    changelog = source / "CHANGELOG.md"
    if not changelog.exists():
        print(f"  Error: {changelog} not found")
        return False

    if section_file is not None:
        return _write_curated_section(changelog, version, release_date, section_file)

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

    content = _insert_section(changelog.read_text(), new_section)
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
        "--check-release-accounting",
        action="store_true",
        help=(
            "Read the current published version from PyPI and verify its git tag, "
            "CHANGELOG.md section, [Unreleased] comparison, and project version."
        ),
    )
    parser.add_argument(
        "--check-curation",
        action="store_true",
        help=(
            "Check that the '## [VERSION]' section has been hand-curated (no raw commit "
            "subjects, no placeholder, at most "
            f"{MAX_CURATED_BULLETS} bullets and {MAX_CURATED_LINES} lines), then exit. "
            "Requires --version. Override with RELEASE_ALLOW_RAW_CHANGELOG=1."
        ),
    )
    parser.add_argument(
        "--print-section",
        action="store_true",
        help="Print the curated CHANGELOG.md body for --version, then exit.",
    )
    parser.add_argument(
        "--sync-github-release-notes",
        action="store_true",
        help="Replace the existing GitHub Release notes for vVERSION with the curated section.",
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
        help="Lower-bound ref for commit range, e.g. origin/release. Overrides --since-tag.",
    )
    parser.add_argument(
        "--section-file",
        type=Path,
        default=None,
        help=(
            "Write the [VERSION] section from this hand-curated body (the ### groups and bullets, "
            "no version header) instead of generating a draft. Replaces an existing [VERSION] section. "
            "--check-curation still checks the result."
        ),
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

    if args.check_release_accounting:
        return _run_release_accounting_check(args.source)

    if not args.version:
        parser.error("--version is required unless a check-only option is set")

    if args.print_section:
        body = _publishable_body_or_report(args.source, args.version)
        if body is None:
            return 1
        print(body)
        return 0

    if args.sync_github_release_notes:
        return _run_release_notes_sync(args.source, args.version)

    if args.check_curation:
        ok, problems = check_changelog_curation(args.source, args.version)
        if ok:
            print(f"  CHANGELOG.md curation guard: OK ([{args.version}] section looks hand-curated)")
            return 0
        print(f"  CHANGELOG.md section [{args.version}] does not look hand-curated:")
        for problem in problems:
            print(f"    - {problem}")
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
        section_file=args.section_file,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
