import sys
from pathlib import Path

import pytest

from benchbox.core.tpcds.c_tools import DSQGenBinary

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _fake_completed(stdout: str = "SELECT 1\n"):
    class _CP:
        def __init__(self):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    return _CP()


def test_dsqgen_uses_main_directory_for_variants(tmp_path, monkeypatch):
    templates_dir = tmp_path / "query_templates"
    variants_dir = tmp_path / "query_variants"
    templates_dir.mkdir(parents=True)
    variants_dir.mkdir(parents=True)

    (templates_dir / "templates.lst").write_text("\n")
    (templates_dir / "ansi.tpl").write_text("-- dialect stub\n")

    (templates_dir / "query1.tpl").write_text("-- base query 1\nSELECT 1;\n")
    (variants_dir / "query1a.tpl").write_text("-- variant query 1a\nSELECT 1;\n")

    dsq = DSQGenBinary()
    dsq.templates_dir = templates_dir

    captured_cmd: list[str] = []

    def fake_run(
        cmd,
        cwd=None,
        env=None,
        capture_output=None,
        text=None,
        timeout=None,
        check=None,
        stdout=None,
        stderr=None,
    ):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        return _fake_completed(stdout="SELECT 1;\n")

    monkeypatch.setattr("subprocess.run", fake_run)

    sql = dsq.generate("1a", seed=22, scale_factor=1.0, dialect="ansi")

    _opt = "/" if sys.platform == "win32" else "-"

    assert f"{_opt}DIRECTORY" in captured_cmd
    dir_idx = captured_cmd.index(f"{_opt}DIRECTORY") + 1
    tmpl_dir = Path(captured_cmd[dir_idx])
    assert tmpl_dir.name == "q"

    assert f"{_opt}TEMPLATE" in captured_cmd
    tpl_idx = captured_cmd.index(f"{_opt}TEMPLATE") + 1
    tpl_arg = captured_cmd[tpl_idx]
    assert tpl_arg == "../query_variants/query1a.tpl"

    assert "select" in sql.lower()


def test_validate_query_id_accepts_variant_in_query_variants(tmp_path):
    templates_dir = tmp_path / "query_templates"
    variants_dir = tmp_path / "query_variants"
    templates_dir.mkdir(parents=True)
    variants_dir.mkdir(parents=True)

    (templates_dir / "templates.lst").write_text("\n")
    (templates_dir / "ansi.tpl").write_text("-- dialect\n")
    (templates_dir / "query14.tpl").write_text("-- base 14\n")
    (variants_dir / "query14a.tpl").write_text("-- variant 14a\n")

    dsq = DSQGenBinary()
    dsq.templates_dir = templates_dir

    assert dsq.validate_query_id("14a") is True
