"""Regression checks for Results Explorer audit screenshot manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
HIERARCHY_MANIFEST = (
    REPO_ROOT
    / "_project"
    / "audits"
    / "screenshots"
    / "results-explorer-hierarchy-usability-data-audit-20260507"
    / "screenshot-manifest.json"
)

DUCKDB_AWS_COMPARE_FILES = {
    "compare-duckdb-aws-390.png",
    "compare-duckdb-aws-768.png",
    "compare-duckdb-aws-1280.png",
    "compare-duckdb-aws-1600.png",
}


def test_pr246_hierarchy_manifest_marks_duckdb_aws_compare_as_comparable() -> None:
    entries = json.loads(HIERARCHY_MANIFEST.read_text(encoding="utf-8"))
    compare_entries = [entry for entry in entries if entry["file"] in DUCKDB_AWS_COMPARE_FILES]

    assert {entry["file"] for entry in compare_entries} == DUCKDB_AWS_COMPARE_FILES
    for entry in compare_entries:
        assert entry["requestedUrl"] == (
            "/results/compare?ids=tpch-duckdb-sf0.01-20260403-b6d2e142,tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce"
        )
        assert entry["h1"] == "TPC-H Comparison"
        assert entry["visibleFlags"] == {
            "rawError": False,
            "binderError": False,
            "cannotCompare": False,
        }
