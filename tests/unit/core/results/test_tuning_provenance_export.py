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

from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload, build_tuning_payload
from benchbox.core.tuning.interface import TableTuning, TuningColumn, UnifiedTuningConfiguration

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


def test_template_run_bundle_carries_source_enum_template_ref_and_hash():
    config = _tuned_config()
    result = _make_result(
        tunings_applied=config.to_dict(),
        tuning_source="auto_discovered",
        tuning_source_file="examples/tunings/duckdb/tpch_tuned.yaml",
        tuning_config_hash=config.get_configuration_hash(),
        tuning_validation_status="APPLIED",
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

    companion = build_tuning_payload(result)
    assert companion["tuning_source"] == "auto_discovered"
    assert companion["source_file"] == "examples/tunings/duckdb/tpch_tuned.yaml"
    assert companion["requested_config_hash"] == config.get_configuration_hash()
    assert companion["hash"] == config.get_configuration_hash()
    assert companion["requested"]["table_tunings"]["lineitem"]["sorting"][0]["name"] == "l_orderkey"


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
