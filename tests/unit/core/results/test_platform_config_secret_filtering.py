"""platform.config extraction, the raw_config fallbacks, and the results.db
metadata sink must filter secrets structurally.

Adapters keep secrets out of platform_info by convention; these boundaries
previously trusted that convention with no enforcement.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json

import pytest

from benchbox.core.results.environment import build_platform_metadata_payload
from benchbox.core.results.platform_options import REDACTED_VALUE
from benchbox.core.results.schema import _extract_platform_config

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestExtractPlatformConfigFiltering:
    def test_password_sentinel_is_filtered(self):
        out = _extract_platform_config({"configuration": {"password": "PW-SENTINEL"}})
        assert "PW-SENTINEL" not in json.dumps(out)
        assert out["password"] == REDACTED_VALUE

    def test_nested_secret_is_filtered(self):
        out = _extract_platform_config({"configuration": {"s3": {"secret_key": "SK-SENTINEL"}}})
        assert "SK-SENTINEL" not in json.dumps(out)

    def test_non_secret_config_keeps_real_values(self):
        out = _extract_platform_config({"configuration": {"memory_limit": "8GB", "threads": 4}})
        assert out["memory_limit"] == "8GB"
        assert out["threads"] == 4


class TestResultsDbMetadataFiltering:
    def test_explicit_raw_config_is_filtered_at_metadata_boundary(self):
        payload = build_platform_metadata_payload(
            platform_info=None,
            platform_config=None,
            deployment=None,
            cloud=None,
            compute=None,
            storage=None,
            raw_config={"password": "RAW-PASSWORD-SENTINEL", "threads": 4},
            raw_metadata=None,
        )

        assert payload["raw_config"]["password"] == REDACTED_VALUE
        assert payload["raw_config"]["threads"] == 4

    def test_platform_info_secret_never_reaches_metadata_json(self, tmp_path):
        from datetime import datetime

        from benchbox.core.results.database import ResultDatabase
        from benchbox.core.results.models import BenchmarkResults

        result = BenchmarkResults(
            benchmark_name="tpch",
            platform="duckdb",
            scale_factor=0.01,
            execution_id="exec-filter-test",
            timestamp=datetime.now(),
            duration_seconds=1.0,
            total_queries=1,
            successful_queries=1,
            failed_queries=0,
            platform_info={"name": "duckdb", "api_key": "DBKEY-SENTINEL"},
        )
        db = ResultDatabase(db_path=tmp_path / "results.db")
        db.store_result(result)
        raw = (tmp_path / "results.db").read_bytes()
        assert b"DBKEY-SENTINEL" not in raw
