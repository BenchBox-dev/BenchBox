"""Tests for the stale _project/ reference lint.

The lint blocks NEW stale references (tracked files outside _project/
mentioning a _project/ path that does not exist) while grandfathering
pre-existing violations in a baseline that cannot rot.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "check_project_references_under_test"
    path = REPO_ROOT / "_project" / "scripts" / "check_project_references.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_script()


class TestNormalize:
    def test_strips_trailing_punctuation(self):
        assert checker._normalize("_project/foo/bar.md`") == "_project/foo/bar.md"
        assert checker._normalize("_project/foo/bar.md).") == "_project/foo/bar.md"

    def test_placeholders_ignored(self):
        assert checker._is_placeholder("_project/foo.md")
        assert checker._is_placeholder("_project/blind-spots/foo.md")
        assert checker._is_placeholder("_project/specs/example.md")
        assert not checker._is_placeholder("_project/decisions/" + "arch-pilot-eval" + ".md")


class TestBaselineRoundTrip:
    def test_baseline_exists_and_gate_passes(self, capsys):
        assert checker.BASELINE_PATH.exists()
        assert checker.main([]) == 0
        assert "no new breakage" in capsys.readouterr().out

    def test_new_reference_detected_against_baseline(self, tmp_path, monkeypatch):
        assert checker._normalize("_project/decisions/foo.md`,".replace("foo", "bar")) == ("_project/decisions/bar.md")
