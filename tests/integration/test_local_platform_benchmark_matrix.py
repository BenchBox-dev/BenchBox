"""Stress matrix: run real local benchmarks and validate result JSON completeness.

This suite is intentionally heavy and marked ``stress`` so it is opt-in.
It executes real benchmark runs for each local SQL platform x benchmark pair,
then validates:
1) run completed successfully with no failed queries
2) expected benchmark workload was fully executed (query cardinality check)
3) row counts match stored expected results when available
"""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path

import pytest

from benchbox.core.benchmark_registry import get_benchmark_metadata, list_benchmark_ids
from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.expected_results.registry import get_registry
from benchbox.core.results.loader import find_latest_result
from benchbox.core.tpch.benchmark import get_reference_seed
from benchbox.core.validation.query_validation import QueryValidator
from tests.e2e.utils import is_dataframe_available, is_gpu_available, is_platform_available
from tests.integration._cli_e2e_utils import run_cli_command
from tests.uat.matrix import LOCAL_SQL_PLATFORMS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.stress,
]


ALL_BENCHMARKS: tuple[str, ...] = tuple(list_benchmark_ids())
DEFAULT_LOCAL_SQL_BENCHMARKS: tuple[str, ...] = ("tpch", "tpcds")
LOCAL_SQL_STABLE_MATRIX: dict[str, set[str]] = {
    "duckdb": {"tpch", "tpcds"},
    "datafusion": {"tpch"},
    "sqlite": set(),
}
LOCAL_SQL_BENCHMARKS: tuple[str, ...] = (
    ALL_BENCHMARKS
    if os.environ.get("BENCHBOX_FULL_LOCAL_SQL_MATRIX", "").strip().lower() in {"1", "true", "yes", "on"}
    else DEFAULT_LOCAL_SQL_BENCHMARKS
)
LOCAL_DATAFRAME_PLATFORMS: tuple[str, ...] = (
    "pandas-df",
    "polars-df",
    "dask-df",
    "pyspark-df",
    "datafusion-df",
    "modin-df",
    "cudf-df",
)
# Platform/benchmark combos known to fail at runtime (not test bugs).
# dask-df/tpcds: fixed by materializing Dask Series before .isin() calls.
# pyspark-df/tpcds: guarded by is_dataframe_available JVM check (skips without Java).
_DATAFRAME_XFAIL_COMBINATIONS: dict[tuple[str, str], str] = {}
DATAFRAME_BENCHMARKS: tuple[str, ...] = tuple(
    benchmark
    for benchmark in ALL_BENCHMARKS
    if bool((get_benchmark_metadata(benchmark) or {}).get("supports_dataframe"))
)
SERVICE_LOCAL_PLATFORMS: tuple[str, ...] = ("postgresql", "timescaledb", "trino", "presto", "firebolt")

# 20 minutes per matrix case: enough for heavy SF=1 workloads in stress mode.
MATRIX_CASE_TIMEOUT = 1200.0
MAINTENANCE_TIMEOUT = 1500.0
CORRECTNESS_GATE_QUERY_IDS_ENV = "BENCHBOX_CORRECTNESS_GATE_QUERY_IDS"


def _select_scale(benchmark_name: str, platform_name: str | None = None) -> float:
    """Choose the smallest valid scale for smoke-like matrix coverage.

    TPC-H/TPC-DS are pinned to SF=1.0 so stored answer-set validations can run.
    """
    if benchmark_name == "tpch":
        if platform_name in {"sqlite", "datafusion"}:
            return 0.01
        return 1.0
    if benchmark_name == "tpcds":
        return 1.0

    metadata = get_benchmark_metadata(benchmark_name) or {}
    min_scale = metadata.get("min_scale", metadata.get("default_scale", 0.01))
    return float(min_scale)


def _load_result_payload(work_dir: Path, benchmark_name: str) -> tuple[Path, dict]:
    """Load the latest result payload for a benchmark/platform run."""
    results_dir = work_dir / "benchmark_runs" / "results"
    result_path = find_latest_result(results_dir, benchmark=benchmark_name)
    assert result_path is not None, f"No result JSON found in {results_dir} for {benchmark_name}"
    return result_path, json.loads(result_path.read_text(encoding="utf-8"))


def _measurement_queries(payload: dict) -> list[dict]:
    queries = payload.get("queries", [])
    return [q for q in queries if q.get("run_type") == "measurement"]


def _query_subset_from_env() -> tuple[str, ...]:
    """Return a CLI query subset for the bounded correctness gate."""
    raw = os.environ.get(CORRECTNESS_GATE_QUERY_IDS_ENV, "").strip()
    if not raw:
        return ()
    return tuple(query_id.strip() for query_id in raw.split(",") if query_id.strip())


def _service_matrix_enabled() -> bool:
    return os.environ.get("BENCHBOX_SERVICE_LOCAL_MATRIX", "").strip().lower() in {"1", "true", "yes", "on"}


def _maintenance_matrix_enabled() -> bool:
    return os.environ.get("BENCHBOX_ENABLE_MAINTENANCE_MATRIX", "").strip().lower() in {"1", "true", "yes", "on"}


def _local_sql_case_enabled(platform_name: str, benchmark_name: str) -> bool:
    """Return whether a local SQL matrix case should run in default CI mode."""
    if os.environ.get("BENCHBOX_FULL_LOCAL_SQL_MATRIX", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return benchmark_name in LOCAL_SQL_STABLE_MATRIX.get(platform_name, set())


def _tcp_open(host: str, port: int, timeout_seconds: float = 1.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_seconds)
        return sock.connect_ex((host, port)) == 0


def _service_endpoint(platform_name: str) -> tuple[str, int]:
    if platform_name in {"postgresql", "timescaledb"}:
        host = os.environ.get("BENCHBOX_PG_HOST", "127.0.0.1")
        port = int(os.environ.get("BENCHBOX_PG_PORT", "5432"))
        return host, port
    if platform_name in {"trino", "presto"}:
        host = os.environ.get("BENCHBOX_TRINO_HOST", "127.0.0.1")
        port = int(os.environ.get("BENCHBOX_TRINO_PORT", "8080"))
        return host, port
    if platform_name == "firebolt":
        host = os.environ.get("BENCHBOX_FIREBOLT_HOST", "127.0.0.1")
        port = int(os.environ.get("BENCHBOX_FIREBOLT_PORT", "3473"))
        return host, port
    raise ValueError(f"Unsupported service local platform: {platform_name}")


def _service_platform_options(platform_name: str) -> list[str]:
    host, port = _service_endpoint(platform_name)

    if platform_name == "postgresql":
        options = [
            f"host={host}",
            f"port={port}",
            f"username={os.environ.get('BENCHBOX_PG_USER', 'postgres')}",
            f"database={os.environ.get('BENCHBOX_PG_DATABASE', 'benchbox')}",
            f"schema={os.environ.get('BENCHBOX_PG_SCHEMA', 'public')}",
        ]
        password = os.environ.get("BENCHBOX_PG_PASSWORD")
        if password:
            options.append(f"password={password}")
        return options

    if platform_name == "timescaledb":
        options = [
            f"host={host}",
            f"port={port}",
            f"username={os.environ.get('BENCHBOX_PG_USER', 'postgres')}",
            f"database={os.environ.get('BENCHBOX_TS_DATABASE', 'benchbox')}",
            f"schema={os.environ.get('BENCHBOX_PG_SCHEMA', 'public')}",
            "deployment_mode=self-hosted",
        ]
        password = os.environ.get("BENCHBOX_PG_PASSWORD")
        if password:
            options.append(f"password={password}")
        return options

    if platform_name in {"trino", "presto"}:
        return [
            f"host={host}",
            f"port={port}",
            f"username={os.environ.get('BENCHBOX_TRINO_USER', platform_name)}",
            f"catalog={os.environ.get('BENCHBOX_TRINO_CATALOG', 'memory')}",
            f"schema={os.environ.get('BENCHBOX_TRINO_SCHEMA', 'default')}",
        ]

    if platform_name == "firebolt":
        return [
            "deployment_mode=core",
            f"url=http://{host}:{port}",
            f"database={os.environ.get('BENCHBOX_FIREBOLT_DATABASE', 'benchbox')}",
        ]

    raise ValueError(f"Unsupported service local platform: {platform_name}")


def _phases_for_benchmark(benchmark_name: str, platform_name: str | None = None) -> list[str]:
    """Select phases to validate for a benchmark."""
    # DataFrame platforms generate data inline during load; there is no separate generate phase.
    is_dataframe = platform_name is not None and platform_name.endswith("-df")
    phases = ["load", "power"] if is_dataframe else ["generate", "load", "power"]
    metadata = get_benchmark_metadata(benchmark_name) or {}
    include_throughput = bool(metadata.get("supports_streams")) and os.environ.get(
        "BENCHBOX_ENABLE_THROUGHPUT_MATRIX", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if include_throughput and platform_name in {"sqlite", "datafusion"}:
        include_throughput = False
    if include_throughput:
        phases.append("throughput")
    return phases


def _phase_keys_for_name(phase_name: str) -> tuple[str, ...]:
    mapping = {
        "generate": ("data_generation",),
        "load": ("data_loading",),
        "power": ("power_test",),
        "throughput": ("throughput_test",),
        "maintenance": ("maintenance_test", "maintenance"),
    }
    return mapping.get(phase_name, (phase_name,))


def _validate_phase_coverage(payload: dict, requested_phases: list[str]) -> None:
    """Validate requested phases were executed and marked as run."""
    config_phases = payload.get("config", {}).get("phases", [])
    if isinstance(config_phases, list):
        assert config_phases == requested_phases, (
            f"Result config phases mismatch: expected {requested_phases}, got {config_phases}"
        )

    phases_payload = payload.get("phases", {})
    for requested in requested_phases:
        phase_keys = _phase_keys_for_name(requested)
        phase_block = None
        for key in phase_keys:
            phase_block = phases_payload.get(key)
            if phase_block:
                break
        if phase_block is None and requested == "maintenance":
            maintenance_queries = [
                q for q in payload.get("queries", []) if str(q.get("test_type", "")).lower() == "maintenance"
            ]
            assert maintenance_queries, "Missing maintenance phase block and no maintenance query executions found"
            continue
        assert phase_block is not None, f"Missing phase block for '{requested}' in result payload"
        status = str(phase_block.get("status", "")).upper()
        assert status not in {"", "NOT_RUN"}, f"Phase '{requested}' was not executed (status={status})"


def _validate_completion(payload: dict, benchmark_name: str, expected_query_count: int | None = None) -> None:
    """Validate that all expected benchmark work completed."""
    summary = payload.get("summary", {})
    query_summary = summary.get("queries", {})

    total = int(query_summary.get("total", 0))
    passed = int(query_summary.get("passed", 0))
    failed = int(query_summary.get("failed", 0))

    assert total > 0, f"{benchmark_name}: no measurement queries were recorded"
    assert failed == 0, f"{benchmark_name}: query failures detected ({failed}/{total})"
    assert passed == total, f"{benchmark_name}: not all queries passed ({passed}/{total})"

    metadata = get_benchmark_metadata(benchmark_name) or {}
    expected_query_count = expected_query_count or int(metadata.get("num_queries", 0))
    measured = _measurement_queries(payload)

    def _canonical_query_id(raw_id: object) -> str:
        value = str(raw_id).strip()
        if benchmark_name == "tpcds":
            match = re.match(r"^q?(\d+)", value, flags=re.IGNORECASE)
            if match:
                return str(int(match.group(1)))
        return value

    unique_measurement_ids = {
        _canonical_query_id(query.get("id")) for query in measured if query.get("status") == "SUCCESS"
    }

    # Ensure the benchmark's defined workload cardinality actually executed.
    if expected_query_count > 0:
        assert len(unique_measurement_ids) == expected_query_count, (
            f"{benchmark_name}: expected {expected_query_count} unique measurement queries, "
            f"got {len(unique_measurement_ids)}"
        )


def _expected_result_queries(payload: dict, expected_query_ids: set[str] | None) -> list[dict]:
    """Select result rows suitable for stored expected-results validation.

    Stored answer sets exist for stream 0 only (the power run executed with the
    reference qgen seed); streams > 0 use derived seeds and are timed but not
    answer-validated (per the TPC-H spec). So for the bounded gate we validate the
    stream-0 executions, not the throughput measurement rows counted by
    ``_validate_completion`` -- both run the same queries, but only stream 0 is
    answer-backed.
    """
    if not expected_query_ids:
        return _measurement_queries(payload)

    return [
        query
        for query in payload.get("queries", [])
        if str(query.get("id")) in expected_query_ids and int(query.get("stream") or 0) == 0
    ]


def _validate_against_expected_results(
    payload: dict,
    benchmark_name: str,
    scale_factor: float,
    expected_query_ids: set[str] | None = None,
) -> None:
    """Validate query row counts against stored expected results where available."""
    validator = QueryValidator()
    checked = 0
    failures: list[str] = []

    for query in _expected_result_queries(payload, expected_query_ids):
        if query.get("status") != "SUCCESS":
            continue
        if query.get("rows") is None:
            continue

        stream_id = int(query.get("stream") or 0)
        validation = validator.validate_query_result(
            benchmark_type=benchmark_name,
            query_id=str(query["id"]),
            actual_row_count=int(query["rows"]),
            scale_factor=scale_factor,
            stream_id=stream_id,
        )

        if validation.validation_mode == ValidationMode.SKIP:
            continue

        checked += 1
        if not validation.is_valid:
            failures.append(
                f"{benchmark_name} query {validation.query_id}: expected={validation.expected_row_count}, "
                f"actual={validation.actual_row_count}, mode={validation.validation_mode.value}"
            )

    # Optional strict mode: require expected-results checks for the bounded PR gate.
    if (
        benchmark_name == "tpch"
        and scale_factor >= 1.0
        and os.environ.get("BENCHBOX_STRICT_EXPECTED_RESULTS", "").strip().lower() in {"1", "true", "yes", "on"}
    ):
        expected_checked = len(expected_query_ids or ())
        if expected_checked:
            assert checked == expected_checked, (
                f"TPC-H validation evaluated {checked} query row counts, expected {expected_checked}"
            )
        else:
            assert checked > 0, "TPC-H validation did not evaluate any query against stored expected results"

    assert not failures, "Row-count validation failures:\n" + "\n".join(failures)


@pytest.mark.integration
@pytest.mark.stress
@pytest.mark.parametrize("platform_name", LOCAL_SQL_PLATFORMS)
@pytest.mark.parametrize("benchmark_name", LOCAL_SQL_BENCHMARKS)
def test_local_platform_benchmark_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    benchmark_name: str,
) -> None:
    """Run a real benchmark and validate emitted result JSON for full completion."""
    if not is_platform_available(platform_name):
        pytest.skip(f"{platform_name} dependencies not available")
    if not _local_sql_case_enabled(platform_name, benchmark_name):
        pytest.skip(f"{platform_name}/{benchmark_name} is excluded from default stable local SQL matrix")

    # Use loose mode for TPC-DS to avoid seed-specific exact-match instability.
    if benchmark_name == "tpcds":
        monkeypatch.setenv("BENCHBOX_QUERY_VALIDATION_MODE", "loose")
        get_registry().clear_cache()

    scale_factor = _select_scale(benchmark_name, platform_name)
    phases = _phases_for_benchmark(benchmark_name, platform_name)
    query_subset = _query_subset_from_env()
    case_dir = tmp_path / f"{platform_name}_{benchmark_name}"
    case_dir.mkdir(parents=True, exist_ok=True)

    command = [
        "run",
        "--platform",
        platform_name,
        "--benchmark",
        benchmark_name,
        "--scale",
        str(scale_factor),
        "--phases",
        ",".join(phases),
        "--non-interactive",
    ]
    if query_subset:
        command.extend(["--queries", ",".join(query_subset)])
        # The bounded correctness gate validates emitted cardinalities against the
        # stored TPC-H answer files. Those answers correspond to the reference qgen
        # seed, so pin it to make stream-0 expected-results validation deterministic
        # and EXACT. Without it, query parameters drift and only structurally-fixed
        # (single-row) queries would coincidentally match.
        gate_seed = get_reference_seed(scale_factor) if benchmark_name == "tpch" else None
        if gate_seed is not None:
            command.extend(["--seed", str(gate_seed)])

    result = run_cli_command(command, cwd=case_dir, timeout=MATRIX_CASE_TIMEOUT)

    assert result.returncode == 0, (
        f"CLI failed for {platform_name}/{benchmark_name} (sf={scale_factor})\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )

    _, payload = _load_result_payload(case_dir, benchmark_name)
    _validate_phase_coverage(payload, phases)
    _validate_completion(payload, benchmark_name, expected_query_count=len(query_subset) or None)
    _validate_against_expected_results(
        payload,
        benchmark_name,
        scale_factor,
        expected_query_ids=set(query_subset) or None,
    )


@pytest.mark.integration
@pytest.mark.stress
@pytest.mark.parametrize("platform_name", LOCAL_SQL_PLATFORMS)
@pytest.mark.parametrize("benchmark_name", ("tpch", "tpcds"))
def test_local_platform_maintenance_phase_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    benchmark_name: str,
) -> None:
    """Smoke maintenance phase for local SQL platforms on TPC benchmarks."""
    if not _maintenance_matrix_enabled():
        pytest.skip("Set BENCHBOX_ENABLE_MAINTENANCE_MATRIX=1 to enable maintenance stress matrix tests")
    if not is_platform_available(platform_name):
        pytest.skip(f"{platform_name} dependencies not available")
    if not _local_sql_case_enabled(platform_name, benchmark_name):
        pytest.skip(f"{platform_name}/{benchmark_name} is excluded from default stable local SQL matrix")

    if benchmark_name == "tpcds":
        monkeypatch.setenv("BENCHBOX_QUERY_VALIDATION_MODE", "loose")
        get_registry().clear_cache()

    scale_factor = _select_scale(benchmark_name, platform_name)
    phases = ["generate", "load", "maintenance"]
    case_dir = tmp_path / f"{platform_name}_{benchmark_name}_maintenance"
    case_dir.mkdir(parents=True, exist_ok=True)

    result = run_cli_command(
        [
            "run",
            "--platform",
            platform_name,
            "--benchmark",
            benchmark_name,
            "--scale",
            str(scale_factor),
            "--phases",
            ",".join(phases),
            "--non-interactive",
        ],
        cwd=case_dir,
        timeout=MAINTENANCE_TIMEOUT,
    )

    assert result.returncode == 0, (
        f"CLI maintenance failed for {platform_name}/{benchmark_name} (sf={scale_factor})\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )

    _, payload = _load_result_payload(case_dir, benchmark_name)
    _validate_phase_coverage(payload, phases)


@pytest.mark.integration
@pytest.mark.stress
@pytest.mark.parametrize("platform_name", LOCAL_DATAFRAME_PLATFORMS)
@pytest.mark.parametrize("benchmark_name", DATAFRAME_BENCHMARKS)
def test_local_dataframe_platform_benchmark_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    benchmark_name: str,
) -> None:
    """Run real local DataFrame benchmarks and validate completion + phases."""
    if platform_name == "cudf-df" and not is_gpu_available():
        pytest.skip("cudf-df requires NVIDIA GPU with CUDA")
    if not is_dataframe_available(platform_name):
        pytest.skip(f"{platform_name} dependencies not available")
    xfail_reason = _DATAFRAME_XFAIL_COMBINATIONS.get((platform_name, benchmark_name))
    if xfail_reason:
        pytest.xfail(xfail_reason)

    if benchmark_name == "tpcds":
        monkeypatch.setenv("BENCHBOX_QUERY_VALIDATION_MODE", "loose")
        get_registry().clear_cache()

    scale_factor = _select_scale(benchmark_name, platform_name)
    phases = _phases_for_benchmark(benchmark_name, platform_name)
    case_dir = tmp_path / f"{platform_name}_{benchmark_name}"
    case_dir.mkdir(parents=True, exist_ok=True)

    result = run_cli_command(
        [
            "run",
            "--platform",
            platform_name,
            "--benchmark",
            benchmark_name,
            "--scale",
            str(scale_factor),
            "--phases",
            ",".join(phases),
            "--non-interactive",
        ],
        cwd=case_dir,
        timeout=MATRIX_CASE_TIMEOUT,
    )

    assert result.returncode == 0, (
        f"CLI failed for {platform_name}/{benchmark_name} (sf={scale_factor})\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )

    _, payload = _load_result_payload(case_dir, benchmark_name)
    _validate_phase_coverage(payload, phases)
    _validate_completion(payload, benchmark_name)


@pytest.mark.integration
@pytest.mark.stress
@pytest.mark.parametrize("platform_name", SERVICE_LOCAL_PLATFORMS)
def test_service_local_platform_tpch_matrix(
    tmp_path: Path,
    platform_name: str,
) -> None:
    """Run TPCH on local service-backed platforms when services are available."""
    if not _service_matrix_enabled():
        pytest.skip("Set BENCHBOX_SERVICE_LOCAL_MATRIX=1 to enable service-backed local matrix tests")
    if not is_platform_available(platform_name):
        pytest.skip(f"{platform_name} dependencies not available")

    host, port = _service_endpoint(platform_name)
    if not _tcp_open(host, port):
        pytest.skip(f"{platform_name} service not reachable at {host}:{port}")

    benchmark_name = "tpch"
    scale_factor = _select_scale(benchmark_name, platform_name)
    phases = _phases_for_benchmark(benchmark_name, platform_name)
    case_dir = tmp_path / f"{platform_name}_{benchmark_name}_service_local"
    case_dir.mkdir(parents=True, exist_ok=True)

    args = [
        "run",
        "--platform",
        platform_name,
        "--benchmark",
        benchmark_name,
        "--scale",
        str(scale_factor),
        "--phases",
        ",".join(phases),
        "--non-interactive",
    ]
    for option in _service_platform_options(platform_name):
        args.extend(["--platform-option", option])

    result = run_cli_command(args, cwd=case_dir, timeout=MATRIX_CASE_TIMEOUT)

    assert result.returncode == 0, (
        f"CLI failed for {platform_name}/{benchmark_name} service-local run\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )

    _, payload = _load_result_payload(case_dir, benchmark_name)
    _validate_phase_coverage(payload, phases)
    _validate_completion(payload, benchmark_name)
    _validate_against_expected_results(payload, benchmark_name, scale_factor)
