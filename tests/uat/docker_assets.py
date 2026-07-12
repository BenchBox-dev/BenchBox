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
    ),
    "cedardb": DockerPlatformSpec(
        platform="cedardb",
        compose_files=(_repo_path("docker/cedardb/docker-compose.yml"),),
    ),
    "starrocks": DockerPlatformSpec(
        platform="starrocks",
        compose_files=(_repo_path("docker/starrocks/docker-compose.yml"),),
    ),
    "postgresql": DockerPlatformSpec(
        platform="postgresql",
        compose_files=(_repo_path("docker/postgresql/docker-compose.yml"),),
    ),
    "presto": DockerPlatformSpec(
        platform="presto",
        compose_files=(_repo_path("docker/presto/docker-compose.yml"),),
    ),
    "trino": DockerPlatformSpec(
        platform="trino",
        compose_files=(_repo_path("docker/trino/docker-compose.yml"),),
    ),
    "databend": DockerPlatformSpec(
        platform="databend",
        compose_files=(_repo_path("docker/databend/docker-compose.yml"),),
    ),
    "doris": DockerPlatformSpec(
        platform="doris",
        compose_files=(_repo_path("docker/doris/docker-compose.yml"),),
    ),
    "influxdb": DockerPlatformSpec(
        platform="influxdb",
        compose_files=(_repo_path("docker/influxdb/docker-compose.yml"),),
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
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "pg-mooncake": DockerPlatformSpec(
        platform="pg-mooncake",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.pg-mooncake.yaml"),),
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "timescaledb": DockerPlatformSpec(
        platform="timescaledb",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.timescaledb.yaml"),),
        notes="PostgreSQL-family stack on localhost:5432; run sequentially with other PG-family platforms.",
    ),
    "questdb": DockerPlatformSpec(
        platform="questdb",
        compose_files=(_repo_path("docker/questdb/docker-compose.yml"),),
    ),
    "singlestore": DockerPlatformSpec(
        platform="singlestore",
        compose_files=(_repo_path("docker/singlestore/docker-compose.yml"),),
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
# Credential and secondary-port literals (password=, http_port=, ...) are NOT
# yet derived — that is the deferred follow-up. They live here as the single
# connection registry so matrix.py no longer keeps a parallel copy.
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

# Static (non-derived) platform options, relocated from matrix.py. The
# reachability `port=` option is injected separately from the compose-derived
# host port (see platform_extra_opts) so an env override flows through.
_PLATFORM_STATIC_OPTS: dict[str, list[str]] = {
    "questdb": ["--platform-option", "http_port=19000"],
    "starrocks": ["--platform-option", "http_port=18040"],
    "doris": [
        "--platform-option",
        "http_port=18030",
        "--platform-option",
        "be_http_port=18040",
    ],
    "singlestore": ["--platform-option", "password=benchbox"],
    "velox": ["--platform-option", "deployment=remote"],
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
_PLATFORM_LOCAL_MANAGED_OPTS: dict[str, list[str]] = {
    "clickhouse-server": ["--platform-option", "password=benchbox"],
    "pg-duckdb": ["--platform-option", "password=benchbox"],
    "pg-mooncake": ["--platform-option", "password=benchbox"],
    "timescaledb": ["--platform-option", "password=benchbox"],
    "postgresql": ["--platform-option", "password=benchbox"],
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
    env = os.environ if env is None else env
    service_port = PLATFORM_SERVICE_PORT.get(platform)
    spec = _DOCKER_PLATFORM_SPECS.get(platform)
    if service_port is None or spec is None:
        return None
    for compose_file in spec.compose_files:
        for host_token, container in _iter_compose_port_mappings(compose_file):
            if container == service_port:
                resolved = _resolve_host_token(host_token, env)
                if resolved is not None:
                    return resolved
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
    opts += list(_PLATFORM_STATIC_OPTS.get(platform, []))
    if platform in _PLATFORM_INJECT_SPARK_CONNECT_ENDPOINT_OPT:
        host_port = resolve_published_host_port(platform, env=env)
        if host_port is not None:
            opts += ["--platform-option", f"endpoint=sc://localhost:{host_port}"]
    return opts


def local_managed_platform_extra_opts(platform: str) -> list[str]:
    """Return managed-Docker-only `--platform-option` argv (credentials)."""
    return list(_PLATFORM_LOCAL_MANAGED_OPTS.get(platform, []))


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


def compose_project_name(config_name: str, platform: str, prefix: str = "benchbox-uat") -> str:
    """Return a deterministic Docker compose project name for one UAT platform block."""
    raw = f"{prefix}-{config_name}-{platform}".lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", raw)
    name = re.sub(r"[-_]{2,}", "-", name).strip("-_")
    if not name or not name[0].isalnum():
        name = f"uat-{name}".strip("-_")
    if len(name) > _PROJECT_NAME_MAX_LEN:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        keep = _PROJECT_NAME_MAX_LEN - len(digest) - 1
        name = f"{name[:keep].rstrip('-_')}-{digest}"
    return name


def _compose_base_command(spec: DockerPlatformSpec, project_name: str) -> list[str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_name):
        raise DockerAssetError(f"Unsafe Docker compose project name {project_name!r}")
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
    """Return environment overrides needed by a compose spec."""
    if spec.platform not in {"lakesail", "velox"} or benchmark_runs_dir is None:
        return {}
    return {"BENCHBOX_DATA_DIR": str(Path(benchmark_runs_dir).expanduser())}


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
