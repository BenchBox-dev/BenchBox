"""Integration tests for ExplorerPipeline."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import duckdb
import pytest
from _project.scripts.explorer_pipeline.pipeline import (
    COMMUNITY_TRUST_LABEL,
    SUBMISSION_MANIFEST_FILENAME,
    ExplorerPipeline,
    _build_short_ids,
)
from _project.scripts.explorer_pipeline.transformer import BundleTransformer

from tests.unit.core.explorer_pipeline.conftest import MINIMAL_BUNDLE

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

    def test_empty_data_dir_produces_empty_duckdb(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        # No bundles/ sub-directory at all
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert _duckdb_results(output) == []

    def test_empty_bundles_dir_produces_empty_duckdb(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        (data_dir / "bundles").mkdir(parents=True)
        output = tmp_path / "out"
        ExplorerPipeline().run(data_dir, output)

        assert _duckdb_results(output) == []

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
