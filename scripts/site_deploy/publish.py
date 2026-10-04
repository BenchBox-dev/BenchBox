from __future__ import annotations

import http.server
import json
import shutil
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

from scripts.publication.assembler import compute_tree_digest
from scripts.site_deploy import checksums, probe as probe_module, receipt as receipt_module, rollback

TARGET = "local-dir"
NOT_FOUND = "404.html"


class SlotServer(http.server.ThreadingHTTPServer):
    slot_dir: Path


class SlotHandler(http.server.BaseHTTPRequestHandler):
    server_version = "PagesEmulator/1"

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def slot_root(self) -> Path:
        server = self.server
        assert isinstance(server, SlotServer)
        return server.slot_dir

    def _resolve(self, url_path: str) -> tuple[int, Path | None]:
        root = self.slot_root()
        relative = unquote(urlsplit(url_path).path).lstrip("/")
        candidate = (root / relative).resolve()
        if root.resolve() not in (candidate, *candidate.parents):
            return 404, root / NOT_FOUND
        if candidate.is_dir():
            index = candidate / "index.html"
            return (200, index) if index.is_file() else (404, root / NOT_FOUND)
        if candidate.is_file():
            return 200, candidate
        html = candidate.with_name(candidate.name + ".html")
        if html.is_file():
            return 200, html
        return 404, root / NOT_FOUND

    def _serve(self, send_body: bool) -> None:
        relative = unquote(urlsplit(self.path).path).lstrip("/")
        directory = self.slot_root() / relative
        if relative and not self.path.endswith("/") and directory.is_dir():
            self.send_response(301)
            self.send_header("Location", self.path + "/")
            self.end_headers()
            return
        status, target = self._resolve(self.path)
        body = target.read_bytes() if target is not None and target.is_file() else b"not found"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._serve(True)

    def do_HEAD(self) -> None:
        self._serve(False)


class LocalDirTarget:
    def __init__(self, slot_dir: Path) -> None:
        self.slot_dir = slot_dir
        self.httpd = SlotServer(("127.0.0.1", 0), SlotHandler)
        self.httpd.slot_dir = slot_dir
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def publish(self, tree: Path) -> None:
        if self.slot_dir.exists():
            shutil.rmtree(self.slot_dir)
        shutil.copytree(tree, self.slot_dir)

    def digest(self) -> str:
        return compute_tree_digest(self.slot_dir)[0]

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


@contextmanager
def running_target(slot_dir: Path) -> Iterator[LocalDirTarget]:
    target = LocalDirTarget(slot_dir)
    target.start()
    try:
        yield target
    finally:
        target.stop()


def _assembly_for(tree: Path, route_paths: list[str], trunk_sha: str, builder: str) -> dict[str, Any]:
    digest, size, manifest = compute_tree_digest(tree)
    routes = [
        {"path": path, "ref": "trunk", "ref_kind": "trunk", "builder": builder, "source_sha": trunk_sha}
        for path in route_paths
    ]
    return {"routes": routes, "tree_sha256": digest, "total_bytes": size, "total_files": len(manifest)}


def _write(receipts_dir: Path, name: str, receipt: dict[str, Any]) -> str:
    raw = receipt_module.canonical_bytes(receipt)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / name).write_bytes(raw)
    return receipt_module.receipt_sha256(raw)


def run_drill(
    *,
    legacy_tree: Path,
    routes_tree: Path,
    route_paths: list[str],
    trunk_sha: str,
    release_tag: str,
    release_sha: str,
    corpus_sha: str,
    routes_assembly: dict[str, Any],
    versions: dict[str, Any],
    gates: dict[str, Any],
    work_dir: Path,
    receipts_dir: Path,
    probe_fn: Callable[..., dict[str, Any]] = probe_module.probe,
) -> dict[str, Any]:
    retained = work_dir / "retained"
    for name, tree in (("A", legacy_tree), ("B", routes_tree)):
        shutil.copytree(tree, retained / name, dirs_exist_ok=True)
    steps: list[dict[str, Any]] = []
    with running_target(work_dir / "slot") as target:
        legacy_assembly = _assembly_for(
            retained / "A", [p for p in route_paths if p != "/docs/dev/"], trunk_sha, "legacy-single-ref"
        )
        legacy_checksums = checksums.checksum_manifest(retained / "A", legacy_assembly_paths(legacy_assembly))
        target.publish(retained / "A")
        probes_a = probe_fn(target.base_url, legacy_checksums, work_dir / "probe-a", attempts=2, delay=0.5)
        receipt_a = receipt_module.build_receipt(
            mode="deploy",
            target=TARGET,
            run_id=1,
            deployment_id=None,
            trunk_sha=trunk_sha,
            release_tag=release_tag,
            release_sha=release_sha,
            corpus_sha=corpus_sha,
            assembly=legacy_assembly,
            artifact_name="legacy-single-ref",
            versions=versions,
            gates=gates,
            probes=probes_a,
            parent=None,
            certifying_run_id=None,
        )
        sha_a = _write(receipts_dir, "receipt-a.json", receipt_a)
        steps.append(
            {
                "step": "publish A (legacy single-ref assembly)",
                "probes_ok": probes_a["ok"],
                "tree_sha256": target.digest(),
            }
        )

        routes_checksums = checksums.checksum_manifest(retained / "B", route_paths)
        target.publish(retained / "B")
        probes_b = probe_fn(target.base_url, routes_checksums, work_dir / "probe-b", attempts=2, delay=0.5)
        receipt_b = receipt_module.build_receipt(
            mode="deploy",
            target=TARGET,
            run_id=2,
            deployment_id=None,
            trunk_sha=trunk_sha,
            release_tag=release_tag,
            release_sha=release_sha,
            corpus_sha=corpus_sha,
            assembly=routes_assembly,
            artifact_name="routes-build",
            versions=versions,
            gates=gates,
            probes=probes_b,
            parent=receipt_module.parent_summary(receipt_a, sha_a),
            certifying_run_id=None,
        )
        sha_b = _write(receipts_dir, "receipt-b.json", receipt_b)
        steps.append({"step": "publish B (route build)", "probes_ok": probes_b["ok"], "tree_sha256": target.digest()})

        restore = rollback.load_restore(receipts_dir / "receipt-a.json", retained / "A", target=TARGET)
        target.publish(restore.tree)
        restored_checksums = checksums.checksum_manifest(restore.tree, legacy_assembly_paths(legacy_assembly))
        probes_r = probe_fn(target.base_url, restored_checksums, work_dir / "probe-r", attempts=2, delay=0.5)
        restored_digest = target.digest()
        receipt_r = receipt_module.build_receipt(
            mode="rollback",
            target=TARGET,
            run_id=3,
            deployment_id=None,
            trunk_sha=trunk_sha,
            release_tag=release_tag,
            release_sha=release_sha,
            corpus_sha=corpus_sha,
            assembly=legacy_assembly,
            artifact_name="legacy-single-ref",
            versions=versions,
            gates=gates,
            probes=probes_r,
            parent=receipt_module.parent_summary(receipt_b, sha_b),
            certifying_run_id=None,
            rollback={"restored_receipt_sha256": restore.receipt_sha256, "restored_run_id": 1, "phase": "full"},
        )
        _write(receipts_dir, "receipt-rollback.json", receipt_r)
        steps.append({"step": "rollback to A by receipt", "probes_ok": probes_r["ok"], "tree_sha256": restored_digest})
    digest_matches = restored_digest == receipt_a["artifact"]["sha256"]
    ok = digest_matches and all(step["probes_ok"] for step in steps)
    return {
        "schema": "site-deploy-preview-drill/v1",
        "ok": ok,
        "restored_digest_equals_a": digest_matches,
        "a_tree_sha256": receipt_a["artifact"]["sha256"],
        "b_tree_sha256": receipt_b["artifact"]["sha256"],
        "steps": steps,
    }


def legacy_assembly_paths(assembly: dict[str, Any]) -> list[str]:
    return [route["path"] for route in assembly["routes"]]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
