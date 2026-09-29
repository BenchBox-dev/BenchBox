"""Tests for the tag-on-develop release preparation and pre-tag check."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"

spec = importlib.util.spec_from_file_location("release_flow", SCRIPTS / "release_flow.py")
release_flow = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = release_flow
spec.loader.exec_module(release_flow)

VERSION = "1.2.3"

CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.3] - 2026-01-01

### Added

- A hand-curated entry that describes a user-visible change.

## [1.2.2] - 2025-12-01

### Added

- Earlier entry.
"""

LOCK = """version = 1
revision = 3
requires-python = ">=3.11"

[[package]]
name = "benchbox"
version = "{version}"
source = {{ editable = "." }}
"""

LANDING = """<a
    href="https://example.invalid/releases"
    class="badge badge-version"
    >v{version}</a
>
"""


def write_tree(root: Path, version: str = VERSION) -> Path:
    """Write the minimum tree the version, changelog, and lock checks read."""
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for name in ("update_version.py", "generate_changelog_entry.py", "release_flow.py"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    (root / "benchbox" / "utils").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "landing").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "benchbox"\nversion = "{version}"\nrequires-python = ">=3.11"\n\n'
        '[tool.ruff]\ntarget-version = "py311"\n',
        encoding="utf-8",
    )
    (root / "benchbox" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (root / "README.md").write_text(f"# BenchBox\n\nCurrent release: v{version}.\n", encoding="utf-8")
    (root / "docs" / "README.md").write_text(f"Current release: `v{version}`. More text.\n", encoding="utf-8")
    (root / "benchbox" / "utils" / "VERSION_MANAGEMENT.md").write_text(
        f"Current release: `v{version}`.\n", encoding="utf-8"
    )
    (root / "landing" / "index.html").write_text(LANDING.format(version=version), encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "uv.lock").write_text(LOCK.format(version=version), encoding="utf-8")
    return root


def ok_runner(argv, cwd):  # noqa: ARG001
    return 0, ""


def failing_runner(script_name: str):
    def runner(argv, cwd):  # noqa: ARG001
        if any(Path(part).name == script_name for part in argv):
            return 1, f"{script_name} failed"
        return 0, ""

    return runner


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return write_tree(tmp_path)


def test_check_passes_when_every_element_is_present(tree: Path) -> None:
    assert release_flow.run_checks(tree, VERSION, ok_runner) == []


@pytest.mark.parametrize(
    ("relative_path", "needle", "replacement", "expected"),
    [
        ("pyproject.toml", f'version = "{VERSION}"', 'version = "1.2.4"', "pyproject.toml"),
        ("benchbox/__init__.py", VERSION, "1.2.4", "benchbox/__init__.py"),
        ("README.md", f"v{VERSION}", "v1.2.4", "README.md"),
        ("docs/README.md", f"v{VERSION}", "v1.2.4", "docs/README.md"),
        ("benchbox/utils/VERSION_MANAGEMENT.md", f"v{VERSION}", "v1.2.4", "VERSION_MANAGEMENT.md"),
        ("landing/index.html", f"v{VERSION}", "v1.2.4", "landing/index.html"),
        ("uv.lock", f'version = "{VERSION}"', 'version = "1.2.4"', "uv.lock"),
    ],
)
def test_check_fails_when_a_version_marker_is_stale(
    tree: Path, relative_path: str, needle: str, replacement: str, expected: str
) -> None:
    path = tree / relative_path
    path.write_text(path.read_text(encoding="utf-8").replace(needle, replacement, 1), encoding="utf-8")

    problems = release_flow.run_checks(tree, VERSION, ok_runner)

    assert any(expected in problem for problem in problems), problems


@pytest.mark.parametrize("relative_path", ["README.md", "landing/index.html", "uv.lock"])
def test_check_fails_when_a_version_marker_is_missing(tree: Path, relative_path: str) -> None:
    (tree / relative_path).write_text("nothing here\n", encoding="utf-8")

    problems = release_flow.run_checks(tree, VERSION, ok_runner)

    assert any(relative_path in problem for problem in problems), problems


def test_check_compares_lock_version_as_pep440(tmp_path: Path) -> None:
    root = write_tree(tmp_path, "1.3.0-rc.1")
    (root / "uv.lock").write_text(LOCK.format(version="1.3.0rc1"), encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG.replace("1.2.3", "1.3.0-rc.1", 1), encoding="utf-8")

    assert release_flow.check_version_markers(root, "1.3.0-rc.1") == []


def test_check_fails_when_the_changelog_entry_is_missing(tree: Path) -> None:
    (tree / "CHANGELOG.md").write_text(CHANGELOG.replace("## [1.2.3]", "## [1.2.0]"), encoding="utf-8")

    problems = release_flow.run_checks(tree, VERSION, ok_runner)

    assert any("no '## [1.2.3]" in problem for problem in problems), problems


def test_check_fails_when_the_changelog_entry_is_an_uncurated_draft(tree: Path) -> None:
    draft = CHANGELOG.replace(
        "- A hand-curated entry that describes a user-visible change.",
        "- add a thing (#123)",
    )
    (tree / "CHANGELOG.md").write_text(draft, encoding="utf-8")

    problems = release_flow.run_checks(tree, VERSION, ok_runner)

    assert any("verbatim commit subjects" in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("script_name", "label"),
    [
        ("check_uv_lock_revision.py", "uv.lock revision"),
        ("check_release_curation.py", "release curation"),
        ("check_dependency_bounds.py", "dependency bounds"),
    ],
)
def test_check_fails_when_a_delegated_check_fails(tree: Path, script_name: str, label: str) -> None:
    problems = release_flow.run_checks(tree, VERSION, failing_runner(script_name))

    assert len(problems) == 1
    assert problems[0].startswith(label)


def test_dependency_bounds_check_blocks_on_cap_reached(tree: Path) -> None:
    seen: list[list[str]] = []

    def runner(argv, cwd):  # noqa: ARG001
        seen.append(list(argv))
        return 0, ""

    release_flow.run_checks(tree, VERSION, runner)

    bounds = next(argv for argv in seen if Path(argv[1]).name == "check_dependency_bounds.py")
    assert "--fail-on=cap-reached" in bounds


def test_check_rejects_an_invalid_version(tree: Path) -> None:
    assert release_flow.run_checks(tree, "not-a-version", ok_runner)


def test_cli_check_reports_all_problems_and_exits_nonzero(tree: Path) -> None:
    (tree / "README.md").write_text("no marker\n", encoding="utf-8")
    (tree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "release_flow.py"), "check", "--version", VERSION, "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "README.md" in result.stderr
    assert "CHANGELOG.md" in result.stderr


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("git") is None, reason="needs uv and git")
def test_prep_updates_every_marker_and_drafts_the_changelog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixture release, never a real one: prep yields exactly the files check reads."""
    monkeypatch.setenv("BENCHBOX_CHANGELOG_SUMMARIZE", "0")
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    root = write_tree(tmp_path, "1.2.2")
    (root / "CHANGELOG.md").write_text(CHANGELOG.split("## [1.2.3]")[0] + "## [1.2.2] - 2025-12-01\n", encoding="utf-8")
    # Offline-resolvable lock: the fixture project has no dependencies.
    subprocess.run(["uv", "lock", "--offline"], cwd=root, check=True, capture_output=True)
    git(root, "init", "-q")
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "chore: initial")
    git(root, "tag", "v1.2.2")
    (root / "feature.txt").write_text("new\n", encoding="utf-8")
    git(root, "add", "feature.txt")
    git(root, "commit", "-q", "-m", "feat: add a fixture feature")
    before = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    assert before == ""

    code = release_flow.prep(root, VERSION, None, "2026-02-03", release_flow.run_command)

    assert code == 0
    changed = set(
        subprocess.run(
            ["git", "diff", "--name-only"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    assert changed == {
        "pyproject.toml",
        "uv.lock",
        "CHANGELOG.md",
        "benchbox/__init__.py",
        "README.md",
        "docs/README.md",
        "benchbox/utils/VERSION_MANAGEMENT.md",
        "landing/index.html",
    }
    assert release_flow.check_version_markers(root, VERSION) == []
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.2.3] - 2026-02-03" in changelog
    assert "add a fixture feature" in changelog


def test_prep_stops_at_the_first_failing_step(tree: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv, cwd):  # noqa: ARG001
        calls.append(list(argv))
        return 3, "boom"

    assert release_flow.prep(tree, VERSION, "refs/tags/v1.2.2", None, runner) == 3
    assert len(calls) == 1
    assert Path(calls[0][1]).name == "update_version.py"


def test_prep_passes_the_requested_lower_bound_to_the_changelog_step(tree: Path) -> None:
    calls: list[list[str]] = []

    def runner(argv, cwd):  # noqa: ARG001
        calls.append(list(argv))
        return 0, ""

    assert release_flow.prep(tree, VERSION, "origin/develop~5", None, runner) == 0

    changelog = next(argv for argv in calls if Path(argv[1]).name == "generate_changelog_entry.py")
    assert changelog[changelog.index("--since-ref") + 1] == "origin/develop~5"
    assert any(argv[:2] == ["uv", "lock"] for argv in calls)


def test_make_targets_exist_and_legacy_release_targets_are_kept() -> None:
    def dry_run(target: str, version: str = VERSION) -> str:
        return subprocess.run(
            ["make", "-n", target, f"VERSION={version}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    assert "release_flow.py check --version" in dry_run("release-check")
    assert "release_flow.py prep --version" in dry_run("release-prep")
    assert "release_finalize.py" in dry_run("release-finalize")
    assert "release_cut_start.sh" in dry_run("release-cut")
