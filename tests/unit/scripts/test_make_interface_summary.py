from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "make" / "interface_summary.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("interface_summary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    shutil.copy2(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    shutil.copytree(
        REPO_ROOT / "make",
        tmp_path / "make",
        ignore=shutil.ignore_patterns("inventory.json", "__pycache__"),
    )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_summary_lists_added_removed_and_changed_public_targets(repository: Path, tmp_path_factory) -> None:
    module = _load_module()
    makefile = repository / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    assert "test-fast:\n" in text
    makefile.write_text(
        text.replace("test-fast:\n", "test-fast-renamed:\n", 1)
        + "\n.PHONY: probe-target\nprobe-target:\n\t@echo probe\n",
        encoding="utf-8",
    )
    _git(repository, "commit", "-q", "-am", "head")
    module.ROOT = repository
    summary = tmp_path_factory.mktemp("summary") / "summary.md"

    assert module.main(["--base-ref", "HEAD~1", "--summary", str(summary)]) == 0

    text = summary.read_text(encoding="utf-8")
    assert "**Removed public targets (1)**" in text and "`test-fast`" in text
    assert "`test-fast-renamed`" in text and "`probe-target`" in text


def test_summary_reports_an_evaluation_change_without_a_public_change(repository: Path, tmp_path_factory) -> None:
    module = _load_module()
    makefile = repository / "Makefile"
    makefile.write_text(makefile.read_text(encoding="utf-8") + "\nPROBE_VARIABLE := probe\n", encoding="utf-8")
    _git(repository, "commit", "-q", "-am", "head")
    module.ROOT = repository
    summary = tmp_path_factory.mktemp("summary") / "summary.md"

    assert module.main(["--base-ref", "HEAD~1", "--summary", str(summary)]) == 0

    text = summary.read_text(encoding="utf-8")
    assert "`PROBE_VARIABLE`" in text
    assert "No public target or recipe changed, but Make's evaluation changed." in text
    assert "Make's evaluation is unchanged." not in text


def test_summary_is_empty_when_no_make_file_changed(repository: Path, tmp_path_factory) -> None:
    module = _load_module()
    (repository / "unrelated.txt").write_text("x\n", encoding="utf-8")
    _git(repository, "add", "unrelated.txt")
    _git(repository, "commit", "-q", "-m", "head")
    module.ROOT = repository
    summary = tmp_path_factory.mktemp("summary") / "summary.md"

    assert module.main(["--base-ref", "HEAD~1", "--summary", str(summary)]) == 0

    assert not summary.exists()


def test_summary_never_fails_on_an_unknown_base(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    module.ROOT = repository

    assert module.main(["--base-ref", "does-not-exist"]) == 0

    assert "Not computed" in capsys.readouterr().out
