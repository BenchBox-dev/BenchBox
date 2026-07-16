"""Unit tests for BundleTransformer."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from _project.scripts.explorer_pipeline.models import DetailResult, ManifestEntry
from _project.scripts.explorer_pipeline.transformer import BundleTransformer
from benchbox.core.cost.models import DeploymentMetadata, NormalizedCost
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestToManifestEntry:
    def test_basic_fields(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert isinstance(entry, ManifestEntry)
        assert entry.benchmark == "tpch"
        assert entry.platform == "duckdb"
        assert entry.scale_factor == pytest.approx(0.1)
        assert entry.run_date == "2026-03-15"
        assert entry.total_duration_s == pytest.approx(45.0)
        assert entry.query_count == 2

    def test_trust_label_and_visibility_defaults(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.trust_label == "maintainer-run"
        assert entry.visibility == "public-curated"

    def test_custom_trust_label_and_visibility(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(
            bundle_file,
            trust_label="community-submission",
            visibility="public-self-reported",
        )

        assert entry.trust_label == "community-submission"
        assert entry.visibility == "public-self-reported"

    def test_power_score_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.power_score == pytest.approx(1234.56)

    def test_driver_version_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.driver_version == "1.2.0"

    def test_result_id_injected(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        explicit_id = "my-explicit-id"
        entry = transformer.to_manifest_entry(bundle_file, result_id=explicit_id)

        assert entry.result_id == explicit_id

    def test_current_result_extension_blocks_are_ingested_without_projection_breakage(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["platform"].update(
            {
                "deployment": {"deployment_type": "local", "endpoint_class": "localhost_port"},
                "cloud": {"provider": "none"},
                "compute": {"instance_type": "developer-laptop"},
                "storage": {"storage_type": "local_disk"},
                "raw_config": {"host": "localhost", "port": 5432},
                "raw_metadata": {"server_version": "16.2"},
            }
        )
        data["phases"] = {
            "migration": {
                "status": "COMPLETED",
                "duration_ms": 2500,
                "tables_migrated": 8,
                "tables_failed": 0,
            }
        }
        data["comparisons"] = {
            "native_duckdb": {
                "generated_at": "2026-05-22T12:00:00",
                "scale_factor": 0.01,
                "total_queries": 1,
                "mean_delta_ms": 12.5,
                "max_delta_ms": 12.5,
                "queries": [{"id": "Q1", "pg_duckdb_ms": 42.5, "duckdb_ms": 30.0, "delta_ms": 12.5}],
            }
        }
        bundle = tmp_path / "extension_bundle.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)
        detail = transformer.to_detail_result(bundle, entry.result_id)

        assert entry.platform_version == "1.2.0"
        assert detail.phase_durations == {"migration": 2.5}
        assert detail.environment["os"] == "macOS 15.3.0"


class TestToDetailResult:
    def test_basic_fields(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert isinstance(detail, DetailResult)
        assert detail.result_id == rid
        assert detail.benchmark == "tpch"
        assert detail.platform == "duckdb"
        assert detail.scale_factor == pytest.approx(0.1)

    def test_queries_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert len(detail.queries) == 2
        q_ids = {q.query_id for q in detail.queries}
        assert q_ids == {"Q1", "Q6"}
        for q in detail.queries:
            assert q.status == "pass"

    def test_environment_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert detail.environment.get("os") == "macOS 15.3.0"
        assert detail.environment.get("arch") == "arm64"

    def test_no_companion_files_by_default(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert detail.has_plans is False
        assert detail.has_tuning is False

    def test_has_plans_detected(self, bundle_file: Path) -> None:
        plans_path = bundle_file.with_name(bundle_file.stem + ".plans.json")
        plans_path.write_text("{}", encoding="utf-8")

        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert detail.has_plans is True

    def test_bundle_download_url_set(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        url = f"/results/data/bundles/{rid}.json"
        detail = transformer.to_detail_result(bundle_file, rid, bundle_download_url=url)

        assert detail.bundle_download_url == url

    def test_detail_run_date_is_short_date(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        assert detail.run_date == "2026-03-15"


class TestResultIdFromBundle:
    def test_stable_id(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid1 = transformer.result_id_from_bundle(bundle_file)
        rid2 = transformer.result_id_from_bundle(bundle_file)

        assert rid1 == rid2

    def test_id_format(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)

        # Expected: {benchmark}-{platform}-sf{scale}-{yyyymmdd}-{sha8}
        assert rid.startswith("tpch-duckdb-sf0.1-")
        parts = rid.split("-")
        # sha8 should be last segment: 8 hex chars
        sha_part = parts[-1]
        assert len(sha_part) == 8
        assert all(c in "0123456789abcdef" for c in sha_part)

    def test_id_differs_for_different_content(self, bundle_file: Path, tmp_path: Path) -> None:
        other_data = json.loads(bundle_file.read_text(encoding="utf-8"))
        other_data["run"]["id"] = "different-exec"
        other_bundle = tmp_path / "other.json"
        other_bundle.write_text(json.dumps(other_data), encoding="utf-8")

        transformer = BundleTransformer()
        rid1 = transformer.result_id_from_bundle(bundle_file)
        rid2 = transformer.result_id_from_bundle(other_bundle)

        assert rid1 != rid2


class TestMalformedJson:
    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json", encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(Exception):
            transformer.result_id_from_bundle(bad_file)

    def test_malformed_json_to_manifest_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("}}broken{{", encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(Exception):
            transformer.to_manifest_entry(bad_file)


class TestSchemaGate:
    @pytest.mark.parametrize("version", ["2.99", "1.0", "2.x"])
    def test_unsupported_schema_rejected_before_manifest_projection(self, tmp_path: Path, version: str) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["version"] = version
        bundle = tmp_path / "unsupported_schema.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(ValueError) as exc_info:
            transformer.to_manifest_entry(bundle)

        message = str(exc_info.value)
        assert "explorer input schema policy" in message
        assert "schema versions 2.0 and 2.1" in message
        assert "Re-export or normalize" in message

    def test_missing_schema_rejected_before_detail_projection(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        del data["version"]
        bundle = tmp_path / "missing_schema.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(ValueError) as exc_info:
            transformer.to_detail_result(bundle, "missing-schema")

        assert "<missing>" in str(exc_info.value)
        assert "explorer input schema policy" in str(exc_info.value)

    def test_preloaded_data_uses_same_schema_gate(self, bundle_file: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["version"] = "2.99"

        transformer = BundleTransformer()
        with pytest.raises(ValueError, match="explorer input schema policy"):
            transformer.result_id_from_bundle(bundle_file, data=data, raw=b"{}")


class TestZeroDurationQuery:
    def test_zero_ms_preserved(self, tmp_path: Path) -> None:
        """A query with ms=0.0 must not be silently skipped or replaced."""
        data = {**MINIMAL_BUNDLE}
        data["queries"] = [
            {"id": "Q1", "ms": 0.0, "rows": 0, "iter": 1, "stream": 0, "run_type": "measurement", "status": "SUCCESS"},
        ]
        bundle = tmp_path / "zero_ms.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle)
        detail = transformer.to_detail_result(bundle, rid)

        assert len(detail.queries) == 1
        assert detail.queries[0].duration_ms == pytest.approx(0.0)

    def test_warmup_queries_excluded(self, tmp_path: Path) -> None:
        """Warmup-typed queries must not appear in query timings."""
        data = {**MINIMAL_BUNDLE}
        data["queries"] = [
            {"id": "Q1", "ms": 100.0, "iter": 0, "stream": 0, "run_type": "warmup", "status": "SUCCESS"},
            {"id": "Q1", "ms": 200.0, "iter": 1, "stream": 0, "run_type": "measurement", "status": "SUCCESS"},
        ]
        bundle = tmp_path / "warmup.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle)
        detail = transformer.to_detail_result(bundle, rid)

        assert len(detail.queries) == 1
        assert detail.queries[0].duration_ms == pytest.approx(200.0)


class TestExtendedManifestFields:
    """Tests for the extended fields added to ManifestEntry and DetailResult."""

    def test_geomean_ms_computed(self, bundle_file: Path) -> None:
        """geomean_ms is exp(mean(ln(ms))) over measurement queries."""
        import math

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        # Q1=8000, Q6=4000 → geomean = sqrt(8000*4000) = sqrt(32_000_000)
        expected = math.exp((math.log(8000.0) + math.log(4000.0)) / 2)
        assert entry.geomean_ms == pytest.approx(expected)

    def test_geomean_ms_none_when_no_queries(self, tmp_path: Path) -> None:
        data = {**MINIMAL_BUNDLE, "queries": []}
        bundle = tmp_path / "no_queries.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.geomean_ms is None

    def test_platform_version_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.platform_version == "1.2.0"

    def test_execution_mode_none_when_absent(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.execution_mode is None

    def test_execution_mode_extracted(self, tmp_path: Path) -> None:
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["execution_mode"] = "sql"
        bundle = tmp_path / "exec_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.execution_mode == "sql"

    def test_tuning_mode_none_when_absent(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.tuning_mode is None

    def test_tuning_hash_none_when_no_tuning(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.tuning_hash is None

    def test_tuning_hash_computed_when_present(self, tmp_path: Path) -> None:
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "tuned"
        bundle = tmp_path / "tuned.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_hash is not None
        assert len(entry.tuning_hash) == 8
        assert all(c in "0123456789abcdef" for c in entry.tuning_hash)

    def test_tuning_mode_falls_back_to_execution_block(self, tmp_path: Path) -> None:
        """Seed-corpus bundles wrote tuning_mode under execution, not config."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["execution"]["tuning_mode"] = "tuned"
        bundle = tmp_path / "exec_tuning_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)
        detail = transformer.to_detail_result(bundle, result_id="exec-tuning-mode")

        assert entry.tuning_mode == "tuned"
        assert detail.tuning_mode == "tuned"

    def test_tuning_mode_prefers_config_over_execution(self, tmp_path: Path) -> None:
        """When both locations carry a value, config.tuning_mode wins."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "custom"
        data["execution"]["tuning_mode"] = "tuned"
        bundle = tmp_path / "both_tuning_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_mode == "custom"

    def test_tuning_mode_stays_none_when_absent_everywhere(self, tmp_path: Path) -> None:
        """A bundle that never recorded tuning_mode must not be assigned a fake mode."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        bundle = tmp_path / "no_tuning_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_mode is None

    def test_legacy_raw_file_path_treated_as_not_recorded(self, tmp_path: Path) -> None:
        """ADR-2 consequences: a pre-vocabulary-pin bundle with a raw local
        tuning-file path as `tuning_mode` is not guessed into `custom` -- it's
        treated as not-recorded, same as if the field were absent."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "examples/tunings/duckdb/tpch_tuned.yaml"
        bundle = tmp_path / "legacy_path_tuning_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_mode is None

    def test_legacy_balanced_flavor_string_treated_as_not_recorded(self, tmp_path: Path) -> None:
        """ADR-2 §2: the wizard's old "balanced" flavor string is not a
        tuning_mode value and must not pass through ingest verbatim."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "balanced"
        bundle = tmp_path / "legacy_balanced_tuning_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_mode is None

    def test_legacy_config_value_falls_back_to_valid_execution_value(self, tmp_path: Path) -> None:
        """An unrecognized config.tuning_mode doesn't block a canonical value
        recorded (redundantly) under execution.tuning_mode on the same bundle."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "balanced"
        data["execution"]["tuning_mode"] = "tuned"
        bundle = tmp_path / "legacy_config_valid_execution.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_mode == "tuned"

    def test_physical_mechanisms_and_rendering_id_extracted_from_logical_profile(self, tmp_path: Path) -> None:
        """ADR-2 §3: platform.tuning.logical_profile feeds DetailResult so the
        ComparabilityReceipt can warn on mismatched physical mechanisms and
        facetMatching can offer physical_rendering_id as a secondary facet."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "tuned"
        data["platform"]["tuning"] = {
            "source": "auto",
            "logical_profile": {
                "physical_rendering_id": "databricks_z_order",
                "physical_mechanisms": ["indexes", "clustering"],
            },
        }
        bundle = tmp_path / "logical_profile.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        detail = transformer.to_detail_result(bundle, result_id="logical-profile")

        assert detail.physical_rendering_id == "databricks_z_order"
        assert detail.physical_mechanisms == ["indexes", "clustering"]

    def test_physical_mechanisms_none_and_rendering_id_none_when_no_logical_profile_recorded(
        self, bundle_file: Path
    ) -> None:
        """A bundle with no platform.tuning.logical_profile at all is UNKNOWN
        (None), not "recorded zero mechanisms" ([]). Collapsing these would
        make a legacy bundle compared against a genuinely zero-mechanism
        tuned run look like a real "different mechanisms" mismatch instead
        of "nothing to compare" (see ComparabilityReceipt's undefined-guard,
        which depends on this distinction surviving ingest)."""
        transformer = BundleTransformer()
        detail = transformer.to_detail_result(bundle_file, result_id="no-logical-profile")

        assert detail.physical_mechanisms is None
        assert detail.physical_rendering_id is None

    def test_physical_mechanisms_empty_list_when_logical_profile_recorded_with_zero_mechanisms(
        self, tmp_path: Path
    ) -> None:
        """A logical_profile object IS present but genuinely has zero
        mechanisms -- this is the ADR-2 motivating case (one platform
        renders six mechanisms, another renders zero, for the same tuned
        template) and must be distinguishable from "no profile recorded"."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_mode"] = "tuned"
        data["platform"]["tuning"] = {
            "source": "auto",
            "logical_profile": {"physical_mechanisms": []},
        }
        bundle = tmp_path / "logical_profile_empty_mechanisms.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        detail = transformer.to_detail_result(bundle, result_id="empty-mechanisms")

        assert detail.physical_mechanisms == []
        assert detail.physical_mechanisms is not None

    def test_tuned_fallback_and_custom_pass_through_verbatim(self, tmp_path: Path) -> None:
        """The two new ADR-2 vocabulary values ingest like any other canonical mode."""
        import copy

        for mode in ("tuned-fallback", "custom"):
            data = copy.deepcopy(MINIMAL_BUNDLE)
            data["config"]["tuning_mode"] = mode
            bundle = tmp_path / f"mode_{mode}.json"
            bundle.write_text(json.dumps(data), encoding="utf-8")

            transformer = BundleTransformer()
            entry = transformer.to_manifest_entry(bundle)

            assert entry.tuning_mode == mode

    def test_tuning_hash_uses_execution_fallback_mode(self, tmp_path: Path) -> None:
        """tuning_hash resolves mode via the same execution.tuning_mode fallback."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["execution"]["tuning_mode"] = "tuned"
        bundle = tmp_path / "exec_tuning_hash.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_hash is not None
        assert len(entry.tuning_hash) == 8

    def test_tuning_hash_dict_detail_is_hashed_canonically(self, tmp_path: Path) -> None:
        """A dict tuning_config is machine-readable, so key order must not affect the hash."""
        import copy

        data_a = copy.deepcopy(MINIMAL_BUNDLE)
        data_a["config"]["tuning_mode"] = "tuned"
        data_a["config"]["tuning_config"] = {"a": 1, "b": 2}
        bundle_a = tmp_path / "dict_a.json"
        bundle_a.write_text(json.dumps(data_a), encoding="utf-8")

        data_b = copy.deepcopy(MINIMAL_BUNDLE)
        data_b["config"]["tuning_mode"] = "tuned"
        data_b["config"]["tuning_config"] = {"b": 2, "a": 1}
        bundle_b = tmp_path / "dict_b.json"
        bundle_b.write_text(json.dumps(data_b), encoding="utf-8")

        transformer = BundleTransformer()
        entry_a = transformer.to_manifest_entry(bundle_a)
        entry_b = transformer.to_manifest_entry(bundle_b)

        assert entry_a.tuning_hash == entry_b.tuning_hash
        assert entry_a.tuning_hash is not None

    def test_tuning_hash_string_repr_detail_is_not_hashed(self, tmp_path: Path) -> None:
        """A repr() string is not canonical: it must be dropped, not hashed verbatim.

        Two bundles with cosmetically different repr strings for the same mode
        must produce the same hash (mode-only), proving the repr text itself
        is excluded from the hash payload.
        """
        import copy

        data_a = copy.deepcopy(MINIMAL_BUNDLE)
        data_a["config"]["tuning_mode"] = "tuned"
        data_a["config"]["tuning_config"] = (
            "UnifiedTuningConfiguration(primary_keys=PrimaryKeyConfiguration(enabled=True))"
        )
        bundle_a = tmp_path / "repr_a.json"
        bundle_a.write_text(json.dumps(data_a), encoding="utf-8")

        data_b = copy.deepcopy(MINIMAL_BUNDLE)
        data_b["config"]["tuning_mode"] = "tuned"
        data_b["config"]["tuning_config"] = (
            "UnifiedTuningConfiguration(primary_keys=PrimaryKeyConfiguration(enabled=False))"
        )
        bundle_b = tmp_path / "repr_b.json"
        bundle_b.write_text(json.dumps(data_b), encoding="utf-8")

        transformer = BundleTransformer()
        entry_a = transformer.to_manifest_entry(bundle_a)
        entry_b = transformer.to_manifest_entry(bundle_b)
        mode_only = transformer.to_manifest_entry(bundle_a, data={**data_a, "config": {"tuning_mode": "tuned"}})

        assert entry_a.tuning_hash is not None
        assert entry_a.tuning_hash == entry_b.tuning_hash
        assert entry_a.tuning_hash == mode_only.tuning_hash

    def test_tuning_hash_none_when_detail_is_repr_string_and_no_mode(self, tmp_path: Path) -> None:
        """No mode + a non-canonical repr string detail: nothing machine-readable to hash."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["config"]["tuning_config"] = (
            "UnifiedTuningConfiguration(primary_keys=PrimaryKeyConfiguration(enabled=True))"
        )
        bundle = tmp_path / "repr_no_mode.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.tuning_hash is None

    def test_test_type_from_benchmark_block(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.test_type == "power"

    def test_validation_status_extracted(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.validation_status == "passed"

    def test_validation_status_dict_form(self, tmp_path: Path) -> None:
        """summary.validation may be a dict {"status": "passed", ...} - extract .status."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["summary"]["validation"] = {"status": "passed", "mode": "exact"}
        bundle = tmp_path / "dict_validation.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.validation_status == "passed"

    def test_translation_fallback_marks_explorer_validation_uncertain(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["summary"]["validation"] = "passed"
        data["execution"] = {
            "mode": "sql",
            "translation": {"status": "fallback", "strict_mode": False},
        }
        bundle = tmp_path / "translation_fallback.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)
        detail = transformer.to_detail_result(bundle, result_id="translation-fallback")

        assert entry.validation_status == "uncertain"
        assert entry.ranking_exclusion_reason == "validation_not_clean"
        assert detail.validation_status == "uncertain"
        assert detail.ranking_exclusion_reason == "validation_not_clean"

    def test_partial_query_failure_count_and_status_extracted(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["summary"]["queries"] = {"total": 2, "passed": 1, "failed": 1}
        data["summary"]["validation"] = "passed"
        data["queries"][1]["status"] = "ERROR"
        bundle = tmp_path / "partial_query_failure.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)
        detail = transformer.to_detail_result(bundle, result_id="partial-query-failure")

        assert entry.failed_query_count == 1
        assert detail.failed_query_count == 1
        assert entry.validation_status == "partial"
        assert detail.validation_status == "partial"

    def test_missing_status_does_not_create_partial_query_failure(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        for query in data["queries"]:
            del query["status"]
        bundle = tmp_path / "legacy_no_query_status.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.failed_query_count == 0
        assert entry.validation_status == "passed"

    def test_cost_usd_none_when_absent(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.cost_usd is None
        assert entry.normalized_cost["cost_status"] == "unavailable"
        assert entry.normalized_cost["normalized_cost_usd"] is None

    def test_legacy_total_cost_does_not_populate_normalized_alias(self, tmp_path: Path) -> None:
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["cost"] = {"total_usd": 1.23}
        bundle = tmp_path / "cost.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.cost_usd is None
        assert entry.normalized_cost["cost_status"] == "unavailable"

    @pytest.mark.parametrize(
        ("normalized_cost", "expected_cost_usd"),
        [
            (
                NormalizedCost(
                    normalized_cost_usd="1.23",
                    cost_model_version="2026.05.0",
                    cost_model_source="benchbox.core.cost.pricing",
                    cost_scope="compute_only",
                    cost_status="normalized",
                    billing_unit="instance_hour",
                    pricing_region="us-east-1",
                    deployment=DeploymentMetadata(
                        cloud_provider="aws",
                        cloud_region="us-east-1",
                        instance_type="r7i.4xlarge",
                        node_count=2,
                        storage_format="parquet",
                    ),
                ),
                1.23,
            ),
            (
                NormalizedCost(
                    normalized_cost_usd="0",
                    cost_model_version="2026.05.0",
                    cost_model_source="benchbox.core.cost.pricing",
                    cost_scope="compute_only",
                    cost_status="not_applicable_local",
                    billing_unit="not_applicable",
                    pricing_region="not_applicable",
                ),
                None,
            ),
            (
                NormalizedCost(
                    normalized_cost_usd=None,
                    cost_model_version="2026.05.0",
                    cost_model_source="benchbox.core.cost.pricing",
                    cost_scope="compute_only",
                    cost_status="unavailable",
                    billing_unit="unknown",
                    pricing_region="unknown",
                ),
                None,
            ),
        ],
    )
    def test_normalized_cost_statuses_extracted(
        self,
        tmp_path: Path,
        normalized_cost: NormalizedCost,
        expected_cost_usd: float | None,
    ) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["normalized_cost"] = normalized_cost.to_dict()
        bundle = tmp_path / f"{normalized_cost.cost_status}.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)
        rid = transformer.result_id_from_bundle(bundle)
        detail = transformer.to_detail_result(bundle, rid)

        assert entry.cost_usd == expected_cost_usd
        assert detail.cost_usd == expected_cost_usd
        assert entry.normalized_cost == normalized_cost.to_dict()
        assert detail.normalized_cost == normalized_cost.to_dict()

    def test_environment_facets_extracted_from_normalized_contract(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["environment"]["platform_runtime"] = {
            "runtime_type": "managed_cloud",
            "collection_status": "partial",
            "source": "requested",
        }
        data["platform"]["deployment"] = {
            "deployment_type": "managed_cloud",
            "endpoint_class": "cloud_endpoint",
            "collection_status": "partial",
        }
        data["platform"]["cloud"] = {
            "provider": "aws",
            "region": "us-east-1",
            "collection_status": "partial",
        }
        data["platform"]["compute"] = {
            "warehouse_size": "XSMALL",
            "warehouse": "warehouse_hash",
            "collection_status": "partial",
        }
        data["platform"]["storage"] = {
            "table_format": "parquet",
            "collection_status": "partial",
        }
        bundle = tmp_path / "normalized_environment.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        entry = BundleTransformer().to_manifest_entry(bundle)

        assert entry.deployment_class == "cloud"
        assert entry.cloud_provider == "aws"
        assert entry.cloud_region == "us-east-1"
        assert entry.instance_or_warehouse == "XSMALL"
        assert entry.storage_format == "parquet"

    def test_environment_facets_do_not_fall_back_to_normalized_cost_deployment(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["environment"]["platform_runtime"] = {
            "runtime_type": "unknown",
            "collection_status": "unavailable",
            "source": "unavailable",
        }
        data["normalized_cost"] = NormalizedCost(
            normalized_cost_usd="1.23",
            cost_model_version="2026.05.0",
            cost_model_source="benchbox.core.cost.pricing",
            cost_scope="compute_only",
            cost_status="normalized",
            billing_unit="instance_hour",
            pricing_region="us-east-1",
            deployment=DeploymentMetadata(
                cloud_provider="aws",
                cloud_region="us-east-1",
                instance_type="r7i.4xlarge",
                warehouse_size="LARGE",
                storage_format="parquet",
            ),
        ).to_dict()
        bundle = tmp_path / "cost_deployment_only.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        entry = BundleTransformer().to_manifest_entry(bundle)

        assert entry.deployment_class == "unavailable"
        assert entry.cloud_provider is None
        assert entry.cloud_region is None
        assert entry.instance_or_warehouse is None
        assert entry.storage_format is None

    def test_legacy_environment_facets_fall_back_to_normalized_cost_deployment(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["normalized_cost"] = NormalizedCost(
            normalized_cost_usd="1.23",
            cost_model_version="2026.05.0",
            cost_model_source="benchbox.core.cost.pricing",
            cost_scope="compute_only",
            cost_status="normalized",
            billing_unit="instance_hour",
            pricing_region="us-east-1",
            deployment=DeploymentMetadata(
                cloud_provider="aws",
                cloud_region="us-east-1",
                instance_type="r7i.4xlarge",
                warehouse_size="LARGE",
                storage_format="parquet",
            ),
        ).to_dict()
        bundle = tmp_path / "legacy_cost_deployment.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        entry = BundleTransformer().to_manifest_entry(bundle)

        assert entry.deployment_class == "cloud"
        assert entry.cloud_provider == "aws"
        assert entry.cloud_region == "us-east-1"
        assert entry.instance_or_warehouse == "r7i.4xlarge"
        assert entry.storage_format == "parquet"

    def test_partial_normalized_cost_rejected(self, tmp_path: Path) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["normalized_cost"] = {
            "normalized_cost_usd": "1.23",
            "cost_status": "normalized",
        }
        bundle = tmp_path / "partial_normalized_cost.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(ValueError, match="cost_model_version"):
            transformer.to_manifest_entry(bundle)

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_normalized_cost_rejected(self, tmp_path: Path, value: str) -> None:
        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["normalized_cost"] = NormalizedCost(
            normalized_cost_usd="1.23",
            cost_model_version="2026.05.0",
            cost_model_source="benchbox.core.cost.pricing",
            cost_scope="compute_only",
            cost_status="normalized",
            billing_unit="instance_hour",
            pricing_region="us-east-1",
        ).to_dict()
        data["normalized_cost"]["normalized_cost_usd"] = value
        bundle = tmp_path / f"non_finite_{value}.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        with pytest.raises(ValueError, match="Invalid normalized_cost_usd"):
            transformer.to_manifest_entry(bundle)

    def test_test_type_inferred_from_phases(self, tmp_path: Path) -> None:
        """test_type falls back to phases block when benchmark.test_type is absent."""
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        del data["benchmark"]["test_type"]
        data["phases"] = {"throughput_test": {"streams": 4}}
        bundle = tmp_path / "phases_throughput.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.test_type == "throughput"

    def test_extended_fields_in_detail_result(self, bundle_file: Path) -> None:
        """DetailResult carries the same extended fields as ManifestEntry."""
        import math

        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        expected_geomean = math.exp((math.log(8000.0) + math.log(4000.0)) / 2)
        assert detail.geomean_ms == pytest.approx(expected_geomean)
        assert detail.platform_version == "1.2.0"
        assert detail.test_type == "power"
        assert detail.validation_status == "passed"


class TestQueryTimingExtendedFields:
    """Tests for run_type, iter, stream fields on QueryTiming."""

    def test_run_type_iter_stream_preserved(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle_file)
        detail = transformer.to_detail_result(bundle_file, rid)

        q1 = next(q for q in detail.queries if q.query_id == "Q1")
        assert q1.run_type == "measurement"
        assert q1.iter == 1
        assert q1.stream == 0

    def test_run_type_none_when_absent(self, tmp_path: Path) -> None:
        data = {**MINIMAL_BUNDLE}
        data["queries"] = [{"id": "Q1", "ms": 500.0, "status": "SUCCESS"}]
        bundle = tmp_path / "no_run_type.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        rid = transformer.result_id_from_bundle(bundle)
        detail = transformer.to_detail_result(bundle, rid)

        assert len(detail.queries) == 1
        assert detail.queries[0].run_type is None
        assert detail.queries[0].iter is None
        assert detail.queries[0].stream is None
