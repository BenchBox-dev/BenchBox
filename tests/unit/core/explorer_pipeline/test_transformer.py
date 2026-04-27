"""Unit tests for BundleTransformer."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchbox.core.explorer_pipeline.models import DetailResult, ManifestEntry
from benchbox.core.explorer_pipeline.transformer import BundleTransformer
from tests.unit.core.explorer_pipeline.conftest import MINIMAL_BUNDLE

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

    def test_cost_usd_none_when_absent(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)

        assert entry.cost_usd is None

    def test_cost_usd_extracted(self, tmp_path: Path) -> None:
        import copy

        data = copy.deepcopy(MINIMAL_BUNDLE)
        data["cost"] = {"total_usd": 1.23}
        bundle = tmp_path / "cost.json"
        bundle.write_text(json.dumps(data), encoding="utf-8")

        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle)

        assert entry.cost_usd == pytest.approx(1.23)

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
