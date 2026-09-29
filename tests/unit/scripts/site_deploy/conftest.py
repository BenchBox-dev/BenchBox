"""Fixtures for site-deploy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.scripts.site_deploy.helpers import git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "develop")
    return root
