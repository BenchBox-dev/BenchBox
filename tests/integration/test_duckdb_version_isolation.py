from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from benchbox.utils.runtime_env import discover_isolated_runtime

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


def _run_isolated_process(version: str) -> dict:
    runtime = discover_isolated_runtime(package_name="duckdb", requested_version=version)
    if runtime is None:
        pytest.skip(f"No isolated runtime found for duckdb=={version}")

    repo_root = Path(__file__).resolve().parents[2]
    code = textwrap.dedent(
        f"""
        import json
        from datetime import datetime

        from benchbox.core.results.models import BenchmarkResults
        from benchbox.core.results.schema import build_result_payload
        from benchbox.platforms.duckdb import DuckDBAdapter

        adapter = DuckDBAdapter(
            database_path=":memory:",
            driver_package="duckdb",
            driver_version_requested="{version}",
            driver_version_resolved="{runtime.version}",
            driver_runtime_strategy="{runtime.strategy}",
            driver_runtime_path={runtime.runtime_path!r},
            driver_runtime_python_executable={runtime.python_executable!r},
        )
        conn = adapter.create_connection()
        try:
            conn.execute("SELECT 1").fetchone()
            platform_info = adapter.get_platform_info(conn)
            result = BenchmarkResults(
                benchmark_name="DuckDB Isolation Test",
                _benchmark_id_override="duckdb_isolation_test",
                platform="duckdb",
                scale_factor=0.01,
                execution_id="duckdb-isolation-{version}",
                timestamp=datetime(2026, 2, 20, 12, 0, 0),
                duration_seconds=0.01,
                total_queries=1,
                successful_queries=1,
                failed_queries=0,
                query_results=[
                    {{
                        "query_id": "Q1",
                        "execution_time_ms": 1,
                        "rows_returned": 1,
                        "status": "SUCCESS",
                    }}
                ],
                platform_info=platform_info,
                execution_metadata={{
                    "mode": "sql",
                    "driver_package": adapter.driver_package,
                    "driver_version_requested": adapter.driver_version_requested,
                    "driver_version_resolved": adapter.driver_version_resolved,
                    "driver_version_actual": adapter.driver_version_actual,
                    "driver_runtime_strategy": adapter.driver_runtime_strategy,
                    "driver_runtime_path": adapter.driver_runtime_path,
                    "driver_runtime_python_executable": adapter.driver_runtime_python_executable,
                }},
                driver_package=adapter.driver_package,
                driver_version_requested=adapter.driver_version_requested,
                driver_version_resolved=adapter.driver_version_resolved,
                driver_version_actual=adapter.driver_version_actual,
                driver_runtime_strategy=adapter.driver_runtime_strategy,
                driver_runtime_path=adapter.driver_runtime_path,
                driver_runtime_python_executable=adapter.driver_runtime_python_executable,
            )
            payload = build_result_payload(result)
            print("JSON_PAYLOAD::" + json.dumps(payload, sort_keys=True))
        finally:
            adapter.close_connection(conn)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    payload_lines = [line for line in completed.stdout.splitlines() if line.startswith("JSON_PAYLOAD::")]
    if not payload_lines:
        raise AssertionError(
            f"Expected JSON payload line, got stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return json.loads(payload_lines[-1].split("::", 1)[1])


@pytest.mark.integration
def test_duckdb_requested_versions_produce_distinct_actual_runtime_versions():
    payload_092 = _run_isolated_process("0.9.2")
    payload_122 = _run_isolated_process("1.2.2")

    assert payload_092["platform"]["version"] == "0.9.2"
    assert payload_122["platform"]["version"] == "1.2.2"
    assert payload_092["platform"]["version"] != payload_122["platform"]["version"]

    assert payload_092["execution"]["driver_version_requested"] == "0.9.2"
    assert payload_122["execution"]["driver_version_requested"] == "1.2.2"
    assert payload_092["execution"]["driver_version_actual"] == "0.9.2"
    assert payload_122["execution"]["driver_version_actual"] == "1.2.2"
    assert payload_092["execution"]["driver_version_actual"] != payload_122["execution"]["driver_version_actual"]
