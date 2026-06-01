"""Drift guard: UAT connection facts must agree with docker-compose `ports:`.

tests.uat.docker_assets is the single connection registry; matrix consumes it.
This pins the derivation so a compose port remap (or a stale hardcoded copy
sneaking back) fails loudly in CI rather than manifesting as a phantom-skipped
platform that masquerades as a down host.
"""

from __future__ import annotations

import re

import pytest

from tests.uat import docker_assets, matrix

pytestmark = pytest.mark.fast

_HOST_CONTAINER_RE = re.compile(r'^\s*-\s*"?(?P<host>.+):(?P<container>\d+)"?\s*$')


def _compose_published_ports(platform: str) -> dict[int, str]:
    """Map container_port -> raw host token from a platform's compose file(s)."""
    spec = docker_assets.docker_platform_spec(platform)
    mapping: dict[int, str] = {}
    for compose_file in spec.compose_files:
        for line in compose_file.read_text(encoding="utf-8").splitlines():
            m = _HOST_CONTAINER_RE.match(line)
            if not m:
                continue
            container = int(m.group("container"))
            mapping.setdefault(container, m.group("host").strip().strip('"'))
    return mapping


def test_connection_registry_drift_matches_compose():
    """Every docker platform's resolved reachability port comes from compose."""
    unresolved = []
    for platform in docker_assets.docker_platform_specs():
        service_port = docker_assets.PLATFORM_SERVICE_PORT.get(platform)
        assert service_port is not None, f"{platform}: missing service-port role"

        published = _compose_published_ports(platform)
        assert service_port in published, (
            f"{platform}: compose publishes no host mapping for service port {service_port}; "
            f"available: {sorted(published)}"
        )

        endpoint = docker_assets.host_reachability_endpoint(platform)
        if endpoint is None:
            unresolved.append(platform)
            continue
        # Endpoint host port must equal what compose publishes for the service port.
        resolved_port = int(endpoint.rsplit(":", 1)[-1])
        expected = docker_assets._resolve_host_token(published[service_port], env={})
        assert resolved_port == expected, f"{platform}: {resolved_port} != compose {expected}"

    # must_preserve: no platform that has a compose probe loses reachability.
    assert unresolved == [], f"platforms lost their reachability probe: {unresolved}"


def test_connection_registry_drift_no_local_port_table_in_matrix():
    """matrix.py must not redeclare a parallel connection registry."""
    text = (matrix.__file__ and open(matrix.__file__, encoding="utf-8").read()) or ""
    for banned in ("PLATFORM_PORTS", "PLATFORM_EXTRA_OPTS", "LOCAL_MANAGED_PLATFORM_EXTRA_OPTS"):
        assert banned not in text, f"matrix.py still references {banned}"


def test_uat_singlestore_host_port_override_flows_through(monkeypatch: pytest.MonkeyPatch):
    """Setting SINGLESTORE_HOST_PORT moves the host probe + adapter port=, not the service port."""
    # Default (env unset, regardless of the ambient shell): host 13306, service
    # /container port 3306 (unchanged).
    monkeypatch.delenv("SINGLESTORE_HOST_PORT", raising=False)
    assert docker_assets.host_reachability_endpoint("singlestore") == "localhost:13306"
    assert docker_assets.PLATFORM_SERVICE_PORT["singlestore"] == 3306

    monkeypatch.setenv("SINGLESTORE_HOST_PORT", "13307")
    assert docker_assets.host_reachability_endpoint("singlestore") == "localhost:13307"
    # The adapter `port=` option follows the host port, not the container port.
    assert "port=13307" in docker_assets.platform_extra_opts("singlestore")
    # Service/container port role is untouched by the host override.
    assert docker_assets.PLATFORM_SERVICE_PORT["singlestore"] == 3306

    # The live reachability probe re-resolves the overridden host port.
    matrix.invalidate_reachability_cache_after_lifecycle_change()
    captured: dict[str, int] = {}

    def fake_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
        captured["port"] = port
        return True

    monkeypatch.setattr(matrix, "tcp_probe", fake_probe)
    assert matrix.platform_is_reachable("singlestore") is True
    assert captured["port"] == 13307


@pytest.mark.parametrize("platform", ["lakesail", "velox"])
def test_uat_spark_connect_host_port_override_flows_through(
    platform: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """SPARK_CONNECT_PORT moves both the host probe and adapter endpoint."""
    monkeypatch.delenv("SPARK_CONNECT_PORT", raising=False)
    assert docker_assets.host_reachability_endpoint(platform) == "localhost:50051"
    assert "endpoint=sc://localhost:50051" in docker_assets.platform_extra_opts(platform)

    monkeypatch.setenv("SPARK_CONNECT_PORT", "50052")
    assert docker_assets.host_reachability_endpoint(platform) == "localhost:50052"
    assert "endpoint=sc://localhost:50052" in docker_assets.platform_extra_opts(platform)

    matrix.invalidate_reachability_cache_after_lifecycle_change()
    captured: dict[str, int] = {}

    def fake_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
        captured["port"] = port
        return True

    monkeypatch.setattr(matrix, "tcp_probe", fake_probe)
    assert matrix.platform_is_reachable(platform) is True
    assert captured["port"] == 50052
