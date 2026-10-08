from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def gcp_adapter_dependency_mocks():

    with ExitStack() as stack:
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_adapter.GOOGLE_CLOUD_AVAILABLE", True))
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_adapter.dataproc_v1", MagicMock()))
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_adapter.storage", MagicMock()))
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_serverless_adapter.GOOGLE_CLOUD_AVAILABLE", True))
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_serverless_adapter.dataproc_v1", MagicMock()))
        stack.enter_context(patch("benchbox.platforms.gcp.dataproc_serverless_adapter.storage", MagicMock()))
        yield


@pytest.fixture(autouse=True)
def _auto_patch_gcp_adapter_dependencies(gcp_adapter_dependency_mocks):
    yield gcp_adapter_dependency_mocks
