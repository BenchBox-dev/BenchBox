"""Fast-test coverage for the Apple `container` cleanup mode."""

from __future__ import annotations

import json

import pytest

from tests.uat import container_cleanup, docker_assets

pytestmark = pytest.mark.fast


_IMAGES = [
    {
        "id": "img-owned",
        "configuration": {"name": "benchbox/tpc-h-linux-arm64:latest", "creationDate": "2026-07-08T17:47:31Z"},
    },
    {
        "id": "img-agent",
        "configuration": {"name": "local/benchbox-agent:latest", "creationDate": "2026-07-01T00:00:00Z"},
    },
    {"id": "img-shared", "configuration": {"name": "postgres:18", "creationDate": "2026-06-01T00:00:00Z"}},
    {"id": "img-shared2", "configuration": {"name": "ubuntu:24.04", "creationDate": "2026-06-02T00:00:00Z"}},
    {
        "id": "img-builder",
        "configuration": {
            "name": "ghcr.io/apple/container-builder-shim/builder:0.12.0",
            "creationDate": "2026-06-30T00:00:00Z",
        },
    },
]

_CONTAINERS = [
    {
        "id": "buildkit",
        "configuration": {
            "id": "buildkit",
            "image": {"reference": "ghcr.io/apple/container-builder-shim/builder:0.12.0"},
            "labels": {"com.apple.container.resource.role": "builder"},
        },
        "status": {"state": "running"},
    },
    {
        "id": "uat-leftover",
        "configuration": {
            "id": "uat-leftover",
            "image": {"reference": "postgres:18"},
            "labels": {"com.docker.compose.project": "benchbox-uat-smoke-postgresql"},
        },
        "status": {"state": "stopped"},
    },
    {
        "id": "external-ctr",
        "configuration": {"id": "external-ctr", "image": {"reference": "redis:7"}, "labels": {}},
        "status": {"state": "running"},
    },
]

_VOLUMES = [
    {"name": "benchbox-uat-smoke-postgresql_pgdata", "driver": "local"},
    {"name": "developer_scratch", "driver": "local"},
]

_SYSTEM_DF = (
    "TYPE           TOTAL  ACTIVE  SIZE      RECLAIMABLE\n"
    "Images         5      1       11.65 GB  11.22 GB (96%)\n"
    "Containers     3      2       14.01 GB  0 B (0%)\n"
    "Local Volumes  2      0       120 MB    120 MB (100%)\n"
)


def _runner(calls: list[tuple[str, ...]], *, df_fails: bool = False):
    def fake(argv, **kwargs):
        argv_tuple = tuple(argv)
        calls.append(argv_tuple)
        if argv_tuple[:4] == ("container", "image", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(_IMAGES), "")
        if argv_tuple[:3] == ("container", "ls", "-a"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(_CONTAINERS), "")
        if argv_tuple[:4] == ("container", "volume", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(_VOLUMES), "")
        if argv_tuple == ("container", "system", "df"):
            if df_fails:
                return docker_assets.DockerCommandResult(argv_tuple, 1, "", "boom", error="unavailable")
            return docker_assets.DockerCommandResult(argv_tuple, 0, _SYSTEM_DF, "")
        # Mutating commands succeed.
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    return fake


def _targets_by_kind(report):
    out: dict[str, set[str]] = {}
    for r in report.targets:
        out.setdefault(r.kind, set()).add(r.display_name)
    return out


def test_owned_mode_targets_only_benchbox_owned():
    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, runner=_runner([]))
    assert _targets_by_kind(report) == {
        "image": {"benchbox/tpc-h-linux-arm64:latest", "local/benchbox-agent:latest"},
        "container": {"uat-leftover"},
        "volume": {"benchbox-uat-smoke-postgresql_pgdata"},
    }
    # Shared + system are retained; builder is never a target.
    retained = {r.display_name for r in report.retained}
    assert {"postgres:18", "ubuntu:24.04", "ghcr.io/apple/container-builder-shim/builder:0.12.0"} <= retained
    assert "buildkit" in retained


def test_images_mode_adds_shared_images_but_not_builder():
    report = container_cleanup.reclaim_container_usage(mode="images", apply=False, runner=_runner([]))
    assert _targets_by_kind(report)["image"] == {
        "benchbox/tpc-h-linux-arm64:latest",
        "local/benchbox-agent:latest",
        "postgres:18",
        "ubuntu:24.04",
    }
    # The builder image + builder container stay retained (system category).
    retained = {r.display_name for r in report.retained}
    assert "ghcr.io/apple/container-builder-shim/builder:0.12.0" in retained
    assert "buildkit" in retained
    # The external non-owned container is only reclaimed at max.
    assert "external-ctr" not in {r.display_name for r in report.targets}


def test_apply_runs_grouped_removals_in_dependency_order():
    calls: list[tuple[str, ...]] = []
    report = container_cleanup.reclaim_container_usage(mode="owned", apply=True, runner=_runner(calls))
    mutations = [
        c
        for c in calls
        if c[:3] not in {("container", "image", "ls"), ("container", "volume", "ls")}
        and c[:3] != ("container", "ls", "-a")
        and c != ("container", "system", "df")
    ]
    # Containers removed before images so image removal is not blocked.
    assert mutations == [
        ("container", "rm", "-f", "uat-leftover"),
        ("container", "volume", "rm", "benchbox-uat-smoke-postgresql_pgdata"),
        ("container", "image", "rm", "benchbox/tpc-h-linux-arm64:latest", "local/benchbox-agent:latest"),
    ]
    assert all(c.status == "ok" for c in report.commands)
    assert report.footprint_after is not None


def test_max_mode_appends_prune_and_builder_reclaim():
    calls: list[tuple[str, ...]] = []
    container_cleanup.reclaim_container_usage(mode="max", apply=True, runner=_runner(calls))
    assert ("container", "prune") in calls
    assert ("container", "volume", "prune") in calls
    assert ("container", "builder", "delete", "--force") in calls


def test_max_mode_reclaims_external_container():
    report = container_cleanup.reclaim_container_usage(mode="max", apply=False, runner=_runner([]))
    assert "external-ctr" in {r.display_name for r in report.targets if r.kind == "container"}


def test_footprint_parses_system_df_rows():
    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, runner=_runner([]))
    rows = {kind: (size, recl) for kind, size, recl in report.footprint_before.rows}
    assert rows["Images"] == ("11.65 GB", "11.22 GB")
    assert rows["Local Volumes"] == ("120 MB", "120 MB")


def test_footprint_unavailable_is_non_fatal():
    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, runner=_runner([], df_fails=True))
    assert report.footprint_before.rows == ()
    assert "disk usage unavailable" in container_cleanup.format_container_cleanup_report(report)


def test_unknown_mode_raises():
    with pytest.raises(container_cleanup.ContainerCleanupError):
        container_cleanup.reclaim_container_usage(mode="everything", apply=False, runner=_runner([]))


def test_report_renders_mode_and_store_path():
    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, runner=_runner([]))
    rendered = container_cleanup.format_container_cleanup_report(report)
    assert "mode: owned (dry-run)" in rendered
    assert "com.apple.container" in rendered
    assert "Retained (widen --mode to reclaim):" in rendered


def test_custom_project_prefix_reaches_classification():
    """#1065 review: --prefix must actually classify resources, not just be
    echoed in the report. _inventory_resources/_list_images/_list_containers/
    _list_volumes previously ignored the caller's project_prefix and always
    classified against the hard-coded DEFAULT_UAT_PROJECT_PREFIX."""
    custom_images = [
        {"id": "img-custom", "configuration": {"name": "foo-tpc-h:latest", "creationDate": "2026-07-08T00:00:00Z"}},
    ]
    custom_containers = [
        {
            "id": "custom-leftover",
            "configuration": {
                "id": "custom-leftover",
                "image": {"reference": "postgres:18"},
                "labels": {"com.docker.compose.project": "foo-smoke-postgresql"},
            },
            "status": {"state": "stopped"},
        },
    ]

    def fake(argv, **kwargs):
        argv_tuple = tuple(argv)
        if argv_tuple[:4] == ("container", "image", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(custom_images), "")
        if argv_tuple[:3] == ("container", "ls", "-a"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(custom_containers), "")
        if argv_tuple[:4] == ("container", "volume", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, "[]", "")
        if argv_tuple == ("container", "system", "df"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, _SYSTEM_DF, "")
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, project_prefix="foo", runner=fake)
    assert _targets_by_kind(report) == {
        "image": {"foo-tpc-h:latest"},
        "container": {"custom-leftover"},
    }


def test_image_reference_read_from_display_reference_field():
    """#1065 review: current `container image ls --format json` renders
    ImageResource rows with the reference at the top-level `displayReference`
    field, not `configuration.name` (which is empty on those rows)."""
    images = [
        {
            "id": "sha256:abc123",
            "displayReference": "benchbox/tpc-h-linux-arm64:latest",
            "configuration": {"descriptor": {"digest": "sha256:abc123"}},
        },
        {
            "id": "sha256:def456",
            "displayReference": "postgres:18",
            "configuration": {"descriptor": {"digest": "sha256:def456"}},
        },
    ]

    def fake(argv, **kwargs):
        argv_tuple = tuple(argv)
        if argv_tuple[:4] == ("container", "image", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, json.dumps(images), "")
        if argv_tuple[:3] == ("container", "ls", "-a"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, "[]", "")
        if argv_tuple[:4] == ("container", "volume", "ls", "--format"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, "[]", "")
        if argv_tuple == ("container", "system", "df"):
            return docker_assets.DockerCommandResult(argv_tuple, 0, _SYSTEM_DF, "")
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    report = container_cleanup.reclaim_container_usage(mode="owned", apply=False, runner=fake)
    assert _targets_by_kind(report) == {"image": {"benchbox/tpc-h-linux-arm64:latest"}}
