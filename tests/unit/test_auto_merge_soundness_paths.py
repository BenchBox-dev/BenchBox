"""Auto-merge must stop for soundness-critical comparator and parser paths."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
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
        # Publication privacy: the anonymizer decides every published byte and
        # the public pseudonym identity. Both failure modes are silent, and
        # PR #1512 auto-merged a change to all of them before this widening.
        # The specs YAML is included because it defines which keys are hashed:
        # dropping an entry there is a silent leak with no code diff to review.
        "benchbox/core/results/anonymization.py",
        "benchbox/core/results/anonymization_specs.yaml",
        "benchbox/core/results/provenance.py",
        "benchbox/validation/bundle.py",
        "benchbox/core/publishing/admission.py",
        "benchbox/core/publishing/bundle_publisher.py",
        "_project/scripts/explorer_pipeline/models.py",
        "_project/scripts/explorer_pipeline/pipeline.py",
        "_project/scripts/explorer_pipeline/ranking.py",
        "_project/scripts/explorer_publish.py",
        "scripts/generate_corpus_inventory.py",
        "scripts/validate_submission.py",
        ".github/workflows/validate-submission.yml",
        ".github/workflows/docs.yml",
        # Self-protection: the review-gate machinery and the PyPI-publishing
        # workflow. In-workflow checks are attacker-controlled for same-repo
        # PRs; the CODEOWNERS/ruleset layer this feeds is the durable control.
        "_project/scripts/auto_merge_soundness_paths.py",
        ".github/workflows/auto-merge-on-open.yml",
        ".github/workflows/release.yml",
        # Independent-publication authority and trust-policy contract.
        "_project/decisions/independent-publication-a0-freeze-2026-08-31.md",
        "docs/development/adr/adr-independent-publication-authorities.md",
        "docs/development/adr/adr-public-result-id-permanence.md",
        "docs/development/adr/adr-published-results-slim-corpus-branch.md",
        "docs/development/independent-publication-threat-model.md",
        "docs/operations/independent-publication-contract.md",
        "docs/operations/results-phase-2-runbook.md",
        "docs/operations/results-phase-3-runbook.md",
        "docs/reference/hosted-results-contract.md",
        "docs/reference/threat-model.md",
        "scripts/check_decision_records.py",
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
        # The anonymizer entries are exact files, not the results package:
        # exporter.py and schema.py stay auto-mergeable.
        "benchbox/core/results/exporter.py",
        "benchbox/core/results/schema.py",
        "benchbox/core/results/anonymization.py.bak",
        "benchbox/core/results/anonymization_specs.yaml.example",
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
    # Revoke-only workflow (D2): the disable step is the only consumer of the
    # predicate output; no enable step exists to pin.
    assert "if: steps.soundness.outputs.soundness_path == 'true'" in workflow
    assert "gh pr merge --auto" not in workflow.replace("gh pr merge --disable-auto", "")
    # A soundness-touching push must re-evaluate and clear any stale auto-merge.
    assert "synchronize" in workflow
    assert "gh pr merge --disable-auto" in workflow

    # auto-merge-predicate-base-ref-execution: base-ref copy must still run so
    # a PR that narrows the predicate can't judge its own diff by its own rules.
    assert (
        "git show \"origin/${{ github.base_ref || 'develop' }}:_project/scripts/auto_merge_soundness_paths.py\" > /tmp/predicate_base.py"
        in workflow
    )
    assert "python3 /tmp/predicate_base.py --stdin --format github-output" in workflow
    # PR checkout copy is evaluated alongside base-ref (union/OR) so a gate
    # *widened* mid-flight still revokes, and the PR copy cannot weaken the
    # gate by narrowing rules (union means either copy saying true wins).
    assert "python3 _project/scripts/auto_merge_soundness_paths.py --stdin --format github-output" in workflow
    assert '[ "$base_result" = "soundness_path=true" ] || [ "$pr_result" = "soundness_path=true" ]' in workflow

    # A PR touching the predicate or this workflow itself must be forced to
    # soundness_path=true, regardless of what either predicate says about the
    # rest of the diff (closes the "edit the predicate to make future PRs
    # unsafe" gap that predicate evaluation alone doesn't cover).
    assert 'grep -qxF "_project/scripts/auto_merge_soundness_paths.py"' in workflow
    assert 'grep -qxF ".github/workflows/auto-merge-on-open.yml"' in workflow
    assert 'result="soundness_path=true"' in workflow


def _assert_git_index_executable(path: Path, *, env: dict[str, str] | None = None) -> None:
    relative_path = path.relative_to(ROOT).as_posix()
    recorded = subprocess.run(
        ["git", "ls-files", "--stage", "--", relative_path],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()

    assert recorded, f"{relative_path} is not tracked by git"
    assert recorded[0] == "100755", f"expected git mode 100755, got {recorded[0]}"


def test_shared_predicate_script_is_executable_for_workflow() -> None:
    """The Linux workflow executes the script, so Git must record mode 100755."""
    _assert_git_index_executable(SCRIPT_PATH)


def test_shared_predicate_executable_guard_rejects_non_executable_index_mode(tmp_path: Path) -> None:
    real_index = subprocess.run(
        ["git", "rev-parse", "--git-path", "index"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    index_path = Path(real_index)
    if not index_path.is_absolute():
        index_path = ROOT / index_path

    test_index = tmp_path / "index"
    shutil.copyfile(index_path, test_index)
    env = {**os.environ, "GIT_INDEX_FILE": str(test_index)}
    subprocess.run(
        ["git", "update-index", "--chmod=-x", "--", SCRIPT_PATH.relative_to(ROOT).as_posix()],
        cwd=ROOT,
        env=env,
        check=True,
    )

    with pytest.raises(AssertionError, match="expected git mode 100755, got 100644"):
        _assert_git_index_executable(SCRIPT_PATH, env=env)


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
    assert "benchbox/core/results/provenance.py @joeharris76" in codeowners
    assert "benchbox/validation/bundle.py @joeharris76" in codeowners
    assert "benchbox/core/publishing/admission.py @joeharris76" in codeowners
    assert "benchbox/core/publishing/bundle_publisher.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/models.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/pipeline.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/ranking.py @joeharris76" in codeowners
    assert "scripts/generate_corpus_inventory.py @joeharris76" in codeowners
    assert "scripts/validate_submission.py @joeharris76" in codeowners
    assert ".github/workflows/validate-submission.yml @joeharris76" in codeowners
    assert "_project/scripts/auto_merge_soundness_paths.py @joeharris76" in codeowners
    assert ".github/workflows/auto-merge-on-open.yml @joeharris76" in codeowners
    assert ".github/workflows/release.yml @joeharris76" in codeowners
    assert "docs/development/adr/adr-independent-publication-authorities.md @joeharris76" in codeowners
    assert "docs/development/independent-publication-threat-model.md @joeharris76" in codeowners
    assert "docs/operations/independent-publication-contract.md @joeharris76" in codeowners
    assert "docs/reference/hosted-results-contract.md @joeharris76" in codeowners
    assert "scripts/check_decision_records.py @joeharris76" in codeowners


def test_codeowners_matches_soundness_prefixes_1to1() -> None:
    """CODEOWNERS must list exactly the same widened path set as
    SOUNDNESS_PREFIXES -- a mismatch means the documented soundness surface
    (and its review-request routing) silently diverges from what the
    auto-merge withholding actually gates."""
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    owned_paths = {
        line.rsplit(" ", 1)[0].strip()
        for line in codeowners.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    expected_paths = set()
    for prefix in soundness.SOUNDNESS_PREFIXES:
        expected_paths.add(prefix if not prefix.endswith("/") else f"{prefix}**")
    expected_paths.update(soundness.SOUNDNESS_FILES)
    expected_paths.add("benchbox/core/**/validation.py")

    assert owned_paths == expected_paths
