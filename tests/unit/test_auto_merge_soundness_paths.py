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
        # Oracle-adjacent widening (soundness-surface-widening).
        "benchbox/core/expected_results/loader.py",
        "benchbox/core/expected_results/registry.py",
        "benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json",
        "benchbox/platforms/base/result_capture.py",
        "benchbox/sql_compat/resolver.py",
        "benchbox/sql_compat/decision.py",
        "benchbox/sql_compat/rules/_registration.py",
        # Self-protection: the review-gate machinery and the PyPI-publishing
        # workflow. In-workflow checks are attacker-controlled for same-repo
        # PRs; the CODEOWNERS/ruleset layer this feeds is the durable control.
        "_project/scripts/auto_merge_soundness_paths.py",
        ".github/workflows/auto-merge-on-open.yml",
        ".github/workflows/release.yml",
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
        # pr.yml stays outside the soundness surface by decision (high churn;
        # its ci-required-result contract is pinned by the develop ruleset +
        # ruleset-drift canary, not by owner review).
        ".github/workflows/pr.yml",
        # Not a prefix-collision false positive for .github/workflows/release.yml.
        ".github/workflows/release-canary.yml",
        "",
        # sql_compat/ is deliberately narrow: only the rule-dispatch core is
        # a soundness path, not the whole (high-churn) tree.
        "benchbox/sql_compat/rules/clickhouse_rewrites.py",
        "benchbox/sql_compat/registry.py",
        "benchbox/sql_compat/actions.py",
        # A sibling file that merely starts with the same basename must not
        # false-positive against the exact-file entries above.
        "benchbox/platforms/base/result_capture_helpers.py",
    ],
)
def test_soundness_predicate_ignores_fast_default_paths(path: str) -> None:
    assert soundness.is_soundness_path(path) is False


def test_make_pr_open_uses_shared_predicate_and_skips_auto_merge() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "_project/scripts/auto_merge_soundness_paths.py --stdin" in makefile
    # --no-renames so a rename out of a protected tree surfaces the deleted
    # source path (rename detection would report only the destination).
    assert "git diff --name-only --no-renames origin/develop...HEAD" in makefile
    assert "Soundness-critical paths changed; leaving auto-merge disabled pending review." in makefile
    assert 'if [ "$$SOUNDNESS_PATH" = "true" ]' in makefile


def test_backstop_workflow_uses_shared_predicate_and_skips_auto_merge() -> None:
    workflow = (ROOT / ".github/workflows/auto-merge-on-open.yml").read_text(encoding="utf-8")

    # Diff via git with --no-renames (gh pr diff --name-only drops rename sources).
    assert "git diff --name-only --no-renames" in workflow
    assert "if: steps.soundness.outputs.soundness_path != 'true'" in workflow
    assert "if: steps.soundness.outputs.soundness_path == 'true'" in workflow
    # A soundness-touching push must re-evaluate and clear any stale auto-merge.
    assert "synchronize" in workflow
    assert "gh pr merge --disable-auto" in workflow

    # auto-merge-predicate-base-ref-execution: the predicate must be executed
    # from the base ref's copy of the file, not the PR's own checkout copy,
    # so a PR that edits the predicate can't judge its own diff by its own
    # modified rules.
    assert (
        'git show "origin/${{ github.base_ref }}:_project/scripts/auto_merge_soundness_paths.py" > /tmp/predicate.py'
        in workflow
    )
    assert "python3 /tmp/predicate.py --stdin --format github-output" in workflow
    # The predicate script itself is executed from the checked-out repo
    # nowhere in this workflow (only the base-ref materialized copy).
    assert "_project/scripts/auto_merge_soundness_paths.py --stdin --format github-output" not in workflow

    # A PR touching the predicate or this workflow itself must be forced to
    # soundness_path=true, regardless of what the base-ref predicate says
    # about the rest of the diff (closes the "edit the predicate to make
    # future PRs unsafe" gap that base-ref execution alone doesn't cover).
    assert 'grep -qxF "_project/scripts/auto_merge_soundness_paths.py"' in workflow
    assert 'grep -qxF ".github/workflows/auto-merge-on-open.yml"' in workflow
    assert 'result="soundness_path=true"' in workflow


def test_shared_predicate_script_is_executable_for_workflow() -> None:
    assert SCRIPT_PATH.stat().st_mode & stat.S_IXUSR


def test_codeowners_covers_soundness_paths() -> None:
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")

    assert "benchbox/core/**/validation.py @joeharris76" in codeowners
    assert "benchbox/core/equivalence/** @joeharris76" in codeowners
    assert "benchbox/core/query_plans/parsers/** @joeharris76" in codeowners
    assert "benchbox/core/expected_results/** @joeharris76" in codeowners
    assert "benchbox/platforms/base/result_capture.py @joeharris76" in codeowners
    assert "benchbox/sql_compat/resolver.py @joeharris76" in codeowners
    assert "benchbox/sql_compat/decision.py @joeharris76" in codeowners
    assert "benchbox/sql_compat/rules/_registration.py @joeharris76" in codeowners
    assert "_project/scripts/auto_merge_soundness_paths.py @joeharris76" in codeowners
    assert ".github/workflows/auto-merge-on-open.yml @joeharris76" in codeowners
    assert ".github/workflows/release.yml @joeharris76" in codeowners


def test_codeowners_matches_soundness_prefixes_1to1() -> None:
    """CODEOWNERS must list exactly the same widened path set as
    SOUNDNESS_PREFIXES -- a mismatch means require_code_owner_review
    silently does nothing for a prefix that only exists on one side."""
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    owned_paths = {
        line.rsplit(" ", 1)[0].strip()
        for line in codeowners.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    expected_paths = set()
    for prefix in soundness.SOUNDNESS_PREFIXES:
        expected_paths.add(prefix if not prefix.endswith("/") else f"{prefix}**")
    expected_paths.add("benchbox/core/**/validation.py")

    assert owned_paths == expected_paths
