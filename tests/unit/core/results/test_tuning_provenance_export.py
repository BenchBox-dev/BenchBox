"""Tests for tuning provenance/requested-config export (ADR-1).

Covers the tuning-bundle-provenance-and-config-export-20260712 TODO: the
platform.tuning summary block and the .tuning.json companion payload built by
build_tuning_payload()/_build_tuning_summary() in benchbox/core/results/schema.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import (
    build_applied_ledger_payload,
    build_result_payload,
    build_tuning_payload,
)
from benchbox.core.tuning.interface import TableTuning, TuningColumn, UnifiedTuningConfiguration
from benchbox.core.tuning.policy_generation import TUNING_POLICY_GENERATION

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _tuned_config() -> UnifiedTuningConfiguration:
    config = UnifiedTuningConfiguration()
    config.table_tunings["lineitem"] = TableTuning(
        table_name="lineitem",
        sorting=[TuningColumn(name="l_orderkey", type="INTEGER", order=1)],
    )
    return config


def _make_result(**overrides) -> BenchmarkResults:
    defaults = {
        "benchmark_name": "tpch",
        "platform": "duckdb",
        "scale_factor": 0.01,
        "execution_id": "run-1",
        "timestamp": datetime(2026, 7, 16),
        "duration_seconds": 1.0,
        "total_queries": 1,
        "successful_queries": 1,
        "failed_queries": 0,
        "query_results": [
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_seconds": 0.1,
                "rows_returned": 1,
                "run_type": "measurement",
            }
        ],
    }
    defaults.update(overrides)
    return BenchmarkResults(**defaults)


def _applied_ledger_payload(status: str = "applied_unverified") -> dict:
    """A representative AppliedTuningLedger.to_payload() dict for a tuned run."""
    return {
        "status": status,
        "applied_ledger_hash": "f" * 64,
        "statements": [
            {
                "statement": "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (l_orderkey)",
                "phase": "ddl",
                "status": "executed",
            }
        ],
        "dropped": [],
    }


def test_template_run_bundle_carries_source_enum_template_ref_and_hash():
    config = _tuned_config()
    applied = _applied_ledger_payload()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="auto_discovered",
        tuning_source_file="examples/tunings/duckdb/tpch_tuned.yaml",
        tuning_config_hash=config.get_configuration_hash(),
        tuning_validation_status="applied_unverified",
        applied_tuning_ledger=applied,
        applied_ledger_hash=applied["applied_ledger_hash"],
    )

    payload = build_result_payload(result)
    summary = payload["platform"]["tuning"]

    assert summary["tuning_source"] == "auto_discovered"
    assert summary["requested_config_hash"] == config.get_configuration_hash()
    # Legacy bridge keys (one generation) must keep the explorer pipeline working.
    assert summary["source"] == "yaml"
    assert summary["hash"] == config.get_configuration_hash()
    assert summary["counts"]["tables_tuned"] == 1
    assert "sorting" in summary["counts"]["tuning_types"]
    # applied_ledger_hash (physical identity) rides alongside requested_config_hash.
    assert summary["applied_ledger_hash"] == applied["applied_ledger_hash"]
    # ADR-1 verified-state is surfaced in the MAIN-bundle summary (not just the
    # .tuning.json companion) so the explorer, which reads only the main bundle,
    # can display it.
    assert summary["validation_status"] == "applied_unverified"

    companion = build_tuning_payload(result)
    assert companion["tuning_source"] == "auto_discovered"
    assert companion["source_file"] == "examples/tunings/duckdb/tpch_tuned.yaml"
    assert companion["requested_config_hash"] == config.get_configuration_hash()
    assert companion["hash"] == config.get_configuration_hash()
    assert companion["applied_ledger_hash"] == applied["applied_ledger_hash"]
    assert companion["validation_status"] == "applied_unverified"
    assert companion["requested"]["table_tunings"]["lineitem"]["sorting"][0]["name"] == "l_orderkey"


def test_applied_ledger_companion_payload_is_the_execution_record():
    config = _tuned_config()
    applied = _applied_ledger_payload()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=config.get_configuration_hash(),
        tuning_validation_status="applied_unverified",
        applied_tuning_ledger=applied,
        applied_ledger_hash=applied["applied_ledger_hash"],
    )

    companion = build_applied_ledger_payload(result)

    assert companion is not None
    assert companion["status"] == "applied_unverified"
    assert companion["applied_ledger_hash"] == applied["applied_ledger_hash"]
    assert companion["statements"][0]["statement"].startswith("CREATE INDEX IF NOT EXISTS")
    assert companion["statements"][0]["status"] == "executed"


def test_no_applied_ledger_returns_no_applied_companion():
    result = _make_result(
        tunings_applied=_tuned_config().to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=_tuned_config().get_configuration_hash(),
    )
    assert build_applied_ledger_payload(result) is None
    # And the .tuning.json companion must not invent an applied_ledger_hash.
    assert "applied_ledger_hash" not in build_tuning_payload(result)


def test_explicit_file_source_also_bridges_to_legacy_yaml():
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="explicit_file",
        tuning_source_file="my_custom_tuning.yaml:0123456789abcdef",
        tuning_config_hash=config.get_configuration_hash(),
    )

    summary = build_result_payload(result)["platform"]["tuning"]

    assert summary["source"] == "yaml"


def test_fallback_run_carries_source_fallback_and_auto_bridge():
    config = UnifiedTuningConfiguration()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="fallback",
        tuning_source_file=None,
        tuning_config_hash=config.get_configuration_hash(),
    )

    summary = build_result_payload(result)["platform"]["tuning"]
    companion = build_tuning_payload(result)

    assert summary["tuning_source"] == "fallback"
    assert summary["source"] == "auto"
    assert companion["tuning_source"] == "fallback"
    assert companion["source"] == "auto"
    assert "source_file" not in companion


def test_wizard_run_carries_source_wizard():
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="wizard",
        tuning_source_file=None,
        tuning_config_hash=config.get_configuration_hash(),
    )

    summary = build_result_payload(result)["platform"]["tuning"]

    assert summary["tuning_source"] == "wizard"
    assert summary["source"] == "auto"


def test_requested_config_hash_distinct_across_differing_configs():
    baseline_result = _make_result(
        tunings_applied=UnifiedTuningConfiguration().to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=UnifiedTuningConfiguration().get_configuration_hash(),
    )
    tuned_config = _tuned_config()
    tuned_result = _make_result(
        tunings_applied=tuned_config.to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=tuned_config.get_configuration_hash(),
    )

    baseline_hash = build_result_payload(baseline_result)["platform"]["tuning"]["requested_config_hash"]
    tuned_hash = build_result_payload(tuned_result)["platform"]["tuning"]["requested_config_hash"]

    assert baseline_hash != tuned_hash


def test_no_absolute_paths_anywhere_in_emitted_bundle_or_companion():
    """must_preserve: no raw local filesystem paths in exported bundles."""
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="explicit_file",
        # A raw absolute path must never be handed to the exporter in the first
        # place (run.py's resolve_template_reference() is the enforcement
        # point) - this asserts the export layer doesn't introduce one either.
        tuning_source_file="custom_tuning.yaml:ab12cd34ef56ab12",
        tuning_config_hash=config.get_configuration_hash(),
    )

    bundle_payload = build_result_payload(result)
    companion_payload = build_tuning_payload(result)

    bundle_text = json.dumps(bundle_payload)
    companion_text = json.dumps(companion_payload)

    for text in (bundle_text, companion_text):
        assert "/home/" not in text
        assert "/Users/" not in text
        assert "/root/" not in text
        assert "C:\\\\" not in text


def test_anonymized_tuning_companion_hides_identifiers_and_preserves_source(tmp_path):
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="explicit_file",
        tuning_source_file="examples/tunings/custom.yaml:0123456789abcdef",
        tuning_config_hash=config.get_configuration_hash(),
    )

    exporter = ResultExporter(output_dir=tmp_path, anonymize=True)
    exporter._write_companion_files(result, "run-1")
    payload = json.loads((tmp_path / "run-1.tuning.json").read_text(encoding="utf-8"))

    table_tunings = payload["requested"]["table_tunings"]
    table_key = next(iter(table_tunings))
    assert table_key.startswith("table_")
    assert table_tunings[table_key]["table_name"].startswith("table_")
    assert table_tunings[table_key]["sorting"][0]["name"].startswith("column_")
    assert payload["source_file"] == "examples/tunings/custom.yaml:0123456789abcdef"


def test_requested_block_reports_platform_optimizations_non_defaults_only():
    config = UnifiedTuningConfiguration()
    config.platform_optimizations.z_ordering_enabled = True
    config.platform_optimizations.z_ordering_columns = ["l_shipdate"]
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=config.get_configuration_hash(),
    )

    companion = build_tuning_payload(result)

    platform_optimizations = companion["requested"]["platform_optimizations"]
    assert platform_optimizations["z_ordering_enabled"] is True
    assert platform_optimizations["z_ordering_columns"] == ["l_shipdate"]
    # Default (unset) fields must be omitted from the diffed block.
    assert "auto_optimize_enabled" not in platform_optimizations
    assert "sorted_ingestion_mode" not in platform_optimizations


def test_no_tuning_returns_no_platform_tuning_block_or_companion():
    result = _make_result(tunings_applied=None)

    assert build_tuning_payload(result) is None
    assert build_result_payload(result)["platform"].get("tuning") is None


def test_tuned_bundle_carries_explicit_tuning_policy_generation_marker():
    """ADR-3 seam: a new-generation tuned bundle stamps the explicit generation
    marker in both the platform.tuning summary and the .tuning.json companion,
    next to the requested/applied hashes (never derived from benchbox_version)."""
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="auto_discovered",
        tuning_config_hash=config.get_configuration_hash(),
    )

    summary = build_result_payload(result)["platform"]["tuning"]
    companion = build_tuning_payload(result)

    assert summary["tuning_policy_generation"] == TUNING_POLICY_GENERATION
    assert companion["tuning_policy_generation"] == TUNING_POLICY_GENERATION


def test_no_tuning_omits_tuning_policy_generation_marker():
    """The generation marker rides with tuning: a run with no tuning emits no
    platform.tuning block at all, so no marker leaks onto untuned bundles."""
    result = _make_result(tunings_applied=None)

    assert build_result_payload(result)["platform"].get("tuning") is None
    assert build_tuning_payload(result) is None


def test_packaged_resource_source_maps_to_yaml_legacy_bridge():
    """A packaged-template run loads a real YAML template; the one-generation
    legacy `source` key must say "yaml", not "auto" (cross-branch composition
    with feat/tuning-template-packaging's PACKAGED_RESOURCE tuning source)."""
    from benchbox.core.results.schema import _legacy_tuning_source_bridge

    assert _legacy_tuning_source_bridge("packaged_resource", "tpch_tuned.yaml:abc123") == "yaml"
    assert _legacy_tuning_source_bridge("packaged_resource", None) == "yaml"
    assert _legacy_tuning_source_bridge("smart_defaults", None) == "auto"
