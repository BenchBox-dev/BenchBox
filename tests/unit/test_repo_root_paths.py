"""Tests for the cwd-independent repository root helper."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.utilities.paths import REPO_ROOT

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_repo_root_points_at_checkout() -> None:
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "tests" / "utilities" / "paths.py").is_file()


def test_paths_module_is_cwd_independent_and_import_free(tmp_path) -> None:
    script = (
        "import runpy, sys\n"
        f"ns = runpy.run_path({str(REPO_ROOT / 'tests' / 'utilities' / 'paths.py')!r})\n"
        "print(ns['REPO_ROOT'])\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'benchbox', 'tests'}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=True, timeout=30
    )
    root_line, modules_line = result.stdout.splitlines()
    assert root_line == str(REPO_ROOT)
    assert modules_line == "[]"
