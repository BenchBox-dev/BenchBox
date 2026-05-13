"""Fast-test coverage for UAT Docker compose lifecycle helpers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.uat import docker_assets, matrix

pytestmark = pytest.mark.fast


def test_docker_specs_cover_matrix_docker_group_only():
    specs = docker_assets.docker_platform_specs()
    assert set(specs) == set(matrix.PLATFORM_GROUPS["docker"])
    assert "duckdb" not in specs
    assert "firebolt" not in specs  # compose exists, but UAT docker group does not include it


def test_compose_down_commands_are_project_scoped_and_targeted():
    spec = docker_assets.docker_platform_spec("postgresql")
    project = "benchbox-uat-smoke-postgresql"

    containers = docker_assets.compose_down_command(spec, project, "containers")
    volumes = docker_assets.compose_down_command(spec, project, "volumes")
    images = docker_assets.compose_down_command(spec, project, "images")

    assert containers[:4] == ["docker", "compose", "-p", project]
    assert "down" in containers
    assert "-v" not in containers
    assert "--remove-orphans" in containers
    assert volumes[:4] == ["docker", "compose", "-p", project]
    assert "-v" in volumes
    assert images[:4] == ["docker", "compose", "-p", project]
    assert images[-2:] == ["--rmi", "local"]
    for argv in (containers, volumes, images):
        assert not docker_assets.command_has_forbidden_prune(argv)
        assert "-f" in argv
        assert any("docker/postgresql/docker-compose.yml" in part for part in argv)


@pytest.mark.parametrize(
    ("platform", "service"),
    [
        ("lakesail", "lakesail-connect"),
        ("velox", "velox-connect"),
    ],
)
def test_compose_up_command_includes_wait_timeout_and_scoped_service(platform, service):
    spec = docker_assets.docker_platform_spec(platform)
    project = f"benchbox-uat-smoke-{platform}"
    argv = docker_assets.compose_up_command(spec, project, start_timeout_s=42)
    assert argv[:4] == ["docker", "compose", "-p", project]
    assert argv[-5:] == ["-d", "--wait", "--wait-timeout", "42", service]


def test_compose_project_name_sanitizes_and_bounds_length():
    name = docker_assets.compose_project_name(
        "UAT! 2026/05 storage constrained sweep with a very long config name",
        "pg.duckdb",
        "BenchBox_UAT",
    )
    assert len(name) <= 63
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name)
    assert name == docker_assets.compose_project_name(
        "UAT! 2026/05 storage constrained sweep with a very long config name",
        "pg.duckdb",
        "BenchBox_UAT",
    )


def test_matrix_docker_specs_are_project_scoped_for_managed_start():
    for platform in matrix.PLATFORM_GROUPS["docker"]:
        spec = docker_assets.docker_platform_spec(platform)
        assert spec.managed_start_allowed is True
        assert spec.fixed_container_names == ()
        docker_assets.validate_managed_start_allowed(spec, "fail")


def test_fixed_container_name_specs_are_rejected_for_managed_start():
    spec = docker_assets.DockerPlatformSpec(
        platform="fixed-name",
        compose_files=(Path("docker-compose.yml"),),
        fixed_container_names=("benchbox-fixed",),
    )
    with pytest.raises(docker_assets.DockerAssetError, match="fixed container_name"):
        docker_assets.validate_managed_start_allowed(spec, "fail")


def test_run_docker_command_dry_run_records_without_execution():
    result = docker_assets.run_docker_command(["docker", "compose", "ps"], dry_run=True)
    assert result.succeeded
    assert result.dry_run is True
    assert result.command == "docker compose ps"


def test_run_docker_command_refuses_global_prune():
    result = docker_assets.run_docker_command(["docker", "system", "prune"], dry_run=True)
    assert not result.succeeded
    assert "forbidden" in (result.error or "")


@pytest.mark.parametrize("platform", ["lakesail", "velox"])
def test_path_mirrored_compose_environment_points_at_benchmark_runs_dir(platform, tmp_path):
    spec = docker_assets.docker_platform_spec(platform)
    env = docker_assets.compose_environment(spec, benchmark_runs_dir=tmp_path / "runs")
    assert env == {"BENCHBOX_DATA_DIR": str(tmp_path / "runs")}


@pytest.mark.parametrize("platform", ["postgresql", "pg-duckdb", "pg-mooncake", "timescaledb"])
def test_local_managed_postgres_compose_password_matches_uat_argv(platform):
    spec = docker_assets.docker_platform_spec(platform)
    compose_text = "\n".join(path.read_text() for path in spec.compose_files)
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01)

    assert "POSTGRES_PASSWORD: benchbox" in compose_text
    assert "password=benchbox" in argv
