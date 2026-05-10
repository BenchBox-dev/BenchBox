"""Recover abandoned UAT-owned Docker resources and report everything else.

The execute phase cleans a UAT-managed compose project in-process, but a hard
kill or host reboot can leave compose-labelled resources behind. This module is
the explicit recovery path: remove resources with a UAT project prefix, and
report non-UAT Docker usage with enough detail for a human to decide what to
remove.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Callable, Literal

from tests.uat import docker_assets

DockerResourceKind = Literal["container", "volume", "network", "image"]
DockerRunner = Callable[..., docker_assets.DockerCommandResult]

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
DEFAULT_UAT_PROJECT_PREFIX = "benchbox-uat"


class DockerCleanupError(RuntimeError):
    """Raised when Docker inventory or cleanup commands fail."""


@dataclass(frozen=True)
class DockerUsageResource:
    """One Docker resource discovered by the recovery inventory."""

    kind: DockerResourceKind
    identifier: str
    name: str
    created_at: str
    project: str | None = None
    status: str = ""
    size: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.identifier

    def cleanup_command(self) -> tuple[str, ...]:
        """Return the manual cleanup command for this single resource."""
        if self.kind == "container":
            return ("docker", "rm", "-f", self.identifier)
        if self.kind == "volume":
            return ("docker", "volume", "rm", self.identifier)
        if self.kind == "network":
            return ("docker", "network", "rm", self.identifier)
        return ("docker", "image", "rm", self.identifier)

    def cleanup_command_text(self) -> str:
        return shlex.join(self.cleanup_command())


@dataclass(frozen=True)
class CleanupCommandResult:
    """A cleanup command and its Docker result."""

    argv: tuple[str, ...]
    result: docker_assets.DockerCommandResult | None = None

    @property
    def command(self) -> str:
        return shlex.join(self.argv)

    @property
    def status(self) -> str:
        if self.result is None:
            return "planned"
        return "ok" if self.result.succeeded else "failed"


@dataclass(frozen=True)
class DockerCleanupReport:
    """Inventory plus recovery-command results."""

    project_prefix: str
    apply: bool
    uat_owned: tuple[DockerUsageResource, ...]
    non_uat: tuple[DockerUsageResource, ...]
    cleanup_commands: tuple[CleanupCommandResult, ...]


def recover_abandoned_uat_docker_usage(
    *,
    project_prefix: str = DEFAULT_UAT_PROJECT_PREFIX,
    apply: bool = False,
    runner: DockerRunner | None = None,
) -> DockerCleanupReport:
    """Inventory Docker resources, clean UAT-owned resources when requested, and report the rest.

    UAT ownership is determined only by Docker Compose's project label with the
    configured UAT prefix. Non-UAT resources are never mutated by this function;
    their cleanup commands are reported for manual operator review.
    """
    run = runner or docker_assets.run_docker_command
    resources = tuple(_inventory_resources(run))
    uat_owned = tuple(r for r in resources if _is_uat_owned(r, project_prefix))
    non_uat = tuple(r for r in resources if not _is_uat_owned(r, project_prefix))
    commands = tuple(_cleanup_commands_for(uat_owned))

    results: list[CleanupCommandResult] = []
    if apply:
        for argv in commands:
            result = run(list(argv))
            results.append(CleanupCommandResult(argv=argv, result=result))
            if not result.succeeded:
                raise DockerCleanupError(f"Docker cleanup failed: {shlex.join(argv)}: {_result_detail(result)}")
    else:
        results = [CleanupCommandResult(argv=argv) for argv in commands]

    return DockerCleanupReport(
        project_prefix=project_prefix,
        apply=apply,
        uat_owned=uat_owned,
        non_uat=non_uat,
        cleanup_commands=tuple(results),
    )


def format_cleanup_report(report: DockerCleanupReport) -> str:
    """Render a human-readable recovery/report summary."""
    lines = [
        "Docker UAT cleanup report",
        f"project_prefix: {report.project_prefix}",
        f"mode: {'apply' if report.apply else 'dry-run'}",
        "",
    ]
    if report.uat_owned:
        verb = "Cleaned" if report.apply else "Would clean"
        lines.append(f"{verb} UAT-owned resources:")
        lines.extend(_format_resource_lines(report.uat_owned))
        lines.append("")
        if report.cleanup_commands:
            lines.append("UAT cleanup commands:")
            for cmd in report.cleanup_commands:
                suffix = f" [{cmd.status}]" if report.apply else ""
                lines.append(f"  - {cmd.command}{suffix}")
            lines.append("")
    else:
        lines.append("No UAT-owned Docker resources found.")
        lines.append("")

    if report.non_uat:
        lines.append("Non-UAT Docker resources were NOT cleaned automatically:")
        lines.extend(_format_resource_lines(report.non_uat, include_cleanup=True))
    else:
        lines.append("No non-UAT Docker resources found.")
    return "\n".join(lines)


def _format_resource_lines(resources: tuple[DockerUsageResource, ...], *, include_cleanup: bool = False) -> list[str]:
    lines: list[str] = []
    for item in sorted(resources, key=lambda r: (r.kind, r.project or "", r.display_name)):
        project = f" project={item.project}" if item.project else ""
        status = f" status={item.status}" if item.status else ""
        size = f" size={item.size}" if item.size else ""
        created = item.created_at or "unknown"
        lines.append(
            f"  - {item.kind} {item.display_name} id={item.identifier}{project} created={created}{status}{size}"
        )
        if include_cleanup:
            lines.append(f"    cleanup: {item.cleanup_command_text()}")
    return lines


def _is_uat_owned(resource: DockerUsageResource, project_prefix: str) -> bool:
    if not resource.project:
        return False
    return resource.project == project_prefix or resource.project.startswith(f"{project_prefix}-")


def _cleanup_commands_for(resources: tuple[DockerUsageResource, ...]) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    for kind, base in (
        ("container", ("docker", "rm", "-f")),
        ("volume", ("docker", "volume", "rm")),
        ("network", ("docker", "network", "rm")),
        ("image", ("docker", "image", "rm")),
    ):
        ids = [r.identifier for r in resources if r.kind == kind]
        if ids:
            commands.append((*base, *ids))
    return commands


def _inventory_resources(run: DockerRunner) -> list[DockerUsageResource]:
    resources: list[DockerUsageResource] = []
    resources.extend(_list_containers(run))
    resources.extend(_list_volumes(run))
    resources.extend(_list_networks(run))
    resources.extend(_list_images(run))
    return resources


def _list_containers(run: DockerRunner) -> list[DockerUsageResource]:
    result = _run_required(run, ["docker", "container", "ls", "-a", "--no-trunc", "--format", "json"])
    out: list[DockerUsageResource] = []
    for row in _json_lines(result.stdout):
        labels = _parse_label_string(str(row.get("Labels", "")))
        out.append(
            DockerUsageResource(
                kind="container",
                identifier=str(row.get("ID", "")),
                name=str(row.get("Names", "")),
                created_at=str(row.get("CreatedAt") or row.get("Created") or ""),
                project=labels.get(COMPOSE_PROJECT_LABEL),
                status=str(row.get("Status", "")),
                size=str(row.get("Size", "")),
            )
        )
    return out


def _list_volumes(run: DockerRunner) -> list[DockerUsageResource]:
    names_result = _run_required(run, ["docker", "volume", "ls", "-q"])
    names = [line.strip() for line in names_result.stdout.splitlines() if line.strip()]
    if not names:
        return []

    inspect_result = _run_required(run, ["docker", "volume", "inspect", *names])
    try:
        rows = json.loads(inspect_result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DockerCleanupError(f"Could not parse Docker volume inspect JSON: {exc}") from exc

    out: list[DockerUsageResource] = []
    for row in rows:
        labels = row.get("Labels") or {}
        if not isinstance(labels, dict):
            labels = {}
        name = str(row.get("Name", ""))
        out.append(
            DockerUsageResource(
                kind="volume",
                identifier=name,
                name=name,
                created_at=str(row.get("CreatedAt", "")),
                project=labels.get(COMPOSE_PROJECT_LABEL),
                status=str(row.get("Driver", "")),
            )
        )
    return out


def _list_networks(run: DockerRunner) -> list[DockerUsageResource]:
    result = _run_required(run, ["docker", "network", "ls", "-q", "--no-trunc"])
    network_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not network_ids:
        return []
    inspect_result = _run_required(run, ["docker", "network", "inspect", *network_ids])
    try:
        rows = json.loads(inspect_result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DockerCleanupError(f"Could not parse Docker network inspect JSON: {exc}") from exc
    if not isinstance(rows, list):
        rows = []

    out: list[DockerUsageResource] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        labels = row.get("Labels") or {}
        if not isinstance(labels, dict):
            labels = {}
        project = labels.get(COMPOSE_PROJECT_LABEL)
        name = str(row.get("Name", ""))
        if not project and name in {"bridge", "host", "none"}:
            continue
        out.append(
            DockerUsageResource(
                kind="network",
                identifier=str(row.get("ID", "")),
                name=name,
                created_at=str(row.get("Created") or ""),
                project=project,
                status=str(row.get("Driver", "")),
            )
        )
    return out


def _list_images(run: DockerRunner) -> list[DockerUsageResource]:
    list_result = _run_required(run, ["docker", "image", "ls", "--no-trunc", "--format", "json"])
    rows = _json_lines(list_result.stdout)
    image_ids = [str(row.get("ID", "")) for row in rows if row.get("ID")]
    inspect_by_id = _inspect_images(run, image_ids)

    out: list[DockerUsageResource] = []
    for row in rows:
        image_id = str(row.get("ID", ""))
        detail = inspect_by_id.get(image_id, {})
        config = detail.get("Config") if isinstance(detail, dict) else {}
        labels = config.get("Labels") if isinstance(config, dict) else {}
        if not isinstance(labels, dict):
            labels = {}
        repository = str(row.get("Repository", ""))
        tag = str(row.get("Tag", ""))
        name = repository if tag in {"", "<none>"} else f"{repository}:{tag}"
        out.append(
            DockerUsageResource(
                kind="image",
                identifier=image_id,
                name=name,
                created_at=str(detail.get("Created") or row.get("CreatedAt") or row.get("CreatedSince") or ""),
                project=labels.get(COMPOSE_PROJECT_LABEL),
                size=str(row.get("Size", "")),
            )
        )
    return out


def _inspect_images(run: DockerRunner, image_ids: list[str]) -> dict[str, dict[str, object]]:
    if not image_ids:
        return {}
    result = _run_required(run, ["docker", "image", "inspect", *image_ids])
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DockerCleanupError(f"Could not parse Docker image inspect JSON: {exc}") from exc
    if not isinstance(rows, list):
        return {}
    return {str(row.get("Id", "")): row for row in rows if isinstance(row, dict)}


def _run_required(run: DockerRunner, argv: list[str]) -> docker_assets.DockerCommandResult:
    result = run(argv)
    if result.succeeded:
        return result
    raise DockerCleanupError(f"Docker inventory command failed: {shlex.join(argv)}: {_result_detail(result)}")


def _result_detail(result: docker_assets.DockerCommandResult) -> str:
    return result.error or result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"


def _json_lines(stdout: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DockerCleanupError(f"Could not parse Docker JSON line {line!r}: {exc}") from exc
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _parse_label_string(raw: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not raw:
        return labels
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels
