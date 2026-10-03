from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from tests.uat import docker_assets
from tests.uat.docker_cleanup import COMPOSE_PROJECT_LABEL, DEFAULT_UAT_PROJECT_PREFIX

MOCKER_COMPOSE_PROJECT_LABEL = "com.mocker.compose.project"

ContainerResourceKind = Literal["image", "container", "volume", "network"]
ContainerCategory = Literal["owned", "shared", "system"]
ContainerRunner = Callable[..., docker_assets.DockerCommandResult]

CONTAINER_BIN = "container"
CONTAINER_CLEANUP_MODES: tuple[str, ...] = ("owned", "images", "max")

CONTAINER_STORAGE_PATH = Path("~/Library/Application Support/com.apple.container")

_OWNED_IMAGE_PREFIXES: tuple[str, ...] = ("benchbox/", "local/benchbox")

_BUILDER_ROLE_LABEL = "com.apple.container.resource.role"
_BUILDER_IMAGE_MARKER = "container-builder-shim"


class ContainerCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContainerResource:
    kind: ContainerResourceKind
    identifier: str
    name: str
    category: ContainerCategory
    created_at: str = ""
    status: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.identifier

    def cleanup_command(self) -> tuple[str, ...]:
        if self.kind == "image":
            return (CONTAINER_BIN, "image", "rm", self.display_name)
        if self.kind == "container":
            return (CONTAINER_BIN, "rm", "-f", self.identifier)
        if self.kind == "network":
            return (CONTAINER_BIN, "network", "rm", self.display_name)
        return (CONTAINER_BIN, "volume", "rm", self.display_name)

    def cleanup_command_text(self) -> str:
        return shlex.join(self.cleanup_command())


@dataclass(frozen=True)
class ContainerFootprint:
    rows: tuple[tuple[str, str, str], ...] = ()

    def as_lines(self) -> list[str]:
        if not self.rows:
            return ["  (disk usage unavailable)"]
        return [f"  {kind}: size={size} reclaimable={reclaimable}" for kind, size, reclaimable in self.rows]


@dataclass(frozen=True)
class ContainerCommandResult:
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
class ContainerCleanupReport:
    project_prefix: str
    mode: str
    apply: bool
    targets: tuple[ContainerResource, ...]
    retained: tuple[ContainerResource, ...]
    commands: tuple[ContainerCommandResult, ...]
    footprint_before: ContainerFootprint = field(default_factory=ContainerFootprint)
    footprint_after: ContainerFootprint | None = None


def reclaim_container_usage(
    *,
    project_prefix: str = DEFAULT_UAT_PROJECT_PREFIX,
    mode: str = "owned",
    apply: bool = False,
    runner: ContainerRunner | None = None,
) -> ContainerCleanupReport:
    if mode not in CONTAINER_CLEANUP_MODES:
        raise ContainerCleanupError(
            f"Unknown container cleanup mode {mode!r}; valid: {', '.join(CONTAINER_CLEANUP_MODES)}"
        )
    run = runner or docker_assets.run_docker_command

    resources = _inventory_resources(run, project_prefix)
    targets, retained = _partition_targets(resources, mode)
    planned = _plan_commands(targets, mode)
    footprint_before = _read_footprint(run)

    executed: list[ContainerCommandResult] = []
    footprint_after: ContainerFootprint | None = None
    if apply:
        for argv in planned:
            if _is_forbidden(argv):
                raise ContainerCleanupError(f"Refusing to run destructive container command: {shlex.join(argv)}")
            result = run(list(argv))
            executed.append(ContainerCommandResult(argv=argv, result=result))
            if not result.succeeded:
                raise ContainerCleanupError(f"Container cleanup failed: {shlex.join(argv)}: {_result_detail(result)}")
        footprint_after = _read_footprint(run)
    else:
        executed = [ContainerCommandResult(argv=argv) for argv in planned]

    return ContainerCleanupReport(
        project_prefix=project_prefix,
        mode=mode,
        apply=apply,
        targets=targets,
        retained=retained,
        commands=tuple(executed),
        footprint_before=footprint_before,
        footprint_after=footprint_after,
    )


def format_container_cleanup_report(report: ContainerCleanupReport) -> str:
    lines = [
        "Apple container cleanup report",
        f"engine store: {CONTAINER_STORAGE_PATH}",
        f"project_prefix: {report.project_prefix}",
        f"mode: {report.mode} ({'apply' if report.apply else 'dry-run'})",
        "",
        "Disk footprint (container system df)" + (" before:" if report.apply else ":"),
    ]
    lines.extend(report.footprint_before.as_lines())
    if report.apply and report.footprint_after is not None:
        lines.append("Disk footprint after:")
        lines.extend(report.footprint_after.as_lines())
    lines.append("")

    if report.targets:
        verb = "Reclaimed" if report.apply else "Would reclaim"
        lines.append(f"{verb} ({report.mode}):")
        lines.extend(_format_resource_lines(report.targets))
        lines.append("")
    else:
        lines.append(f"No reclaimable resources for mode {report.mode!r}.")
        lines.append("")

    if report.commands:
        lines.append("Cleanup commands:")
        for cmd in report.commands:
            suffix = f" [{cmd.status}]" if report.apply else ""
            lines.append(f"  - {cmd.command}{suffix}")
        lines.append("")

    if report.retained:
        lines.append("Retained (widen --mode to reclaim):")
        lines.extend(_format_resource_lines(report.retained, include_cleanup=True))
    else:
        lines.append("Nothing retained.")
    return "\n".join(lines)


def _format_resource_lines(resources: tuple[ContainerResource, ...], *, include_cleanup: bool = False) -> list[str]:
    lines: list[str] = []
    for item in sorted(resources, key=lambda r: (r.kind, r.category, r.display_name)):
        created = f" created={item.created_at}" if item.created_at else ""
        status = f" status={item.status}" if item.status else ""
        lines.append(f"  - {item.kind} {item.display_name} [{item.category}]{created}{status}")
        if include_cleanup:
            lines.append(f"    cleanup: {item.cleanup_command_text()}")
    return lines


def _is_owned_image_name(name: str, project_prefix: str) -> bool:
    lowered = name.lower()
    if lowered.startswith(project_prefix.lower()):
        return True
    return any(lowered.startswith(prefix) for prefix in _OWNED_IMAGE_PREFIXES)


def _compose_project_label(labels: dict[str, object]) -> str | None:
    value = labels.get(MOCKER_COMPOSE_PROJECT_LABEL) or labels.get(COMPOSE_PROJECT_LABEL)
    return str(value) if value else None


def _partition_targets(
    resources: tuple[ContainerResource, ...], mode: str
) -> tuple[tuple[ContainerResource, ...], tuple[ContainerResource, ...]]:
    targets: list[ContainerResource] = []
    retained: list[ContainerResource] = []
    for resource in resources:
        if resource.category == "system":
            retained.append(resource)
        elif resource.category == "owned" or resource.kind == "image" and mode in {"images", "max"} or mode == "max":
            targets.append(resource)
        else:
            retained.append(resource)
    return tuple(targets), tuple(retained)


def _plan_commands(targets: tuple[ContainerResource, ...], mode: str) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    commands.extend(_grouped_removals(targets, "container", (CONTAINER_BIN, "rm", "-f"), key=lambda r: r.identifier))
    commands.extend(_grouped_removals(targets, "volume", (CONTAINER_BIN, "volume", "rm"), key=lambda r: r.display_name))
    commands.extend(
        _grouped_removals(targets, "network", (CONTAINER_BIN, "network", "rm"), key=lambda r: r.display_name)
    )
    commands.extend(_grouped_removals(targets, "image", (CONTAINER_BIN, "image", "rm"), key=lambda r: r.display_name))
    if mode == "max":
        commands.append((CONTAINER_BIN, "prune"))
        commands.append((CONTAINER_BIN, "volume", "prune"))
        commands.append((CONTAINER_BIN, "network", "prune"))
        commands.append((CONTAINER_BIN, "builder", "delete", "--force"))
    return commands


def _grouped_removals(
    targets: tuple[ContainerResource, ...],
    kind: ContainerResourceKind,
    base: tuple[str, ...],
    *,
    key: Callable[[ContainerResource], str],
) -> list[tuple[str, ...]]:
    seen: set[str] = set()
    ids: list[str] = []
    for resource in targets:
        if resource.kind != kind:
            continue
        value = key(resource)
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return [(*base, *ids)] if ids else []


def _is_forbidden(argv: tuple[str, ...]) -> bool:
    joined = " ".join(argv)
    return "rm -rf" in joined or "system stop" in joined or "system kill" in joined


def _inventory_resources(run: ContainerRunner, project_prefix: str) -> tuple[ContainerResource, ...]:
    resources: list[ContainerResource] = []
    resources.extend(_list_images(run, project_prefix))
    resources.extend(_list_containers(run, project_prefix))
    resources.extend(_list_volumes(run, project_prefix))
    resources.extend(_list_networks(run, project_prefix))
    return tuple(resources)


def _list_images(run: ContainerRunner, project_prefix: str) -> list[ContainerResource]:
    rows = _run_json_array(run, [CONTAINER_BIN, "image", "ls", "--format", "json"])
    out: list[ContainerResource] = []
    for row in rows:
        row = row if isinstance(row, dict) else {}
        config = row.get("configuration") if isinstance(row, dict) else None
        config = config if isinstance(config, dict) else {}
        name = str(row.get("displayReference") or config.get("name") or "")
        identifier = str(row.get("id") or row.get("digest") or "")
        created_at = str(config.get("creationDate") or "")
        category: ContainerCategory
        if _BUILDER_IMAGE_MARKER in name:
            category = "system"
        elif _is_owned_image_name(name, project_prefix):
            category = "owned"
        else:
            category = "shared"
        out.append(
            ContainerResource(
                kind="image",
                identifier=identifier,
                name=name,
                category=category,
                created_at=created_at,
            )
        )
    return out


def _list_containers(run: ContainerRunner, project_prefix: str) -> list[ContainerResource]:
    rows = _run_json_array(run, [CONTAINER_BIN, "ls", "-a", "--format", "json"])
    out: list[ContainerResource] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        config = row.get("configuration") if isinstance(row.get("configuration"), dict) else {}
        labels = config.get("labels") if isinstance(config.get("labels"), dict) else {}
        identifier = str(row.get("id") or config.get("id") or "")
        image_ref = ""
        image = config.get("image")
        if isinstance(image, dict):
            image_ref = str(image.get("reference") or "")
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        state = str(status.get("state") or "")
        project = _compose_project_label(labels)

        if labels.get(_BUILDER_ROLE_LABEL) == "builder" or _BUILDER_IMAGE_MARKER in image_ref:
            category = "system"
        elif _is_owned(project, project_prefix) or _is_owned_image_name(image_ref, project_prefix):
            category = "owned"
        else:
            category = "shared"
        out.append(
            ContainerResource(
                kind="container",
                identifier=identifier,
                name=identifier or image_ref,
                category=category,
                created_at=str(config.get("creationDate") or ""),
                status=state,
            )
        )
    return out


def _list_volumes(run: ContainerRunner, project_prefix: str) -> list[ContainerResource]:
    rows = _run_json_array(run, [CONTAINER_BIN, "volume", "ls", "--format", "json"])
    out: list[ContainerResource] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("Name") or "")
        if not name:
            continue
        category: ContainerCategory = "owned" if _is_owned(name, project_prefix) else "shared"
        out.append(
            ContainerResource(
                kind="volume",
                identifier=name,
                name=name,
                category=category,
                status=str(row.get("driver") or row.get("Driver") or ""),
            )
        )
    return out


def _list_networks(run: ContainerRunner, project_prefix: str) -> list[ContainerResource]:
    rows = _run_json_array(run, [CONTAINER_BIN, "network", "ls", "--format", "json"])
    out: list[ContainerResource] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        config = row.get("configuration") if isinstance(row.get("configuration"), dict) else {}
        labels = config.get("labels") if isinstance(config.get("labels"), dict) else {}
        name = str(config.get("name") or "")
        identifier = str(row.get("id") or name)
        project = _compose_project_label(labels)

        if labels.get(_BUILDER_ROLE_LABEL) == "builtin" or name == "default":
            category: ContainerCategory = "system"
        elif _is_owned(project, project_prefix) or _is_owned(name, project_prefix):
            category = "owned"
        else:
            category = "shared"
        out.append(
            ContainerResource(
                kind="network",
                identifier=identifier,
                name=name,
                category=category,
                created_at=str(config.get("creationDate") or ""),
            )
        )
    return out


def _read_footprint(run: ContainerRunner) -> ContainerFootprint:
    result = run([CONTAINER_BIN, "system", "df"])
    if not result.succeeded or not result.stdout.strip():
        return ContainerFootprint()
    rows: list[tuple[str, str, str]] = []
    lines = result.stdout.splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        num_idx = next((i for i, tok in enumerate(parts) if tok.isdigit()), None)
        if num_idx is None or num_idx == 0 or len(parts) < num_idx + 6:
            continue
        kind = " ".join(parts[:num_idx])
        size = " ".join(parts[num_idx + 2 : num_idx + 4])
        reclaimable = " ".join(parts[num_idx + 4 : num_idx + 6])
        rows.append((kind, size, reclaimable))
    return ContainerFootprint(rows=tuple(rows))


def _is_owned(project: str | None, project_prefix: str) -> bool:
    if not project:
        return False
    return (
        project == project_prefix
        or project.startswith(f"{project_prefix}-")
        or project.startswith(f"{project_prefix}_")
    )


def _run_json_array(run: ContainerRunner, argv: list[str]) -> list[object]:
    result = run(argv)
    if not result.succeeded:
        raise ContainerCleanupError(f"Container inventory command failed: {shlex.join(argv)}: {_result_detail(result)}")
    stdout = result.stdout.strip()
    if not stdout:
        return []
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ContainerCleanupError(f"Could not parse container JSON from {shlex.join(argv)}: {exc}") from exc
    return list(parsed) if isinstance(parsed, list) else []


def _result_detail(result: docker_assets.DockerCommandResult) -> str:
    return result.error or result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
