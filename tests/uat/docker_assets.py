"""Docker compose lifecycle helpers for UAT-managed platform stacks.

The UAT harness may start and stop Docker-backed platforms at execute-phase
platform boundaries. This module owns the platform → compose-file mapping and
keeps command construction small, deterministic, and safe to unit test without
a live Docker daemon.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCKER_PLATFORM_SWITCH_MODES: tuple[str, ...] = ("off", "containers", "volumes", "images")
DOCKER_FIXED_CONTAINER_NAME_POLICIES: tuple[str, ...] = ("fail", "override", "allow")

# `_PROJECT_NAME_MAX_LEN` is compose's own project-name ceiling, but it is not
# the identifier that actually gets constrained at runtime: compose derives
# the CONTAINER name as `<project>-<service>-<replica>`, and mocker rejects
# anything over `_CONTAINER_NAME_MAX_LEN` (uat-compose-project-name-overflows-
# container-id-limit-20260805). Plain Docker's own limit is looser (~255), but
# the bound below is intentionally the tighter mocker one applied everywhere.
#
# NOT "safe for Docker too" in the sense of unchanged: this tightens the
# budget, so it RENAMES roughly half of the checked-in (config, platform)
# project names (shorter, never longer -- never re-introduces an overflow).
# A pre-upgrade sweep's containers are registered under the OLD, longer name;
# `compose_project_name()` is deterministic on *current* code, so the next
# sweep's exact `-p <new-name>` teardown will not match and tear down those
# leftovers -- they keep holding host ports until removed separately. They
# remain recoverable: `docker_cleanup.py`'s recovery inventory matches by the
# `benchbox-uat` *prefix*, which this rename preserves (only the tail after
# the prefix is truncated differently). This overflow is mocker-only, so
# every affected operator is on macOS/mocker, where the default
# `ENGINE=docker` cleanup pass alone is NOT sufficient: it degrades to
# named-volumes-only inventory and reports no orphaned containers, leaving
# them holding host ports for the next sweep to collide on. Recovery needs
# BOTH `ENGINE=container APPLY=1` (containers/networks/images) and the
# default `ENGINE=docker APPLY=1` pass (mocker-managed named volumes, which
# `ENGINE=container` cannot see). See "Compose project naming and the
# container-id limit" in docs/operations/uat-framework.md for the operator
# recovery step.
_CONTAINER_NAME_MAX_LEN = 64
# Reserve room for a two-digit compose replica index ("-10".."-99"), not just
# "-1": a scaled service silently overflows by one character the moment it
# reaches its 10th replica if the budget only ever assumes a single digit.
_REPLICA_SUFFIX_MAX_LEN = len("-99")
_PROJECT_NAME_MAX_LEN = 63

# Env override honored by resolve_container_cli() -- verbatim, no rewriting.
# Mirrors the convention _project/scripts/build_joinorder_data.py:879-883
# already uses for the joinorder Docker build path; this is the UAT-side
# resolver for the same contract (uat-container-engine-routing prior_art).
CONTAINER_CLI_ENV_VAR = "BENCHBOX_CONTAINER_CLI"


class DockerAssetError(ValueError):
    """Raised when a UAT Docker lifecycle request is unsafe or unsupported."""


def _which_container_cli(cli: str) -> str | None:
    """Thin ``shutil.which`` wrapper so tests can stub PATH lookups without touching the real ``shutil`` module."""
    return shutil.which(cli)


def _current_platform() -> str:
    """Thin ``sys.platform`` wrapper so tests can stub the OS without mutating the real ``sys`` module."""
    return sys.platform


@functools.lru_cache(maxsize=1)
def resolve_container_cli() -> str:
    """Resolve the Docker-CLI-compatible binary UAT lifecycle commands should invoke.

    Resolution order (uat-container-engine-routing, user decision
    2026-07-11): ``BENCHBOX_CONTAINER_CLI`` env override, honored verbatim >
    platform default: on macOS, ``mocker`` if it is on PATH, else ``docker``;
    on every other platform, always ``docker`` (no mocker probing happens off
    darwin -- this keeps a docker-only Linux host byte-identical to before
    this resolver existed).

    Resolved once per process and memoized (the engine does not change mid
    sweep); call ``resolve_container_cli.cache_clear()`` to force
    re-resolution -- tests use this, production code never does.

    Raises DockerAssetError when the resolved binary is not on PATH -- a
    missing engine is a hard stop, not a silent fallback.
    """
    override = os.environ.get(CONTAINER_CLI_ENV_VAR)
    if override:
        candidate, source = override, f"{CONTAINER_CLI_ENV_VAR} override"
    elif _current_platform() == "darwin" and _which_container_cli("mocker") is not None:
        candidate, source = "mocker", "darwin mocker-if-present default"
    else:
        candidate, source = "docker", "platform default"
    if _which_container_cli(candidate) is None:
        raise DockerAssetError(
            f"Resolved container CLI {candidate!r} ({source}) is not available on PATH; "
            f"install it or set {CONTAINER_CLI_ENV_VAR} to a Docker-CLI-compatible binary that is."
        )
    return candidate


def container_engine_identity() -> tuple[str, str]:
    """Return ``(binary, version_line)`` for the resolved container CLI.

    ``version_line`` is the first line of ``<binary> --version`` output, or a
    diagnostic placeholder if that command itself fails -- a failed version
    probe still records engine identity, just without a version string.
    Raises DockerAssetError (propagated from resolve_container_cli) when no
    engine binary is available at all.
    """
    binary = resolve_container_cli()
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = (completed.stdout or completed.stderr or "").strip()
        version = text.splitlines()[0] if text else f"{binary} --version produced no output"
    except (OSError, subprocess.SubprocessError) as exc:
        version = f"{binary} --version failed: {exc}"
    return binary, version


@dataclass(frozen=True)
class DockerPlatformSpec:
    """UAT-owned compose metadata for one Docker-backed platform."""

    platform: str
    compose_files: tuple[Path, ...]
    services: tuple[str, ...] = ()
    fixed_container_names: tuple[str, ...] = ()
    managed_start_allowed: bool = True
    tcp_probe_label: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class DockerCommandResult:
    """Captured result from a Docker command invocation."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    dry_run: bool = False
    error: str | None = None

    @property
    def command(self) -> str:
        """Shell-quoted command string for logs."""
        return shlex.join(self.argv)

    @property
    def succeeded(self) -> bool:
        """Return True when the command completed successfully."""
        return self.returncode == 0 and not self.timed_out and self.error is None


DockerRunner = Callable[..., DockerCommandResult]


def _repo_path(relative: str) -> Path:
    return REPO_ROOT / relative


# Firebolt has a compose file but is intentionally not listed here: it is not
# currently in matrix.PLATFORM_GROUPS["docker"] for UAT sweeps.
_DOCKER_PLATFORM_SPECS: dict[str, DockerPlatformSpec] = {
    "clickhouse-server": DockerPlatformSpec(
        platform="clickhouse-server",
        compose_files=(_repo_path("docker/clickhouse/docker-compose.yml"),),
        services=("clickhouse",),
    ),
    "cedardb": DockerPlatformSpec(
        platform="cedardb",
        compose_files=(_repo_path("docker/cedardb/docker-compose.yml"),),
        services=("cedardb",),
    ),
    "starrocks": DockerPlatformSpec(
        platform="starrocks",
        compose_files=(_repo_path("docker/starrocks/docker-compose.yml"),),
        services=("starrocks",),
    ),
    "postgresql": DockerPlatformSpec(
        platform="postgresql",
        compose_files=(_repo_path("docker/postgresql/docker-compose.yml"),),
        services=("postgresql",),
    ),
    "presto": DockerPlatformSpec(
        platform="presto",
        compose_files=(_repo_path("docker/presto/docker-compose.yml"),),
        services=("presto",),
    ),
    "trino": DockerPlatformSpec(
        platform="trino",
        compose_files=(_repo_path("docker/trino/docker-compose.yml"),),
        services=("trino",),
    ),
    "databend": DockerPlatformSpec(
        platform="databend",
        compose_files=(_repo_path("docker/databend/docker-compose.yml"),),
        # All three declared services start together (no host-run subset like
        # lakesail/velox below); "minio-setup" is the longest at 11 chars.
        services=("minio", "minio-setup", "databend"),
    ),
    "doris": DockerPlatformSpec(
        platform="doris",
        compose_files=(_repo_path("docker/doris/docker-compose.yml"),),
        services=("doris",),
    ),
    "influxdb": DockerPlatformSpec(
        platform="influxdb",
        compose_files=(_repo_path("docker/influxdb/docker-compose.yml"),),
        services=("influxdb",),
    ),
    "lakesail": DockerPlatformSpec(
        platform="lakesail",
        compose_files=(_repo_path("docker/lakesail/docker-compose.yml"),),
        services=("lakesail-connect",),
        notes="Start only lakesail-connect for host-run UAT; BENCHBOX_DATA_DIR is set to the sweep output root.",
    ),
    "pg-duckdb": DockerPlatformSpec(
        platform="pg-duckdb",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.pg-duckdb.yaml"),),
        services=("pg-duckdb",),
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "pg-mooncake": DockerPlatformSpec(
        platform="pg-mooncake",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.pg-mooncake.yaml"),),
        services=("pg-mooncake",),
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "timescaledb": DockerPlatformSpec(
        platform="timescaledb",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.timescaledb.yaml"),),
        services=("timescaledb",),
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "questdb": DockerPlatformSpec(
        platform="questdb",
        compose_files=(_repo_path("docker/questdb/docker-compose.yml"),),
        services=("questdb",),
    ),
    "singlestore": DockerPlatformSpec(
        platform="singlestore",
        compose_files=(_repo_path("docker/singlestore/docker-compose.yml"),),
        services=("singlestore",),
    ),
    "velox": DockerPlatformSpec(
        platform="velox",
        compose_files=(_repo_path("docker/velox/docker-compose.yml"),),
        services=("velox-connect",),
        notes="Start only velox-connect for host-run UAT; BENCHBOX_DATA_DIR is set to the sweep output root.",
    ),
}


# ---------------------------------------------------------------------------
# Single source of truth for platform connection facts.
#
# Host reachability ports are DERIVED from each platform's docker-compose
# `ports:` mapping (honoring `${VAR:-default}` overrides), keyed by the
# in-container service port the adapter connects to. This is the one fact a
# "lightweight user-exercising" layer needs and the one most certain to rot;
# deriving it means an override like SINGLESTORE_HOST_PORT flows through to both
# the reachability probe and the adapter `port=` option without editing code.
#
# Endpoint roles are modeled explicitly: PLATFORM_SERVICE_PORT is the
# container/service port (NOT the host port). Do not collapse the two.
#
# Secondary host ports and managed credentials derive from the registered
# Compose files below. The small role/key maps identify which Compose fact an
# adapter option consumes; they do not duplicate the values themselves.
# ---------------------------------------------------------------------------

# Platform -> in-container service port the adapter connects to. The host
# reachability port is whatever the compose `ports:` mapping publishes for this
# container port.
PLATFORM_SERVICE_PORT: dict[str, int] = {
    "clickhouse-server": 9000,
    "cedardb": 5432,
    "starrocks": 9030,
    "postgresql": 5432,
    "presto": 8080,
    "trino": 8080,
    "databend": 8000,
    "doris": 9030,
    "influxdb": 8181,
    "lakesail": 50051,
    "pg-duckdb": 5432,
    "pg-mooncake": 5432,
    "timescaledb": 5432,
    "questdb": 8812,
    "singlestore": 3306,
    "velox": 50051,
}

_PLATFORM_STATIC_OPTS: dict[str, list[str]] = {
    "velox": ["--platform-option", "deployment=remote"],
}

# Platform -> adapter option -> in-container port. The host-side value is
# resolved from Compose, including ${VAR:-default} overrides.
_PLATFORM_SECONDARY_PORTS: dict[str, dict[str, int]] = {
    "questdb": {"http_port": 9000},
    "starrocks": {"http_port": 8040},
    "doris": {"http_port": 8030, "be_http_port": 8040},
}

# Platform -> Compose environment key whose value is the adapter password.
_PLATFORM_PASSWORD_ENV_KEYS: dict[str, str] = {
    "clickhouse-server": "CLICKHOUSE_PASSWORD",
    "pg-duckdb": "POSTGRES_PASSWORD",
    "pg-mooncake": "POSTGRES_PASSWORD",
    "timescaledb": "POSTGRES_PASSWORD",
    "postgresql": "POSTGRES_PASSWORD",
    "singlestore": "ROOT_PASSWORD",
}

# Platforms that pass the resolved host reachability port to the adapter as the
# `port=` platform-option (kept first to preserve existing argv order).
_PLATFORM_INJECT_HOST_PORT_OPT: frozenset[str] = frozenset({"clickhouse-server", "singlestore", "starrocks", "doris"})

# Spark Connect platforms also need the adapter endpoint to follow the
# compose-published host port. Otherwise an override such as SPARK_CONNECT_PORT
# moves the reachability probe while the run still connects to :50051.
_PLATFORM_INJECT_SPARK_CONNECT_ENDPOINT_OPT: frozenset[str] = frozenset({"lakesail", "velox"})

# Local managed-Docker credentials, appended only when UAT manages the stack
# (kept separate because PLATFORM options apply even for externally managed
# local platforms).
#
# postgresql's compose stack (docker/postgresql/docker-compose.yml) sets
# POSTGRES_USER=benchbox, which makes `benchbox` the ONLY superuser role the
# official postgres image creates (POSTGRES_USER replaces the default
# `postgres` role rather than adding alongside it) -- the adapter's own
# `username` default ("postgres") does not exist in this container and
# authentication fails outright. `username=benchbox` must be injected here
# alongside `password=benchbox` for any docker-managed postgresql cell (e.g.
# the throughput UAT cell) to connect at all.
_PLATFORM_LOCAL_MANAGED_STATIC_OPTS: dict[str, list[str]] = {
    "postgresql": ["--platform-option", "username=benchbox"],
}

# A compose `ports:` entry: "[ip:]host:container", host may be ${VAR:-default}.
_COMPOSE_PORT_MAPPING_RE = re.compile(r'^\s*-\s*"?(?P<mapping>[^"\s]+)"?\s*$')
_ENV_DEFAULT_RE = re.compile(r"^\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*):-(?P<default>\d+)\}$")
_ENV_BARE_RE = re.compile(r"^\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)\}$")
_HOST_CONTAINER_RE = re.compile(r"^(?P<host>.+):(?P<container>\d+)$")


def _resolve_host_token(token: str, env: dict[str, str]) -> int | None:
    """Resolve a compose published-port token to a concrete host port."""
    token = token.strip().strip('"')
    m = _ENV_DEFAULT_RE.match(token)
    if m:
        raw = env.get(m.group("var"), m.group("default"))
        return int(raw) if str(raw).isdigit() else int(m.group("default"))
    m = _ENV_BARE_RE.match(token)
    if m:
        raw = env.get(m.group("var"))
        return int(raw) if raw and raw.isdigit() else None
    if token.isdigit():
        return int(token)
    # ip:port form -> take the trailing published port.
    if ":" in token and token.rsplit(":", 1)[-1].isdigit():
        return int(token.rsplit(":", 1)[-1])
    return None


def _iter_compose_port_mappings(compose_file: Path) -> Iterable[tuple[str, int]]:
    """Yield (host_token, container_port) for every `- "host:container"` entry."""
    try:
        text = compose_file.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        entry = _COMPOSE_PORT_MAPPING_RE.match(line)
        if not entry:
            continue
        hc = _HOST_CONTAINER_RE.match(entry.group("mapping"))
        if not hc:
            continue
        yield hc.group("host"), int(hc.group("container"))


def resolve_published_host_port(platform: str, *, env: dict[str, str] | None = None) -> int | None:
    """Return the host port that compose publishes for `platform`'s service port.

    Matches the compose `ports:` entry whose *container* side equals
    PLATFORM_SERVICE_PORT[platform], disambiguating sidecar ports (e.g. databend
    MinIO, questdb REST) from the reachability endpoint.
    """
    service_port = PLATFORM_SERVICE_PORT.get(platform)
    return resolve_published_host_port_for_container(platform, service_port, env=env)


def resolve_published_host_port_for_container(
    platform: str,
    container_port: int | None,
    *,
    env: dict[str, str] | None = None,
) -> int | None:
    """Resolve one Compose container port to its published host port."""
    env = os.environ if env is None else env
    spec = _DOCKER_PLATFORM_SPECS.get(platform)
    if container_port is None or spec is None:
        return None
    for compose_file in spec.compose_files:
        for host_token, mapped_container_port in _iter_compose_port_mappings(compose_file):
            if mapped_container_port == container_port:
                resolved = _resolve_host_token(host_token, env)
                if resolved is not None:
                    return resolved
    return None


@functools.cache
def _compose_document(compose_file: Path) -> dict:
    payload = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _compose_service_environment_value(
    platform: str,
    key: str,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Resolve a registered service's Compose environment value."""
    process_env = os.environ if env is None else env
    spec = _DOCKER_PLATFORM_SPECS.get(platform)
    if spec is None:
        return None
    for compose_file in spec.compose_files:
        services = _compose_document(compose_file).get("services", {})
        if not isinstance(services, dict):
            continue
        for service_name in spec.services:
            service = services.get(service_name, {})
            if not isinstance(service, dict):
                continue
            raw_environment = service.get("environment", {})
            if isinstance(raw_environment, list):
                entries = dict(
                    entry.split("=", 1) for entry in raw_environment if isinstance(entry, str) and "=" in entry
                )
            elif isinstance(raw_environment, dict):
                entries = raw_environment
            else:
                continue
            raw = entries.get(key)
            if raw is None:
                continue
            text = str(raw)
            default_match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-(.*)\}", text)
            if default_match:
                return process_env.get(default_match.group(1), default_match.group(2))
            bare_match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
            if bare_match:
                return process_env.get(bare_match.group(1))
            return text
    return None


def host_reachability_endpoint(platform: str, *, env: dict[str, str] | None = None) -> str | None:
    """Return ``"localhost:<host_port>"`` for `platform`, or None if not derivable."""
    host_port = resolve_published_host_port(platform, env=env)
    return None if host_port is None else f"localhost:{host_port}"


def platform_extra_opts(platform: str, *, env: dict[str, str] | None = None) -> list[str]:
    """Return the `--platform-option` argv for `platform`.

    The reachability `port=` (for platforms that take one) is derived from the
    compose-published host port; remaining options are static literals.
    """
    opts: list[str] = []
    if platform in _PLATFORM_INJECT_HOST_PORT_OPT:
        host_port = resolve_published_host_port(platform, env=env)
        if host_port is not None:
            opts += ["--platform-option", f"port={host_port}"]
    for option, container_port in _PLATFORM_SECONDARY_PORTS.get(platform, {}).items():
        host_port = resolve_published_host_port_for_container(platform, container_port, env=env)
        if host_port is not None:
            opts += ["--platform-option", f"{option}={host_port}"]
    if platform == "singlestore":
        password = _compose_service_environment_value(platform, _PLATFORM_PASSWORD_ENV_KEYS[platform], env=env)
        if password is not None:
            opts += ["--platform-option", f"password={password}"]
    opts += list(_PLATFORM_STATIC_OPTS.get(platform, []))
    if platform in _PLATFORM_INJECT_SPARK_CONNECT_ENDPOINT_OPT:
        host_port = resolve_published_host_port(platform, env=env)
        if host_port is not None:
            opts += ["--platform-option", f"endpoint=sc://localhost:{host_port}"]
    return opts


def local_managed_platform_extra_opts(platform: str, *, env: dict[str, str] | None = None) -> list[str]:
    """Return managed-Docker-only `--platform-option` argv (credentials)."""
    opts = list(_PLATFORM_LOCAL_MANAGED_STATIC_OPTS.get(platform, []))
    password_key = _PLATFORM_PASSWORD_ENV_KEYS.get(platform)
    if password_key is not None:
        password = _compose_service_environment_value(platform, password_key, env=env)
        if password is not None:
            opts += ["--platform-option", f"password={password}"]
    return opts


# Fill each spec's display probe label from the compose-derived endpoint (default
# env). The live reachability probe re-resolves at call time so env overrides
# (e.g. SINGLESTORE_HOST_PORT) still take effect after import.
_DOCKER_PLATFORM_SPECS = {
    platform: replace(spec, tcp_probe_label=host_reachability_endpoint(platform))
    for platform, spec in _DOCKER_PLATFORM_SPECS.items()
}


def docker_platform_specs() -> dict[str, DockerPlatformSpec]:
    """Return a copy of the UAT Docker platform mapping."""
    return dict(_DOCKER_PLATFORM_SPECS)


def is_docker_platform(platform: str) -> bool:
    """Return True iff `platform` has a UAT Docker compose mapping."""
    return platform in _DOCKER_PLATFORM_SPECS


def docker_platform_spec(platform: str) -> DockerPlatformSpec:
    """Return the compose spec for `platform` or raise DockerAssetError."""
    try:
        return _DOCKER_PLATFORM_SPECS[platform]
    except KeyError as exc:
        raise DockerAssetError(f"No UAT Docker compose spec is registered for platform {platform!r}") from exc


def _max_declared_service_len(platform: str) -> int:
    """Return the longest compose service name UAT can start for `platform`, or 0 if unknown.

    Reads `spec.services`, populated once at module load for every registered
    platform -- never the compose YAML itself, which would make this callable
    from compose_project_name()'s hot teardown path without a per-call parse.
    Unregistered platforms (e.g. a synthetic name in a unit test) return 0,
    which leaves the project-name budget at its unconstrained `_PROJECT_NAME_MAX_LEN`
    ceiling -- compose_project_name() is only ever invoked for real container
    lifecycle work through a registered `is_docker_platform()` platform.
    """
    spec = _DOCKER_PLATFORM_SPECS.get(platform)
    if spec is None or not spec.services:
        return 0
    return max(len(service) for service in spec.services)


def _project_name_budget(platform: str, max_service_len: int | None = None) -> int:
    """Return the max project-name length that still leaves room for the container id.

    The constrained identifier is the derived CONTAINER id --
    ``<project>-<service>-<replica>`` -- not the project name alone, so the
    budget is derived from `_CONTAINER_NAME_MAX_LEN` minus the longest service
    name this platform starts and a multi-digit replica suffix, capped at
    compose's own `_PROJECT_NAME_MAX_LEN` ceiling (never looser than before).
    """
    service_len = _max_declared_service_len(platform) if max_service_len is None else max_service_len
    if service_len <= 0:
        return _PROJECT_NAME_MAX_LEN
    # -1 for the hyphen joining <project> and <service>; the replica suffix
    # budget already accounts for its own leading hyphen.
    derived = _CONTAINER_NAME_MAX_LEN - service_len - _REPLICA_SUFFIX_MAX_LEN - 1
    return min(_PROJECT_NAME_MAX_LEN, derived)


def compose_project_name(
    config_name: str,
    platform: str,
    prefix: str = "benchbox-uat",
    *,
    max_service_len: int | None = None,
) -> str:
    """Return a deterministic Docker compose project name for one UAT platform block.

    The length budget is derived from the *container* id limit
    (`_CONTAINER_NAME_MAX_LEN`), not just compose's project-name ceiling: a
    project name that itself fits under 63 chars can still produce a
    container id (`<project>-<service>-<replica>`) that overflows mocker's
    64-char limit once the service name and replica suffix are appended.
    `max_service_len` lets a caller override the auto-derived value (e.g. for
    a service not yet in the registry); by default it is looked up from the
    platform's registered `DockerPlatformSpec.services`.
    """
    raw = f"{prefix}-{config_name}-{platform}".lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", raw)
    name = re.sub(r"[-_]{2,}", "-", name).strip("-_")
    if not name or not name[0].isalnum():
        name = f"uat-{name}".strip("-_")
    budget = _project_name_budget(platform, max_service_len)
    if len(name) > budget:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        keep = max(budget - len(digest) - 1, 1)
        name = f"{name[:keep].rstrip('-_')}-{digest}"
    return name


def validate_project_name_budget(spec: DockerPlatformSpec, project_name: str) -> None:
    """Raise DockerAssetError if `project_name` would overflow `spec.platform`'s container-id budget.

    `compose_project_name()` always returns a name within budget, but an
    operator-supplied project name (e.g. `--project-name` on
    `scripts/uat-bring-up/uat_bring_up.py`) never goes through it, so it can
    carry an arbitrary length. `_compose_base_command` calls this on every
    UAT-managed compose verb (up/pull/build/down/ps) so the budget is enforced
    at one chokepoint regardless of caller; a caller that accepts an operator-
    supplied project name up front can also call this directly for a clear,
    actionable error before any Docker command runs, instead of an oversized-
    container-id failure well into `compose up`/`pull`/`build`
    (uat-compose-project-name-budget-review-20260806 finding 4).
    """
    budget = _project_name_budget(spec.platform)
    if len(project_name) > budget:
        raise DockerAssetError(
            f"Docker compose project name {project_name!r} is {len(project_name)} chars, "
            f"which exceeds the {budget}-char budget for platform {spec.platform!r} "
            "(derived from the 64-char container-id limit minus the longest started "
            "service name and replica-suffix headroom; see compose_project_name())."
        )


def _compose_base_command(spec: DockerPlatformSpec, project_name: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_name):
        raise DockerAssetError(f"Unsafe Docker compose project name {project_name!r}")
    validate_project_name_budget(spec, project_name)
    argv = [resolve_container_cli(), "compose", "-p", project_name]
    for compose_file in spec.compose_files:
        argv.extend(["-f", str(compose_file)])
    return argv


def compose_up_command(
    spec: DockerPlatformSpec,
    project_name: str,
    *,
    start_timeout_s: int = 300,
) -> list[str]:
    """Build `docker compose up` argv for a UAT-owned platform project."""
    argv = _compose_base_command(spec, project_name)
    argv.extend(["up", "-d", "--wait", "--wait-timeout", str(start_timeout_s)])
    argv.extend(spec.services)
    return argv


def compose_ps_command(spec: DockerPlatformSpec, project_name: str) -> list[str]:
    """Build `docker compose ps -a` argv for a UAT-owned platform project.

    `-a`/`--all` is load-bearing, not defensive. Plain `compose ps` lists
    only RUNNING containers, so the one state this readiness check exists to
    detect -- a service that started and then died -- is simply absent from
    the output, and the check passes on an empty table. Live-observed
    2026-08-04: mocker reported CedarDB Started, and `mocker compose ps -a`
    showed it Exited.

    Deliberately NOT `--format json`: mocker's `--format json` output is
    non-Docker-compatible for several inventory verbs (see
    `list_mocker_volumes_matching`'s docstring and docker_cleanup.py's
    `--format json` note), so the readiness check parses the STATUS column of
    the default table output instead (`compose_ps_unhealthy_services`).
    """
    argv = _compose_base_command(spec, project_name)
    argv.extend(["ps", "-a"])
    return argv


# Every `compose ps` STATUS that is not "this service is up and serving".
#
#   Exited      -- compose v2, the 2026-08-04 CedarDB state
#   Exit 1      -- compose v1 spelling of the same thing
#   Restarting  -- crash-looping; may be briefly listening, never stably
#   Created     -- container exists but was never started
#   Dead        -- engine could not remove/stop it cleanly
#   Paused      -- SIGSTOPped; the port accepts nothing
#   (unhealthy) -- "Up 30 seconds (unhealthy)": the engine's OWN healthcheck
#                  says no. `(healthy)` and a bare `Up` do not match, since
#                  the pattern requires the literal "un".
#
# Previously only Exited/Restarting were treated as not-ready, so the other
# five states all passed the check.
_UNHEALTHY_PS_STATE_RE = re.compile(r"\b(?:Exited|Restarting|Created|Dead|Paused)\b|\bExit\s+\d+|\(unhealthy\)")

# Table headers: docker compose v2 emits "NAME  IMAGE  ...", compose v1
# emits "Name  Command  ..." followed by a dashed separator row.
_PS_HEADER_RE = re.compile(r"^\s*(?:NAME|Name)\b")
_PS_SEPARATOR_RE = re.compile(r"^[\s\-+]+$")


def compose_ps_service_rows(ps_stdout: str) -> tuple[str, ...]:
    """Return the per-service rows of a `compose ps` table, header/separator stripped."""
    rows: list[str] = []
    for line in ps_stdout.splitlines():
        if not line.strip():
            continue
        if _PS_HEADER_RE.match(line) or _PS_SEPARATOR_RE.match(line):
            continue
        rows.append(line)
    return tuple(rows)


def compose_ps_unhealthy_services(ps_stdout: str) -> tuple[str, ...]:
    """Return the name column of every `compose ps -a` row whose STATUS is not up-and-serving.

    The state vocabulary is `_UNHEALTHY_PS_STATE_RE` above. Matching is done
    against the row with its FIRST column removed, so a container whose NAME
    happens to contain a state word (`benchbox-uat-Created-1`) cannot
    false-positive; only the status/command columns are considered.

    Best-effort text parsing, not a strict table parser: an unexpected
    `compose ps` layout that mentions none of these states reports no
    unhealthy services rather than raising. Note that "no unhealthy rows" is
    NOT by itself sufficient for readiness -- see
    `compose_ps_service_rows`, and the empty-table branch in
    `execute.py::_check_docker_platform_readiness`, which treats a project
    with no rows at all as not ready.
    """
    unhealthy: list[str] = []
    for line in compose_ps_service_rows(ps_stdout):
        columns = line.split(None, 1)
        remainder = columns[1] if len(columns) > 1 else ""
        if _UNHEALTHY_PS_STATE_RE.search(remainder):
            unhealthy.append(columns[0])
    return tuple(unhealthy)


def compose_declared_memory_limits(spec: DockerPlatformSpec) -> dict[str, str]:
    """Return {service: declared-memory-limit} for services with an explicit compose memory cap.

    Reads `mem_limit` or `deploy.resources.limits.memory` straight from the
    compose YAML -- static configuration, not a live container inspect (mocker
    and docker do not expose a portable "runtime cgroup limit" query). Most
    UAT compose files declare no limit at all (e.g.
    docker/cedardb/docker-compose.yml): the 2026-08-04 postmortem's "Running
    under cgroup memory limit: 1024 MB" for CedarDB was the CONTAINER ENGINE's
    own default sizing, not anything this repo's compose files requested --
    logged as "no declared memory limit (engine default)" by callers in that
    case (see execute.py's per-platform-boundary memory gate logging, w3).
    """
    limits: dict[str, str] = {}
    for compose_file in spec.compose_files:
        try:
            data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            continue
        for name, service in services.items():
            if not isinstance(service, dict):
                continue
            mem_limit = service.get("mem_limit")
            if mem_limit:
                limits[str(name)] = str(mem_limit)
                continue
            deploy = service.get("deploy")
            resources = deploy.get("resources") if isinstance(deploy, dict) else None
            # Every level is isinstance-guarded rather than relying on
            # `.get(key, {})` defaults: a default only applies when the key
            # is ABSENT, so a compose file that writes `limits:` with no
            # children yields an explicit None and `.get("memory")` on it
            # raises AttributeError. That would escape this function's
            # `except (OSError, yaml.YAMLError)` AND the caller's
            # `except DockerAssetError` (execute.py's
            # `_describe_platform_vm_request`) and abort the whole sweep
            # from a logging helper. Same reasoning for a scalar or list
            # under `limits:`.
            limits_block = resources.get("limits") if isinstance(resources, dict) else None
            declared = limits_block.get("memory") if isinstance(limits_block, dict) else None
            if declared:
                limits[str(name)] = str(declared)
    return limits


def compose_pull_command(spec: DockerPlatformSpec, project_name: str) -> list[str]:
    """Build `docker compose pull --ignore-buildable` argv for a UAT-owned
    platform project (uat-operator-provisioning w4).

    `--ignore-buildable` skips services that declare only `build:` (no
    `image:` to pull) instead of erroring on them -- pair with
    ``compose_build_command`` to cover those.
    """
    argv = _compose_base_command(spec, project_name)
    argv.extend(["pull", "--ignore-buildable"])
    argv.extend(spec.services)
    return argv


def compose_build_command(spec: DockerPlatformSpec, project_name: str) -> list[str]:
    """Build `docker compose build` argv for a UAT-owned platform project.

    Covers services with a `build:` directive (e.g. LakeSail's PySail
    image) that `compose_pull_command` deliberately skips.
    """
    argv = _compose_base_command(spec, project_name)
    argv.append("build")
    argv.extend(spec.services)
    return argv


def compose_down_command(spec: DockerPlatformSpec, project_name: str, cleanup_mode: str) -> list[str]:
    """Build targeted `docker compose down` argv for a UAT-owned project."""
    if cleanup_mode == "off":
        raise DockerAssetError("cleanup_mode='off' does not have a Docker teardown command")
    if cleanup_mode not in {"containers", "volumes", "images"}:
        raise DockerAssetError(f"Unknown Docker cleanup mode {cleanup_mode!r}; valid: containers, volumes, images")

    argv = _compose_base_command(spec, project_name)
    argv.append("down")
    if cleanup_mode in {"volumes", "images"}:
        argv.append("-v")
    argv.append("--remove-orphans")
    if cleanup_mode == "images":
        argv.extend(["--rmi", "local"])
    return argv


def validate_managed_start_allowed(spec: DockerPlatformSpec, fixed_container_name_policy: str = "fail") -> None:
    """Reject unsafe or unsupported UAT-managed Docker startup requests."""
    if fixed_container_name_policy not in DOCKER_FIXED_CONTAINER_NAME_POLICIES:
        raise DockerAssetError(
            f"Unknown fixed-container-name policy {fixed_container_name_policy!r}; "
            f"valid: {', '.join(DOCKER_FIXED_CONTAINER_NAME_POLICIES)}"
        )
    if not spec.managed_start_allowed:
        reason = spec.notes or "the compose file is not eligible for UAT-managed startup"
        raise DockerAssetError(f"Platform {spec.platform!r} cannot be UAT-managed: {reason}")
    if spec.fixed_container_names:
        names = ", ".join(spec.fixed_container_names)
        if fixed_container_name_policy == "fail":
            raise DockerAssetError(
                f"Platform {spec.platform!r} compose file declares fixed container_name value(s): {names}; "
                "remove/override them before enabling UAT-managed startup"
            )
        if fixed_container_name_policy == "override":
            raise DockerAssetError(
                f"Platform {spec.platform!r} requested fixed-container-name override, but no override is registered"
            )


def compose_environment(
    spec: DockerPlatformSpec,
    *,
    benchmark_runs_dir: Path | str | None = None,
) -> dict[str, str]:
    """Return environment overrides needed by a compose spec.

    Raises DockerAssetError when ``benchmark_runs_dir`` is missing or not
    absolute for a path-mirroring platform (lakesail, velox): their compose
    files bind-mount BENCHBOX_DATA_DIR at the SAME absolute path inside the
    container as on the host (the server resolves client-sent file paths
    server-side), so a relative value -- or a caller that never resolved a
    value at all -- silently breaks every file load instead of failing
    loudly (lakesail-compose-nested-variable-default). A `None`
    benchmark_runs_dir must NOT fall through to returning `{}` for these two
    platforms: `run_docker_command` fills an omitted/empty ``env`` with
    `os.environ.copy()`, so a `{}` return here would let the child process
    silently inherit whatever ambient BENCHBOX_DATA_DIR happens to be set
    (or unset) in the caller's shell instead of the resolved run directory.

    This is the single choke point every UAT-managed bring-up path funnels
    through -- tests/uat/phases/execute.py's up AND down calls, and
    scripts/uat-bring-up/uat_bring_up.py -- unlike the Makefile's
    require_data_dir_if_mounted, which only guards direct
    `make test-docker-up-<platform>` invocations that never call this
    function. Keep both: the Makefile check is defence-in-depth for the
    shell entry point, this one is the enforcement point every Python entry
    point actually reaches. Teardown callers that must not fail just because
    BENCHBOX_DATA_DIR is unset or relative (``down`` never mounts anything)
    should catch DockerAssetError and substitute a throwaway absolute value
    rather than skip this validation.
    """
    if spec.platform not in {"lakesail", "velox"}:
        return {}
    if benchmark_runs_dir is None:
        raise DockerAssetError(
            f"benchmark_runs_dir is required for platform {spec.platform!r} -- its compose "
            "file mounts BENCHBOX_DATA_DIR at the SAME absolute path inside the container as "
            "on the host, so omitting it would let the child process silently inherit "
            "whatever ambient BENCHBOX_DATA_DIR (if any) is set in the caller's environment "
            "instead of the resolved run directory. Pass an absolute benchmark_runs_dir / "
            "--benchmark-runs-dir."
        )
    data_dir = Path(benchmark_runs_dir).expanduser()
    if not data_dir.is_absolute():
        raise DockerAssetError(
            f"BENCHBOX_DATA_DIR must be an absolute path for platform {spec.platform!r} "
            f"(got {str(benchmark_runs_dir)!r}) -- its compose file mounts BENCHBOX_DATA_DIR "
            "at the SAME absolute path inside the container as on the host, so a relative "
            "value can never match. Pass an absolute benchmark_runs_dir / --benchmark-runs-dir."
        )
    return {"BENCHBOX_DATA_DIR": str(data_dir)}


_FORBIDDEN_PRUNE_VERBS: frozenset[tuple[str, str]] = frozenset(
    {
        ("system", "prune"),
        ("volume", "prune"),
        ("image", "prune"),
        ("builder", "prune"),
    }
)

# The Apple-native `container` CLI is exempt from the prune guard: its prune
# verbs are deliberate, documented operator actions of `make uat-docker-cleanup
# ENGINE=container MODE=max` (reclaiming the Apple container store), guarded by
# container_cleanup._is_forbidden instead. The guard below protects the SHARED
# docker/mocker host state, which the Apple store is not part of.
_APPLE_CONTAINER_CLI = "container"


def command_has_forbidden_prune(argv: Iterable[str]) -> bool:
    """Return True when argv is a global prune against a shared container host.

    Matches on the verb pair (e.g. ``volume prune``) in the tokens *after*
    the binary name, not a ``"docker system prune"`` string literal -- the
    binary is resolved (``docker``, ``mocker``, or a BENCHBOX_CONTAINER_CLI
    override), so a literal-prefix match would silently stop catching
    forbidden commands the moment the resolved engine is not ``docker``.
    The Apple-native ``container`` CLI is exempt (see _APPLE_CONTAINER_CLI):
    its max-mode prunes are a deliberate documented operator action with its
    own guard, and blocking them here broke `make uat-docker-cleanup
    ENGINE=container MODE=max APPLY=1` outright.
    """
    tokens = list(argv)
    if len(tokens) < 3:
        return False
    if Path(tokens[0]).name == _APPLE_CONTAINER_CLI:
        return False
    rest = tokens[1:]
    return any(pair in _FORBIDDEN_PRUNE_VERBS for pair in zip(rest, rest[1:]))


def list_mocker_volumes_matching(project_prefix: str, *, runner: DockerRunner | None = None) -> tuple[str, ...]:
    """List (never remove) mocker volumes whose name starts with `project_prefix`.

    ``mocker volume ls`` is the one Docker-shaped inventory verb mocker
    implements faithfully as plain text (unlike ``container``/``image ls
    --format json``, which echo the literal string ``json`` instead of
    JSON -- live-validated in uat-container-engine-routing w0; see
    container_cleanup.py's module docstring for the same finding on the
    JSON verbs). No-op (empty) when the resolved engine is not mocker.

    This is PREFIX-scoped by design: its consumer is docker_cleanup's
    recovery inventory, whose ownership rule is the project *prefix*
    (`_is_uat_owned`) spanning every project under it -- not one project's
    exact volume set. For per-project teardown, use
    `sweep_leaked_mocker_volumes`, which matches exact compose-declared
    volume names and cannot touch a sibling project.
    """
    if resolve_container_cli() != "mocker":
        return ()
    run = runner or run_docker_command
    list_result = run(["mocker", "volume", "ls"])
    if not list_result.succeeded:
        return ()
    pattern = re.compile(rf"{re.escape(project_prefix)}[-_][A-Za-z0-9._-]+")
    found: list[str] = []
    for line in list_result.stdout.splitlines():
        for match in pattern.finditer(line):
            volume_name = match.group(0)
            if volume_name not in found:
                found.append(volume_name)
    return tuple(found)


def compose_declared_volume_names(spec: DockerPlatformSpec) -> tuple[str, ...]:
    """Return the top-level named-volume keys declared by the spec's compose files."""
    names: list[str] = []
    for compose_file in spec.compose_files:
        try:
            data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        volumes = data.get("volumes") if isinstance(data, dict) else None
        if isinstance(volumes, dict):
            names.extend(str(key) for key in volumes)
    return tuple(dict.fromkeys(names))


def expected_mocker_volume_names(project_name: str, spec: DockerPlatformSpec) -> tuple[str, ...]:
    """Exact volume names one compose project can have created, for both joiners.

    mocker 0.5.4 joins ``<project>-<volume-key>`` with a HYPHEN
    (live-verified twice in uat-container-engine-routing: scratch project
    ``sepcheck`` + volume key ``checkvol`` produced ``sepcheck-checkvol``,
    and the postgresql stack's ``postgresql18-data`` key produced
    ``benchbox-uat-manual-postgresql-postgresql18-data``); docker compose
    joins with an underscore. Both joiners are generated so the exact-match
    set stays correct if mocker ever aligns with docker's convention.
    """
    names: list[str] = []
    for key in compose_declared_volume_names(spec):
        names.append(f"{project_name}-{key}")
        names.append(f"{project_name}_{key}")
    return tuple(names)


def sweep_leaked_mocker_volumes(
    project_name: str,
    spec: DockerPlatformSpec,
    *,
    runner: DockerRunner | None = None,
    dry_run: bool = False,
) -> tuple[str, ...]:
    """Remove named volumes mocker 0.5.4's ``compose down -v`` leaks, for exactly one project.

    Live-validated in uat-container-engine-routing w0: mocker's ``compose
    down -v`` removes containers but leaves named volumes behind (docker's
    does not). Matches EXACT names derived from the spec's compose-declared
    volume keys (`expected_mocker_volume_names`), never a name-prefix scan --
    a prefix scan on project ``p`` would also match a sibling project
    ``p-ha``'s volumes (mocker joins project and volume key with ``-``, so
    ``p-ha-data`` starts with ``p-``), and deleting a sibling's data is the
    one thing a project-scoped sweep must never do. Never a global prune (w3
    anti-pattern). No-op when the resolved engine is not mocker (docker
    already removes named volumes on ``down -v``) or when `dry_run` is set
    (nothing was actually started, so nothing can have leaked).

    Returns the volume names actually removed; a single volume's removal
    failure is swallowed (matches the Makefile's ``|| true``) so one stale
    entry cannot abort the rest of the sweep.
    """
    if dry_run or resolve_container_cli() != "mocker":
        return ()
    run = runner or run_docker_command
    list_result = run(["mocker", "volume", "ls"])
    if not list_result.succeeded:
        return ()
    existing = {token for line in list_result.stdout.splitlines() for token in line.split()}
    removed: list[str] = []
    for volume_name in expected_mocker_volume_names(project_name, spec):
        if volume_name not in existing:
            continue
        rm_result = run(["mocker", "volume", "rm", volume_name], dry_run=dry_run)
        if rm_result.succeeded:
            removed.append(volume_name)
    return tuple(removed)


def run_docker_command(
    argv: list[str],
    *,
    dry_run: bool = False,
    timeout_s: int = 300,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> DockerCommandResult:
    """Run a Docker command and capture result data without raising on setup failures."""
    argv_tuple = tuple(argv)
    if command_has_forbidden_prune(argv_tuple):
        return DockerCommandResult(
            argv=argv_tuple,
            returncode=2,
            stdout="",
            stderr="",
            error="refusing to run forbidden Docker prune command",
        )
    if dry_run:
        return DockerCommandResult(argv=argv_tuple, returncode=0, stdout="", stderr="", dry_run=True)

    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd or REPO_ROOT),
            env=command_env,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        return DockerCommandResult(
            argv=argv_tuple,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError as exc:
        return DockerCommandResult(
            argv=argv_tuple,
            returncode=127,
            stdout="",
            stderr=str(exc),
            error="docker command not found",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return DockerCommandResult(
            argv=argv_tuple,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            error=f"docker command timed out after {timeout_s}s",
        )
    except subprocess.SubprocessError as exc:
        return DockerCommandResult(
            argv=argv_tuple,
            returncode=1,
            stdout="",
            stderr=str(exc),
            error="docker command failed before completion",
        )
