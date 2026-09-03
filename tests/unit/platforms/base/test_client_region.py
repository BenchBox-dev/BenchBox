"""Unit tests for client region and cloud discovery."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.base.client_region import (
    discover_client_region,
    reset_client_region_cache,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_client_region_cache()
    yield
    reset_client_region_cache()


def test_aws_imds_discovery() -> None:
    token_response = MagicMock()
    token_response.read.return_value = b"test-aws-token"
    token_response.__enter__.return_value = token_response

    doc_response = MagicMock()
    doc_response.read.return_value = json.dumps({"region": "us-west-2"}).encode("utf-8")
    doc_response.__enter__.return_value = doc_response

    def fake_urlopen(req, timeout=0.2):
        if "latest/api/token" in req.full_url:
            assert req.get_method() == "PUT"
            assert req.headers.get("X-aws-ec2-metadata-token-ttl-seconds") == "60"
            return token_response
        if "instance-identity/document" in req.full_url:
            assert req.get_method() == "GET"
            assert req.headers.get("X-aws-ec2-metadata-token") == "test-aws-token"
            return doc_response
        raise urllib.error.URLError("Not found")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = discover_client_region()

    assert result == {
        "client_region": "us-west-2",
        "client_cloud": "aws",
        "source": "observed",
    }


def test_gcp_metadata_discovery() -> None:
    gcp_response = MagicMock()
    gcp_response.read.return_value = b"projects/123456789/zones/us-central1-a"
    gcp_response.__enter__.return_value = gcp_response

    def fake_urlopen(req, timeout=0.2):
        if "computeMetadata/v1/instance/zone" in req.full_url:
            assert req.headers.get("Metadata-flavor") == "Google"
            return gcp_response
        raise urllib.error.URLError("AWS not available")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = discover_client_region()

    assert result == {
        "client_region": "us-central1",
        "client_cloud": "gcp",
        "source": "observed",
    }


def test_azure_imds_discovery() -> None:
    azure_response = MagicMock()
    azure_response.read.return_value = b"eastus2"
    azure_response.__enter__.return_value = azure_response

    def fake_urlopen(req, timeout=0.2):
        if "metadata/instance/compute/location" in req.full_url:
            assert req.headers.get("Metadata") == "true"
            return azure_response
        raise urllib.error.URLError("Not available")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = discover_client_region()

    assert result == {
        "client_region": "eastus2",
        "client_cloud": "azure",
        "source": "observed",
    }


def test_unreachable_imds_fallback() -> None:
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        result = discover_client_region()

    assert result == {
        "client_region": None,
        "client_cloud": None,
        "source": "unavailable",
    }


def test_cli_option_override_region_and_cloud() -> None:
    config = {
        "client_region": "eu-central-1",
        "client_cloud": "aws",
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = discover_client_region(config)
        mock_urlopen.assert_not_called()

    assert result == {
        "client_region": "eu-central-1",
        "client_cloud": "aws",
        "source": "cli_option",
    }


def test_cli_option_override_region_only_defaults_unknown_cloud() -> None:
    config = {
        "client_region": "my-custom-region",
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = discover_client_region(config)
        mock_urlopen.assert_not_called()

    assert result == {
        "client_region": "my-custom-region",
        "client_cloud": "unknown",
        "source": "cli_option",
    }


def test_process_caching() -> None:
    token_response = MagicMock()
    token_response.read.return_value = b"token"
    token_response.__enter__.return_value = token_response

    doc_response = MagicMock()
    doc_response.read.return_value = json.dumps({"region": "ap-southeast-1"}).encode("utf-8")
    doc_response.__enter__.return_value = doc_response

    call_count = 0

    def fake_urlopen(req, timeout=0.2):
        nonlocal call_count
        call_count += 1
        if "latest/api/token" in req.full_url:
            return token_response
        if "instance-identity/document" in req.full_url:
            return doc_response
        raise urllib.error.URLError("Not found")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        res1 = discover_client_region()
        assert call_count == 2
        # Second call should use cache, not call urlopen again
        res2 = discover_client_region()
        assert call_count == 2

    assert res1 == res2
    assert res1["client_region"] == "ap-southeast-1"
