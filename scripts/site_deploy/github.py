"""Thin GitHub REST access through the ``gh`` CLI.

Everything that reads GitHub state takes an ``api`` callable so tests can supply
recorded responses. The default implementation shells out to ``gh api``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

Api = Callable[[str], Any]


class GitHubError(RuntimeError):
    """A ``gh api`` call failed."""


def gh_api(path: str) -> Any:
    """GET ``path`` (a REST path such as ``repos/o/r/deployments``) and decode the JSON body."""
    result = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitHubError(f"gh api {path} failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout or "null")


def gh_post(path: str, fields: dict[str, str]) -> Any:
    """POST form fields to ``path`` and decode the JSON response."""
    argv = ["gh", "api", "--method", "POST", path]
    for key, value in fields.items():
        argv.extend(["-f", f"{key}={value}"])
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitHubError(f"gh api POST {path} failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout or "null")
