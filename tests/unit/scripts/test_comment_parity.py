from __future__ import annotations

import json
import subprocess
from pathlib import Path

import comment_parity as parity
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def compare(base: str, head: str) -> parity.FileReport:
    return parity.compare_python("a.py", base.encode(), head.encode())


@pytest.mark.parametrize(
    "base,head,comments,docstrings,passes",
    [
        ("x = 1  # note\n", "x = 1\n", 1, 0, 0),
        ("# note\nx = 1\n", "x = 1\n", 1, 0, 0),
        ('def f():\n    """doc"""\n    return 1\n', "def f():\n    return 1\n", 0, 1, 0),
        ('"""module"""\nimport os\n', "import os\n", 0, 1, 0),
        ('class A:\n    """doc"""\n    x = 1\n', "class A:\n    x = 1\n", 0, 1, 0),
        ('def f():\n    """doc"""\n', "def f():\n    pass\n", 0, 1, 1),
        ('class A:\n    """doc"""\n', "class A:\n    pass\n", 0, 1, 1),
        ('def f():\n    """doc"""\n    pass\n', "def f():\n    pass\n", 0, 1, 0),
        ('def f():\n    """doc"""\n', 'def f():\n    """doc"""\n', 0, 0, 0),
        ("def f(): return 1\n", "def f(): return 1\n", 0, 0, 0),
    ],
)
def test_removing_only_comments_and_leading_docstrings_is_parity(
    base: str, head: str, comments: int, docstrings: int, passes: int
) -> None:
    report = compare(base, head)
    assert report.status == "ok", report.problems
    assert (report.comments_removed, report.docstrings_removed, report.pass_added) == (comments, docstrings, passes)


@pytest.mark.parametrize(
    "base,head",
    [
        ("x = 1\n", "x = 2\n"),
        ('query = "SELECT 1"\n', 'query = "SELECT 2"\n'),
        ('def f():\n    """doc"""\n', "def f():\n    ...\n"),
        ('def f():\n    """doc"""\n    return 1\n', "def f():\n    pass\n    return 1\n"),
        ('def f():\n    x = 1\n    "not a docstring"\n    return x\n', "def f():\n    x = 1\n    return x\n"),
        ("def f(x):  # type: (int) -> int\n    return x\n", "def f(x):\n    return x\n"),
        ("import os  # type: ignore\n", "import os\n"),
        ("def f():\n    return 1\n", "def g():\n    return 1\n"),
        ('def f():\n    """doc"""\n    return 1\n', 'def f():\n    "not the same docstring"\n    return 1\n'),
        ("a = 1\nb = 2\n", "b = 2\na = 1\n"),
    ],
)
def test_any_other_change_is_drift(base: str, head: str) -> None:
    report = compare(base, head)
    assert report.status == "drift"
    assert report.problems


@pytest.mark.parametrize(
    "base,head,wording",
    [
        ("x = 1\n", "x = 1  # new\n", "comment"),
        ("x = 1\n", "# new\nx = 1\n", "comment"),
        ("def f():\n    return 1\n", 'def f():\n    """new"""\n    return 1\n', "docstring"),
        ('def f():\n    """old"""\n    return 1  # old\n', 'def f():\n    """new"""\n    return 1\n', "docstring"),
        ("x = 1  # old\n", "x = 1  # other\n", "comment"),
    ],
)
def test_adding_or_rewording_text_is_drift_even_when_the_syntax_tree_matches(
    base: str, head: str, wording: str
) -> None:
    report = compare(base, head)
    assert report.status == "drift"
    assert any(wording in problem for problem in report.problems)


@pytest.mark.parametrize(
    "base,head",
    [
        ("#!/usr/bin/env python3\nx = 1\n", "x = 1\n"),
        ("#!/usr/bin/env python3\nx = 1\n", "#!/usr/bin/python\nx = 1\n"),
        ("# -*- coding: latin-1 -*-\nx = 1\n", "x = 1\n"),
        ("#!/usr/bin/env python3\n# coding: utf-8\nx = 1\n", "#!/usr/bin/env python3\nx = 1\n"),
    ],
)
def test_removing_or_changing_a_shebang_or_encoding_declaration_is_drift(base: str, head: str) -> None:
    report = compare(base, head)
    assert report.status == "drift"
    assert any("shebang or encoding" in problem for problem in report.problems)


def test_keeping_a_shebang_and_encoding_declaration_while_removing_other_comments_is_parity() -> None:
    base = "#!/usr/bin/env python3\n# coding: utf-8\nx = 1  # note\n# trailing\n"
    report = compare(base, "#!/usr/bin/env python3\n# coding: utf-8\nx = 1\n")
    assert report.status == "ok" and report.comments_removed == 2


def test_a_removal_cannot_pay_for_an_addition_in_the_same_file() -> None:
    report = compare("x = 1  # old\ny = 2\n", "x = 1\ny = 2  # new\n")
    assert report.status == "drift" and report.comments_removed == 1


@pytest.mark.parametrize("source", ["def broken(:\n", "x = (\n", "\tx = 1\n  y = 2\n"])
def test_unparseable_source_is_an_error_not_a_pass(source: str) -> None:
    assert compare("x = 1\n", source).status == "error"
    assert compare(source, "x = 1\n").status == "error"


def test_comparison_does_not_depend_on_line_numbers_or_blank_lines() -> None:
    report = compare('"""m"""\n\n\n\ndef f():\n\n    """d"""\n\n    return 1\n', "def f():\n    return 1\n")
    assert report.status == "ok" and report.docstrings_removed == 2


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@e.invalid",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "--initial-branch=trunk")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/a.py").write_text(
        '"""module"""\n\n\ndef f():\n    """doc"""\n    return 1  # note\n', encoding="utf-8"
    )
    (tmp_path / "pkg/b.py").write_text("x = 1  # keep\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("text\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_cli_accepts_a_deletion_only_change_in_the_worktree_and_reports_totals(
    repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (repo / "pkg/a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = git(repo, "rev-parse", "HEAD")
    out = tmp_path / "report.json"
    assert parity.main(["--root", str(repo), "--base", base, "--json-out", str(out)]) == 0
    assert "1 files, 1 ok, 0 drift" in capsys.readouterr().out
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report == [
        {
            "path": "pkg/a.py",
            "status": "ok",
            "comments_removed": 1,
            "docstrings_removed": 2,
            "pass_added": 0,
            "problems": [],
        }
    ]


def test_cli_compares_a_committed_head_and_restricts_to_path_prefixes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = git(repo, "rev-parse", "HEAD")
    (repo / "pkg/a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (repo / "pkg/b.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "commit", "-aqm", "change")
    assert parity.main(["--root", str(repo), "--base", base, "--head", "HEAD"]) == 1
    assert "pkg/a.py: drift" in capsys.readouterr().out
    assert parity.main(["--root", str(repo), "--base", base, "--head", "HEAD", "--path", "pkg/b.py"]) == 0


def test_cli_rejects_added_and_deleted_files_and_unverified_languages(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = git(repo, "rev-parse", "HEAD")
    (repo / "pkg/new.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "pkg/b.py").unlink()
    (repo / "notes.md").write_text("edited\n", encoding="utf-8")
    assert parity.main(["--root", str(repo), "--base", base]) == 1
    out = capsys.readouterr().out
    assert "pkg/new.py: drift: file added" in out
    assert "pkg/b.py: drift: file deleted" in out
    assert "notes.md: unverified: no comparator for .md" in out
    (repo / "pkg/new.py").unlink()
    git(repo, "checkout", "pkg/b.py")
    assert parity.main(["--root", str(repo), "--base", base]) == 1
    assert parity.main(["--root", str(repo), "--base", base, "--unverified-ok", "md"]) == 0
    assert "1 skipped" in capsys.readouterr().out


def test_cli_reports_a_git_failure_with_status_two(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert parity.main(["--root", str(repo), "--base", "f" * 40]) == 2
    assert "comment-parity:" in capsys.readouterr().err
