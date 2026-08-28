"""CHANGELOG.md released-version sections must have a matching git tag.

Pins the guard added by ``release-accounting-drift-correction``: a
``## [X.Y.Z] - <date>`` header is this repo's convention for a *released*
section, and this repo shipped a real accounting drift where a
``## [0.3.1] - 2026-05-30`` section sat on ``develop`` for weeks with no
``v0.3.1`` tag ever pushed and no corresponding PyPI release. The guard
lives in ``scripts/generate_changelog_entry.py`` (the module that already
knows how to detect the latest ``v*`` tag for changelog generation) so the
tag-detection logic has exactly one home.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _load():
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "generate_changelog_entry", SCRIPTS_DIR / "generate_changelog_entry.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gce = _load()

FIXTURE_CHANGELOG = """\
# Changelog

## [Unreleased]

## [0.3.1] - 2026-05-30

### Added

- something

## [0.3.0] - 2026-05-16

### Fixed

- something else

## [0.2.1] - 2026-04-26

### Added

- oldest thing
"""


def test_released_versions_in_changelog_excludes_unreleased():
    versions = gce.released_versions_in_changelog(FIXTURE_CHANGELOG)
    assert versions == ["0.3.1", "0.3.0", "0.2.1"]


def test_find_untagged_versions_flags_missing_tag_on_develop():
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="develop")
    assert untagged == ["0.3.1"]


def test_find_untagged_versions_flags_missing_tag_on_main():
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="main")
    assert untagged == ["0.3.1"]


def test_find_untagged_versions_flags_missing_tag_with_no_branch_info():
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch=None)
    assert untagged == ["0.3.1"]


def test_find_untagged_versions_exempts_in_progress_release_branch_draft():
    # release-cut drafts the CHANGELOG entry for the version being cut
    # before its tag exists; the branch is named after that same version.
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="v0.3.1")
    assert untagged == []


def test_release_branch_exemption_does_not_cover_a_different_untagged_version():
    # A v0.3.2 release branch does not exempt an unrelated, already-merged
    # 0.3.1 section from a prior accounting drift.
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="v0.3.2")
    assert untagged == ["0.3.1"]


def test_release_branch_suffix_is_recognised():
    tags = {"v0.3.0", "v0.2.1"}
    untagged = gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="v0.3.1-rc1")
    assert untagged == []


def test_fully_tagged_changelog_has_no_untagged_versions():
    tags = {"v0.3.1", "v0.3.0", "v0.2.1"}
    assert gce.find_untagged_changelog_versions(FIXTURE_CHANGELOG, tags, current_branch="develop") == []


def test_existing_tags_returns_only_tags_visible_to_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(
        gce,
        "_run_git",
        lambda _source, *args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="v0.3.1\n", stderr=""),
    )
    assert gce.existing_tags(tmp_path) == {"v0.3.1"}


def test_existing_tags_fails_closed_when_local_tag_inspection_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        gce,
        "_run_git",
        lambda _source, *args, **_kwargs: subprocess.CompletedProcess([], 2, stdout="", stderr="not a git repository"),
    )
    with pytest.raises(RuntimeError, match="local release tags"):
        gce.existing_tags(tmp_path)


def test_release_accounting_flags_stale_default_branch_claims():
    errors = gce.find_release_accounting_errors(
        FIXTURE_CHANGELOG,
        {"v0.4.0", "v0.3.1", "v0.3.0"},
        published_version="0.4.0",
        pyproject_version="0.3.1",
        current_branch="develop",
    )
    assert errors == [
        "CHANGELOG.md has no dated [0.4.0] section for published version v0.4.0",
        "CHANGELOG.md [Unreleased] comparison does not start at v0.4.0",
        "pyproject.toml version '0.3.1' does not match published PyPI version v0.4.0",
    ]


def test_release_accounting_accepts_synchronized_default_branch():
    changelog = (
        FIXTURE_CHANGELOG.replace("## [0.3.1]", "## [0.4.0]", 1)
        + "\n[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/v0.4.0...HEAD\n"
    )
    assert (
        gce.find_release_accounting_errors(
            changelog,
            {"v0.4.0", "v0.3.0"},
            published_version="0.4.0",
            pyproject_version="0.4.0",
            current_branch="develop",
        )
        == []
    )


def test_release_accounting_selectively_exempts_in_progress_release_branch_version():
    changelog = FIXTURE_CHANGELOG + "\n[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/v0.3.1...HEAD\n"
    assert (
        gce.find_release_accounting_errors(
            changelog,
            {"v0.3.1", "v0.3.0", "v0.2.1"},
            published_version="0.3.1",
            pyproject_version="0.4.0",
            current_branch="v0.4.0",
        )
        == []
    )


def test_release_accounting_release_branch_still_checks_tag_section_and_compare_link():
    errors = gce.find_release_accounting_errors(
        FIXTURE_CHANGELOG,
        {"v0.4.0", "v0.3.1", "v0.3.0"},
        published_version="0.4.0",
        pyproject_version="0.5.0",
        current_branch="v0.5.0",
    )
    assert errors == [
        "CHANGELOG.md has no dated [0.4.0] section for published version v0.4.0",
        "CHANGELOG.md [Unreleased] comparison does not start at v0.4.0",
    ]


def test_release_accounting_release_branch_only_exempts_its_own_project_version():
    changelog = FIXTURE_CHANGELOG + "\n[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/v0.3.1...HEAD\n"
    errors = gce.find_release_accounting_errors(
        changelog,
        {"v0.3.1", "v0.3.0", "v0.2.1"},
        published_version="0.3.1",
        pyproject_version="0.4.1",
        current_branch="v0.4.0",
    )
    assert errors == ["pyproject.toml version '0.4.1' does not match release branch v0.4.0"]


def test_release_accounting_does_not_infer_pypi_publication_from_a_newer_git_tag():
    changelog = FIXTURE_CHANGELOG + "\n[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/v0.3.1...HEAD\n"
    assert (
        gce.find_release_accounting_errors(
            changelog,
            {"v0.4.0", "v0.3.1", "v0.3.0"},
            published_version="0.3.1",
            pyproject_version="0.3.1",
            current_branch="develop",
        )
        == []
    )


def test_release_accounting_fails_closed_for_partial_tags_missing_published_version():
    changelog = (
        FIXTURE_CHANGELOG.replace("## [0.3.1]", "## [0.4.0]", 1)
        + "\n[Unreleased]: https://github.com/BenchBox-dev/BenchBox/compare/v0.4.0...HEAD\n"
    )
    errors = gce.find_release_accounting_errors(
        changelog,
        {"v0.3.1", "v0.3.0"},
        published_version="0.4.0",
        pyproject_version="0.4.0",
        current_branch="develop",
    )
    assert errors == ["published PyPI version 0.4.0 has no visible git tag v0.4.0"]


def test_release_accounting_rejects_invalid_published_version():
    errors = gce.find_release_accounting_errors(
        FIXTURE_CHANGELOG,
        {"v0.4.0-rc1"},
        published_version="0.4.0-rc1",
        pyproject_version="0.4.0-rc1",
        current_branch="develop",
    )
    assert errors == ["published version '0.4.0-rc1' is not a stable X.Y.Z version"]


def test_repo_changelog_has_no_untagged_released_section_on_this_branch():
    """Guard the actual repo state: no dated CHANGELOG.md section should
    claim a version without a matching tag, unless this happens to be run
    from an in-progress release branch for that exact version."""
    ok, untagged = gce.check_tag_claims(REPO_ROOT)
    assert ok, f"CHANGELOG.md claims untagged version(s): {untagged}"


def test_repo_release_accounting_matches_v040_published_state():
    ok, errors = gce.check_release_accounting(REPO_ROOT, "0.4.0")
    assert ok, "\n".join(errors)


def test_current_branch_falls_back_to_github_head_ref(tmp_path, monkeypatch):
    """On a detached-HEAD PR checkout, the release-branch exemption must come
    from GITHUB_HEAD_REF (set by Actions for pull_request events)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "--detach"], check=True)

    monkeypatch.setenv("GITHUB_HEAD_REF", "v9.9.9")
    assert gce._current_branch(tmp_path) == "v9.9.9"

    monkeypatch.delenv("GITHUB_HEAD_REF")
    assert gce._current_branch(tmp_path) is None
