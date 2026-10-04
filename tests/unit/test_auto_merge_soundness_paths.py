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
        "benchbox/core/expected_results/loader.py",
        "benchbox/core/expected_results/registry.py",
        "benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json",
        "benchbox/platforms/base/result_capture.py",
        "benchbox/sql_compat/resolver.py",
        "benchbox/sql_compat/decision.py",
        "benchbox/sql_compat/rules/_registration.py",
        "_project/scripts/oracle_review_check.py",
        ".github/workflows/oracle-review.yml",
        "benchbox/core/results/anonymization.py",
        "benchbox/core/results/anonymization_specs.yaml",
        "benchbox/core/results/provenance.py",
        "benchbox/core/results/status.py",
        "benchbox/core/results/query_status.py",
        "benchbox/validation/bundle.py",
        "benchbox/core/publishing/admission.py",
        "benchbox/core/publishing/bundle_publisher.py",
        "_project/scripts/explorer_pipeline/models.py",
        "_project/scripts/explorer_pipeline/pipeline.py",
        "_project/scripts/explorer_pipeline/ranking.py",
        "_project/scripts/explorer_pipeline/transformer.py",
        "_project/scripts/explorer_pipeline/duckdb_builder.py",
        "_project/scripts/explorer_pipeline/compare_math.py",
        "_project/scripts/results_explorer_snapshot_invariants.py",
        "benchbox/core/results/canonical_json.py",
        "benchbox/core/results/schema_policy.py",
        "_project/scripts/explorer_publish.py",
        "scripts/generate_corpus_inventory.py",
        "scripts/validate_submission.py",
        ".github/CODEOWNERS",
        "_project/scripts/soundness_merge_digest.py",
        ".github/workflows/soundness-merge-digest.yml",
        "results-data/bundles/tpch/duckdb/sf1.override.json",
        "results-data/bundles/sf1.override.json",
        ".github/workflows/validate-submission.yml",
        ".github/workflows/sync-results-data-to-published.yml",
        ".github/workflows/docs.yml",
        ".github/workflows/publication-transaction.yml",
        ".github/workflows/publication-recover.yml",
        ".github/workflows/publication-canaries.yml",
        ".github/workflows/publication-lane-docs.yml",
        ".github/workflows/publication-lane-explorer.yml",
        ".github/workflows/publication-corpus-cutover.yml",
        "_project/scripts/auto_merge_soundness_paths.py",
        ".github/workflows/release.yml",
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
        "_project/decisions/independent-publication-a0-freeze-2026-08-31.md",
        "docs/development/adr/adr-independent-publication-authorities.md",
        "docs/development/adr/adr-public-result-id-permanence.md",
        "docs/development/adr/adr-published-results-slim-corpus-branch.md",
        "docs/development/independent-publication-threat-model.md",
        "docs/operations/independent-publication-contract.md",
        "docs/operations/publication-deployer-soak-and-retirement.md",
        "docs/operations/results-phase-2-runbook.md",
        "docs/operations/results-phase-3-runbook.md",
        "docs/reference/hosted-results-contract.md",
        "docs/reference/threat-model.md",
        "tests/unit/test_auto_merge_soundness_paths.py",
        ".github/workflows/pr.yml",
        ".github/workflows/release-canary.yml",
        "",
        "benchbox/sql_compat/rules/clickhouse_rewrites.py",
        "benchbox/sql_compat/registry.py",
        "benchbox/sql_compat/actions.py",
        "benchbox/platforms/base/result_capture_helpers.py",
        "benchbox/core/results/exporter.py",
        "benchbox/core/results/schema.py",
        "benchbox/core/results/anonymization.py.bak",
        "benchbox/core/results/anonymization_specs.yaml.example",
        "results-data/bundles/tpch/duckdb/sf1.json",
        "results-data/bundles/tpch/duckdb/sf1.plans.json",
        "results-data/corpus-inventory.json",
        "publicationx",
        "publicationx/notes.md",
        "scripts/publicationx/check.py",
        "benchbox/core/equivalencex",
        "benchbox/core/equivalencex/helpers.py",
        "benchbox/core/query_plans/parsersx/spark.py",
        "benchbox/core/expected_resultsx/loader.py",
    ],
)
def test_soundness_predicate_ignores_fast_default_paths(path: str) -> None:
    assert soundness.is_soundness_path(path) is False


def test_soundness_prefixes_are_directory_prefixes() -> None:
    assert soundness.surface_invariant_violations() == []


def test_soundness_files_glob_duality_stays_pinned() -> None:
    assert soundness.OVERRIDE_FILES_GLOB in soundness.SOUNDNESS_FILES
    assert soundness.is_soundness_path("results-data/bundles/tpch/duckdb/sf1.override.json") is True
    assert soundness.is_soundness_path("results-data/bundles/x.override.json.bak") is False


def test_make_pr_open_uses_shared_predicate_and_skips_auto_merge() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "scripts/pr_landing.py" in makefile
    assert "pr-landing-ready" in makefile
    assert "delivery_mode as 'serial' or 'batch'" in (ROOT / "scripts/pr_landing.py").read_text(encoding="utf-8")
    assert "EVIDENCE is required" in makefile
    helper = (ROOT / "scripts/pr_landing.py").read_text(encoding="utf-8")
    assert "soundness_paths_changed" in helper
    assert "auto-enqueue is forbidden" in helper


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
    assert "benchbox/core/results/status.py @joeharris76" in codeowners
    assert "benchbox/core/results/query_status.py @joeharris76" in codeowners
    assert "benchbox/validation/bundle.py @joeharris76" in codeowners
    assert "benchbox/core/publishing/admission.py @joeharris76" in codeowners
    assert "benchbox/core/publishing/bundle_publisher.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/models.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/pipeline.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/ranking.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/transformer.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/duckdb_builder.py @joeharris76" in codeowners
    assert "_project/scripts/explorer_pipeline/compare_math.py @joeharris76" in codeowners
    assert "_project/scripts/results_explorer_snapshot_invariants.py @joeharris76" in codeowners
    assert "benchbox/core/results/canonical_json.py @joeharris76" in codeowners
    assert "benchbox/core/results/schema_policy.py @joeharris76" in codeowners
    assert "scripts/generate_corpus_inventory.py @joeharris76" in codeowners
    assert "scripts/validate_submission.py @joeharris76" in codeowners
    assert "results-data/bundles/**/*.override.json @joeharris76" in codeowners
    assert "AGENTS.md @joeharris76" in codeowners
    assert ".github/CODEOWNERS @joeharris76" in codeowners
    assert ".github/PULL_REQUEST_TEMPLATE.md @joeharris76" in codeowners
    assert ".github/soundness-paths.txt @joeharris76" in codeowners
    assert "_project/scripts/soundness_paths.py @joeharris76" in codeowners
    assert "_project/scripts/check_soundness_review.py @joeharris76" in codeowners
    assert "_project/scripts/soundness_merge_digest.py @joeharris76" in codeowners
    assert ".github/workflows/soundness-merge-digest.yml @joeharris76" in codeowners
    assert ".github/workflows/ci.yml @joeharris76" in codeowners
    assert ".github/workflows/validate-submission.yml @joeharris76" in codeowners
    assert "_project/scripts/auto_merge_soundness_paths.py @joeharris76" in codeowners
    assert ".github/ci-units.yml @joeharris76" in codeowners
    assert "scripts/ci_units.py @joeharris76" in codeowners
    assert "scripts/ci_unit_result.py @joeharris76" in codeowners
    assert ".github/workflows/release.yml @joeharris76" in codeowners
    assert "scripts/check_decision_records.py @joeharris76" in codeowners
    assert "publication/** @joeharris76" in codeowners
    assert "scripts/publication/** @joeharris76" in codeowners


def test_codeowners_matches_soundness_prefixes_1to1() -> None:
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
