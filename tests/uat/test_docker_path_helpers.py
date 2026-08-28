"""Tests for separator-neutral managed-Docker path assertions."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.docker_path_helpers import (
    compose_path_ends_with,
    find_env_files_with_non_absolute_data_dir,
    find_nested_variable_defaults,
    find_non_flat_benchbox_data_dir_mounts,
)

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "compose_path",
    (
        "/workspace/BenchBox/docker/postgresql/docker-compose.yml",
        r"D:\a\BenchBox\BenchBox\docker\postgresql\docker-compose.yml",
    ),
)
def test_compose_path_ends_with_accepts_posix_and_windows_separators(compose_path: str) -> None:
    assert compose_path_ends_with(compose_path, "docker", "postgresql", "docker-compose.yml")


def test_compose_path_ends_with_compares_complete_components() -> None:
    compose_path = "/workspace/BenchBox/docker/not-postgresql/docker-compose.yml"

    assert not compose_path_ends_with(compose_path, "docker", "postgresql", "docker-compose.yml")


def test_find_nested_variable_defaults_flags_the_braced_nested_pattern(tmp_path: Path) -> None:
    """must_preserve: mocker cannot resolve ${VAR:-${OTHER}} -- it must be
    caught by lint rather than silently mounting a doubled, brace-mangled
    path (lakesail-compose-nested-variable-default)."""
    nested = tmp_path / "docker-compose.yml"
    nested.write_text('    - "${BENCHBOX_DATA_DIR:-${PWD}/benchmark_runs}:/data:ro"\n', encoding="utf-8")
    flat = tmp_path / "sibling" / "docker-compose.yml"
    flat.parent.mkdir()
    flat.write_text('    - "${BENCHBOX_DATA_DIR:-./benchmark_runs}:/data:ro"\n', encoding="utf-8")

    assert find_nested_variable_defaults(tmp_path) == [nested]


def test_find_nested_variable_defaults_flags_the_brace_less_nested_pattern(tmp_path: Path) -> None:
    """Reviewer-verified against mocker 0.7.2: ${VAR:-$OTHER/path} (inner
    substitution with no braces) is left unresolved identically to the
    braced form -- it must be caught too, not just ${VAR:-${OTHER}}."""
    nested = tmp_path / "docker-compose.yml"
    nested.write_text('    - "${BENCHBOX_DATA_DIR:-$PWD/benchmark_runs}:/data:ro"\n', encoding="utf-8")

    assert find_nested_variable_defaults(tmp_path) == [nested]


def test_find_nested_variable_defaults_does_not_flag_the_required_variable_form(tmp_path: Path) -> None:
    """${VAR:?message} is not a nested default -- it must not be flagged by
    this lint. It is a separately broken form under mocker (mocker 0.7.2 has
    no required-variable support: it leaves ${VAR:?...} completely
    unsubstituted, even when the variable IS set, instead of erroring or
    interpolating), which is why no compose file in this repo uses it -- but
    that is a different defect than a nested default and out of this
    helper's scope."""
    required = tmp_path / "docker-compose.yml"
    required.write_text('    - "${BENCHBOX_DATA_DIR:?required}:/data:ro"\n', encoding="utf-8")

    assert find_nested_variable_defaults(tmp_path) == []


def test_find_nested_variable_defaults_covers_yaml_extension(tmp_path: Path) -> None:
    """docker/postgres-extensions declares per-extension stacks as
    docker-compose.<extension>.yaml (.yaml, not .yml) -- the glob must catch
    both extensions or the lint silently skips real, registered UAT compose
    files."""
    nested = tmp_path / "docker-compose.pg-duckdb.yaml"
    nested.write_text('    - "${BENCHBOX_DATA_DIR:-${PWD}/x}:/data:ro"\n', encoding="utf-8")

    assert find_nested_variable_defaults(tmp_path) == [nested]


def test_no_repo_compose_file_has_a_nested_variable_default() -> None:
    """Repo-wide lint: no docker-compose*.yml/.yaml under docker/ may nest a
    substitution inside another variable's default -- mocker misparses it
    into a doubled, brace-mangled mount path."""
    bad = find_nested_variable_defaults(REPO_ROOT / "docker")

    assert not bad, [str(p) for p in bad]


def test_find_non_flat_benchbox_data_dir_mounts_flags_a_default(tmp_path: Path) -> None:
    """must_preserve: docker/lakesail/docker-compose.yml and
    docker/velox/docker-compose.yml must mount BENCHBOX_DATA_DIR with the
    bare ${BENCHBOX_DATA_DIR} form -- a flat *default* value
    (${BENCHBOX_DATA_DIR:-./benchmark_runs}) can only ever be relative here,
    which breaks the host/container path-mirroring contract
    (lakesail-compose-nested-variable-default)."""
    lakesail_dir = tmp_path / "lakesail"
    lakesail_dir.mkdir()
    (lakesail_dir / "docker-compose.yml").write_text(
        '    - "${BENCHBOX_DATA_DIR:-./benchmark_runs}:${BENCHBOX_DATA_DIR:-./benchmark_runs}:ro"\n',
        encoding="utf-8",
    )

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == [lakesail_dir / "docker-compose.yml"]


def test_find_non_flat_benchbox_data_dir_mounts_flags_the_required_variable_form(tmp_path: Path) -> None:
    """${BENCHBOX_DATA_DIR:?message} is unsubstituted (silently, even when
    set) by mocker 0.7.2 -- it must be flagged just like a default."""
    velox_dir = tmp_path / "velox"
    velox_dir.mkdir()
    (velox_dir / "docker-compose.yml").write_text(
        '    - "${BENCHBOX_DATA_DIR:?required}:${BENCHBOX_DATA_DIR:?required}:ro"\n',
        encoding="utf-8",
    )

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == [velox_dir / "docker-compose.yml"]


@pytest.mark.parametrize(
    "reference",
    (
        "${BENCHBOX_DATA_DIR-./x}",
        "${BENCHBOX_DATA_DIR?msg}",
        "${BENCHBOX_DATA_DIR:+/alt}",
        "${BENCHBOX_DATA_DIR+/alt}",
        "${BENCHBOX_DATA_DIR:=./x}",
    ),
)
def test_find_non_flat_benchbox_data_dir_mounts_flags_colon_less_posix_forms(tmp_path: Path, reference: str) -> None:
    """must_preserve: the colon is OPTIONAL in POSIX parameter expansion --
    ${VAR-x}, ${VAR?msg}, ${VAR:+alt}/${VAR+alt}, and ${VAR:=x} are all
    valid forms a colon-anchored regex misses entirely. ${VAR-./x} in
    particular is not theoretical: mocker 0.7.2 resolves it correctly (live-
    verified), so it reintroduces the exact relative-default defect this
    guard exists to catch, on both engines, silently."""
    compose_dir = tmp_path / "lakesail"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text(f'    - "{reference}:{reference}:ro"\n', encoding="utf-8")

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == [compose_dir / "docker-compose.yml"]


def test_find_non_flat_benchbox_data_dir_mounts_accepts_the_bare_form(tmp_path: Path) -> None:
    lakesail_dir = tmp_path / "lakesail"
    lakesail_dir.mkdir()
    (lakesail_dir / "docker-compose.yml").write_text(
        '    - "${BENCHBOX_DATA_DIR}:${BENCHBOX_DATA_DIR}:ro"\n', encoding="utf-8"
    )

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == []


def test_find_non_flat_benchbox_data_dir_mounts_ignores_a_longer_variable_name(tmp_path: Path) -> None:
    """${BENCHBOX_DATA_DIRECTORY} is a DIFFERENT variable that merely shares a
    prefix -- it must not be misread as a non-flat reference to
    BENCHBOX_DATA_DIR."""
    other_dir = tmp_path / "lakesail"
    other_dir.mkdir()
    (other_dir / "docker-compose.yml").write_text('    - "${BENCHBOX_DATA_DIRECTORY}:/data:ro"\n', encoding="utf-8")

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == []


def test_find_non_flat_benchbox_data_dir_mounts_covers_any_platform_not_just_lakesail_and_velox(
    tmp_path: Path,
) -> None:
    """Not scoped to an allowlist: a hypothetical third path-mirroring
    platform (e.g. docker/gluten) reintroducing the exact defect this guard
    exists to catch must be caught with zero extra wiring."""
    other_dir = tmp_path / "gluten"
    other_dir.mkdir()
    (other_dir / "docker-compose.yml").write_text(
        '    - "${BENCHBOX_DATA_DIR:-./benchmark_runs}:/data:ro"\n', encoding="utf-8"
    )

    assert find_non_flat_benchbox_data_dir_mounts(tmp_path) == [other_dir / "docker-compose.yml"]


def test_no_repo_lakesail_or_velox_compose_file_has_a_non_flat_benchbox_data_dir_mount() -> None:
    """Repo-wide lint: no compose file under docker/ may reference
    BENCHBOX_DATA_DIR with anything but the bare ${BENCHBOX_DATA_DIR} form --
    no default, no required-variable modifier, colon or colon-less."""
    bad = find_non_flat_benchbox_data_dir_mounts(REPO_ROOT / "docker")

    assert not bad, [str(p) for p in bad]


def test_find_env_files_with_non_absolute_data_dir_flags_a_relative_value(tmp_path: Path) -> None:
    """must_preserve: a checked-in docker/<stack>/.env with a relative
    BENCHBOX_DATA_DIR fallback was tried and reverted
    (lakesail-compose-nested-variable-default) -- it must never reappear."""
    stack_dir = tmp_path / "lakesail"
    stack_dir.mkdir()
    (stack_dir / ".env").write_text("BENCHBOX_DATA_DIR=./benchmark_runs\n", encoding="utf-8")

    assert find_env_files_with_non_absolute_data_dir(tmp_path) == [stack_dir / ".env"]


def test_find_env_files_with_non_absolute_data_dir_flags_an_empty_value(tmp_path: Path) -> None:
    """must_preserve: BENCHBOX_DATA_DIR= (empty) resolves to the same
    silent-empty-mount defect as an unset variable -- arguably worse than a
    relative value, since it is easy to miss in review. Must be flagged,
    not skipped as falsy."""
    stack_dir = tmp_path / "velox"
    stack_dir.mkdir()
    (stack_dir / ".env").write_text("BENCHBOX_DATA_DIR=\n", encoding="utf-8")

    assert find_env_files_with_non_absolute_data_dir(tmp_path) == [stack_dir / ".env"]


def test_find_env_files_with_non_absolute_data_dir_accepts_an_absolute_value(tmp_path: Path) -> None:
    stack_dir = tmp_path / "lakesail"
    stack_dir.mkdir()
    (stack_dir / ".env").write_text("BENCHBOX_DATA_DIR=/mnt/benchbox-data\n", encoding="utf-8")

    assert find_env_files_with_non_absolute_data_dir(tmp_path) == []


def test_find_env_files_with_non_absolute_data_dir_ignores_unrelated_env_entries(tmp_path: Path) -> None:
    stack_dir = tmp_path / "velox"
    stack_dir.mkdir()
    (stack_dir / ".env").write_text("VELOX_IMAGE_TAG=dev\n", encoding="utf-8")

    assert find_env_files_with_non_absolute_data_dir(tmp_path) == []


@pytest.mark.parametrize("filename", (".env.local", ".env.lakesail", "compose.env"))
def test_find_env_files_with_non_absolute_data_dir_covers_non_dotenv_literal_filenames(
    tmp_path: Path, filename: str
) -> None:
    """must_preserve: `.env.local`, `.env.lakesail`, and `compose.env` are all
    real dotenv filenames wirable via `docker compose --env-file` -- a check
    that only globs the literal name `.env` misses all of them."""
    stack_dir = tmp_path / "lakesail"
    stack_dir.mkdir()
    (stack_dir / filename).write_text("BENCHBOX_DATA_DIR=./benchmark_runs\n", encoding="utf-8")

    assert find_env_files_with_non_absolute_data_dir(tmp_path) == [stack_dir / filename]


def test_no_repo_env_file_under_docker_sets_a_non_absolute_benchbox_data_dir() -> None:
    """Repo-wide lint: no dotenv-style file under docker/ may set
    BENCHBOX_DATA_DIR to a relative or empty value -- docker/lakesail/docker-
    compose.yml and docker/velox/docker-compose.yml mount it at the SAME
    absolute path on host and in container."""
    bad = find_env_files_with_non_absolute_data_dir(REPO_ROOT / "docker")

    assert not bad, [str(p) for p in bad]
