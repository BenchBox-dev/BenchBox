"""Bind release distributions to one successful merge-queue producer attempt.

This admission boundary never builds or publishes packages. Older artifacts
without a producer receipt are deliberately unsupported.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY = "BenchBox-dev/BenchBox"
WORKFLOW = ".github/workflows/ci.yml"
JOB_NAME = "dist-artifact"
PRODUCER_RECEIPT = "producer-receipt.json"
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
Api = Callable[[str], dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _timestamp(value: Any) -> datetime:
    _require(isinstance(value, str), "missing API timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.tzinfo is not None, "API timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def github_json(path: str) -> dict[str, Any]:
    """Read a constructed repository API path using gh's credential handling."""
    endpoint = f"repos/{REPOSITORY}" + (f"/{path}" if path else "")
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, check=True, timeout=60)
    value = json.loads(result.stdout, object_pairs_hook=_object)
    _require(isinstance(value, dict), "API response is not an object")
    return value


def _pages(api: Api, path: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(1, 101):
        payload = api(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        count = payload.get("total_count")
        part = payload.get(key)
        _require(type(count) is int and count >= 0, "missing API pagination count")
        if not isinstance(part, list) or len(part) > 100:
            raise ValueError("malformed API page")
        _require(all(isinstance(row, dict) and _positive(row.get("id")) for row in part), "malformed API row")
        if total is None:
            total = count
        _require(total == count, "API population changed during pagination")
        rows.extend(part)
        if len(part) < 100:
            _require(len(rows) == total, "incomplete API pagination")
            _require(len({row["id"] for row in rows}) == len(rows), "duplicate API rows")
            return rows
    raise ValueError("API pagination limit exceeded")


def _run_identity(run: dict[str, Any], sha: str, repository_id: int) -> None:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "invalid candidate SHA")
    _require(_positive(repository_id), "invalid repository ID")
    _require(run.get("head_sha") == sha and run.get("event") == "merge_group", "wrong producer SHA or event")
    _require(run.get("path") == WORKFLOW, "wrong producer workflow")
    for field in ("repository", "head_repository"):
        repository = run.get(field)
        _require(isinstance(repository, dict), "missing producer repository")
        _require(
            repository.get("id") == repository_id and repository.get("full_name") == REPOSITORY,
            "wrong producer repository",
        )
    _require(_positive(run.get("id")) and _positive(run.get("run_attempt")), "invalid producer run identity")


def select_producer(sha: str, api: Api = github_json) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Select the latest exact-SHA run, never falling back to an older success."""
    repository = api("")
    _require(repository.get("full_name") == REPOSITORY, "wrong repository")
    runs = _pages(api, f"actions/workflows/ci.yml/runs?head_sha={sha}&event=merge_group", "workflow_runs")
    _require(bool(runs), "no merge-queue producer")
    for run in runs:
        _run_identity(run, sha, repository.get("id"))
        _timestamp(run.get("created_at"))
        _timestamp(run.get("run_started_at") or run["created_at"])
    latest = max(runs, key=lambda run: (_timestamp(run["created_at"]), run["id"]))
    for other in runs:
        if other["id"] == latest["id"]:
            continue
        # A re-run keeps its original creation time, so an older run can hold the newest attempt.
        _require(other.get("status") == "completed", "another producer run for this SHA is still pending")
        _require(
            _timestamp(other.get("run_started_at") or other["created_at"])
            <= _timestamp(latest.get("run_started_at") or latest["created_at"]),
            "an older producer run has a newer attempt",
        )
    run = api(f"actions/runs/{latest['id']}")
    _run_identity(run, sha, repository["id"])
    _require(run["id"] == latest["id"] and run["run_attempt"] == latest["run_attempt"], "producer attempt changed")
    _require(
        run.get("status") == "completed" and run.get("conclusion") == "success", "latest producer is not successful"
    )
    attempt = run["run_attempt"]
    jobs = _pages(api, f"actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
    producers = [job for job in jobs if job.get("name") == JOB_NAME]
    _require(len(producers) == 1, "missing or ambiguous distribution producer job")
    job = producers[0]
    _require(
        job.get("run_id") == run["id"] and job.get("run_attempt") == attempt and job.get("head_sha") == sha,
        "wrong producer job identity",
    )
    _require(job.get("status") == "completed" and job.get("conclusion") == "success", "producer job is not successful")
    name = f"dist-{sha}-attempt-{attempt}"
    artifacts = _pages(api, f"actions/runs/{run['id']}/artifacts", "artifacts")
    matches = [artifact for artifact in artifacts if artifact.get("name") == name]
    _require(len(matches) == 1, "missing or ambiguous attempt-bound artifact")
    artifact = api(f"actions/artifacts/{matches[0]['id']}")
    _require(artifact == matches[0], "artifact metadata changed")
    _require(
        _positive(artifact.get("size_in_bytes")) and artifact["size_in_bytes"] <= MAX_PAYLOAD_BYTES,
        "invalid artifact size",
    )
    origin = artifact.get("workflow_run", {})
    _require(
        origin.get("id") == run["id"]
        and origin.get("head_sha") == sha
        and origin.get("repository_id") == repository["id"]
        and origin.get("head_repository_id") == repository["id"],
        "wrong artifact producer",
    )
    _require(artifact.get("expired") is False, "expired artifact")
    expiry = _timestamp(artifact.get("expires_at"))
    _require(expiry > datetime.now(timezone.utc), "artifact expiration is not in the future")
    _require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest", "")))), "missing artifact digest")
    return run, job, artifact


def _files(directory: Path) -> dict[str, dict[str, Any]]:
    distributions = [path for path in directory.iterdir() if path.name.endswith((".whl", ".tar.gz"))]
    _require(
        sum(path.name.endswith(".whl") for path in distributions) == 1
        and sum(path.name.endswith(".tar.gz") for path in distributions) == 1,
        "expected one wheel and one sdist",
    )
    result = {}
    for path in distributions:
        _require(path.is_file() and not path.is_symlink(), "distribution is not regular")
        _require(path.stat().st_size <= MAX_PAYLOAD_BYTES, "distribution exceeds size limit")
        result[path.name] = {"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def producer_receipt(directory: Path, run: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Record immutable bytes and the actual job ID before artifact upload."""
    _run_identity(run, run["head_sha"], run["repository"]["id"])
    _require(job.get("name") == JOB_NAME and _positive(job.get("id")), "invalid producer job")
    _require(
        job.get("run_id") == run["id"]
        and job.get("run_attempt") == run["run_attempt"]
        and job.get("head_sha") == run["head_sha"],
        "wrong producer job identity",
    )
    return {
        "schema": 1,
        "repository": REPOSITORY,
        "repository_id": run["repository"]["id"],
        "head_repository_id": run["head_repository"]["id"],
        "workflow_path": WORKFLOW,
        "head_sha": run["head_sha"],
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "job_id": job["id"],
        "job_name": JOB_NAME,
        "artifact_name": f"dist-{run['head_sha']}-attempt-{run['run_attempt']}",
        "sha256sums_sha256": hashlib.sha256((directory / "SHA256SUMS").read_bytes()).hexdigest(),
        "files": _files(directory),
    }


def verify_archive(archive: Path, artifact: dict[str, Any]) -> dict[str, bytes]:
    """Read four bounded, flat, regular members after verifying the ZIP digest."""
    _require(archive.stat().st_size <= MAX_PAYLOAD_BYTES, "archive exceeds size limit")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    _require(artifact.get("digest") == f"sha256:{digest}", "artifact ZIP digest mismatch")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        _require(len(members) == 4, "expected four artifact members; legacy producers are unsupported")
        _require(sum(member.file_size for member in members) <= MAX_PAYLOAD_BYTES, "payload exceeds size limit")
        names: set[str] = set()
        payloads = {}
        for member in members:
            name = member.filename
            _require(
                member.orig_filename == name
                and PurePosixPath(name).name == name
                and name not in {"", ".", ".."}
                and not any(char in name for char in "\\:\0")
                and name.rstrip(" .") == name,
                "unsafe artifact member",
            )
            _require(name.casefold() not in names, "duplicate artifact member")
            names.add(name.casefold())
            _require(
                not member.is_dir()
                and not member.external_attr & 0x10
                and not member.flag_bits & 1
                and stat.S_IFMT(member.external_attr >> 16) in {0, stat.S_IFREG},
                "nonregular artifact member",
            )
            payloads[name] = bundle.read(member)
    distributions = {name for name in payloads if name.endswith((".whl", ".tar.gz"))}
    _require(
        len(distributions) == 2
        and sum(name.endswith(".whl") for name in distributions) == 1
        and set(payloads) == distributions | {"SHA256SUMS", PRODUCER_RECEIPT},
        "unexpected artifact membership",
    )
    sums: dict[str, str] = {}
    for line in payloads["SHA256SUMS"].decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        _require(match is not None, "malformed SHA256SUMS record")
        assert match is not None
        digest, name = match.groups()
        _require(name not in sums, "duplicate SHA256SUMS record")
        sums[name] = digest
    _require(set(sums) == distributions, "SHA256SUMS membership differs")
    _require(
        all(hashlib.sha256(payloads[name]).hexdigest() == sums[name] for name in sums), "distribution hash mismatch"
    )
    return payloads


def verify_producer_receipt(directory: Path, run: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """Require exact JSON types as well as exact attempt and byte identities."""
    receipt = json.loads((directory / PRODUCER_RECEIPT).read_bytes(), object_pairs_hook=_object)
    expected = producer_receipt(directory, run, job)
    _require(
        json.dumps(receipt, sort_keys=True) == json.dumps(expected, sort_keys=True),
        "producer receipt does not bind this attempt and payload",
    )
    return expected


def resolve_tag(root: Path, tag: str, develop_ref: str = "refs/remotes/origin/develop") -> dict[str, str]:
    """Require an annotated version tag and an exact checked-out develop ancestor."""
    _require(bool(re.fullmatch(r"v[0-9][A-Za-z0-9.+-]*", tag)), "invalid version tag")

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    ref = f"refs/tags/{tag}"
    _require(git("cat-file", "-t", ref) == "tag", "lightweight tags are unsupported")
    commit = git("rev-parse", f"{ref}^{{commit}}")
    _require(git("rev-parse", "HEAD") == commit, "checkout differs from tagged source")
    _require(not git("status", "--porcelain", "--untracked-files=all"), "tagged source checkout is dirty")
    subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", commit, develop_ref], check=True)
    spec = importlib.util.spec_from_file_location("_release_version", Path(__file__).with_name("release_flow.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    _require(module.normalize_version(tag[1:]) == module.normalize_version(version) is not None, "tag/version mismatch")
    return {"tag": tag, "tag_object": git("rev-parse", ref), "head_sha": commit, "version": version}


def _download(artifact_id: int, archive: Path) -> None:
    """Stream the constructed artifact endpoint, refusing more than the payload bound."""
    total = 0
    with archive.open("xb") as stream:
        process = subprocess.Popen(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"], stdout=subprocess.PIPE
        )
        assert process.stdout is not None
        try:
            while chunk := process.stdout.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PAYLOAD_BYTES:
                    process.kill()
                    raise ValueError("archive exceeds size limit")
                stream.write(chunk)
        finally:
            process.stdout.close()
            code = process.wait(timeout=60)
    _require(code == 0, "artifact download failed")


def admit(root: Path, tag: str, output: Path, api: Api = github_json) -> dict[str, Any]:
    """Admit exact bytes only after provenance, archive and binary verification."""
    source = resolve_tag(root, tag)
    run, job, artifact = select_producer(source["head_sha"], api)
    _require(not output.exists(), "output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-admission-", dir=output.parent) as temporary:
        stage = Path(temporary)
        archive = stage / "download.zip"
        _download(artifact["id"], archive)
        payloads = verify_archive(archive, artifact)
        archive.unlink()
        for name, payload in payloads.items():
            (stage / name).write_bytes(payload)
        receipt = verify_producer_receipt(stage, run, job)
        from packaging.utils import parse_sdist_filename, parse_wheel_filename
        from packaging.version import Version

        for name in receipt["files"]:
            package, version = parse_wheel_filename(name)[:2] if name.endswith(".whl") else parse_sdist_filename(name)
            _require(
                package == "benchbox" and version == Version(source["version"]), "distribution package/version mismatch"
            )
        verifier = root / "scripts/verify_distribution_binaries.py"
        _require(verifier.is_file(), "tagged source lacks required distribution binary verifier")
        subprocess.run(
            [
                sys.executable,
                str(verifier),
                *[str(stage / name) for name in receipt["files"]],
                "--source-root",
                str(root / "benchbox/_binaries"),
            ],
            cwd=root,
            check=True,
        )
        current = select_producer(source["head_sha"], api)
        _require(current == (run, job, artifact), "producer changed during admission")
        _require(resolve_tag(root, tag) == source, "tagged source changed during admission")
        summary = {
            **source,
            "producer": receipt,
            "artifact_id": artifact["id"],
            "artifact_digest": artifact["digest"],
            "expires_at": artifact["expires_at"],
        }
        (stage / "admission-receipt.json").write_text(json.dumps(summary, indent=2) + "\n")
        _require(not output.exists(), "output appeared during admission")
        stage.rename(output)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    produce = commands.add_parser("producer")
    produce.add_argument("--dist", type=Path, required=True)
    consume = commands.add_parser("admit")
    consume.add_argument("--source", type=Path, required=True)
    consume.add_argument("--tag", required=True)
    consume.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "producer":
            run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
            run = github_json(f"actions/runs/{run_id}")
            _require(
                run["id"] == run_id and run["run_attempt"] == attempt and run["head_sha"] == os.environ["GITHUB_SHA"],
                "workflow context differs from API producer",
            )
            _require(run["repository"]["id"] == int(os.environ["GITHUB_REPOSITORY_ID"]), "repository context differs")
            jobs = _pages(github_json, f"actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
            matches = [job for job in jobs if job.get("name") == JOB_NAME]
            _require(
                len(matches) == 1 and matches[0].get("status") == "in_progress",
                "producer job is not unique and running",
            )
            receipt = producer_receipt(args.dist, run, matches[0])
            (args.dist / PRODUCER_RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n")
        else:
            subprocess.run(["git", "-C", str(args.source), "fetch", "--no-tags", "origin", "develop"], check=True)
            print(json.dumps(admit(args.source.resolve(), args.tag, args.output.resolve()), indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release artifact admission failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
