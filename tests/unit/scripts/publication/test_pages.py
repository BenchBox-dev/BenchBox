"""Unit tests for the GitHub Pages deployment adapter (scripts/publication/pages.cjs).

Drives the adapter via tests/unit/scripts/publication/pages_adapter_harness.cjs
to test input validation, OIDC token acquisition/masking, provider POST/GET/cancel,
allowlisted response filtering, and secret redaction.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[4]
HARNESS_PATH = REPO_ROOT / "tests/unit/scripts/publication/pages_adapter_harness.cjs"
VALID_SHA = "0123456789abcdef0123456789abcdef01234567"


def run_harness(payload: dict[str, Any]) -> dict[str, Any]:
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js is required for pages.cjs adapter unit tests")

    proc = subprocess.run(
        [node_bin, str(HARNESS_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Harness exited with {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def test_create_deployment_success() -> None:
    payload = {
        "action": "create",
        "effect": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "artifact_id": 42,
            "pages_build_version": VALID_SHA,
        },
        "mock": {
            "token": "secret-token-abc",
            "post_response": {
                "id": "deploy-12345",
                "status_url": "https://api.github.com/repos/BenchBox-dev/BenchBox/pages/deployments/deploy-12345",
                "page_url": "https://benchbox.dev/",
                "pages_build_version": VALID_SHA,
                "unauthorized_field": "leak_candidate",
            },
        },
    }
    result = run_harness(payload)
    assert result["success"] is True
    res = result["result"]
    assert res["id"] == "deploy-12345"
    assert res["status_url"] == "https://api.github.com/repos/BenchBox-dev/BenchBox/pages/deployments/deploy-12345"
    assert res["page_url"] == "https://benchbox.dev/"
    assert res["pages_build_version"] == VALID_SHA
    assert "unauthorized_field" not in res
    assert "secret-token-abc" in result["masked_secrets"]

    # Verify request was correctly shaped
    reqs = result["recorded_requests"]
    assert len(reqs) == 1
    assert reqs[0]["route"] == "POST /repos/{owner}/{repo}/pages/deployments"
    assert reqs[0]["params"]["artifact_id"] == 42
    assert reqs[0]["params"]["pages_build_version"] == VALID_SHA
    assert reqs[0]["params"]["oidc_token"] == "secret-token-abc"


@pytest.mark.parametrize(
    ("field", "value", "expected_err"),
    [
        ("owner", "", "owner must be a non-empty string"),
        ("repo", "", "repo must be a non-empty string"),
        ("artifact_id", -1, "artifact_id must be a positive integer"),
        ("artifact_id", "abc", "artifact_id must be a positive integer"),
        ("artifact_id", True, "artifact_id must be a positive integer"),
        ("artifact_id", 1.5, "artifact_id must be a positive integer"),
        ("artifact_id", "9007199254740993", "artifact_id must be a positive integer"),
        ("pages_build_version", "short", "pages_build_version must be a 40-character hexadecimal commit SHA"),
        ("pages_build_version", "g" * 40, "pages_build_version must be a 40-character hexadecimal commit SHA"),
    ],
)
def test_create_deployment_validation_fails_pre_send(field: str, value: Any, expected_err: str) -> None:
    effect = {
        "owner": "BenchBox-dev",
        "repo": "BenchBox",
        "artifact_id": 42,
        "pages_build_version": VALID_SHA,
    }
    effect[field] = value

    result = run_harness({"action": "create", "effect": effect})
    assert result["success"] is False
    assert result["error"]["stage"] == "pre_send"
    assert result["error"]["code"] == "ERR_VALIDATION"
    assert expected_err in result["error"]["message"]
    assert len(result["recorded_requests"]) == 0
    assert len(result["masked_secrets"]) == 0


def test_create_deployment_oidc_denial_fails_pre_send() -> None:
    payload = {
        "action": "create",
        "effect": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "artifact_id": 42,
            "pages_build_version": VALID_SHA,
        },
        "mock": {
            "token_error": "OIDC token request rejected by provider",
        },
    }
    result = run_harness(payload)
    assert result["success"] is False
    assert result["error"]["stage"] == "pre_send"
    assert result["error"]["code"] == "ERR_OIDC_DENIAL"
    assert "OIDC token request rejected" in result["error"]["message"]
    assert len(result["recorded_requests"]) == 0


def test_create_deployment_redacts_secret_in_error() -> None:
    secret_token = "my-secret-jwt-token-999"
    payload = {
        "action": "create",
        "effect": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "artifact_id": 42,
            "pages_build_version": VALID_SHA,
        },
        "mock": {
            "token": secret_token,
            "post_error": {
                "message": f"Server rejected bearer {secret_token} with status 401",
                "status": 401,
            },
        },
    }
    result = run_harness(payload)
    assert result["success"] is False
    assert result["error"]["stage"] == "post_send"
    assert result["error"]["code"] == "ERR_PROVIDER_POST"
    assert result["error"]["status"] == 401
    assert secret_token not in result["error"]["message"]
    assert "[REDACTED]" in result["error"]["message"]
    assert secret_token in result["masked_secrets"]
    assert result["error"]["cause_message"] is None


def test_create_response_does_not_fabricate_provider_acknowledgement() -> None:
    result = run_harness(
        {
            "action": "create",
            "effect": {
                "owner": "BenchBox-dev",
                "repo": "BenchBox",
                "artifact_id": 42,
                "pages_build_version": VALID_SHA,
            },
            "mock": {"post_response": {"id": "deploy-12345"}},
        }
    )
    assert result["result"]["pages_build_version"] is None
    assert result["result"]["created_at"] is None


def test_get_deployment_status_success() -> None:
    payload = {
        "action": "status",
        "options": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "deployment_id": "deploy-555",
        },
        "mock": {
            "get_response": {
                "id": "deploy-555",
                "status": "success",
                "page_url": "https://benchbox.dev/",
                "created_at": "2026-09-05T00:00:00Z",
                "updated_at": "2026-09-05T00:01:00Z",
                "extra_metadata": "hidden",
            },
        },
    }
    result = run_harness(payload)
    assert result["success"] is True
    res = result["result"]
    assert res["id"] == "deploy-555"
    assert res["status"] == "SUCCESS"
    assert res["page_url"] == "https://benchbox.dev/"
    assert "extra_metadata" not in res


def test_get_deployment_status_missing_id_fails() -> None:
    payload = {
        "action": "status",
        "options": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
        },
    }
    result = run_harness(payload)
    assert result["success"] is False
    assert result["error"]["code"] == "ERR_VALIDATION"
    assert "deployment_id is required" in result["error"]["message"]


def test_cancel_deployment_success() -> None:
    payload = {
        "action": "cancel",
        "options": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "deployment_id": "deploy-777",
        },
        "mock": {
            "cancel_response": {
                "id": "deploy-777",
                "status": "canceled",
            },
        },
    }
    result = run_harness(payload)
    assert result["success"] is True
    assert result["result"]["id"] == "deploy-777"
    assert result["result"]["status"] == "CANCELED"


def test_cancel_deployment_failure() -> None:
    payload = {
        "action": "cancel",
        "options": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
            "deployment_id": "deploy-777",
        },
        "mock": {
            "cancel_error": {
                "message": "Cannot cancel completed deployment",
                "status": 409,
            },
        },
    }
    result = run_harness(payload)
    assert result["success"] is False
    assert result["error"]["code"] == "ERR_PROVIDER_CANCEL"
    assert result["error"]["stage"] == "post_send"
    assert result["error"]["status"] == 409
    assert "Cannot cancel completed deployment" in result["error"]["message"]


def test_cancel_deployment_missing_args_fails() -> None:
    payload = {
        "action": "cancel",
        "options": {
            "owner": "BenchBox-dev",
            "repo": "BenchBox",
        },
    }
    result = run_harness(payload)
    assert result["success"] is False
    assert result["error"]["code"] == "ERR_VALIDATION"
    assert result["error"]["stage"] == "pre_send"
