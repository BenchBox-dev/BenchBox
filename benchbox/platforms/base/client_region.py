"""Client region and cloud discovery for link locality disclosure.

Discovers client runner placement using cloud Instance Metadata Services (IMDS)
or CLI option overrides.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_CACHED_CLIENT_REGION: dict[str, Any] | None = None
_CACHE_LOCK = threading.Lock()
_IMDS_TIMEOUT_SECONDS: float = 0.2
_IMDS_BASE_URL = "http://169.254.169.254"
_MAX_IMDS_BODY_BYTES = 8192

# IMDS endpoints are link-local and must never be sent to a proxy: with
# HTTP(S)_PROXY set (common in corp/CI), the default opener would hand the
# metadata request to the proxy, leaking the token and publishing whatever
# the proxy answers as the client region. An empty ProxyHandler registers
# no *_open methods, so the opener below routes direct by construction and
# the default env-proxy handler is skipped.
_IMDS_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_REGION_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_KNOWN_CLIENT_CLOUDS = frozenset({"aws", "gcp", "azure"})


def reset_client_region_cache() -> None:
    """Reset the process-cached client region discovery result."""
    global _CACHED_CLIENT_REGION
    with _CACHE_LOCK:
        _CACHED_CLIENT_REGION = None


def _imds_open(request: urllib.request.Request, timeout: float = _IMDS_TIMEOUT_SECONDS) -> Any:
    """Open a link-local IMDS request without proxy handling."""
    return _IMDS_OPENER.open(request, timeout=timeout)


def _read_body(response: Any) -> str:
    """Read a bounded, decoded IMDS response body."""
    return response.read(_MAX_IMDS_BODY_BYTES).decode("utf-8", errors="replace").strip()


def _valid_region(value: Any) -> str | None:
    """Return the value when it is a tight region token, else None.

    Rejects HTML error pages, hostnames, and other non-region bodies that a
    proxy or middlebox might return for the metadata URL.
    """
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if _REGION_TOKEN_RE.match(token):
        return token
    return None


def _probe_aws_imds() -> dict[str, Any] | None:
    """Probe AWS IMDSv2 for EC2 instance region, falling back to IMDSv1."""
    region: str | None = None
    try:
        token_req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            method="PUT",
        )
        with _imds_open(token_req) as resp:
            token = _read_body(resp)

        doc_req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/latest/dynamic/instance-identity/document",
            headers={"X-aws-ec2-metadata-token": token},
            method="GET",
        )
        with _imds_open(doc_req) as resp:
            data = json.loads(_read_body(resp))
            region = _valid_region(data.get("region"))
        if region:
            logger.debug("Client region observed via AWS IMDSv2")
    except Exception as exc:
        logger.debug("AWS IMDSv2 discovery skipped: %r", exc)
    if region:
        return {
            "client_region": region,
            "client_cloud": "aws",
            "source": "observed",
        }
    # IMDSv1-only hosts (HttpTokens=optional) have no token endpoint; the
    # document GET still answers without a token.
    try:
        doc_req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/latest/dynamic/instance-identity/document",
            method="GET",
        )
        with _imds_open(doc_req) as resp:
            data = json.loads(_read_body(resp))
            region = _valid_region(data.get("region"))
        if region:
            logger.debug("Client region observed via AWS IMDSv1 fallback")
            return {
                "client_region": region,
                "client_cloud": "aws",
                "source": "observed",
            }
    except Exception as exc:
        logger.debug("AWS IMDSv1 discovery skipped: %r", exc)
    return None


def _probe_gcp_imds() -> dict[str, Any] | None:
    """Probe GCP metadata server for compute engine zone and derive region."""
    try:
        req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/computeMetadata/v1/instance/zone",
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        with _imds_open(req) as resp:
            raw_zone = _read_body(resp)
            # GCP zone can be 'projects/12345/zones/us-central1-a' or 'us-central1-a'
            zone = raw_zone.split("/")[-1]
            region = zone.rsplit("-", 1)[0] if "-" in zone else zone
            region = _valid_region(region)
            if region:
                return {
                    "client_region": region,
                    "client_cloud": "gcp",
                    "source": "observed",
                }
    except Exception as exc:
        logger.debug("GCP IMDS discovery skipped: %r", exc)
    return None


def _probe_azure_imds() -> dict[str, Any] | None:
    """Probe Azure Instance Metadata Service (IMDS) for location."""
    try:
        req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/metadata/instance/compute/location?api-version=2021-02-01&format=text",
            headers={"Metadata": "true"},
            method="GET",
        )
        with _imds_open(req) as resp:
            location = _valid_region(_read_body(resp))
            if location:
                return {
                    "client_region": location,
                    "client_cloud": "azure",
                    "source": "observed",
                }
    except Exception as exc:
        logger.debug("Azure IMDS discovery skipped: %r", exc)
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
    """Return process-cached IMDS discovery or execute probe if uncached.

    The cache is process-lifetime by design: IMDS identity describes the
    host, which does not change under a running process, while re-probing
    on every run would add up to three link-local timeouts to each
    benchmark. Tests reset it via :func:`reset_client_region_cache`.
    """
    global _CACHED_CLIENT_REGION
    with _CACHE_LOCK:
        if _CACHED_CLIENT_REGION is None:
            _CACHED_CLIENT_REGION = _probe_imds()
        return dict(_CACHED_CLIENT_REGION)


def _valid_explicit_region(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if _REGION_TOKEN_RE.match(token):
        return token
    logger.warning("Ignoring --client-region value that is not a region token")
    return None


def _valid_explicit_cloud(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if token in _KNOWN_CLIENT_CLOUDS or token == "unknown":
        return token
    logger.warning("Ignoring --client-cloud value outside {aws, gcp, azure, unknown}")
    return None


def discover_client_region(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Discover or resolve client region and cloud provider.

    Parameters:
        config: Optional configuration mapping or runner config that may specify
            explicit `client_region` and/or `client_cloud` overrides.

    Returns:
        Dictionary containing `client_region`, `client_cloud`, and `source`.
        Explicit values are validated and never raise; invalid values are
        ignored with a warning.
    """
    if config is not None:
        if isinstance(config, Mapping):
            explicit_region = config.get("client_region")
            explicit_cloud = config.get("client_cloud")
        else:
            explicit_region = getattr(config, "client_region", None)
            explicit_cloud = getattr(config, "client_cloud", None)

        region = _valid_explicit_region(explicit_region) if explicit_region else None
        cloud = _valid_explicit_cloud(explicit_cloud) if explicit_cloud else None

        if region:
            return {
                "client_region": region,
                "client_cloud": cloud or "unknown",
                "source": "cli_option",
            }
        if cloud:
            observed = _get_cached_imds()
            # An explicitly attested cloud must not relabel an observed region
            # from another cloud: that fabricates a cross-cloud collocation
            # signal. Keep the observed region only when the clouds agree.
            observed_region = observed.get("client_region")
            if observed.get("client_cloud") != cloud:
                observed_region = None
            return {
                "client_region": observed_region,
                "client_cloud": cloud,
                "source": "cli_option",
            }

    return dict(_get_cached_imds())


__all__ = [
    "discover_client_region",
    "reset_client_region_cache",
]
