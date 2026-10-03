from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 30
MAX_PAGES = 10

UrlOpen = Callable[..., Any]


class ApiError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, repo: str, token: str, urlopen: UrlOpen = urllib.request.urlopen) -> None:
        if not repo or not token:
            raise ApiError("repo and token are required")
        self.repo = repo
        self.token = token
        self.urlopen = urlopen

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{API_BASE}/repos/{self.repo}/{path.lstrip('/')}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc
        try:
            return json.loads(raw) if raw else {}
        except ValueError as exc:
            raise ApiError(f"{method} {path} returned invalid JSON") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("POST", path, body)

    def get_list(self, path: str, key: str | None = None, per_page: int = 100) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self.get(f"{path}{separator}per_page={per_page}&page={page}")
            chunk = payload.get(key) if key and isinstance(payload, dict) else payload
            if not isinstance(chunk, list):
                raise ApiError(f"{path} did not return a list")
            items.extend(item for item in chunk if isinstance(item, dict))
            if len(chunk) < per_page:
                return items
        raise ApiError(f"{path} has more than {MAX_PAGES * per_page} items; refusing a truncated listing")

    def get_first(self, path: str, count: int, key: str | None = None) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        per_page = min(100, count)
        page = 1
        while len(items) < count:
            payload = self.get(f"{path}{separator}per_page={per_page}&page={page}")
            chunk = payload.get(key) if key and isinstance(payload, dict) else payload
            if not isinstance(chunk, list):
                raise ApiError(f"{path} did not return a list")
            items.extend(item for item in chunk if isinstance(item, dict))
            if len(chunk) < per_page:
                break
            page += 1
        return items[:count]
