"""Tests for scripts/check_windows_antipatterns.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from check_windows_antipatterns import check_file, check_tree

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write(tmp_path: Path, source: str) -> Path:
    """Write source to a temp .py file and return the path."""
    p = tmp_path / "test_source.py"
    p.write_text(source)
    return p


# ------------------------------------------------------------------ #
# WA001 tests                                                          #
# ------------------------------------------------------------------ #


def test_wa001_bare_os_access(tmp_path: Path) -> None:
    src = "import os\nos.access('/tmp/x', os.X_OK)\n"
    violations = check_file(_write(tmp_path, src))
    assert len(violations) == 1
    assert violations[0].code == "WA001"


def test_wa001_guarded_os_name(tmp_path: Path) -> None:
    src = "import os\nos.name != 'nt' and os.access('/tmp/x', os.X_OK)\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa001_guarded_sys_platform(tmp_path: Path) -> None:
    src = "import os, sys\nsys.platform != 'win32' and os.access('/tmp/x', os.X_OK)\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa001_guarded_if_block(tmp_path: Path) -> None:
    src = "import os\nif os.name != 'nt':\n    os.access('/tmp/x', os.X_OK)\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa001_unguarded_else_branch(tmp_path: Path) -> None:
    src = "import os\nif os.name != 'nt':\n    pass\nelse:\n    os.access('/tmp/x', os.X_OK)\n"
    violations = check_file(_write(tmp_path, src))
    assert len(violations) == 1
    assert violations[0].code == "WA001"


# ------------------------------------------------------------------ #
# WA002 tests                                                          #
# ------------------------------------------------------------------ #


def test_wa002_bare_signal(tmp_path: Path) -> None:
    src = "import signal\nsignal.SIGTERM\n"
    violations = check_file(_write(tmp_path, src))
    assert len(violations) == 1
    assert violations[0].code == "WA002"


def test_wa002_guarded_hasattr_if(tmp_path: Path) -> None:
    src = "import signal\nif hasattr(signal, 'SIGTERM'):\n    signal.SIGTERM\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa002_guarded_hasattr_boolop(tmp_path: Path) -> None:
    src = "import signal\ncond = True\nif hasattr(signal, 'SIGTERM') and cond:\n    signal.SIGTERM\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa002_guarded_getattr_3arg(tmp_path: Path) -> None:
    src = "import signal\ngetattr(signal, 'SIGTERM', None)\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa002_unguarded_getattr_2arg(tmp_path: Path) -> None:
    src = "import signal\ngetattr(signal, 'SIGTERM')\n"
    violations = check_file(_write(tmp_path, src))
    assert len(violations) == 1
    assert violations[0].code == "WA002"


def test_wa002_guarded_try_except(tmp_path: Path) -> None:
    src = "import signal\ntry:\n    signal.SIGTERM\nexcept AttributeError:\n    pass\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa002_guarded_try_bare_except(tmp_path: Path) -> None:
    src = "import signal\ntry:\n    signal.SIGTERM\nexcept:\n    pass\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_wa002_all_signal_names(tmp_path: Path) -> None:
    signal_names = ["SIGTERM", "SIGKILL", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGCHLD", "SIGPIPE"]
    for sig_name in signal_names:
        f = tmp_path / f"sig_{sig_name}.py"
        f.write_text(f"import signal\nsignal.{sig_name}\n")
        violations = check_file(f)
        assert len(violations) == 1, f"{sig_name} not flagged"
        assert violations[0].code == "WA002"


# ------------------------------------------------------------------ #
# noqa suppression tests                                               #
# ------------------------------------------------------------------ #


def test_noqa_suppresses_wa001(tmp_path: Path) -> None:
    src = "import os\nos.access('/tmp/x', os.X_OK)  # noqa: WA001\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_noqa_suppresses_wa002(tmp_path: Path) -> None:
    src = "import signal\nsignal.SIGTERM  # noqa: WA002\n"
    violations = check_file(_write(tmp_path, src))
    assert violations == []


def test_noqa_wrong_code_no_effect(tmp_path: Path) -> None:
    src = "import os\nos.access('/tmp/x', os.X_OK)  # noqa: WA002\n"
    violations = check_file(_write(tmp_path, src))
    assert len(violations) == 1
    assert violations[0].code == "WA001"


# ------------------------------------------------------------------ #
# Integration: check_tree                                              #
# ------------------------------------------------------------------ #


def test_check_tree_walks_directory(tmp_path: Path) -> None:
    (tmp_path / "clean1.py").write_text("import os\n")
    (tmp_path / "clean2.py").write_text("x = 1\n")
    (tmp_path / "bad.py").write_text("import os\nos.access('/tmp/x', os.X_OK)\n")
    violations, file_count = check_tree([tmp_path])
    assert file_count == 3
    assert len(violations) == 1
    assert violations[0].code == "WA001"


def test_check_tree_empty_directory(tmp_path: Path) -> None:
    violations, file_count = check_tree([tmp_path])
    assert violations == []
    assert file_count == 0
