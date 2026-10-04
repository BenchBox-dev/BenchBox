from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "_project/scripts/soundness_paths.py"

spec = importlib.util.spec_from_file_location("soundness_paths_predicate_test", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
soundness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = soundness
spec.loader.exec_module(soundness)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    "path",
    [
        "benchbox/core/tpchavoc/validation.py",
        "benchbox/core/validation/engines.py",
        "benchbox/utils/data_validation.py",
        "benchbox/core/tpcdi/query_validation.py",
        "benchbox/core/tpchavoc/dataframe_equivalence.py",
        "benchbox/core/tpchavoc/equivalence.py",
        "benchbox/core/results/result_digest.py",
        "_project/scripts/regenerate_correctness_gate_digests.py",
        "benchbox/core/dataframe/query_validation.py",
        "benchbox/core/datavault/validation_specs.yaml",
        "benchbox/core/validation/cross_platform.py",
        "benchbox/core/validation/query_validation.py",
        "benchbox/core/validation/data.py",
        "benchbox/platforms/base/validation.py",
        "benchbox/core/tpc_validation.py",
        "_project/scripts/build_joinorder_data.py",
        "_project/joinorder/reference_cardinalities.json",
        "_project/joinorder/tiny_reference_cardinalities.json",
        "_sources/tpc-h/dbgen/answers/q1.out",
        "_sources/tpc-ds/answer_sets/1.ans",
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
        "_project/scripts/soundness_paths.py",
        ".github/workflows/release.yml",
        ".github/workflows/pr.yml",
        ".github/workflows/release-canary.yml",
        ".github/workflows/trunk.yml",
        ".github/workflows/nightly.yml",
        ".github/workflows/new-example.yml",
        "scripts/pr_arm.py",
        "_project/decisions/single-repo-migration.md",
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
        "tests/unit/scripts/test_soundness_paths.py",
        "AGENTS.md",
        ".github/workflowsx/new-example.yml",
        "scripts/pr_arm.py.bak",
        "_sources/tpc-h/dbgen/answersx/q1.out",
        "_sources/tpc-ds/answer_sets_backup/1.ans",
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
