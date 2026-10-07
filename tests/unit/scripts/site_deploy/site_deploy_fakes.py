from __future__ import annotations

import json
import re
import urllib.error
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from scripts.site_deploy import receipt as receipt_module
from scripts.site_deploy.githubapi import GitHubClient

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


@dataclass
class FakeGitHub:
    runs: list[dict[str, Any]] = field(default_factory=list)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    statuses: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    receipts: dict[int, bytes] = field(default_factory=dict)
    fail: bool = False
    ignore_status_filter: bool = False
    requests: list[tuple[str, str]] = field(default_factory=list)

    def urlopen(self, request: Any, timeout: float = 0) -> FakeResponse:
        del timeout
        if self.fail:
            raise urllib.error.URLError("boom")
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        self.requests.append((request.get_method(), url.path + "?" + url.query))
        runs_match = re.search(r"/actions/workflows/([^/]+)/runs$", url.path)
        if runs_match:
            wanted = query.get("head_sha", [""])[0]
            rows = [run for run in self.runs if run["head_sha"] == wanted and run["event"] == query["event"][0]]
            if "branch" in query:
                rows = [run for run in rows if run.get("head_branch") == query["branch"][0]]
            if query.get("status") == ["success"] and not self.ignore_status_filter:
                rows = [run for run in rows if run["conclusion"] == "success"]
            return FakeResponse({"workflow_runs": self._page(rows, query), "total_count": len(rows)})
        if url.path.endswith("/deployments"):
            return FakeResponse(
                self._page(sorted(self.deployments, key=lambda d: d["created_at"], reverse=True), query)
            )
        status_match = re.search(r"/deployments/(\d+)/statuses$", url.path)
        if status_match:
            if request.get_method() == "POST":
                body = json.loads(request.data)
                row = {
                    **body,
                    "created_at": f"2026-01-01T00:00:{len(self.statuses.get(int(status_match.group(1)), [])):02d}Z",
                }
                self.statuses.setdefault(int(status_match.group(1)), []).append(row)
                return FakeResponse(row)
            return FakeResponse(self._page(self.statuses.get(int(status_match.group(1)), []), query))
        raise AssertionError(f"unexpected request {url.path}")

    @staticmethod
    def _page(rows: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
        per_page = int(query.get("per_page", ["100"])[0])
        page = int(query.get("page", ["1"])[0])
        return rows[(page - 1) * per_page : page * per_page]

    def client(self) -> GitHubClient:
        return GitHubClient("owner/repo", "token", self.urlopen)

    def load_receipt(self, run_id: int, expected_sha256: str | None = None) -> bytes:
        return self.receipts[run_id]

    def record_deployment(
        self,
        deployment_id: int,
        receipt: dict[str, Any],
        created: str,
        state: str = "success",
        log_url: str | None = None,
    ) -> str:
        raw = receipt_module.canonical_bytes(receipt)
        sha = receipt_module.receipt_sha256(raw)
        self.deployments.append({"id": deployment_id, "created_at": created})
        self.statuses[deployment_id] = [
            {
                "state": state,
                "description": receipt_module.status_description(sha, receipt["run_id"]),
                "created_at": created,
                "log_url": log_url,
            }
        ]
        self.receipts[receipt["run_id"]] = raw
        return sha


def make_receipt(
    *,
    run_id: int,
    trunk: str,
    tag: str = "v0.4.1",
    generation: int = 1,
    corpus: str = "1" * 40,
    ui: int = 11,
    snapshot: int = 11,
    probes_ok: bool = True,
    parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly = {
        "routes": [{"path": "/", "source_sha": trunk}],
        "tree_sha256": "f" * 64,
        "total_bytes": 10,
        "total_files": 2,
    }
    built = receipt_module.build_receipt(
        mode="deploy",
        target="github-pages",
        run_id=run_id,
        deployment_id=run_id * 10,
        trunk_sha=trunk,
        release_tag=tag,
        release_sha="9" * 40,
        corpus_sha=corpus,
        assembly=assembly,
        artifact_name=f"site-deploy-artifact-{run_id}",
        versions={"ui_expected": ui, "snapshot": snapshot},
        gates={"ok": True, "results": {"privacy": {"status": "pass"}}},
        probes={"ok": probes_ok},
        parent=parent,
        certifying_run_id=run_id + 1000,
    )
    built["generation"] = generation
    return built
