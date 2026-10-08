from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def aws_adapter_dependency_mocks():

    with ExitStack() as stack:
        stack.enter_context(patch("benchbox.platforms.aws.athena_spark_adapter.BOTO3_AVAILABLE", True))
        stack.enter_context(patch("benchbox.platforms.aws.athena_spark_adapter.boto3", MagicMock()))
        stack.enter_context(patch("benchbox.platforms.aws.emr_serverless_adapter.BOTO3_AVAILABLE", True))
        stack.enter_context(patch("benchbox.platforms.aws.emr_serverless_adapter.boto3", MagicMock()))
        stack.enter_context(patch("benchbox.platforms.aws.glue_adapter.BOTO3_AVAILABLE", True))
        stack.enter_context(patch("benchbox.platforms.aws.glue_adapter.boto3", MagicMock()))
        yield


@pytest.fixture(autouse=True)
def _auto_patch_aws_adapter_dependencies(aws_adapter_dependency_mocks):
    yield aws_adapter_dependency_mocks
