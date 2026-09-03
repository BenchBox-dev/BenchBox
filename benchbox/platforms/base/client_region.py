"""Client region and cloud discovery for link locality disclosure.

Discovers client runner placement using cloud Instance Metadata Services (IMDS)
or CLI option overrides.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_CACHED_CLIENT_REGION: dict[str, Any] | None = None
_IMDS_TIMEOUT_SECONDS: float = 0.2


def reset_client_region_cache() -> None:
    """Reset the process-cached client region discovery result."""
    global _CACHED_CLIENT_REGION
    _CACHED_CLIENT_REGION = None


def _probe_aws_imds() -> dict[str, Any] | None:
    """Probe AWS IMDSv2 for EC2 instance region."""
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            method="PUT",
        )
        with urllib.request.urlopen(token_req, timeout=_IMDS_TIMEOUT_SECONDS) as resp:
            token = resp.read().decode("utf-8").strip()

        doc_req = urllib.request.Request(
            "http://169.254.169.254/latest/dynamic/instance-identity/document",
            headers={"X-aws-ec2-metadata-token": token},
            method="GET",
        )
        with urllib.request.urlopen(doc_req, timeout=_IMDS_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            region = data.get("region")
            if region:
                return {
                    "client_region": str(region),
                    "client_cloud": "aws",
                    "source": "observed",
                }
    except Exception:
        pass
    return None


def _probe_gcp_imds() -> dict[str, Any] | None:
    """Probe GCP metadata server for compute engine zone and derive region."""
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/computeMetadata/v1/instance/zone",
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=_IMDS_TIMEOUT_SECONDS) as resp:
            raw_zone = resp.read().decode("utf-8").strip()
            # GCP zone can be 'projects/12345/zones/us-central1-a' or 'us-central1-a'
            zone = raw_zone.split("/")[-1]
            region = zone.rsplit("-", 1)[0] if "-" in zone else zone
            if region:
                return {
                    "client_region": str(region),
                    "client_cloud": "gcp",
                    "source": "observed",
                }
    except Exception:
        pass
    return None


def _probe_azure_imds() -> dict[str, Any] | None:
    """Probe Azure Instance Metadata Service (IMDS) for location."""
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/metadata/instance/compute/location?api-version=2021-02-01&format=text",
            headers={"Metadata": "true"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=_IMDS_TIMEOUT_SECONDS) as resp:
            location = resp.read().decode("utf-8").strip()
            if location:
                return {
                    "client_region": str(location),
                    "client_cloud": "azure",
                    "source": "observed",
                }
    except Exception:
        pass
    return None


def _probe_imds() -> dict[str, Any]:
    """Try probing known cloud IMDS endpoints in sequence."""
    for probe in (_probe_aws_imds, _probe_gcp_imds, _probe_azure_imds):
        try:
            result = probe()
            if result and result.get("client_region"):
                return result
        except Exception:
            continue
    return {
        "client_region": None,
        "client_cloud": None,
        "source": "unavailable",
    }


def _get_cached_imds() -> dict[str, Any]:
    """Return process-cached IMDS discovery or execute probe if uncached."""
    global _CACHED_CLIENT_REGION
    if _CACHED_CLIENT_REGION is None:
        _CACHED_CLIENT_REGION = _probe_imds()
    return _CACHED_CLIENT_REGION


def discover_client_region(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Discover or resolve client region and cloud provider.

    Parameters:
        config: Optional configuration mapping or runner config that may specify
            explicit `client_region` and/or `client_cloud` overrides.

    Returns:
        Dictionary containing `client_region`, `client_cloud`, and `source`.
    """
    if config is not None:
        if isinstance(config, Mapping):
            explicit_region = config.get("client_region")
            explicit_cloud = config.get("client_cloud")
        else:
            explicit_region = getattr(config, "client_region", None)
            explicit_cloud = getattr(config, "client_cloud", None)

        if explicit_region:
            return {
                "client_region": str(explicit_region),
                "client_cloud": str(explicit_cloud) if explicit_cloud else "unknown",
                "source": "cli_option",
            }
        if explicit_cloud:
            observed = _get_cached_imds()
            return {
                "client_region": observed.get("client_region"),
                "client_cloud": str(explicit_cloud),
                "source": "cli_option",
            }

    return dict(_get_cached_imds())


__all__ = [
    "discover_client_region",
    "reset_client_region_cache",
]
