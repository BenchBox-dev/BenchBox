from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.core.runner.runner import (
    _build_clickhouse_load_failure_result,
    _clickhouse_load_failure_details,
)
from benchbox.core.schemas import BenchmarkConfig
from benchbox.platforms.base.data_loading import ClickHouseServerLoadError

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _failure() -> ClickHouseServerLoadError:
    return ClickHouseServerLoadError(
        "lineitem",
        [Path("/tmp/lineitem.tbl.1"), Path("/tmp/lineitem.tbl.2")],
        65_536,
        RuntimeError("server closed the connection after memory limit"),
    )


def test_clickhouse_load_failure_details_preserve_streaming_and_memory_settings():
    adapter = SimpleNamespace(
        platform_name="clickhouse-server",
        max_memory_usage="16GB",
        max_threads=8,
        max_execution_time=300,
        insert_block_size=65_536,
        send_receive_timeout=900,
    )
    details = _clickhouse_load_failure_details(
        _failure(),
        adapter=adapter,
        platform_config={"max_memory_usage": "24GB", "send_receive_timeout": 1200},
    )

    assert details == {
        "table": "lineitem",
        "source_files": ["/tmp/lineitem.tbl.1", "/tmp/lineitem.tbl.2"],
        "rows_attempted": 65_536,
        "memory_settings": {
            "max_memory_usage": "24GB",
            "max_threads": 8,
            "max_execution_time": 300,
            "insert_block_size": 65_536,
        },
        "driver_timeout_s": 1200,
        "exception": {
            "type": "RuntimeError",
            "message": "server closed the connection after memory limit",
        },
        "result_json": None,
    }


def test_clickhouse_load_failure_result_is_failed_sentinel_without_result_bundle():
    config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)
    result = _build_clickhouse_load_failure_result(
        benchmark=SimpleNamespace(),
        benchmark_config=config,
        database_config=SimpleNamespace(type="clickhouse-server"),
        adapter=SimpleNamespace(platform_name="clickhouse-server", max_memory_usage="8GB"),
        platform_config={},
        exc=_failure(),
        execution_context=None,
    )

    assert result.validation_status == "FAILED"
    assert result.execution_metadata == {"mode": "load_failure"}
    assert result.validation_details["load_failure"]["result_json"] is None
    assert result.validation_details["load_failure"]["rows_attempted"] == 65_536
