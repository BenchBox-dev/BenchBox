"""Auto-merge must stop for soundness-critical comparator and parser paths."""

from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "_project/scripts/auto_merge_soundness_paths.py"

spec = importlib.util.spec_from_file_location("auto_merge_soundness_paths", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
soundness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soundness)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    "path",
    [
        "benchbox/core/tpchavoc/validation.py",
        "benchbox/core/results/validation.py",
        "benchbox/core/equivalence/cross_surface.py",
        "benchbox/core/equivalence/nested/module.py",
        "benchbox/core/query_plans/parsers/spark.py",
        r"benchbox\core\query_plans\parsers\spark.py",
    ],
)
def test_soundness_predicate_matches_review_required_paths(path: str) -> None:
    assert soundness.is_soundness_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "benchbox/core/tpchavoc/benchmark.py",
        "benchbox/core/query_plans/comparison.py",
        "tests/unit/test_auto_merge_soundness_paths.py",
        ".github/workflows/auto-merge-on-open.yml",
        "",
    ],
)
def test_soundness_predicate_ignores_fast_default_paths(path: str) -> None:
    assert soundness.is_soundness_path(path) is False


def test_make_pr_open_uses_shared_predicate_and_skips_auto_merge() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "_project/scripts/auto_merge_soundness_paths.py --stdin" in makefile
    assert "git diff --name-only origin/develop...HEAD" in makefile
    assert "Soundness-critical paths changed; leaving auto-merge disabled pending review." in makefile
    assert 'if [ "$$SOUNDNESS_PATH" = "true" ]' in makefile


def test_backstop_workflow_uses_shared_predicate_and_skips_auto_merge() -> None:
    workflow = (ROOT / ".github/workflows/auto-merge-on-open.yml").read_text(encoding="utf-8")

    assert "| _project/scripts/auto_merge_soundness_paths.py --stdin --format github-output" in workflow
    assert "gh pr diff --name-only" in workflow
    assert "if: steps.soundness.outputs.soundness_path != 'true'" in workflow
    assert "if: steps.soundness.outputs.soundness_path == 'true'" in workflow


def test_shared_predicate_script_is_executable_for_workflow() -> None:
    assert SCRIPT_PATH.stat().st_mode & stat.S_IXUSR


def test_codeowners_covers_soundness_paths() -> None:
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")

    assert "benchbox/core/**/validation.py @joeharris76" in codeowners
    assert "benchbox/core/equivalence/** @joeharris76" in codeowners
    assert "benchbox/core/query_plans/parsers/** @joeharris76" in codeowners
