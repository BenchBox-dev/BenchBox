"""Shared fixtures for explorer pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Minimal schema-v2 bundle that passes SchemaV2Validator.
# Field names follow the actual JSON keys written by build_result_payload().
# ---------------------------------------------------------------------------

MINIMAL_BUNDLE: dict = {
    "version": "2.1",
    "run": {
        "id": "test-exec-001",
        "timestamp": "2026-03-15T10:00:00.000000",
        "total_duration_ms": 45000,
        "query_time_ms": 12000,
        "iterations": 1,
        "streams": 1,
    },
    "benchmark": {
        "id": "tpch",
        "name": "TPC-H",
        "scale_factor": 0.1,
        "test_type": "power",
    },
    "platform": {
        "name": "duckdb",
        "version": "1.2.0",
    },
    "config": {},
    "summary": {
        "queries": {
            "total": 2,
            "passed": 2,
            "failed": 0,
        },
        "timing": {
            "total_ms": 12000,
            "mean_ms": 6000.0,
        },
        "validation": "passed",
        "tpc_metrics": {
            "power_at_size": 1234.56,
        },
    },
    "phases": {},
    "queries": [
        {
            "id": "Q1",
            "ms": 8000.0,
            "rows": 100,
            "iter": 1,
            "stream": 0,
            "run_type": "measurement",
            "status": "SUCCESS",
        },
        {
            "id": "Q6",
            "ms": 4000.0,
            "rows": 1,
            "iter": 1,
            "stream": 0,
            "run_type": "measurement",
            "status": "SUCCESS",
        },
    ],
    "environment": {
        "os": "macOS 15.3.0",
        "arch": "arm64",
        "cpu_count": 10,
        "memory_gb": 32.0,
        "python": "3.12.0",
    },
    "execution": {
        "driver_actual_version": "1.2.0",
        "driver_resolved_version": "1.2.0",
        "driver_package": "duckdb",
    },
}


@pytest.fixture()
def bundle_file(tmp_path: Path) -> Path:
    """Write a minimal valid schema-v2 bundle to a temp file and return its path."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    bundle_path = bundles_dir / "tpch_duckdb_sf0.1_20260315.json"
    bundle_path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
    return bundle_path


@pytest.fixture()
def data_dir(bundle_file: Path) -> Path:
    """Return the data dir containing the bundles/ sub-directory."""
    return bundle_file.parent.parent
