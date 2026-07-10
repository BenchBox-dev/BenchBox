"""Tests for release changelog generation."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_changelog_entry.py"

spec = importlib.util.spec_from_file_location("generate_changelog_entry", SCRIPT_PATH)
assert spec is not None
generate_changelog_entry = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(generate_changelog_entry)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit(repo: Path, message: str, filename: str, content: str) -> None:
    path = repo / filename
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def test_since_ref_limits_release_changelog_to_main_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Release branches should summarize changes absent from main, not all reachable commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "chore: initial")
    initial_commit = _git(repo, "rev-parse", "HEAD")

    _git(repo, "branch", "-M", "main")
    _commit(repo, "fix: main-only release hardening", "main.txt", "main\n")

    _git(repo, "checkout", "-b", "develop", initial_commit)
    _commit(repo, "feat: add broad release feature", "feature.txt", "feature\n")
    _commit(repo, "fix: repair clean install", "fix.txt", "fix\n")

    monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)

    assert generate_changelog_entry.generate_changelog_entry(
        repo,
        version="0.3.1",
        release_date="2026-05-26",
        since_ref="main",
    )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.3.1] - 2026-05-26" in changelog
    assert "- add broad release feature" in changelog
    assert "- repair clean install" in changelog
    assert "main-only release hardening" not in changelog


def test_since_ref_ignores_commits_already_present_via_squash_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A squash-merged release on main must not make old develop commits reappear."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "chore: initial")
    _git(repo, "branch", "-M", "main")

    _git(repo, "checkout", "-b", "develop")
    _commit(repo, "feat: already released feature", "released_feature.txt", "feature\n")
    _commit(repo, "fix: already released fix", "released_fix.txt", "fix\n")

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--squash", "develop")
    _git(repo, "commit", "-m", "Release v0.3.1")

    _git(repo, "checkout", "develop")
    _commit(repo, "feat: add next release feature", "next_feature.txt", "next\n")

    monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)

    assert generate_changelog_entry.generate_changelog_entry(
        repo,
        version="0.3.2",
        release_date="2026-05-31",
        since_ref="main",
    )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- add next release feature" in changelog
    assert "already released feature" not in changelog
    assert "already released fix" not in changelog


def test_since_ref_ignores_squashed_commit_when_new_patch_touches_same_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later same-file patch must not pull already released commit subjects back in."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "chore: initial")
    _git(repo, "branch", "-M", "main")

    _git(repo, "checkout", "-b", "develop")
    _commit(repo, "feat: already released same-file feature", "f.txt", "released\n")

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--squash", "develop")
    _git(repo, "commit", "-m", "Release v0.3.1")

    _git(repo, "checkout", "develop")
    _commit(repo, "fix: add next same-file patch", "f.txt", "released\nnext\n")

    monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)

    assert generate_changelog_entry.generate_changelog_entry(
        repo,
        version="0.3.2",
        release_date="2026-05-31",
        since_ref="main",
    )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- add next same-file patch" in changelog
    assert "already released same-file feature" not in changelog


def test_since_ref_ignores_intermediate_squashed_same_file_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intermediate same-file states from a squashed release must stay released."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "chore: initial")
    _git(repo, "branch", "-M", "main")

    _git(repo, "checkout", "-b", "develop")
    _commit(repo, "feat: already released same-file feature", "f.txt", "A\n")
    _commit(repo, "fix: already released same-file fix", "f.txt", "A\nB\n")

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--squash", "develop")
    _git(repo, "commit", "-m", "Release v0.3.1")

    _git(repo, "checkout", "develop")
    _commit(repo, "fix: add next same-file patch", "f.txt", "A\nB\nC\n")

    monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)

    assert generate_changelog_entry.generate_changelog_entry(
        repo,
        version="0.3.2",
        release_date="2026-05-31",
        since_ref="main",
    )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- add next same-file patch" in changelog
    assert "already released same-file feature" not in changelog
    assert "already released same-file fix" not in changelog


class TestSummarizeSkipReason:
    """`claude --print` must never be spawned from inside a Claude Code session.

    The v0.3.1 cut hung twice on the nested CLI call, leaving an orphaned
    make/uv/python tree and a half-applied cut.
    """

    def test_nested_session_skips_summarization(self) -> None:
        for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID"):
            reason = generate_changelog_entry.summarize_skip_reason({var: "1"})
            assert reason is not None and var in reason

    def test_outside_session_runs_summarization(self) -> None:
        assert generate_changelog_entry.summarize_skip_reason({}) is None

    def test_explicit_opt_in_overrides_nesting(self) -> None:
        env = {"CLAUDECODE": "1", "BENCHBOX_CHANGELOG_SUMMARIZE": "1"}
        assert generate_changelog_entry.summarize_skip_reason(env) is None

    def test_explicit_opt_out_wins_outside_session(self) -> None:
        env = {"BENCHBOX_CHANGELOG_SUMMARIZE": "0"}
        assert generate_changelog_entry.summarize_skip_reason(env) is not None

    def test_skipped_summarization_never_spawns_a_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("BENCHBOX_CHANGELOG_SUMMARIZE", raising=False)

        def _explode(*args: object, **kwargs: object) -> None:
            raise AssertionError("nested claude CLI must not be spawned")

        monkeypatch.setattr(generate_changelog_entry.subprocess, "Popen", _explode)
        assert generate_changelog_entry._summarize_changelog_with_claude("0.3.1", "2026-07-09", ["a"], [], []) is None

    def test_claude_cli_runs_in_its_own_process_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A timeout must be able to kill grandchildren holding the stdout pipe."""
        captured: dict[str, object] = {}

        class _FakeProc:
            args = ["claude"]
            returncode = 0

            def __enter__(self) -> _FakeProc:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                return ("### Added\n- x\n", "")

        def _fake_popen(cmd: list[str], **kwargs: object) -> _FakeProc:
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(generate_changelog_entry.subprocess, "Popen", _fake_popen)
        generate_changelog_entry._run_claude_cli("prompt")
        assert captured["start_new_session"] is True
        assert captured["stdin"] is generate_changelog_entry.subprocess.DEVNULL


class TestChangelogCurationGuard:
    """`EDITOR=true` used to wave a raw commit dump straight into a release."""

    def _write(self, repo: Path, body: str) -> None:
        (repo / "CHANGELOG.md").write_text(body, encoding="utf-8")

    def test_raw_commit_subjects_are_rejected(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "## [0.3.1] - 2026-07-09\n\n### Fixed\n\n- restore auto_merge_soundness_paths (#1086)\n",
        )
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
        assert any("verbatim commit subjects" in p for p in problems)

    def test_manual_edit_placeholder_is_rejected(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            f"## [0.3.1] - 2026-07-09\n\n### Added\n\n- {generate_changelog_entry.RAW_PLACEHOLDER}\n",
        )
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
        assert any("placeholder" in p for p in problems)

    def test_bullet_ceiling_is_enforced(self, tmp_path: Path) -> None:
        bullets = "\n".join(f"- change number {i}" for i in range(generate_changelog_entry.MAX_CURATED_BULLETS + 1))
        self._write(tmp_path, f"## [0.3.1] - 2026-07-09\n\n### Added\n\n{bullets}\n")
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
        assert any("ceiling" in p for p in problems)

    def test_missing_section_is_rejected(self, tmp_path: Path) -> None:
        self._write(tmp_path, "## [0.3.0] - 2026-05-16\n\n### Added\n\n- **Thing** - does things.\n")
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
        assert "no '## [0.3.1] - <date>' section found" in problems[0]

    def test_curated_section_passes(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "## [0.3.1] - 2026-07-09\n\n### Fixed\n\n"
            "- **Release bootstrap** - validate-base now restores its helper module.\n\n"
            "## [0.3.0] - 2026-05-16\n\n### Added\n\n- Older entry (#1) still ignored.\n",
        )
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert ok, problems

    def test_every_shipped_changelog_section_passes_the_guard(self) -> None:
        """The ceiling is calibrated on real releases, not on the prompt's target.

        0.2.1 shipped 39 hand-curated bullets; a tighter ceiling would reject it.
        """
        repo_root = Path(__file__).resolve().parents[3]
        text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
        for version in generate_changelog_entry.released_versions_in_changelog(text):
            ok, problems = generate_changelog_entry.check_changelog_curation(repo_root, version)
            assert ok, f"shipped section [{version}] fails the curation guard: {problems}"


class TestChangelogGenerationIsIdempotent:
    """Re-running an interrupted `make release-cut` must not double-insert."""

    def test_existing_section_is_left_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        _commit(repo, "feat: a new feature", "f.txt", "A\n")

        curated = "## [0.3.1] - 2026-07-09\n\n### Added\n\n- **Curated** - written by hand.\n"
        (repo / "CHANGELOG.md").write_text(curated, encoding="utf-8")

        monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)
        assert generate_changelog_entry.generate_changelog_entry(repo, version="0.3.1", release_date="2026-07-09")

        text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        assert text == curated
        assert text.count("## [0.3.1]") == 1


class TestCurationOverrideScope:
    """RELEASE_ALLOW_RAW_CHANGELOG forgives an uncurated section, not a missing one."""

    def test_missing_changelog_reports_cleanly(self, tmp_path: Path) -> None:
        ok, problems = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
        assert "not found" in problems[0]

    def test_override_does_not_apply_without_a_section(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text("## [0.3.0] - 2026-05-16\n\n- **X** - y.\n", encoding="utf-8")
        assert not generate_changelog_entry.has_changelog_section(tmp_path, "0.3.1")
        assert generate_changelog_entry.has_changelog_section(tmp_path, "0.3.0")

    def test_override_applies_to_a_raw_section(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text("## [0.3.1] - 2026-07-09\n\n- raw subject (#1086)\n", encoding="utf-8")
        assert generate_changelog_entry.has_changelog_section(tmp_path, "0.3.1")
        ok, _ = generate_changelog_entry.check_changelog_curation(tmp_path, "0.3.1")
        assert not ok
