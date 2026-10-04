from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.site_deploy import mixed_version, routes as routes_module
from scripts.site_deploy.candidate import SEMVER_TAG
from scripts.site_inventory import INFO_KINDS

PASS = "pass"
FAIL = "fail"
SKIPPED = "skipped"
SCRIPTS = Path(__file__).resolve().parents[1]
PUBLICATION = SCRIPTS / "publication"
SNAPSHOT_RELATIVE = Path("results/data/results.duckdb")
OUTPUT_TAIL_LINES = 40


@dataclass(frozen=True)
class GateInputs:
    repo_root: Path
    site_dir: Path
    work_dir: Path
    trunk_sha: str
    corpus_sha: str
    mode: str
    deployed: dict[str, Any] | None
    deployed_snapshot: Path | None
    rollback_phase: str = mixed_version.PHASE_FULL
    ui_version: int | None = None
    release_tag: str | None = None
    routes_manifest: Path | None = None


Runner = Callable[[list[str], Path], tuple[int, str]]


def run_subprocess(command: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-OUTPUT_TAIL_LINES:])
    return result.returncode, tail


def _result(status: str, detail: str, command: list[str] | None = None, code: int | None = None) -> dict[str, Any]:
    return {"status": status, "detail": detail, "command": command, "exit_code": code}


def _from_run(runner: Runner, command: list[str], cwd: Path) -> dict[str, Any]:
    code, tail = runner(command, cwd)
    return _result(PASS if code == 0 else FAIL, tail, command, code)


def corpus_tree_sha(repo_root: Path, sha: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{sha}:results-data"], check=True, capture_output=True, text=True
    ).stdout.strip()


def privacy_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    command = [sys.executable, str(PUBLICATION / "check_artifact_privacy.py"), str(inputs.site_dir)]
    return _from_run(runner, command, inputs.repo_root)


def explorer_compat_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    command = [
        sys.executable,
        str(PUBLICATION / "check_explorer_compat.py"),
        "--artifact",
        str(inputs.site_dir / "results"),
        "--db-path",
        str(inputs.site_dir / SNAPSHOT_RELATIVE),
    ]
    return _from_run(runner, command, inputs.repo_root)


def mixed_version_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    del runner
    try:
        candidate = mixed_version.Versions(
            ui=inputs.ui_version
            if inputs.ui_version is not None
            else mixed_version.ui_expected_from_tree(inputs.repo_root),
            snapshot=mixed_version.snapshot_version(inputs.site_dir / SNAPSHOT_RELATIVE),
        )
    except mixed_version.VersionError as exc:
        return _result(FAIL, str(exc))
    current = None
    if inputs.deployed is not None:
        current = mixed_version.Versions(
            ui=int(inputs.deployed["ui_version"]), snapshot=int(inputs.deployed["snapshot_version"])
        )
    kind = mixed_version.ROLLBACK if inputs.mode == "rollback" else mixed_version.FORWARD
    evaluation = mixed_version.evaluate(candidate, current, kind, inputs.rollback_phase)
    result = _result(PASS if evaluation.ok else FAIL, evaluation.reason)
    result["evaluation"] = evaluation.to_dict()
    result["versions"] = {"ui_expected": candidate.ui, "snapshot": candidate.snapshot}
    return result


def corpus_bijection_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    command = [
        sys.executable,
        str(PUBLICATION / "check_corpus_bijection.py"),
        "--accepted-ref",
        inputs.trunk_sha,
        "--expect-source",
        inputs.trunk_sha,
        "--bundles-dir",
        str(inputs.repo_root / "results-data" / "bundles"),
        "--artifact",
        str(inputs.site_dir / SNAPSHOT_RELATIVE),
        "--require-artifact",
        "--ledger-seed",
        str(inputs.repo_root / "publication" / "ledger-seed.json"),
    ]
    return _from_run(runner, command, inputs.repo_root)


def digest_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    if inputs.deployed is None:
        return _result(SKIPPED, "no deployed generation to compare against")
    if inputs.deployed_snapshot is None or not inputs.deployed_snapshot.is_file():
        return _result(FAIL, "deployed snapshot was not provided for the digest comparison")
    candidate = inputs.site_dir / SNAPSHOT_RELATIVE
    tool = str(PUBLICATION / "compare_db_digest.py")
    if inputs.deployed["corpus_sha"] == inputs.corpus_sha:
        return _from_run(
            runner, [sys.executable, tool, "compare", str(candidate), str(inputs.deployed_snapshot)], inputs.repo_root
        )
    digests = {}
    for label, path in (("candidate", candidate), ("deployed", inputs.deployed_snapshot)):
        code, tail = runner([sys.executable, tool, "digest", str(path)], inputs.repo_root)
        if code != 0:
            return _result(FAIL, f"{label} digest failed: {tail}")
        digests[label] = tail.strip().splitlines()[-1]
    result = _result(SKIPPED, "corpus changed; digests recorded without equality requirement")
    result["digests"] = digests
    return result


def validator_parity_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    if inputs.deployed is None:
        return _result(SKIPPED, "no deployed corpus to use as the parity base")
    if inputs.deployed["corpus_sha"] == inputs.corpus_sha:
        return _result(SKIPPED, "corpus tree unchanged since the deployed generation")
    base = inputs.deployed["trunk_sha"]
    command = [
        sys.executable,
        str(PUBLICATION / "validator_parity.py"),
        "--base-sha",
        base,
        "--merge-sha",
        inputs.trunk_sha,
        "--head-sha",
        inputs.trunk_sha,
    ]
    return _from_run(runner, command, inputs.repo_root)


DEV_DOCS_PREFIX = "/docs/dev/"
ROUTES_MANIFEST_RELATIVE = Path("deploy/routes.yml")


def _remap_docs(path: str) -> str:
    if path.startswith("/docs/"):
        return DEV_DOCS_PREFIX + path[len("/docs/") :]
    return path


def routed_allowance(known: list[list[str]]) -> list[list[str]]:
    remapped = [[_remap_docs(source), _remap_docs(target), reason] for source, target, reason in known]
    return known + [entry for entry in remapped if entry not in known]


LINK_KINDS = ("broken internal link", "missing path", "missing fragment")


def _only_broken_links(summary: str) -> bool:
    counts: dict[str, int] = {}
    for part in summary.removeprefix("summary:").split(","):
        number, _, kind = part.strip().partition(" ")
        if not number.isdigit():
            return False
        counts[kind] = int(number)
    tolerated = LINK_KINDS + INFO_KINDS
    return bool(counts) and all(count == 0 for kind, count in counts.items() if kind not in tolerated)


RELEASE_ALLOWANCE_RELATIVE = Path("_project/design/site-inventory/release-known-broken")


def _release_baseline(
    inputs: GateInputs, release_owned_known: list[tuple[str, ...]]
) -> tuple[set[tuple[str, ...]], str]:
    recorded = (inputs.deployed or {}).get("link_baseline") or {}
    if inputs.release_tag is not None and inputs.release_tag in recorded:
        return {tuple(entry) for entry in recorded[inputs.release_tag]}, "last deployed receipt"
    baseline = set(release_owned_known)
    if inputs.release_tag is not None and SEMVER_TAG.match(inputs.release_tag):
        tag_file = inputs.repo_root / RELEASE_ALLOWANCE_RELATIVE / f"{inputs.release_tag}.json"
        if tag_file.is_file():
            baseline |= {tuple(entry) for entry in json.loads(tag_file.read_text(encoding="utf-8"))}
            return baseline, f"allowance files (develop and {tag_file.name})"
    return baseline, "allowance file"


def link_gate(inputs: GateInputs, runner: Runner) -> dict[str, Any]:
    manifest = routes_module.load_manifest(inputs.routes_manifest or inputs.repo_root / ROUTES_MANIFEST_RELATIVE)
    inputs.work_dir.mkdir(parents=True, exist_ok=True)
    inventory = inputs.work_dir / "site-inventory.json"
    tool = str(SCRIPTS / "site_inventory.py")
    build = [sys.executable, tool, "build", "--site-dir", str(inputs.site_dir), "--output", str(inventory)]
    build += ["--source-sha", inputs.trunk_sha]
    code, tail = runner(build, inputs.repo_root)
    if code != 0:
        return _result(FAIL, f"inventory build failed: {tail}", build, code)
    command = [sys.executable, tool, "check", "--inventory", str(inventory)]
    known: list[list[str]] = []
    known_broken = inputs.repo_root / "_project" / "design" / "site-inventory" / "known-broken-links.json"
    if known_broken.is_file():
        known = routed_allowance(json.loads(known_broken.read_text(encoding="utf-8")))
        allowance = inputs.work_dir / "known-broken-routed.json"
        allowance.write_text(json.dumps(known), encoding="utf-8")
        command += ["--known-broken", str(allowance)]
    code, tail = runner(command, inputs.repo_root)
    if code != 0 and not _only_broken_links(tail.strip().splitlines()[-1] if tail.strip() else ""):
        return _result(FAIL, tail, command, code)
    listing_path = inputs.work_dir / "broken-links.json"
    dump = [sys.executable, tool, "check", "--inventory", str(inventory), "--write-known-broken", str(listing_path)]
    dump_code, dump_tail = runner(dump, inputs.repo_root)
    if dump_code != 0:
        return _result(FAIL, f"broken link listing failed: {dump_tail}", dump, dump_code)
    listing = [tuple(entry) for entry in json.loads(listing_path.read_text(encoding="utf-8"))]
    allowed = {tuple(entry) for entry in known}

    def trunk_involved(entry: tuple[str, ...]) -> bool:
        return any(routes_module.is_trunk_owned(manifest, endpoint) for endpoint in entry[:2])

    fresh_trunk = [entry for entry in listing if entry not in allowed and trunk_involved(entry)]
    if fresh_trunk:
        return _result(
            FAIL, f"{len(fresh_trunk)} new broken links touching trunk routes, first: {fresh_trunk[0]}", command, code
        )
    release_links = sorted({entry for entry in listing if not trunk_involved(entry)})
    baseline, source = _release_baseline(inputs, [tuple(entry) for entry in known if not trunk_involved(tuple(entry))])
    outside = [entry for entry in release_links if entry not in baseline]
    if outside:
        return _result(
            FAIL,
            f"{len(outside)} broken links in release-tag pages are outside the {source} baseline "
            f"of {len(baseline)} for {inputs.release_tag}, first: {outside[0]}",
            command,
            code,
        )
    result = _result(
        PASS,
        f"{len(release_links)} broken links from release tag {inputs.release_tag} "
        f"within the {source} baseline of {len(baseline)}",
        command,
        code,
    )
    result["link_baseline"] = {
        "release_tag": inputs.release_tag,
        "broken": len(release_links),
        "links": [list(entry) for entry in release_links],
    }
    return result


GATES: tuple[tuple[str, Callable[[GateInputs, Runner], dict[str, Any]]], ...] = (
    ("privacy", privacy_gate),
    ("explorer_compat", explorer_compat_gate),
    ("mixed_version", mixed_version_gate),
    ("corpus_bijection", corpus_bijection_gate),
    ("digest", digest_gate),
    ("validator_parity", validator_parity_gate),
    ("links", link_gate),
)


ROLLBACK_GATES = ("privacy", "explorer_compat", "mixed_version")


def run_gates(inputs: GateInputs, runner: Runner = run_subprocess) -> dict[str, Any]:
    inputs.work_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for name, gate in GATES:
        if inputs.mode == "rollback" and name not in ROLLBACK_GATES:
            results[name] = _result(SKIPPED, "a restored artifact was gated when it was first deployed")
            continue
        try:
            results[name] = gate(inputs, runner)
        except Exception as exc:
            results[name] = _result(FAIL, f"gate raised {type(exc).__name__}: {exc}")
    return {
        "ok": all(result["status"] != FAIL for result in results.values()),
        "trunk_sha": inputs.trunk_sha,
        "corpus_sha": inputs.corpus_sha,
        "mode": inputs.mode,
        "results": results,
    }


def write_gates(path: Path, gates: dict[str, Any]) -> str:
    raw = (json.dumps(gates, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()
