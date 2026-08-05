"""Tests for separator-neutral managed-Docker path assertions."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.docker_path_helpers import compose_path_ends_with, find_nested_variable_defaults

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


def test_find_nested_variable_defaults_flags_the_nested_pattern(tmp_path: Path) -> None:
    """must_preserve: mocker cannot resolve ${VAR:-${OTHER}} -- it must be
    caught by lint rather than silently mounting a doubled, brace-mangled
    path (lakesail-compose-nested-variable-default)."""
    nested = tmp_path / "docker-compose.yml"
    nested.write_text('    - "${BENCHBOX_DATA_DIR:-${PWD}/benchmark_runs}:/data:ro"\n', encoding="utf-8")
    flat = tmp_path / "sibling" / "docker-compose.yml"
    flat.parent.mkdir()
    flat.write_text('    - "${BENCHBOX_DATA_DIR:?required}:/data:ro"\n', encoding="utf-8")

    assert find_nested_variable_defaults(tmp_path) == [nested]


def test_no_repo_compose_file_has_a_nested_variable_default() -> None:
    """Repo-wide lint: no docker-compose*.yml under docker/ may nest a
    ${...} substitution inside another variable's default -- mocker
    misparses it into a doubled, brace-mangled mount path."""
    bad = find_nested_variable_defaults(REPO_ROOT / "docker")

    assert not bad, [str(p) for p in bad]
