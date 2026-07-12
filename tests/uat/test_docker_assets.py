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
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01, local_managed_platform=True)

    assert "POSTGRES_PASSWORD: benchbox" in compose_text
    assert "password=benchbox" in argv


def test_local_managed_clickhouse_compose_password_matches_uat_argv():
    spec = docker_assets.docker_platform_spec("clickhouse-server")
    compose_text = "\n".join(path.read_text() for path in spec.compose_files)
    argv = matrix.benchbox_run_argv("clickhouse-server", "tpch", 0.01, local_managed_platform=True)

    assert "CLICKHOUSE_DB: default" in compose_text
    assert "CLICKHOUSE_PASSWORD: benchbox" in compose_text
    assert 'CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"' in compose_text
    assert "init-default-database.sql:/docker-entrypoint-initdb.d/init-default-database.sql:ro" in compose_text
    assert "password=benchbox" in argv


# --------------------------------------------------------------------------
# resolve_container_cli() -- uat-container-engine-routing w1
#
# The autouse `isolate_container_cli_resolution` fixture (tests/uat/conftest.py)
# defaults every test to a clean cache + BENCHBOX_CONTAINER_CLI=docker + a
# stubbed `_which_container_cli` that reports everything present. These tests
# override that within their own body to exercise the real resolution logic.
# --------------------------------------------------------------------------


def test_resolve_container_cli_env_override_wins_over_platform_default(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "podman")
    monkeypatch.setattr(docker_assets, "_current_platform", lambda: "darwin")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/usr/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    try:
        assert docker_assets.resolve_container_cli() == "podman"
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_resolve_container_cli_darwin_prefers_mocker_when_present(monkeypatch):
    monkeypatch.delenv(docker_assets.CONTAINER_CLI_ENV_VAR, raising=False)
    monkeypatch.setattr(docker_assets, "_current_platform", lambda: "darwin")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    try:
        assert docker_assets.resolve_container_cli() == "mocker"
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_resolve_container_cli_darwin_falls_back_to_docker_without_mocker(monkeypatch):
    monkeypatch.delenv(docker_assets.CONTAINER_CLI_ENV_VAR, raising=False)
    monkeypatch.setattr(docker_assets, "_current_platform", lambda: "darwin")
    monkeypatch.setattr(
        docker_assets, "_which_container_cli", lambda cli: None if cli == "mocker" else "/usr/bin/docker"
    )
    docker_assets.resolve_container_cli.cache_clear()
    try:
        assert docker_assets.resolve_container_cli() == "docker"
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_resolve_container_cli_non_darwin_never_probes_mocker(monkeypatch):
    """must_preserve: a docker-only Linux host stays byte-identical -- no mocker `which()` probe off darwin."""
    monkeypatch.delenv(docker_assets.CONTAINER_CLI_ENV_VAR, raising=False)
    monkeypatch.setattr(docker_assets, "_current_platform", lambda: "linux")
    probed: list[str] = []

    def fake_which(cli):
        probed.append(cli)
        return "/usr/bin/docker" if cli == "docker" else None

    monkeypatch.setattr(docker_assets, "_which_container_cli", fake_which)
    docker_assets.resolve_container_cli.cache_clear()
    try:
        assert docker_assets.resolve_container_cli() == "docker"
        assert probed == ["docker"]
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_resolve_container_cli_hard_errors_when_resolved_binary_missing(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "ghost-cli")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: None)
    docker_assets.resolve_container_cli.cache_clear()
    try:
        with pytest.raises(docker_assets.DockerAssetError, match="ghost-cli"):
            docker_assets.resolve_container_cli()
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_resolve_container_cli_is_memoized_across_calls(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "docker")
    calls: list[str] = []

    def fake_which(cli):
        calls.append(cli)
        return "/usr/bin/docker"

    monkeypatch.setattr(docker_assets, "_which_container_cli", fake_which)
    docker_assets.resolve_container_cli.cache_clear()
    try:
        assert docker_assets.resolve_container_cli() == "docker"
        assert docker_assets.resolve_container_cli() == "docker"
        assert calls == ["docker"]  # resolved once, memoized on the second call
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_compose_commands_use_the_resolved_engine_binary(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    try:
        spec = docker_assets.docker_platform_spec("postgresql")
        argv = docker_assets.compose_up_command(spec, "benchbox-uat-smoke-postgresql")
        assert argv[0] == "mocker"
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_command_has_forbidden_prune_matches_regardless_of_resolved_engine():
    """must_preserve: the forbidden-prune guard applies to every engine, not just a literal `docker` argv[0]."""
    assert docker_assets.command_has_forbidden_prune(["mocker", "system", "prune"])
    assert docker_assets.command_has_forbidden_prune(["mocker", "volume", "prune"])
    assert docker_assets.command_has_forbidden_prune(["docker", "image", "prune", "-f"])
    assert not docker_assets.command_has_forbidden_prune(["mocker", "compose", "up"])
    assert not docker_assets.command_has_forbidden_prune(["docker", "volume", "ls"])


# --------------------------------------------------------------------------
# sweep_leaked_mocker_volumes() -- uat-container-engine-routing w3
# --------------------------------------------------------------------------


def test_sweep_leaked_mocker_volumes_removes_project_scoped_volumes_only(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        argv_tuple = tuple(argv)
        calls.append(argv_tuple)
        if argv_tuple == ("mocker", "volume", "ls"):
            return docker_assets.DockerCommandResult(
                argv_tuple,
                0,
                "DRIVER   VOLUME NAME\n"
                "local    benchbox-uat-smoke-postgresql_pgdata\n"
                "local    benchbox-uat-smoke-postgresql_other\n"
                "local    unrelated-project_data\n",
                "",
            )
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("benchbox-uat-smoke-postgresql", runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert set(removed) == {"benchbox-uat-smoke-postgresql_pgdata", "benchbox-uat-smoke-postgresql_other"}
    rm_calls = [c for c in calls if c[:2] == ("mocker", "volume") and c[2] == "rm"]
    assert ("mocker", "volume", "rm", "benchbox-uat-smoke-postgresql_pgdata") in rm_calls
    assert ("mocker", "volume", "rm", "benchbox-uat-smoke-postgresql_other") in rm_calls
    assert not any("unrelated-project_data" in c for c in rm_calls)


def test_sweep_leaked_mocker_volumes_is_noop_on_docker_engine(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "docker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/usr/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        calls.append(tuple(argv))
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("benchbox-uat-smoke-postgresql", runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert removed == ()
    assert calls == []  # docker already removes named volumes on `down -v`; no probe needed


def test_sweep_leaked_mocker_volumes_is_noop_on_dry_run(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        calls.append(tuple(argv))
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "", dry_run=True)

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes(
            "benchbox-uat-smoke-postgresql", runner=fake_runner, dry_run=True
        )
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert removed == ()
    assert calls == []


def test_sweep_leaked_mocker_volumes_swallows_individual_removal_failure(monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()

    def fake_runner(argv, **kwargs):
        argv_tuple = tuple(argv)
        if argv_tuple == ("mocker", "volume", "ls"):
            return docker_assets.DockerCommandResult(
                argv_tuple, 0, "local    benchbox-uat-demo_pgdata\nlocal    benchbox-uat-demo_cache\n", ""
            )
        if argv_tuple == ("mocker", "volume", "rm", "benchbox-uat-demo_pgdata"):
            return docker_assets.DockerCommandResult(argv_tuple, 1, "", "boom", error="stale reference")
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("benchbox-uat-demo", runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    # One volume's rm failure does not abort the rest of the sweep.
    assert removed == ("benchbox-uat-demo_cache",)
