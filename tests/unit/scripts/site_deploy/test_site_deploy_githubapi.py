from __future__ import annotations

import pytest

from scripts.site_deploy import deployments
from scripts.site_deploy.githubapi import MAX_PAGES, ApiError
from tests.unit.scripts.site_deploy.site_deploy_fakes import FakeGitHub

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _rows(count: int) -> list[dict[str, object]]:
    return [{"id": index, "created_at": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}Z"} for index in range(count)]


def test_get_list_follows_every_page() -> None:
    api = FakeGitHub(deployments=_rows(250))
    assert len(api.client().get_list("deployments")) == 250


def test_get_list_errors_instead_of_truncating_past_the_page_bound() -> None:
    api = FakeGitHub(deployments=_rows(MAX_PAGES * 100 + 1))
    with pytest.raises(ApiError, match="truncated"):
        api.client().get_list("deployments")


def test_get_first_returns_exactly_the_requested_window() -> None:
    api = FakeGitHub(deployments=_rows(150))
    assert len(api.client().get_first("deployments", 100)) == 100
    assert len(api.client().get_first("deployments", 10)) == 10
    assert len(FakeGitHub(deployments=_rows(3)).client().get_first("deployments", 100)) == 3


def test_deployment_scan_window_is_one_hundred_everywhere() -> None:
    api = FakeGitHub(deployments=_rows(150))
    assert deployments.DEPLOYMENT_SCAN_LIMIT == 100
    assert len(deployments.scan_deployments(api.client())) == 100
