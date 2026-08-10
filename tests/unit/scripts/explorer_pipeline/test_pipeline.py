"""Integration tests for ExplorerPipeline."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import duckdb
import pytest

from _project.scripts.explorer_pipeline import pipeline as pipeline_module
from _project.scripts.explorer_pipeline.pipeline import (
    COMMUNITY_TRUST_LABEL,
    SUBMISSION_MANIFEST_FILENAME,
    ExplorerPipeline,
    _build_short_ids,
)
from _project.scripts.explorer_pipeline.transformer import BundleTransformer
from benchbox.core.results.anonymization import AnonymizationManager
from benchbox.core.results.canonical_json import canonical_json_bytes
from benchbox.validation.bundle import COMPANION_SUFFIXES
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Unit tests for _build_short_ids
# ---------------------------------------------------------------------------


class TestBuildShortIds:
    def test_empty_input_returns_empty_dict(self) -> None:
        assert _build_short_ids([]) == {}

    def test_single_id_returns_8_char_prefix(self) -> None:
        result = _build_short_ids(["tpch-duckdb-sf0.1-20260315-abcdef01"])
        assert len(result) == 1
        short_id = next(iter(result))
        assert len(short_id) == 8

    def test_short_id_is_sha256_prefix(self) -> None:
        rid = "tpch-duckdb-sf0.1-20260315-abcdef01"
        result = _build_short_ids([rid])
        expected_prefix = hashlib.sha256(rid.encode()).hexdigest()[:8]
        assert expected_prefix in result
        assert result[expected_prefix] == rid

    def test_all_values_map_back_to_input_ids(self) -> None:
        rids = [
            "tpch-duckdb-sf0.1-20260315-aaaa0001",
            "tpch-sqlite-sf0.1-20260315-bbbb0002",
            "tpch-polars-sf0.1-20260315-cccc0003",
        ]
        result = _build_short_ids(rids)
        assert set(result.values()) == set(rids)

    def test_no_duplicate_short_ids(self) -> None:
        rids = [f"tpch-platform{i}-sf0.1-20260315-{i:08x}" for i in range(20)]
        result = _build_short_ids(rids)
        assert len(result) == len(rids), "Every input must get a unique short ID"

    def test_collision_extends_to_longer_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When 8-char prefixes collide, the function extends until unique."""
        # Force a collision by patching hexdigest to return the same prefix for
        # the first two IDs at length 8 but different prefixes at length 10.
        rid_a = "tpch-duckdb-sf1-20260101-aaa"
        rid_b = "tpch-sqlite-sf1-20260101-bbb"
        real_sha256 = hashlib.sha256

        digest_a = real_sha256(rid_a.encode()).hexdigest()
        digest_b = real_sha256(rid_b.encode()).hexdigest()

        # Build a fake digest that shares the first 8 chars between rid_a and rid_b.
        shared_prefix = "deadbeef"  # 8 chars, injected for both
        fake_digests = {
            rid_a.encode(): shared_prefix + digest_a[8:],
            rid_b.encode(): shared_prefix + digest_b[8:],  # same 8-char prefix, different from 10+
        }

        class _FakeHash:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def hexdigest(self) -> str:
                return fake_digests.get(self._data, real_sha256(self._data).hexdigest())

        monkeypatch.setattr(hashlib, "sha256", _FakeHash)

        result = _build_short_ids([rid_a, rid_b])
        # All short IDs must be ≥ 8 chars and unique
        assert len(result) == 2
        for short_id in result:
            assert len(short_id) >= 8
        # Because the 8-char prefixes were identical, the result must use > 8 chars
        assert all(len(k) > 8 for k in result)


def _duckdb_results(output: Path) -> list[dict]:
    """Return results rows as dicts for assertions."""
    with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
        rows = con.execute("SELECT * FROM results").fetchall()
        description = con.description
        assert description is not None
        cols = [d[0] for d in description]
    return [dict(zip(cols, row)) for row in rows]


class TestExplorerPipelineRun:
    def test_does_not_emit_manifest_json(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert not (output / "manifest.json").exists()

    def test_results_table_populated(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        results = _duckdb_results(output)
        assert len(results) == 1

    def test_one_usable_row_populates_every_required_browser_scan(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        required_scans = (
            "results",
            "platform_index_rows",
            "benchmark_rankings",
            "benchmark_matrix_cells",
            "result_detail_metrics",
        )
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in required_scans}

        assert all(count >= 1 for count in counts.values()), counts

    def test_result_row_fields_from_bundle(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        entry = _duckdb_results(output)[0]
        assert entry["benchmark"] == "tpch"
        assert entry["platform"] == "duckdb"
        assert entry["scale_factor"] == pytest.approx(0.1)
        assert entry["trust_label"] == "maintainer-run"
        assert entry["visibility"] == "public-curated"

    def test_does_not_emit_details_dir(self, data_dir: Path, tmp_path: Path) -> None:
        """details/*.json was retired when Compare migrated to DuckDB (W4 slice 5)."""
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert not (output / "details").exists()

    def test_result_detail_metrics_populated_in_duckdb(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        result_id = _duckdb_results(output)[0]["result_id"]

        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            wide = con.execute(
                "SELECT result_id FROM result_detail_metrics WHERE result_id = ?",
                [result_id],
            ).fetchone()
            exec_count = con.execute(
                "SELECT COUNT(*) FROM query_executions WHERE result_id = ?",
                [result_id],
            ).fetchone()
        assert wide is not None
        assert exec_count is not None and exec_count[0] == 2

    def test_creates_results_duckdb(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert (output / "results.duckdb").exists()

    def test_copies_bundle_file(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        result_id = _duckdb_results(output)[0]["result_id"]
        bundle_copy = output / "bundles" / f"{result_id}.json"
        assert bundle_copy.exists()

    def test_copied_bundle_scrubs_private_paths(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle = json.loads(json.dumps(MINIMAL_BUNDLE))
        bundle["platform"]["working_dir"] = "/Users/alice/private-run"
        source = bundles_dir / "private_path.json"
        source.write_text(json.dumps(bundle), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        result_id = _duckdb_results(output)[0]["result_id"]
        published = (output / "bundles" / f"{result_id}.json").read_text(encoding="utf-8")
        assert "/Users/alice" not in published
        # working_dir is dropped at the public boundary (not path-hashed).
        assert "working_dir" not in published
        assert "private-run" not in published

    def test_result_id_and_bundle_filename_use_public_bytes(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle = json.loads(json.dumps(MINIMAL_BUNDLE))
        bundle["platform"]["working_dir"] = "/Users/alice/private-run"
        source = bundles_dir / "private_path.json"
        source.write_text(json.dumps(bundle), encoding="utf-8")

        transformer = BundleTransformer()
        raw = source.read_bytes()
        public_bundle = AnonymizationManager().anonymize_result_payload(bundle)
        private_result_id = transformer.result_id_from_bundle(source, data=bundle, raw=raw)
        public_result_id = transformer.result_id_from_bundle(
            source, data=public_bundle, raw=canonical_json_bytes(public_bundle)
        )
        assert public_result_id != private_result_id

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert (output / "bundles" / f"{public_result_id}.json").exists()
        assert not (output / "bundles" / f"{private_result_id}.json").exists()

    def test_applied_receipt_is_sanitized_before_duckdb_publication(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        source = bundles_dir / "with_receipt.json"
        source.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        source.with_name("with_receipt.applied.json").write_text(
            json.dumps({"receipt": {"entries": [{"statement": "SET path=/Users/alice/private"}]}}),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        row = _duckdb_results(output)[0]
        assert row["applied_receipt"] is not None
        assert "/Users/alice" not in row["applied_receipt"]

    def test_publishes_plans_sidecar_when_present(self, tmp_path: Path) -> None:
        """w1 wire-up: when a ``*.plans.json`` sidecar exists alongside a
        bundle, the pipeline must copy it to ``out/bundles/<result_id>.plans.json``
        AND set ``plans_published=true`` on the result row.

        Pre-wire-up (PR #179 added ``plans_published`` only to the consumer
        side), the field was never set anywhere → always falsy → the explorer
        UI never rendered a download link even for bundles that genuinely had
        plans. This test confirms the producer side now fills the field."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "with_plans.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("with_plans.plans.json").write_text(
            '{"queries": [{"query_id": "Q1", "plan": "SCAN tpch.lineitem"}]}',
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        rows = _duckdb_results(output)
        assert len(rows) == 1
        result_id = rows[0]["result_id"]
        assert rows[0]["plans_published"] is True
        assert (output / "bundles" / f"{result_id}.plans.json").exists()

    def test_plans_published_false_when_no_sidecar(self, data_dir: Path, tmp_path: Path) -> None:
        """w1 wire-up (negative side): without a ``*.plans.json`` sidecar,
        ``plans_published`` must remain false and no plans file should be
        written to the published bundles directory."""
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        rows = _duckdb_results(output)
        assert all(row["plans_published"] is False for row in rows)
        assert not list((output / "bundles").glob("*.plans.json"))

    def test_publishes_tuning_sidecar_and_sets_has_tuning_after_copy(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "with_tuning.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("with_tuning.tuning.json").write_text(
            json.dumps(
                {
                    "version": "2.1",
                    "run_id": "test-exec-001",
                    "source_file": "/Users/alice/private/tuning.yaml",
                    "requested": {"table_tunings": {"lineitem": {"table_name": "lineitem"}}},
                }
            ),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        row = _duckdb_results(output)[0]
        result_id = row["result_id"]
        tuning_path = output / "bundles" / f"{result_id}.tuning.json"
        assert row["has_tuning"] is True
        assert tuning_path.exists()
        published = tuning_path.read_text(encoding="utf-8")
        assert "/Users/alice" not in published
        assert "lineitem" not in published

    def test_publishes_sanitized_applied_companion(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "with_applied.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("with_applied.applied.json").write_text(
            json.dumps(
                {
                    "status": "applied_unverified",
                    "applied_ledger_hash": "a" * 64,
                    "statements": [{"statement": "SET warehouse=/Users/alice/private", "status": "executed"}],
                    "dropped": [{"reason": "private adapter detail"}],
                    "receipt": {"entries": [{"statement": "CREATE INDEX private_table", "verdict": "unknown"}]},
                }
            ),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        row = _duckdb_results(output)[0]
        result_id = row["result_id"]
        applied_path = output / "bundles" / f"{result_id}.applied.json"
        assert applied_path.exists()
        published = applied_path.read_text(encoding="utf-8")
        assert "/Users/alice" not in published
        assert '"statement"' not in published

    @pytest.mark.parametrize("suffix", [".tuning.json", ".applied.json"])
    def test_malformed_companion_is_not_published_or_advertised(
        self, data_dir: Path, tmp_path: Path, suffix: str
    ) -> None:
        bundle = next(data_dir.joinpath("bundles").rglob("*.json"))
        bundle.with_name(f"{bundle.stem}{suffix}").write_text("{not json", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        row = _duckdb_results(output)[0]
        assert row["has_tuning"] is False
        assert not list((output / "bundles").glob(f"*{suffix}"))

    def test_discovers_nested_bundle_layout(self, tmp_path: Path) -> None:
        nested_dir = tmp_path / "data" / "bundles" / "tpch" / "duckdb" / "sf0.1"
        nested_dir.mkdir(parents=True)
        bundle_path = nested_dir / "nested.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        results = _duckdb_results(output)
        assert len(results) == 1
        assert results[0]["result_id"].startswith("tpch-duckdb-sf0.1-")

    def test_skips_companion_files_during_recursive_discovery(self, tmp_path: Path) -> None:
        nested_dir = tmp_path / "data" / "bundles" / "tpch" / "duckdb" / "sf0.1"
        nested_dir.mkdir(parents=True)
        bundle_path = nested_dir / "sample.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("sample.plans.json").write_text("{}", encoding="utf-8")
        bundle_path.with_name("sample.tuning.json").write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert len(_duckdb_results(output)) == 1

    def test_loads_each_bundle_once(self, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        transformer = BundleTransformer()
        load_calls = 0
        real_load_bundle_full = transformer.load_bundle_full

        def counted_load_bundle_full(bundle_path: Path) -> tuple:
            nonlocal load_calls
            load_calls += 1
            return real_load_bundle_full(bundle_path)

        monkeypatch.setattr(transformer, "load_bundle_full", counted_load_bundle_full)

        output = tmp_path / "out"
        ExplorerPipeline(transformer=transformer).run(data_dir, output)

        assert load_calls == 1

    def test_skips_corrupt_bundle_and_keeps_valid_results(self, data_dir: Path, tmp_path: Path) -> None:
        corrupt_dir = data_dir / "bundles" / "tpch" / "duckdb" / "sf0.1"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        (corrupt_dir / "broken.json").write_text("{not valid json", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert len(_duckdb_results(output)) == 1

    def test_empty_data_dir_is_rejected_before_promotion(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        # No bundles/ sub-directory at all
        output = tmp_path / "out"
        with pytest.raises(ValueError, match="required browser scan"):
            ExplorerPipeline().run(data_dir, output)

        assert not output.exists()

    def test_empty_bundles_dir_is_rejected_before_promotion(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        (data_dir / "bundles").mkdir(parents=True)
        output = tmp_path / "out"
        with pytest.raises(ValueError, match="required browser scan"):
            ExplorerPipeline().run(data_dir, output)

        assert not output.exists()

    def test_all_skipped_corpus_fails_before_promotion(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        bundles_dir = data_dir / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "invalid.json").write_text("{not valid json", encoding="utf-8")
        output = tmp_path / "out"

        with pytest.raises(ValueError, match="required browser scan"):
            ExplorerPipeline().run(data_dir, output)

        assert not output.exists()

    def test_unpublishable_rebuild_preserves_last_known_good_output(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)
        before_db = (output / "results.duckdb").read_bytes()
        before_bundles = sorted(path.name for path in (output / "bundles").iterdir())

        invalid_data_dir = tmp_path / "invalid_data"
        (invalid_data_dir / "bundles").mkdir(parents=True)
        (invalid_data_dir / "bundles" / "invalid.json").write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ValueError, match="required browser scan"):
            ExplorerPipeline().run(invalid_data_dir, output)

        assert (output / "results.duckdb").read_bytes() == before_db
        assert sorted(path.name for path in (output / "bundles").iterdir()) == before_bundles

    def test_submission_manifest_sidecar_overrides_trust_label(self, tmp_path: Path) -> None:
        """A bundle with a submission-manifest.json sidecar gets community-submission trust."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "community_result.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        # Place sidecar manifest alongside the bundle
        (bundles_dir / SUBMISSION_MANIFEST_FILENAME).write_text(
            json.dumps({"bundle_hash": "abc123", "bundle_file": "community_result.json"}),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        entry = _duckdb_results(output)[0]
        assert entry["trust_label"] == COMMUNITY_TRUST_LABEL

        # result_detail_metrics row carries the same override
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            row = con.execute(
                "SELECT trust_label FROM result_detail_metrics WHERE result_id = ?",
                [entry["result_id"]],
            ).fetchone()
        assert row is not None and row[0] == COMMUNITY_TRUST_LABEL

    def test_no_sidecar_keeps_default_trust_label(self, data_dir: Path, tmp_path: Path) -> None:
        """Without a submission-manifest.json, the pipeline-level trust_label is used."""
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output, trust_label="maintainer-run")

        assert _duckdb_results(output)[0]["trust_label"] == "maintainer-run"

    def test_top_level_vendor_subtree_sets_vendor_label_and_visibility(self, tmp_path: Path) -> None:
        """A bundle under the top-level vendor/ subtree is vendor-supplied + public-vendor-reported."""
        vendor_dir = tmp_path / "data" / "bundles" / "vendor"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "vendor_result.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        entry = _duckdb_results(output)[0]
        assert entry["trust_label"] == "vendor-supplied"
        assert entry["visibility"] == "public-vendor-reported"

    def test_nested_vendor_dir_does_not_grant_vendor_label(self, tmp_path: Path) -> None:
        """A nested directory merely named 'vendor' must NOT self-grant the vendor label."""
        nested = tmp_path / "data" / "bundles" / "community" / "vendor"
        nested.mkdir(parents=True)
        (nested / "result.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        assert _duckdb_results(output)[0]["trust_label"] == "maintainer-run"

    def test_funding_flows_from_bundle_provenance(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        funded = {**MINIMAL_BUNDLE, "provenance": {"funding": "free-trial"}}
        (bundles_dir / "funded_result.json").write_text(json.dumps(funded), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert _duckdb_results(output)[0]["funding"] == "free-trial"

    def test_funding_defaults_to_unspecified(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert _duckdb_results(output)[0]["funding"] == "unspecified"

    def test_per_bundle_manifest_sidecar_overrides_trust_label(self, tmp_path: Path) -> None:
        """The new `<stem>.manifest.json` naming triggers the community trust label."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "community_result.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        # Per-bundle manifest naming: <stem>.manifest.json next to the bundle.
        (bundles_dir / "community_result.manifest.json").write_text(
            json.dumps({"bundle_hash": "abc123", "bundle_file": "community_result.json"}),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        assert _duckdb_results(output)[0]["trust_label"] == COMMUNITY_TRUST_LABEL

    def test_per_bundle_manifest_excluded_from_bundle_discovery(self, tmp_path: Path) -> None:
        """`<stem>.manifest.json` files are not picked up as bundles."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "real_bundle.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        (bundles_dir / "real_bundle.manifest.json").write_text("{}", encoding="utf-8")
        (bundles_dir / "other.manifest.json").write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        # Only the real bundle, not either manifest sidecar.
        assert len(_duckdb_results(output)) == 1

    def test_submission_manifest_excluded_from_bundle_discovery(self, tmp_path: Path) -> None:
        """submission-manifest.json should not be treated as a bundle file."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "real_bundle.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        (bundles_dir / SUBMISSION_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        # Only the real bundle, not the sidecar
        assert len(_duckdb_results(output)) == 1

    def test_applied_companion_excluded_from_bundle_discovery(self, tmp_path: Path) -> None:
        """Regression: `<stem>.applied.json` is a companion, never a bundle.

        ``bundle_publisher`` copies every entry of ``COMPANION_SUFFIXES`` next
        to the published bundle, so an ``.applied.json`` sits in the bundles
        dir for every tuned run. Discovery previously excluded only the
        plans/tuning companions, so the applied ledger was picked up and
        transformed as if it were a result bundle.
        """
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "real_bundle.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("real_bundle.applied.json").write_text(
            json.dumps(
                {
                    "status": "applied_verified",
                    "applied_ledger_hash": "a" * 64,
                    "statements": [{"statement": "CREATE INDEX ...", "status": "applied"}],
                    "receipt": {"platform": "duckdb", "corroborated": True, "entries": []},
                }
            ),
            encoding="utf-8",
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        # Only the real bundle, not the applied-ledger companion.
        assert len(_duckdb_results(output)) == 1

    def test_discovery_ignores_json_named_directories_and_mixed_case_companions(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "directory.json").mkdir()
        (bundles_dir / "real_bundle.JSON").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        (bundles_dir / "real_bundle.APPLIED.JSON").write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert len(_duckdb_results(output)) == 1

    def test_applied_receipt_reaches_results_table_and_detail_view(self, tmp_path: Path) -> None:
        """End-to-end: the companion's receipt lands in DuckDB verbatim.

        Pins the DDL / positional-INSERT / ``result_detail_metrics`` projection
        alignment for the ``applied_receipt`` column -- a mismatch there would
        silently store the receipt in the wrong column.
        """
        receipt = {
            "platform": "duckdb",
            "corroborated": True,
            "entries": [{"statement": "CREATE INDEX ...", "verdict": "corroborated", "table": "lineitem"}],
        }
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        bundle_path = bundles_dir / "receipted.json"
        bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_path.with_name("receipted.applied.json").write_text(
            json.dumps({"status": "applied_verified", "receipt": receipt}), encoding="utf-8"
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        rows = _duckdb_results(output)
        assert len(rows) == 1
        assert json.loads(rows[0]["applied_receipt"]) == receipt

        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            projected = con.execute("SELECT applied_receipt FROM result_detail_metrics").fetchall()
        assert json.loads(projected[0][0]) == receipt

    def test_applied_receipt_null_when_no_companion(self, tmp_path: Path) -> None:
        """A run with no receipt stores SQL NULL, not an empty string."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "plain.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert _duckdb_results(output)[0]["applied_receipt"] is None

    def test_discovery_excludes_every_canonical_companion_suffix(self, tmp_path: Path) -> None:
        """Pin discovery against the canonical companion tuple.

        A newly added companion kind must not silently start being transformed
        as a bundle -- that is exactly how ``.applied.json`` slipped through.
        """
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "real_bundle.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        for suffix in COMPANION_SUFFIXES:
            (bundles_dir / f"real_bundle{suffix}").write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output)

        assert len(_duckdb_results(output)) == 1

    def test_mixed_bundles_with_and_without_sidecar(self, tmp_path: Path) -> None:
        """Bundles in different dirs get independent trust labels based on sidecar presence."""
        data_dir = tmp_path / "data" / "bundles"
        # Maintainer bundle - no sidecar
        maintainer_dir = data_dir / "tpch" / "duckdb" / "sf0.1"
        maintainer_dir.mkdir(parents=True)
        (maintainer_dir / "maintainer.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        # Community bundle - with sidecar
        community_dir = data_dir / "tpch" / "sqlite" / "sf0.1"
        community_dir.mkdir(parents=True)
        community_bundle = {**MINIMAL_BUNDLE, "platform": {"name": "sqlite", "version": "3.45"}}
        (community_dir / "community.json").write_text(json.dumps(community_bundle), encoding="utf-8")
        (community_dir / SUBMISSION_MANIFEST_FILENAME).write_text(
            json.dumps({"bundle_hash": "abc123"}), encoding="utf-8"
        )

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        rows = _duckdb_results(output)
        assert len(rows) == 2
        entries = {e["platform"]: e["trust_label"] for e in rows}
        assert entries["duckdb"] == "maintainer-run"
        assert entries["sqlite"] == COMMUNITY_TRUST_LABEL

    def test_malformed_sidecar_still_triggers_community_trust(self, tmp_path: Path) -> None:
        """Presence-only contract: even a malformed sidecar triggers the override."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "result.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        # Malformed JSON - pipeline should not parse it, only check existence
        (bundles_dir / SUBMISSION_MANIFEST_FILENAME).write_text("NOT VALID JSON", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        assert _duckdb_results(output)[0]["trust_label"] == COMMUNITY_TRUST_LABEL

    def test_duckdb_snapshot_reflects_overridden_trust_label(self, tmp_path: Path) -> None:
        """DuckDB snapshot must contain community-submission for sidecar bundles."""
        data_dir = tmp_path / "data" / "bundles"
        # Maintainer bundle
        maintainer_dir = data_dir / "tpch" / "duckdb" / "sf0.1"
        maintainer_dir.mkdir(parents=True)
        (maintainer_dir / "m.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        # Community bundle with sidecar
        community_dir = data_dir / "tpch" / "sqlite" / "sf0.1"
        community_dir.mkdir(parents=True)
        community_bundle = {**MINIMAL_BUNDLE, "platform": {"name": "sqlite", "version": "3.45"}}
        (community_dir / "c.json").write_text(json.dumps(community_bundle), encoding="utf-8")
        (community_dir / SUBMISSION_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            rows = con.execute("SELECT platform, trust_label FROM results ORDER BY platform").fetchall()

        trust_by_platform = {row[0]: row[1] for row in rows}
        assert trust_by_platform["duckdb"] == "maintainer-run"
        assert trust_by_platform["sqlite"] == COMMUNITY_TRUST_LABEL

    def test_sidecar_detection_emits_debug_log(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Logger.debug fires when a submission-manifest.json sidecar is detected."""
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "result.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        (bundles_dir / SUBMISSION_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        with caplog.at_level(logging.DEBUG, logger="_project.scripts.explorer_pipeline.pipeline"):
            ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        assert any("Found submission manifest" in rec.message for rec in caplog.records)

    def test_sidecar_in_root_bundles_dir_overrides_all_flat_bundles(self, tmp_path: Path) -> None:
        """A sidecar in the top-level bundles/ dir affects all bundles in that directory.

        This is intentional: the directory-locality rule means all bundles sharing
        a directory share the same trust label.
        """
        bundles_dir = tmp_path / "data" / "bundles"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "a.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
        bundle_b = {**MINIMAL_BUNDLE, "platform": {"name": "sqlite", "version": "3.45"}}
        (bundles_dir / "b.json").write_text(json.dumps(bundle_b), encoding="utf-8")
        # Sidecar at root level - both bundles in this dir become community
        (bundles_dir / SUBMISSION_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")

        output = tmp_path / "out"
        ExplorerPipeline().run(tmp_path / "data", output, trust_label="maintainer-run")

        rows = _duckdb_results(output)
        assert len(rows) == 2
        trust_labels = {e["trust_label"] for e in rows}
        assert trust_labels == {COMMUNITY_TRUST_LABEL}

    def test_custom_trust_label_and_visibility(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(
            data_dir,
            output,
            trust_label="community-submission",
            visibility="public-self-reported",
        )

        entry = _duckdb_results(output)[0]
        assert entry["trust_label"] == COMMUNITY_TRUST_LABEL
        assert entry["visibility"] == "public-self-reported"

    def test_custom_bundle_url_prefix(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output, bundle_url_prefix="/cdn/bundles")

        result_id = _duckdb_results(output)[0]["result_id"]
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            row = con.execute(
                "SELECT bundle_download_url FROM result_detail_metrics WHERE result_id = ?",
                [result_id],
            ).fetchone()
        assert row is not None
        assert row[0] == f"/cdn/bundles/{result_id}.json"

    def test_custom_bundle_url_prefix_trailing_slash(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output, bundle_url_prefix="/cdn/bundles/")

        result_id = _duckdb_results(output)[0]["result_id"]
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            row = con.execute(
                "SELECT bundle_download_url FROM result_detail_metrics WHERE result_id = ?",
                [result_id],
            ).fetchone()
        assert row is not None
        assert row[0] == f"/cdn/bundles/{result_id}.json"

    def test_permission_error_propagates(self, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """System-level errors must not be silently swallowed."""
        transformer = BundleTransformer()
        monkeypatch.setattr(
            transformer,
            "load_bundle_full",
            lambda _: (_ for _ in ()).throw(PermissionError("access denied")),
        )
        output = tmp_path / "out"
        with pytest.raises(PermissionError):
            ExplorerPipeline(transformer=transformer).run(data_dir, output)

    def test_duckdb_contains_correct_row_count(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        assert count == 1

    def test_does_not_emit_short_ids_json(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert not (output / "short_ids.json").exists(), (
            "short_ids.json must not be emitted - short IDs live in the DuckDB short_ids table"
        )

    def test_short_ids_table_maps_short_to_full_result_id(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        result_id = _duckdb_results(output)[0]["result_id"]
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            rows = con.execute("SELECT short_id, result_id FROM short_ids").fetchall()
        assert len(rows) == 1
        short_id, mapped_result_id = rows[0]
        assert len(short_id) >= 8, "Short IDs must be at least 8 hex chars"
        assert mapped_result_id == result_id, "short → full mapping must be correct"

    def test_short_id_is_sha256_prefix_of_result_id(self, data_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        result_id = _duckdb_results(output)[0]["result_id"]
        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            short_id = con.execute("SELECT short_id FROM short_ids WHERE result_id = ?", [result_id]).fetchone()[0]

        expected = hashlib.sha256(result_id.encode()).hexdigest()[: len(short_id)]
        assert short_id == expected, "Short ID must be a sha256 prefix of the full result_id"

    def test_benchmark_rankings_short_id_matches_short_ids_table(self, data_dir: Path, tmp_path: Path) -> None:
        """Each benchmark_rankings row's short_id must round-trip through short_ids."""
        import duckdb

        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        with duckdb.connect(str(output / "results.duckdb"), read_only=True) as con:
            rows = con.execute(
                "SELECT br.short_id, br.result_id, si.result_id AS resolved"
                " FROM benchmark_rankings br"
                " LEFT JOIN short_ids si ON si.short_id = br.short_id"
            ).fetchall()

        assert rows, "At least one benchmark_rankings row must be written"
        for short_id, result_id, resolved in rows:
            if short_id:
                assert resolved == result_id, (
                    f"short_id {short_id!r} in benchmark_rankings must resolve to {result_id!r}"
                )


# ---------------------------------------------------------------------------
# Staged-output publication guards (PR #1483 review follow-ups)
# ---------------------------------------------------------------------------


class TestStagedOutputGuards:
    def test_symlinked_bundles_destination_is_rejected(self, data_dir: Path, tmp_path: Path) -> None:
        """A symlinked `bundles/` must not be published into.

        `mkdir(exist_ok=True)` accepts a symlink to a directory, so without an
        explicit check every copy and the post-promotion stale sweep would
        follow the link and delete unrelated `*.json` in the target.
        """
        output = tmp_path / "out"
        output.mkdir()
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        bystander = unrelated / "keep-me.json"
        bystander.write_text('{"keep": true}', encoding="utf-8")
        (output / "bundles").symlink_to(unrelated, target_is_directory=True)

        with pytest.raises(ValueError, match="must be a real directory"):
            ExplorerPipeline().run(data_dir, output)

        assert bystander.exists(), "A build must never sweep files inside a symlink target"

    def test_staging_dir_is_removed_when_a_pre_build_step_fails(
        self, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An uncaught error before the DB build must not strand the staging tree."""
        output = tmp_path / "out"

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("input vanished mid-build")

        monkeypatch.setattr(pipeline_module, "_build_short_ids", _boom)

        with pytest.raises(OSError, match="input vanished"):
            ExplorerPipeline().run(data_dir, output)

        leftovers = [p.name for p in output.parent.iterdir() if p.name.startswith(f".{output.name}.")]
        assert leftovers == [], f"Staging directory leaked after a pre-build failure: {leftovers}"
