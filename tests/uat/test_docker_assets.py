"""Fast-test coverage for UAT Docker compose lifecycle helpers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.uat import docker_assets, matrix
from tests.uat.docker_path_helpers import compose_path_ends_with

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
        assert any(compose_path_ends_with(part, "docker", "postgresql", "docker-compose.yml") for part in argv)


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


def test_compose_pull_command_uses_ignore_buildable_and_is_project_scoped():
    spec = docker_assets.docker_platform_spec("postgresql")
    project = "benchbox-uat-smoke-postgresql"
    argv = docker_assets.compose_pull_command(spec, project)
    assert argv[:4] == ["docker", "compose", "-p", project]
    assert "pull" in argv
    assert "--ignore-buildable" in argv
    assert not docker_assets.command_has_forbidden_prune(argv)


def test_compose_pull_command_scopes_to_declared_service():
    spec = docker_assets.docker_platform_spec("lakesail")
    project = "benchbox-uat-smoke-lakesail"
    argv = docker_assets.compose_pull_command(spec, project)
    assert argv[-1] == "lakesail-connect"


def test_compose_build_command_is_project_scoped():
    spec = docker_assets.docker_platform_spec("lakesail")
    project = "benchbox-uat-smoke-lakesail"
    argv = docker_assets.compose_build_command(spec, project)
    assert argv[:4] == ["docker", "compose", "-p", project]
    assert "build" in argv
    assert argv[-1] == "lakesail-connect"


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


@pytest.mark.parametrize("platform", ["lakesail", "velox"])
@pytest.mark.parametrize(
    "relative_dir",
    (
        Path("relative_runs"),
        Path("./relative_runs"),
        Path("../sibling_runs"),
        "relative_runs",
    ),
)
def test_compose_environment_raises_for_relative_benchmark_runs_dir(platform, relative_dir):
    """must_preserve: compose_environment() is the single choke point every
    UAT-managed bring-up path funnels through (tests/uat/phases/execute.py's
    up AND down, scripts/uat-bring-up/uat_bring_up.py) -- the Makefile's
    require_data_dir_if_mounted only guards `make test-docker-up-*`
    directly, so a relative --benchmark-runs-dir / benchmark_runs_dir_template
    reached compose unguarded through those Python entry points until this
    check moved here. lakesail/velox mount BENCHBOX_DATA_DIR at the SAME
    absolute path on host and in container, so a relative value silently
    breaks every file load."""
    spec = docker_assets.docker_platform_spec(platform)

    with pytest.raises(docker_assets.DockerAssetError, match="absolute"):
        docker_assets.compose_environment(spec, benchmark_runs_dir=relative_dir)


@pytest.mark.parametrize("platform", ["postgresql", "clickhouse-server", "questdb"])
def test_compose_environment_ignores_relative_dir_for_non_path_mirroring_platforms(platform):
    """Only lakesail/velox reference BENCHBOX_DATA_DIR at all -- a relative
    benchmark_runs_dir must not raise for any other platform, since
    compose_environment() returns {} for them regardless."""
    spec = docker_assets.docker_platform_spec(platform)

    assert docker_assets.compose_environment(spec, benchmark_runs_dir=Path("relative_runs")) == {}


@pytest.mark.parametrize("platform", ["lakesail", "velox"])
def test_compose_environment_error_names_platform_and_the_offending_value(platform):
    spec = docker_assets.docker_platform_spec(platform)

    with pytest.raises(docker_assets.DockerAssetError) as excinfo:
        docker_assets.compose_environment(spec, benchmark_runs_dir="relative_runs")

    assert platform in str(excinfo.value)
    assert "relative_runs" in str(excinfo.value)


@pytest.mark.parametrize("platform", ["lakesail", "velox"])
def test_compose_environment_raises_for_missing_benchmark_runs_dir(platform):
    """must_preserve: a `None` benchmark_runs_dir must NOT fall through to
    compose_environment() returning `{}` for lakesail/velox the way it does
    for every other platform. run_docker_command() fills an empty/omitted
    `env` with `os.environ.copy()` (tests/uat/docker_assets.py), so `{}`
    here would let the child compose process silently inherit whatever
    ambient BENCHBOX_DATA_DIR happens to be set (or unset) in the caller's
    shell -- exactly the same silent-no-mount failure mode the relative-path
    guard closes, just reached by omitting the argument instead of passing
    a relative one."""
    spec = docker_assets.docker_platform_spec(platform)

    with pytest.raises(docker_assets.DockerAssetError, match="benchmark_runs_dir"):
        docker_assets.compose_environment(spec, benchmark_runs_dir=None)

    with pytest.raises(docker_assets.DockerAssetError):
        docker_assets.compose_environment(spec)


@pytest.mark.parametrize("platform", ["postgresql", "clickhouse-server", "questdb"])
def test_compose_environment_returns_empty_for_missing_dir_on_non_path_mirroring_platforms(platform):
    """Only lakesail/velox reference BENCHBOX_DATA_DIR at all -- a missing
    benchmark_runs_dir must not raise for any other platform."""
    spec = docker_assets.docker_platform_spec(platform)

    assert docker_assets.compose_environment(spec, benchmark_runs_dir=None) == {}
    assert docker_assets.compose_environment(spec) == {}


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


def test_command_has_forbidden_prune_matches_compose_engines_but_exempts_apple_container():
    """The forbidden-prune guard covers every compose engine argv[0] (docker,
    mocker, an override) -- but NOT the Apple-native `container` CLI, whose
    max-mode prunes are a deliberate documented operator action guarded by
    container_cleanup._is_forbidden instead. Blocking those here broke
    `make uat-docker-cleanup ENGINE=container MODE=max APPLY=1` outright."""
    assert docker_assets.command_has_forbidden_prune(["mocker", "system", "prune"])
    assert docker_assets.command_has_forbidden_prune(["mocker", "volume", "prune"])
    assert docker_assets.command_has_forbidden_prune(["docker", "image", "prune", "-f"])
    assert docker_assets.command_has_forbidden_prune(["podman", "volume", "prune"])
    assert docker_assets.command_has_forbidden_prune(["/usr/local/bin/docker", "system", "prune"])
    assert not docker_assets.command_has_forbidden_prune(["mocker", "compose", "up"])
    assert not docker_assets.command_has_forbidden_prune(["docker", "volume", "ls"])
    # Apple-native container CLI: max-mode prunes must pass through.
    assert not docker_assets.command_has_forbidden_prune(["container", "volume", "prune"])
    assert not docker_assets.command_has_forbidden_prune(["container", "network", "prune"])
    assert not docker_assets.command_has_forbidden_prune(["container", "builder", "delete", "--force"])


def test_command_has_forbidden_prune_is_robust_to_repeated_tokens():
    # Pairwise scan, not index arithmetic: a repeated token earlier in argv
    # must not confuse adjacency detection.
    assert docker_assets.command_has_forbidden_prune(["docker", "volume", "volume", "prune"])
    assert not docker_assets.command_has_forbidden_prune(["docker", "prune", "volume", "ls"])


# --------------------------------------------------------------------------
# sweep_leaked_mocker_volumes() -- uat-container-engine-routing w3
#
# Exact-name matching against compose-declared volume keys. mocker 0.5.4
# joins <project>-<key> with a HYPHEN (live-verified: scratch project
# `sepcheck` + key `checkvol` -> `sepcheck-checkvol`); docker compose joins
# with `_`. Both joiners are matched exactly; a name-prefix scan is never
# used because it would also match a sibling project (`p` vs `p-ha`).
# --------------------------------------------------------------------------


def _spec_with_volume_keys(tmp_path: Path, keys: tuple[str, ...]) -> docker_assets.DockerPlatformSpec:
    compose = tmp_path / "docker-compose.yml"
    volume_lines = "\n".join(f"  {key}:" for key in keys)
    compose.write_text(f"services:\n  s:\n    image: alpine:3.19\nvolumes:\n{volume_lines}\n", encoding="utf-8")
    return docker_assets.DockerPlatformSpec(platform="scratch", compose_files=(compose,))


def test_compose_declared_volume_names_reads_real_platform_spec():
    spec = docker_assets.docker_platform_spec("postgresql")
    assert docker_assets.compose_declared_volume_names(spec) == ("postgresql18-data",)
    assert "benchbox-uat-manual-postgresql-postgresql18-data" in docker_assets.expected_mocker_volume_names(
        "benchbox-uat-manual-postgresql", spec
    )


def test_sweep_leaked_mocker_volumes_removes_exact_declared_names_only(tmp_path, monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    spec = _spec_with_volume_keys(tmp_path, ("pgdata", "other"))
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        argv_tuple = tuple(argv)
        calls.append(argv_tuple)
        if argv_tuple == ("mocker", "volume", "ls"):
            return docker_assets.DockerCommandResult(
                argv_tuple,
                0,
                "DRIVER   VOLUME NAME\n"
                "local    p-pgdata\n"  # mocker joiner
                "local    p_other\n"  # docker-compose joiner (future-proofing)
                "local    unrelated-project_data\n",
                "",
            )
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("p", spec, runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert set(removed) == {"p-pgdata", "p_other"}
    rm_calls = [c for c in calls if c[:3] == ("mocker", "volume", "rm")]
    assert ("mocker", "volume", "rm", "p-pgdata") in rm_calls
    assert ("mocker", "volume", "rm", "p_other") in rm_calls
    assert not any("unrelated-project_data" in c for c in rm_calls)


def test_sweep_leaked_mocker_volumes_never_touches_hyphen_sibling_project(tmp_path, monkeypatch):
    """REQUIRED-2 regression: a sweep of project `p` must NOT match volumes
    of sibling project `p-ha` -- under mocker's `-` joiner, `p-ha-data` and
    `p-ha_data` both start with `p-`, so any prefix scan would delete a
    sibling's data. Exact compose-declared-name matching cannot."""
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    spec = _spec_with_volume_keys(tmp_path, ("data",))
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        argv_tuple = tuple(argv)
        calls.append(argv_tuple)
        if argv_tuple == ("mocker", "volume", "ls"):
            return docker_assets.DockerCommandResult(
                argv_tuple,
                0,
                "DRIVER   VOLUME NAME\n"
                "local    p-data\n"  # project p's own volume
                "local    p-ha_data\n"  # sibling project p-ha (docker joiner)
                "local    p-ha-data\n",  # sibling project p-ha (mocker joiner)
                "",
            )
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("p", spec, runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert removed == ("p-data",)
    rm_calls = [c for c in calls if c[:3] == ("mocker", "volume", "rm")]
    assert rm_calls == [("mocker", "volume", "rm", "p-data")]
    assert not any("p-ha" in " ".join(c) for c in rm_calls)


def test_sweep_leaked_mocker_volumes_is_noop_on_docker_engine(tmp_path, monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "docker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/usr/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    spec = _spec_with_volume_keys(tmp_path, ("pgdata",))
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        calls.append(tuple(argv))
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("benchbox-uat-smoke-postgresql", spec, runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert removed == ()
    assert calls == []  # docker already removes named volumes on `down -v`; no probe needed


def test_sweep_leaked_mocker_volumes_is_noop_on_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    spec = _spec_with_volume_keys(tmp_path, ("pgdata",))
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        calls.append(tuple(argv))
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "", dry_run=True)

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes(
            "benchbox-uat-smoke-postgresql", spec, runner=fake_runner, dry_run=True
        )
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    assert removed == ()
    assert calls == []


def test_sweep_leaked_mocker_volumes_swallows_individual_removal_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    spec = _spec_with_volume_keys(tmp_path, ("pgdata", "cache"))

    def fake_runner(argv, **kwargs):
        argv_tuple = tuple(argv)
        if argv_tuple == ("mocker", "volume", "ls"):
            return docker_assets.DockerCommandResult(
                argv_tuple, 0, "local    benchbox-uat-demo-pgdata\nlocal    benchbox-uat-demo-cache\n", ""
            )
        if argv_tuple == ("mocker", "volume", "rm", "benchbox-uat-demo-pgdata"):
            return docker_assets.DockerCommandResult(argv_tuple, 1, "", "boom", error="stale reference")
        return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

    try:
        removed = docker_assets.sweep_leaked_mocker_volumes("benchbox-uat-demo", spec, runner=fake_runner)
    finally:
        docker_assets.resolve_container_cli.cache_clear()

    # One volume's rm failure does not abort the rest of the sweep.
    assert removed == ("benchbox-uat-demo-cache",)


@pytest.mark.parametrize(
    ("platform", "expected_service_names"),
    [
        # The validated mocker failure is specifically databend's `minio`
        # service exiting under mocker (AGENTS.md) -- `minio` is the
        # load-bearing token in that guidance, not just "three services".
        ("databend", frozenset({"minio", "minio-setup", "databend"})),
        # all-in-one FE+BE image -- single container, unaffected by mocker.
        ("doris", frozenset({"doris"})),
        # all-in-one image -- single container, unaffected by mocker.
        ("starrocks", frozenset({"starrocks"})),
    ],
)
def test_multi_service_platform_service_names_match_documented_guidance(platform, expected_service_names):
    """Pin the compose service *identities* AGENTS.md and uat-framework.md cite.

    Guards against the mocker multi-service guidance drifting out of sync
    with the compose files it describes, the way it silently did once before
    (commit fd29aa77c0 compressed the specific databend/minio caveat into a
    vague, unverifiable claim). A count-only assertion would stay green even
    if databend's `minio` service were renamed to something else, so this
    pins the actual service names, not just how many there are.
    """
    spec = docker_assets.docker_platform_spec(platform)
    service_names: set[str] = set()
    for compose_file in spec.compose_files:
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        service_names.update(data.get("services", {}).keys())
    assert service_names == expected_service_names


# ---------------------------------------------------------------------------
# compose_declared_memory_limits: static compose-file parsing for the
# free-memory gate's log decoration.
# ---------------------------------------------------------------------------


def _spec_for_compose(tmp_path: Path, body: str) -> docker_assets.DockerPlatformSpec:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(body, encoding="utf-8")
    return docker_assets.DockerPlatformSpec(platform="fake", compose_files=(compose_file,))


def test_compose_declared_memory_limits_reads_mem_limit(tmp_path: Path):
    spec = _spec_for_compose(tmp_path, "services:\n  db:\n    mem_limit: 4g\n")
    assert docker_assets.compose_declared_memory_limits(spec) == {"db": "4g"}


def test_compose_declared_memory_limits_reads_deploy_resources_limits(tmp_path: Path):
    spec = _spec_for_compose(
        tmp_path,
        "services:\n  db:\n    deploy:\n      resources:\n        limits:\n          memory: 2G\n",
    )
    assert docker_assets.compose_declared_memory_limits(spec) == {"db": "2G"}


def test_compose_declared_memory_limits_empty_when_nothing_declared(tmp_path: Path):
    spec = _spec_for_compose(tmp_path, "services:\n  db:\n    image: postgres:16\n")
    assert docker_assets.compose_declared_memory_limits(spec) == {}


@pytest.mark.parametrize(
    "body",
    [
        # `limits:` present with NO children -> yaml gives an explicit None.
        # `.get("limits", {})` returns that None (a default applies only when
        # the key is ABSENT), and `None.get("memory")` raises AttributeError.
        "services:\n  db:\n    deploy:\n      resources:\n        limits:\n",
        # Same trap one level up.
        "services:\n  db:\n    deploy:\n      resources:\n",
        "services:\n  db:\n    deploy:\n",
        # Non-mapping values where a mapping is expected.
        "services:\n  db:\n    deploy:\n      resources:\n        limits: 2G\n",
        "services:\n  db:\n    deploy:\n      resources:\n        limits:\n          - memory\n",
    ],
)
def test_compose_declared_memory_limits_survives_degenerate_limits_blocks(tmp_path: Path, body: str):
    """Regression: this helper only decorates a log line, but it ran inside a
    `try` catching just (OSError, yaml.YAMLError) and its caller
    (`execute.py::_describe_platform_vm_request`) caught only
    DockerAssetError -- so an AttributeError here propagated out of
    run_execute and aborted an entire sweep. No compose file in the repo
    triggers it today; one `limits:` with no children would have.
    """
    spec = _spec_for_compose(tmp_path, body)
    assert docker_assets.compose_declared_memory_limits(spec) == {}


def test_compose_declared_memory_limits_ignores_unparseable_file(tmp_path: Path):
    spec = _spec_for_compose(tmp_path, "services: [oops\n")
    assert docker_assets.compose_declared_memory_limits(spec) == {}


# ---------------------------------------------------------------------------
# compose ps readiness parsing.
# ---------------------------------------------------------------------------


def test_compose_ps_command_passes_all_so_stopped_containers_are_listed():
    """Without `-a`, a container that started and then died is simply absent
    from the output and the readiness check passes on an empty table -- the
    exact state the check exists to detect."""
    spec = docker_assets.docker_platform_spec("postgresql")
    argv = docker_assets.compose_ps_command(spec, "benchbox-uat-smoke-postgresql")
    assert argv[-2:] == ["ps", "-a"]
    assert "-p" in argv and "benchbox-uat-smoke-postgresql" in argv


@pytest.mark.parametrize(
    ("status", "why"),
    [
        ("Exited (137) 5 seconds ago", "compose v2 dead container -- the 2026-08-04 CedarDB state"),
        ("Exit 1", "compose v1 spelling of the same state"),
        ("Restarting (1) 3 seconds ago", "crash-looping"),
        ("Created", "never started"),
        ("Dead", "engine could not clean it up"),
        ("Paused", "SIGSTOPped; the port accepts nothing"),
        ("Up 30 seconds (unhealthy)", "the engine's own healthcheck says no"),
    ],
)
def test_compose_ps_unhealthy_services_flags_every_not_ready_state(status: str, why: str):
    stdout = f"NAME      IMAGE     COMMAND   STATUS\nsvc       img       cmd       {status}\n"
    assert docker_assets.compose_ps_unhealthy_services(stdout) == ("svc",), why


@pytest.mark.parametrize("status", ["Up 5 seconds", "Up 2 hours (healthy)", "Up About a minute"])
def test_compose_ps_unhealthy_services_passes_a_serving_container(status: str):
    stdout = f"NAME      IMAGE     COMMAND   STATUS\nsvc       img       cmd       {status}\n"
    assert docker_assets.compose_ps_unhealthy_services(stdout) == ()


def test_compose_ps_unhealthy_services_ignores_state_words_in_the_name_column():
    """A container NAME containing a state word must not false-positive; only
    the status/command columns are considered."""
    stdout = "NAME               IMAGE     COMMAND   STATUS\nbenchbox-Created   img       cmd       Up 5 seconds\n"
    assert docker_assets.compose_ps_unhealthy_services(stdout) == ()


def test_compose_ps_unhealthy_services_reports_every_bad_row():
    stdout = (
        "NAME      IMAGE     COMMAND   STATUS\n"
        "alpha     img       cmd       Up 5 seconds\n"
        "beta      img       cmd       Exited (1) 2 seconds ago\n"
        "gamma     img       cmd       Restarting (1) 1 second ago\n"
    )
    assert docker_assets.compose_ps_unhealthy_services(stdout) == ("beta", "gamma")


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "NAME      IMAGE     COMMAND   STATUS\n",
        "Name   Command   State   Ports\n--------------------------------\n",
        "\n\n",
    ],
)
def test_compose_ps_service_rows_is_empty_for_no_service_rows(stdout: str):
    """Header-only and blank output carry no services. The caller treats this
    as NOT ready: `ps -a` finding nothing for a project that was just `up`'d
    means the containers are gone, which is not a state to run a whole cell
    list against."""
    assert docker_assets.compose_ps_service_rows(stdout) == ()


def test_compose_ps_service_rows_keeps_real_rows():
    stdout = "NAME      IMAGE     COMMAND   STATUS\nsvc       img       cmd       Up 5 seconds\n"
    assert len(docker_assets.compose_ps_service_rows(stdout)) == 1
