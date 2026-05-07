"""Docker compose lifecycle helpers for UAT-managed platform stacks.

The UAT harness may start and stop Docker-backed platforms at execute-phase
platform boundaries. This module owns the platform → compose-file mapping and
keeps command construction small, deterministic, and safe to unit test without
a live Docker daemon.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.uat import matrix

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCKER_PLATFORM_SWITCH_MODES: tuple[str, ...] = ("off", "containers", "volumes", "images")
DOCKER_FIXED_CONTAINER_NAME_POLICIES: tuple[str, ...] = ("fail", "override", "allow")
_PROJECT_NAME_MAX_LEN = 63


class DockerAssetError(ValueError):
    """Raised when a UAT Docker lifecycle request is unsafe or unsupported."""


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


def _repo_path(relative: str) -> Path:
    return REPO_ROOT / relative


# Firebolt has a compose file but is intentionally not listed here: it is not
# currently in matrix.PLATFORM_GROUPS["docker"] for UAT sweeps.
_DOCKER_PLATFORM_SPECS: dict[str, DockerPlatformSpec] = {
    "clickhouse-server": DockerPlatformSpec(
        platform="clickhouse-server",
        compose_files=(_repo_path("docker/clickhouse/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("clickhouse-server"),
    ),
    "cedardb": DockerPlatformSpec(
        platform="cedardb",
        compose_files=(_repo_path("docker/cedardb/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("cedardb"),
    ),
    "starrocks": DockerPlatformSpec(
        platform="starrocks",
        compose_files=(_repo_path("docker/starrocks/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("starrocks"),
    ),
    "postgresql": DockerPlatformSpec(
        platform="postgresql",
        compose_files=(_repo_path("docker/postgresql/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("postgresql"),
    ),
    "presto": DockerPlatformSpec(
        platform="presto",
        compose_files=(_repo_path("docker/presto/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("presto"),
    ),
    "trino": DockerPlatformSpec(
        platform="trino",
        compose_files=(_repo_path("docker/trino/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("trino"),
    ),
    "databend": DockerPlatformSpec(
        platform="databend",
        compose_files=(_repo_path("docker/databend/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("databend"),
    ),
    "doris": DockerPlatformSpec(
        platform="doris",
        compose_files=(_repo_path("docker/doris/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("doris"),
    ),
    "influxdb": DockerPlatformSpec(
        platform="influxdb",
        compose_files=(_repo_path("docker/influxdb/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("influxdb"),
    ),
    "pg-duckdb": DockerPlatformSpec(
        platform="pg-duckdb",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.pg-duckdb.yaml"),),
        fixed_container_names=("benchbox-pg-duckdb",),
        managed_start_allowed=False,
        tcp_probe_label=matrix.PLATFORM_PORTS.get("pg-duckdb"),
        notes="Compose declares a fixed container_name; keep external-only until that is removed or overridden.",
    ),
    "pg-mooncake": DockerPlatformSpec(
        platform="pg-mooncake",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.pg-mooncake.yaml"),),
        fixed_container_names=("benchbox-pg-mooncake",),
        managed_start_allowed=False,
        tcp_probe_label=matrix.PLATFORM_PORTS.get("pg-mooncake"),
        notes="Compose declares a fixed container_name; keep external-only until that is removed or overridden.",
    ),
    "timescaledb": DockerPlatformSpec(
        platform="timescaledb",
        compose_files=(_repo_path("docker/postgres-extensions/docker-compose.timescaledb.yaml"),),
        fixed_container_names=("benchbox-timescaledb",),
        managed_start_allowed=False,
        tcp_probe_label=matrix.PLATFORM_PORTS.get("timescaledb"),
        notes="Compose declares a fixed container_name; keep external-only until that is removed or overridden.",
    ),
    "questdb": DockerPlatformSpec(
        platform="questdb",
        compose_files=(_repo_path("docker/questdb/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("questdb"),
    ),
    "singlestore": DockerPlatformSpec(
        platform="singlestore",
        compose_files=(_repo_path("docker/singlestore/docker-compose.yml"),),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("singlestore"),
    ),
    "velox": DockerPlatformSpec(
        platform="velox",
        compose_files=(_repo_path("docker/velox/docker-compose.yml"),),
        services=("velox-connect",),
        tcp_probe_label=matrix.PLATFORM_PORTS.get("velox"),
        notes="Start only velox-connect for host-run UAT; BENCHBOX_DATA_DIR is set to the sweep output root.",
    ),
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
    argv = ["docker", "compose", "-p", project_name]
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
    if spec.platform != "velox" or benchmark_runs_dir is None:
        return {}
    return {"BENCHBOX_DATA_DIR": str(Path(benchmark_runs_dir).expanduser())}


def command_has_forbidden_prune(argv: Iterable[str]) -> bool:
    """Return True when argv contains a Docker prune command UAT must never run."""
    joined = " ".join(argv)
    forbidden = (
        "docker system prune",
        "docker volume prune",
        "docker image prune",
        "docker builder prune",
    )
    return any(term in joined for term in forbidden)


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
