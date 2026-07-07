"""Tests for scripts/generate_corpus_inventory.py."""

from __future__ import annotations

import json
from pathlib import Path

import generate_corpus_inventory as script
import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _minimal_bundle(*, benchmark_id: str = "tpch", scale_factor: float = 0.01, platform: str = "DuckDB") -> dict:
    return {
        "version": "2.1",
        "run": {
            "id": f"{benchmark_id}-{platform.lower()}",
            "timestamp": "2026-04-12T12:00:00+00:00",
            "total_duration_ms": 1200,
        },
        "benchmark": {
            "id": benchmark_id,
            "name": benchmark_id.upper(),
            "scale_factor": scale_factor,
        },
        "platform": {
            "name": platform,
            "version": "1.0.0",
        },
        "summary": {
            "queries": {"total": 2, "passed": 2, "failed": 0},
        },
        "queries": [
            {"id": "Q1", "ms": 100, "status": "pass"},
            {"id": "Q2", "ms": 200, "status": "pass"},
        ],
    }


def _write_bundle(
    path: Path,
    *,
    benchmark_id: str = "tpch",
    scale_factor: float = 0.01,
    platform: str = "DuckDB",
    provenance: dict | None = None,
) -> None:
    bundle = _minimal_bundle(benchmark_id=benchmark_id, scale_factor=scale_factor, platform=platform)
    if provenance is not None:
        bundle["provenance"] = provenance
    path.write_text(json.dumps(bundle), encoding="utf-8")


class TestGenerateInventory:
    def test_empty_dir_has_consistent_shape(self, tmp_path: Path) -> None:
        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"] == []
        assert inventory["cohorts"] == {}
        assert inventory["summary"] == {
            "total_bundles": 0,
            "by_benchmark": {},
            "by_platform": {},
            "by_trust_label": {},
            "by_funding": {},
        }

    def test_sidecar_sets_community_trust_label(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "tpch" / "duckdb" / "sf0.01"
        bundle_dir.mkdir(parents=True)
        _write_bundle(bundle_dir / "result.json")
        (bundle_dir / "submission-manifest.json").write_text("{}", encoding="utf-8")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["trust_label"] == "community-submission"

    def test_per_bundle_sidecar_sets_community_trust_label(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "tpch" / "duckdb" / "sf0.01"
        bundle_dir.mkdir(parents=True)
        _write_bundle(bundle_dir / "result.json")
        (bundle_dir / "result.manifest.json").write_text("{}", encoding="utf-8")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["trust_label"] == "community-submission"

    def test_top_level_vendor_subtree_sets_vendor_label(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "vendor"
        bundle_dir.mkdir(parents=True)
        _write_bundle(bundle_dir / "result.json")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["trust_label"] == "vendor-supplied"

    def test_nested_vendor_dir_does_not_grant_vendor_label(self, tmp_path: Path) -> None:
        # Anchored: only the top-level vendor/ subtree counts. A nested directory
        # named 'vendor' must NOT self-grant the ranking-eligible vendor label.
        bundle_dir = tmp_path / "community" / "vendor"
        bundle_dir.mkdir(parents=True)
        _write_bundle(bundle_dir / "result.json")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["trust_label"] == "maintainer-run"

    def test_funding_from_bundle_provenance(self, tmp_path: Path) -> None:
        _write_bundle(tmp_path / "result.json", provenance={"funding": "free-trial"})

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["funding"] == "free-trial"

    def test_funding_defaults_to_unspecified(self, tmp_path: Path) -> None:
        _write_bundle(tmp_path / "result.json")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["bundles"][0]["funding"] == "unspecified"
        assert "by_funding" in inventory["summary"]

    def test_excludes_companions_and_sorts_deterministically(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "bundles"
        bundle_dir.mkdir()
        _write_bundle(bundle_dir / "b.json", benchmark_id="tpch", platform="DuckDB")
        _write_bundle(bundle_dir / "a.json", benchmark_id="tpch", platform="DataFusion")
        (bundle_dir / "a.plans.json").write_text("{}", encoding="utf-8")
        (bundle_dir / "a.manifest.json").write_text("{}", encoding="utf-8")
        (bundle_dir / "submission-manifest.json").write_text("{}", encoding="utf-8")

        inventory = script.generate_inventory(bundle_dir)

        assert [entry["file"] for entry in inventory["bundles"]] == ["a.json", "b.json"]
        assert inventory["summary"]["total_bundles"] == 2

    def test_cohort_summary_groups_platforms(self, tmp_path: Path) -> None:
        _write_bundle(tmp_path / "duckdb.json", benchmark_id="tpch", scale_factor=0.1, platform="DuckDB")
        _write_bundle(tmp_path / "datafusion.json", benchmark_id="tpch", scale_factor=0.1, platform="DataFusion")
        _write_bundle(tmp_path / "polars.json", benchmark_id="tpch", scale_factor=0.1, platform="Polars")

        inventory = script.generate_inventory(tmp_path)

        assert inventory["cohorts"] == {
            "tpch@sf0.1": ["DataFusion", "DuckDB", "Polars"],
        }

    def test_internal_benchmark_bundles_are_hidden(self, tmp_path: Path) -> None:
        _write_bundle(tmp_path / "joinorder.json", benchmark_id="joinorder", scale_factor=1.0, platform="DuckDB")
        _write_bundle(
            tmp_path / "joinorder_synthetic.json",
            benchmark_id="joinorder_synthetic",
            scale_factor=1.0,
            platform="DuckDB",
        )

        inventory = script.generate_inventory(tmp_path)

        assert [entry["benchmark"] for entry in inventory["bundles"]] == ["joinorder"]
        assert inventory["summary"]["by_benchmark"] == {"joinorder": 1}

    def test_extract_metadata_raises_clear_error_for_malformed_json(self, tmp_path: Path) -> None:
        bad_bundle = tmp_path / "broken.json"
        bad_bundle.write_text("{", encoding="utf-8")

        with pytest.raises(ValueError, match="Malformed bundle JSON"):
            script.extract_metadata(bad_bundle, tmp_path)


class TestMain:
    def test_check_mode_succeeds_when_inventory_matches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bundles_dir = tmp_path / "bundles"
        bundles_dir.mkdir()
        _write_bundle(bundles_dir / "result.json")
        inventory_path = tmp_path / "corpus-inventory.json"

        monkeypatch.setattr(script, "BUNDLES_DIR", bundles_dir)
        monkeypatch.setattr(script, "INVENTORY_PATH", inventory_path)

        assert script.main(["--write"]) == 0
        assert script.main(["--check"]) == 0

    def test_check_mode_detects_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bundles_dir = tmp_path / "bundles"
        bundles_dir.mkdir()
        _write_bundle(bundles_dir / "result.json")
        inventory_path = tmp_path / "corpus-inventory.json"
        inventory_path.write_text(json.dumps({"bundles": []}), encoding="utf-8")

        monkeypatch.setattr(script, "BUNDLES_DIR", bundles_dir)
        monkeypatch.setattr(script, "INVENTORY_PATH", inventory_path)

        assert script.main(["--check"]) == 1
        assert "out of date" in capsys.readouterr().err
