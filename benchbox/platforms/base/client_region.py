# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_IMDS_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())

_REGION_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_KNOWN_CLIENT_CLOUDS = frozenset({"aws", "gcp", "azure"})


def reset_client_region_cache() -> None:
    global _CACHED_CLIENT_REGION
    with _CACHE_LOCK:
        _CACHED_CLIENT_REGION = None


def _imds_open(request: urllib.request.Request, timeout: float = _IMDS_TIMEOUT_SECONDS) -> Any:
    return _IMDS_OPENER.open(request, timeout=timeout)


def _read_body(response: Any) -> str:
    return response.read(_MAX_IMDS_BODY_BYTES).decode("utf-8", errors="replace").strip()


def _valid_region(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if _REGION_TOKEN_RE.match(token):
        return token
    return None


def _probe_aws_imds() -> dict[str, Any] | None:
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
    try:
        req = urllib.request.Request(
            f"{_IMDS_BASE_URL}/computeMetadata/v1/instance/zone",
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        with _imds_open(req) as resp:
            raw_zone = _read_body(resp)
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
            observed_region = observed.get("client_region")
            if cloud in _KNOWN_CLIENT_CLOUDS and observed.get("client_cloud") != cloud:
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
