from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.release.workflow import compute_source_fingerprint, prepare_public_release

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def temp_source(tmp_path: Path) -> Path:
    # create minimal source tree
    (tmp_path / "benchbox/platforms").mkdir(parents=True)
    (tmp_path / "benchbox/platforms/__init__.py").write_text("# platforms\n", encoding="utf-8")
    (tmp_path / "benchbox/__init__.py").write_text("__version__='0.1.0'\n", encoding="utf-8")
    (tmp_path / "benchbox/release").mkdir(parents=True)
    (tmp_path / "benchbox/release/sync.py").write_text("def cmd_push():\n    return 0\n", encoding="utf-8")
    (tmp_path / "benchbox/core/explorer_pipeline").mkdir(parents=True)
    (tmp_path / "benchbox/core/explorer_pipeline/__init__.py").write_text("# explorer pipeline\n", encoding="utf-8")
    (tmp_path / "benchbox/cli/commands").mkdir(parents=True)
    (tmp_path / "benchbox/cli/commands/__init__.py").write_text(
        """from .df_tuning import df_tuning_group
from .download_answers import download_answers
from .explorer import explorer_group
from .export import export

COMMANDS = (
    df_tuning_group,
    explorer_group,
    export,
)

__all__ = [
    "df_tuning_group",
    "explorer_group",
    "export",
]
""",
        encoding="utf-8",
    )
    (tmp_path / "benchbox/cli/commands/explorer.py").write_text("explorer_group = object()\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='benchbox'\n", encoding="utf-8")
    (tmp_path / "MANIFEST.in").write_text("include README.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Private README\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts =\n    -p _benchbox_pytest_xdist_safety\n", encoding="utf-8"
    )
    (tmp_path / "pytest-ci.ini").write_text(
        "[pytest]\naddopts =\n    -p _benchbox_pytest_xdist_safety\n    -n auto\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/dummy.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "scripts/prepare_release.py").write_text(
        "from benchbox.release.workflow import prepare_public_release\n", encoding="utf-8"
    )
    (tmp_path / "tests/unit/core/explorer_pipeline").mkdir(parents=True)
    (tmp_path / "tests/unit/core/explorer_pipeline/test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/unit/release").mkdir(parents=True)
    (tmp_path / "tests/unit/release/test_workflow.py").write_text(
        "from benchbox.release.workflow import prepare_public_release\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/unit/test_xdist_safety.py").write_text(
        "import _benchbox_pytest_xdist_safety\n", encoding="utf-8"
    )
    (tmp_path / "docs/development").mkdir(parents=True)
    (tmp_path / "docs/development/results-explorer-brand-ownership.md").write_text("# private doc\n", encoding="utf-8")
    (tmp_path / "docs/development/results-explorer-browser-testing.md").write_text("# private doc\n", encoding="utf-8")
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/test.yml").write_text(
        """name: Tests

jobs:
  parity:
    runs-on: ubuntu-latest
    steps:
      - name: Install Node dependencies
        run: npm ci
        working-directory: results-explorer

  test:
    runs-on: ubuntu-latest
    steps:
      - run: uv run -- python -m pytest -m fast -q
""",
        encoding="utf-8",
    )
    (tmp_path / ".github/workflows/results-explorer-browser.yml").write_text("name: Explorer\n", encoding="utf-8")
    # Create .gitignore for transform testing
    (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__/\n", encoding="utf-8")
    return tmp_path


@pytest.mark.skip(
    reason=(
        "Obsolete under the two-branch single-repo migration: HOLD_BACK_PATHS no "
        "longer contains benchbox/release/ etc.; those live on develop and main "
        "and are curated out of the wheel via pyproject + MANIFEST.in instead of "
        "via prepare_public_release(). Removed in Phase 6."
    )
)
def test_prepare_public_release_strips_holdbacks(temp_source: Path, tmp_path: Path) -> None:
    target = tmp_path / "public"

    prepare_public_release(
        source=temp_source,
        target=target,
        version="0.1.0",
        clean=True,
        init_git=False,
    )

    # ensure benchbox copied
    assert (target / "benchbox/__init__.py").exists()
    # ensure hold back paths removed
    assert not (target / "benchbox/release").exists()
    assert not (target / "benchbox/core/explorer_pipeline").exists()
    assert not (target / "benchbox/cli/commands/explorer.py").exists()
    assert not (target / "scripts/prepare_release.py").exists()
    assert not (target / "tests/unit/core/explorer_pipeline").exists()
    assert not (target / "tests/unit/release").exists()
    assert not (target / "tests/unit/test_xdist_safety.py").exists()
    assert not (target / ".github/workflows/results-explorer-browser.yml").exists()
    assert not (target / "docs/development/results-explorer-brand-ownership.md").exists()
    assert not (target / "docs/development/results-explorer-browser-testing.md").exists()

    # Note: README no longer sanitized - public releases use the full README
    # Only pyproject is sanitized
    assert (target / "README.md").read_text(encoding="utf-8") == "Private README\n"
    assert (target / "pyproject.toml").read_text(encoding="utf-8") == "[project]\nname='benchbox'\n"
    cli_init = (target / "benchbox/cli/commands/__init__.py").read_text(encoding="utf-8")
    assert "explorer_group" not in cli_init
    test_workflow = (target / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "hashFiles('results-explorer/package.json')" in test_workflow
    assert "_benchbox_pytest_xdist_safety" not in (target / "pytest.ini").read_text(encoding="utf-8")
    assert "_benchbox_pytest_xdist_safety" not in (target / "pytest-ci.ini").read_text(encoding="utf-8")

    # gitignore written
    assert (target / ".gitignore").exists()

    # timestamps normalized (file exists implies utime run)
    assert (target / "RELEASE_VERSION").read_text(encoding="utf-8").strip() == "0.1.0"


@pytest.mark.skip(
    reason=(
        "Obsolete under the two-branch single-repo migration: "
        "_benchbox_pytest_xdist_safety.py is now in ALLOWED_ROOT_FILES (dev tooling "
        "ships on develop). Removed in Phase 6."
    )
)
def test_prepare_public_release_no_clean(temp_source: Path, tmp_path: Path) -> None:
    target = tmp_path / "public"
    target.mkdir()
    (target / "old.txt").write_text("remove me\n", encoding="utf-8")
    (target / "_benchbox_pytest_xdist_safety.py").write_text("stale helper\n", encoding="utf-8")
    (target / "results-explorer").mkdir()
    (target / "results-explorer/package.json").write_text("{}\n", encoding="utf-8")
    (target / "dist").mkdir()
    (target / "dist/existing.whl").write_text("wheel\n", encoding="utf-8")
    (target / "build").mkdir()
    (target / "build/artifact.txt").write_text("artifact\n", encoding="utf-8")
    (target / "benchbox.egg-info").mkdir()
    (target / "benchbox.egg-info/PKG-INFO").write_text("metadata\n", encoding="utf-8")

    prepare_public_release(
        source=temp_source,
        target=target,
        version="0.1.0",
        clean=False,
    )

    # stale root files should be removed, but expected build artifacts preserved
    assert not (target / "old.txt").exists()
    assert not (target / "_benchbox_pytest_xdist_safety.py").exists()
    assert not (target / "results-explorer").exists()
    assert (target / "dist/existing.whl").exists()
    assert (target / "build/artifact.txt").exists()
    assert (target / "benchbox.egg-info/PKG-INFO").exists()
    assert (target / "benchbox").exists()


def test_prepare_public_release_includes_extra_files(temp_source: Path, tmp_path: Path) -> None:
    extra_file = temp_source / "RELEASE_NOTES.md"
    extra_file.write_text("Notes\n", encoding="utf-8")

    target = tmp_path / "public"

    prepare_public_release(
        source=temp_source,
        target=target,
        version="0.1.0",
        extra_root_files=["RELEASE_NOTES.md"],
    )

    assert (target / "RELEASE_NOTES.md").read_text(encoding="utf-8") == "Notes\n"


def test_prepare_public_release_missing_extra_raises(temp_source: Path, tmp_path: Path) -> None:
    target = tmp_path / "public"

    with pytest.raises(FileNotFoundError):
        prepare_public_release(
            source=temp_source,
            target=target,
            version="0.1.0",
            extra_root_files=["MISSING.txt"],
        )


def test_prepare_public_release_init_git(temp_source: Path, tmp_path: Path) -> None:
    target = tmp_path / "public"

    prepare_public_release(
        source=temp_source,
        target=target,
        version="0.1.0",
        init_git=True,
    )

    assert (target / ".git").exists()
    head = (target / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    assert head.startswith("ref: refs/heads/")


class TestComputeSourceFingerprint:
    """Tests for compute_source_fingerprint()."""

    def test_same_directory_produces_same_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "module.py").write_text("def f(): pass\n", encoding="utf-8")

        fp1 = compute_source_fingerprint(pkg)
        fp2 = compute_source_fingerprint(pkg)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA256 hex length

    def test_modified_file_changes_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        mod = pkg / "module.py"
        mod.write_text("x = 1\n", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        mod.write_text("x = 2\n", encoding="utf-8")
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before != fp_after

    def test_added_file_changes_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        (pkg / "new_module.py").write_text("y = 2\n", encoding="utf-8")
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before != fp_after

    def test_non_py_files_ignored(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        (pkg / "data.txt").write_text("not python\n", encoding="utf-8")
        (pkg / "config.json").write_text("{}\n", encoding="utf-8")
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before == fp_after

    def test_empty_directory_produces_consistent_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()

        fp1 = compute_source_fingerprint(pkg)
        fp2 = compute_source_fingerprint(pkg)
        assert fp1 == fp2

    def test_subdirectory_files_included(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        sub = pkg / "sub"
        sub.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (sub / "__init__.py").write_text("", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        (sub / "deep.py").write_text("z = 3\n", encoding="utf-8")
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before != fp_after

    def test_deleted_file_changes_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        target = pkg / "to_delete.py"
        target.write_text("x = 1\n", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        target.unlink()
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before != fp_after

    def test_renamed_file_changes_hash(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        original = pkg / "old_name.py"
        original.write_text("x = 1\n", encoding="utf-8")

        fp_before = compute_source_fingerprint(pkg)
        original.rename(pkg / "new_name.py")
        fp_after = compute_source_fingerprint(pkg)

        assert fp_before != fp_after
