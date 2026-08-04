"""Pins the public result-ID derivation contract.

Decision (2026-08-03): a public result ID hashes the bytes that are actually
published, not the raw source bundle. A public content address the public
cannot fetch is not verifiable, and hashing raw bytes also publishes a
confirmable fingerprint of private content.

`pipeline.py` gets this right today, but only by statement order - the ID is
derived after `_public_bundle_data`. Reordering those two lines would silently
revert the contract and no existing test would fail, so pin it here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _project.scripts.explorer_pipeline.transformer import BundleTransformer
from benchbox.core.results.anonymization import AnonymizationManager
from benchbox.core.results.canonical_json import canonical_json_bytes

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _bundle() -> dict:
    return {
        "version": "2.0",
        "benchmark": {"id": "tpch", "scale_factor": 0.01, "test_type": "power", "name": "TPC-H"},
        "platform": {"name": "DuckDB", "version": "1.2.3"},
        "run": {"id": "run-1", "timestamp": "2026-05-01T12:00:00Z", "total_duration_ms": 42},
        "summary": {"validation": "passed", "queries": 1},
        "queries": [{"id": "q1", "ms": 42, "status": "SUCCESS", "run_type": "measurement"}],
        "metadata": {"working_dir": "/Users/someone/benchbox"},
    }


def test_result_id_hashes_published_bytes_not_raw_bytes(tmp_path: Path) -> None:
    """The ID must be reproducible from the published artifact alone."""
    transformer = BundleTransformer()
    raw_data = _bundle()
    path = tmp_path / "bundle.json"
    raw_bytes = json.dumps(raw_data).encode()
    path.write_bytes(raw_bytes)

    public_data = AnonymizationManager().anonymize_result_payload(raw_data)
    public_bytes = canonical_json_bytes(public_data)
    assert public_bytes != raw_bytes, "fixture must actually be changed by anonymization"

    published_id = transformer.result_id_from_bundle(path, data=public_data, raw=public_bytes)
    raw_id = transformer.result_id_from_bundle(path, data=raw_data, raw=raw_bytes)

    assert published_id != raw_id
    # Anyone holding only the published bundle can recompute the ID.
    recomputed = transformer.result_id_from_bundle(path, data=public_data, raw=public_bytes)
    assert recomputed == published_id


def test_pipeline_derives_the_id_after_anonymizing() -> None:
    """Guard the statement order the contract depends on.

    `result_id` must be computed from `public_raw`. If it is ever derived from
    `bundle_raw` again the published ID stops matching the published bytes.
    """
    source = (
        Path(__file__).resolve().parents[4] / "_project" / "scripts" / "explorer_pipeline" / "pipeline.py"
    ).read_text(encoding="utf-8")

    public_raw_assign = source.index("public_raw = canonical_json_bytes(public_bundle)")
    id_assign = source.index("result_id = self._transformer.result_id_from_bundle(")
    assert public_raw_assign < id_assign, "result_id is derived before the public bytes exist"

    derivation = source[id_assign : id_assign + 220]
    assert "raw=public_raw" in derivation, "result_id is no longer derived from the published bytes"
    assert "raw=bundle_raw" not in derivation, "result_id reverted to hashing raw source bytes"
