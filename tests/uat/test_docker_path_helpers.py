"""Tests for separator-neutral managed-Docker path assertions."""

from __future__ import annotations

import pytest

from tests.uat.docker_path_helpers import compose_path_ends_with

pytestmark = pytest.mark.fast


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
