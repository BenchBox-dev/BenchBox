"""Side-effect-free platform readiness diagnostics for the CLI."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from importlib import util

DEFAULT_LAKESAIL_ENDPOINT = "sc://localhost:50051"


@dataclass(frozen=True)
class LocalTcpEndpoint:
    """Local service endpoint that must already be provisioned."""

    platform: str
    display_name: str
    host: str
    port: int
    remediation: str

    @property
    def address(self) -> str:
        """Return host:port for display."""
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class PlatformReadinessResult:
    """A single platform readiness check result.

    Status is intentionally string-valued so CLI and tests can assert the public
    contract without importing an enum.
    """

    platform: str
    check: str
    status: str
    summary: str
    detail: str = ""
    remediation: str = ""
    endpoint: str | None = None

    @property
    def ready(self) -> bool:
        """Whether this readiness check passed."""
        return self.status == "ready"


_DATAFRAME_ALIASES: dict[str, str] = {
    "polars-df": "polars",
    "pandas-df": "pandas",
    "pyspark-df": "pyspark",
    "datafusion-df": "datafusion",
    "dask-df": "dask",
    "modin-df": "modin",
    "cudf-df": "cudf",
    "lakesail-df": "lakesail",
}

_LOCAL_TCP_ENDPOINTS: dict[str, LocalTcpEndpoint] = {
    "clickhouse-server": LocalTcpEndpoint(
        "clickhouse-server",
        "ClickHouse Server",
        "localhost",
        9000,
        "Start the local ClickHouse server before running clickhouse-server benchmarks.",
    ),
    "cedardb": LocalTcpEndpoint(
        "cedardb",
        "CedarDB",
        "localhost",
        5435,
        "Start the local CedarDB service before running cedardb benchmarks.",
    ),
    "starrocks": LocalTcpEndpoint(
        "starrocks",
        "StarRocks",
        "localhost",
        19030,
        "Start the local StarRocks FE service before running starrocks benchmarks.",
    ),
    "postgresql": LocalTcpEndpoint(
        "postgresql",
        "PostgreSQL",
        "localhost",
        5432,
        "Start the local PostgreSQL service before running postgresql benchmarks.",
    ),
    "presto": LocalTcpEndpoint(
        "presto",
        "PrestoDB",
        "localhost",
        18081,
        "Start the local Presto coordinator before running presto benchmarks.",
    ),
    "trino": LocalTcpEndpoint(
        "trino",
        "Trino",
        "localhost",
        18080,
        "Start the local Trino coordinator before running trino benchmarks.",
    ),
    "databend": LocalTcpEndpoint(
        "databend",
        "Databend",
        "localhost",
        8000,
        "Start the local Databend service before running databend benchmarks.",
    ),
    "doris": LocalTcpEndpoint(
        "doris",
        "Doris",
        "localhost",
        19031,
        "Start the local Doris FE service before running doris benchmarks.",
    ),
    "influxdb": LocalTcpEndpoint(
        "influxdb",
        "InfluxDB",
        "localhost",
        8181,
        "Start the local InfluxDB service before running influxdb benchmarks.",
    ),
    "pg-duckdb": LocalTcpEndpoint(
        "pg-duckdb",
        "pg_duckdb",
        "localhost",
        5432,
        "Start the local PostgreSQL-compatible pg_duckdb service before running pg-duckdb benchmarks.",
    ),
    "pg-mooncake": LocalTcpEndpoint(
        "pg-mooncake",
        "pg_mooncake",
        "localhost",
        5432,
        "Start the local PostgreSQL-compatible pg_mooncake service before running pg-mooncake benchmarks.",
    ),
    "timescaledb": LocalTcpEndpoint(
        "timescaledb",
        "TimescaleDB",
        "localhost",
        5432,
        "Start the local TimescaleDB service before running timescaledb benchmarks.",
    ),
    "questdb": LocalTcpEndpoint(
        "questdb",
        "QuestDB",
        "localhost",
        8812,
        "Start the local QuestDB PostgreSQL-wire service before running questdb benchmarks.",
    ),
    "singlestore": LocalTcpEndpoint(
        "singlestore",
        "SingleStore",
        "localhost",
        13306,
        "Start the local SingleStore service before running singlestore benchmarks.",
    ),
    "velox": LocalTcpEndpoint(
        "velox",
        "Velox Spark Connect",
        "localhost",
        50051,
        "Start the local Velox Spark Connect service before running remote velox benchmarks.",
    ),
}


def normalize_readiness_platform(platform: str) -> str:
    """Normalize CLI platform aliases used only by readiness checks."""
    normalized = platform.lower()
    return _DATAFRAME_ALIASES.get(normalized, normalized)


def check_platform_readiness(
    platform: str,
    *,
    timeout_seconds: float = 1.0,
) -> tuple[PlatformReadinessResult, ...]:
    """Return side-effect-free readiness checks for a platform.

    These diagnostics intentionally avoid adapter construction. They may inspect
    import specs, environment variables, saved endpoint config, and local TCP
    reachability only.
    """
    canonical_platform = normalize_readiness_platform(platform)

    if canonical_platform in _LOCAL_TCP_ENDPOINTS:
        return (_check_local_tcp_endpoint(_LOCAL_TCP_ENDPOINTS[canonical_platform], timeout_seconds),)
    if canonical_platform == "lakesail":
        return _check_lakesail(platform, timeout_seconds)
    if canonical_platform == "modin":
        return _check_modin(platform)
    return ()


def has_readiness_failures(results: tuple[PlatformReadinessResult, ...]) -> bool:
    """Return True when any readiness result reports an environment gap."""
    return any(not result.ready for result in results)


def _check_local_tcp_endpoint(endpoint: LocalTcpEndpoint, timeout_seconds: float) -> PlatformReadinessResult:
    if _tcp_reachable(endpoint.host, endpoint.port, timeout_seconds):
        return PlatformReadinessResult(
            platform=endpoint.platform,
            check="local_tcp_endpoint",
            status="ready",
            summary=f"{endpoint.display_name} endpoint is reachable at {endpoint.address}.",
            endpoint=endpoint.address,
        )

    return PlatformReadinessResult(
        platform=endpoint.platform,
        check="local_tcp_endpoint",
        status="environment_skip",
        summary=f"{endpoint.display_name} endpoint is not reachable at {endpoint.address}.",
        detail="Benchmarks for this platform should be skipped until the local service is provisioned.",
        remediation=endpoint.remediation,
        endpoint=endpoint.address,
    )


def _check_lakesail(platform: str, timeout_seconds: float) -> tuple[PlatformReadinessResult, ...]:
    endpoint = _configured_lakesail_endpoint()
    results: list[PlatformReadinessResult] = []

    if _module_available("pyspark"):
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="pyspark_client",
                status="ready",
                summary="PySpark Spark Connect client is importable.",
            )
        )
    else:
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="pyspark_client",
                status="environment_skip",
                summary="PySpark Spark Connect client is not importable.",
                remediation="Install the LakeSail client dependency with: uv add pyspark",
            )
        )

    host, port = _parse_spark_connect_endpoint(endpoint)
    if _tcp_reachable(host, port, timeout_seconds):
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="spark_connect_endpoint",
                status="ready",
                summary=f"LakeSail Spark Connect endpoint is reachable at {endpoint}.",
                endpoint=endpoint,
            )
        )
        return tuple(results)

    pysail_available = _module_available("pysail")
    auto_start_detail = (
        "The SQL adapter can auto-start a local pysail server at run time, but this readiness check does not "
        "start it. LakeSail DataFrame mode still needs an already-running endpoint."
        if pysail_available
        else "The SQL adapter also needs pysail for local auto-start; DataFrame mode needs an already-running endpoint."
    )
    results.append(
        PlatformReadinessResult(
            platform=platform,
            check="spark_connect_endpoint",
            status="environment_skip",
            summary=f"LakeSail Spark Connect endpoint is not reachable at {endpoint}.",
            detail=auto_start_detail,
            remediation=(
                "Start a Sail Spark Connect server, save LakeSail credentials with endpoint=sc://host:port, "
                "or install pysail with uv add pysail for SQL-mode local auto-start."
            ),
            endpoint=endpoint,
        )
    )
    return tuple(results)


def _check_modin(platform: str) -> tuple[PlatformReadinessResult, ...]:
    if not _module_available("modin"):
        return (
            PlatformReadinessResult(
                platform=platform,
                check="modin_package",
                status="environment_skip",
                summary="Modin is not importable.",
                remediation="Install Modin with: uv add benchbox --extra modin",
            ),
        )

    backend = os.environ.get("MODIN_ENGINE", "ray").strip().lower() or "ray"
    backend_module = {"ray": "ray", "dask": "dask", "unidist": "unidist"}.get(backend)
    results = [
        PlatformReadinessResult(
            platform=platform,
            check="modin_package",
            status="ready",
            summary="Modin package is importable without initializing a backend.",
        )
    ]

    if backend_module is None:
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="modin_backend",
                status="environment_skip",
                summary=f"MODIN_ENGINE={backend!r} is not a supported BenchBox Modin backend.",
                remediation="Set MODIN_ENGINE to ray, dask, or unidist before running modin-df benchmarks.",
            )
        )
        return tuple(results)

    if _module_available(backend_module):
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="modin_backend",
                status="ready",
                summary=f"Modin backend dependency {backend_module!r} is importable for MODIN_ENGINE={backend}.",
            )
        )
    else:
        results.append(
            PlatformReadinessResult(
                platform=platform,
                check="modin_backend",
                status="environment_skip",
                summary=f"Modin backend dependency {backend_module!r} is not importable for MODIN_ENGINE={backend}.",
                detail="The readiness check does not import modin.pandas or initialize Ray/Dask.",
                remediation=f"Install the selected backend with: uv add {_modin_backend_install_spec(backend)}",
            )
        )
    return tuple(results)


def _configured_lakesail_endpoint() -> str:
    try:
        from benchbox.security.credentials import CredentialManager

        credentials = CredentialManager().get_platform_credentials("lakesail") or {}
    except Exception:
        credentials = {}

    credential_endpoint = credentials.get("endpoint")
    if credential_endpoint:
        return str(credential_endpoint)

    return DEFAULT_LAKESAIL_ENDPOINT


def _modin_backend_install_spec(backend: str) -> str:
    return {
        "ray": '"modin[ray]"',
        "dask": '"modin[dask]"',
        "unidist": '"modin[unidist]"',
    }.get(backend, backend)


def _module_available(module_name: str) -> bool:
    try:
        return util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _parse_spark_connect_endpoint(endpoint: str) -> tuple[str, int]:
    address = endpoint[5:] if endpoint.startswith("sc://") else endpoint
    host, _, port_text = address.partition(":")
    try:
        port = int(port_text) if port_text else 50051
    except ValueError:
        port = 50051
    return host or "localhost", port


def _tcp_reachable(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False
