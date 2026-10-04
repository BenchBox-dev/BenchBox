from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.publication.assembler import compute_tree_digest
from scripts.site_deploy import (
    artifacts,
    candidate as candidate_module,
    deployments,
    generation,
    mixed_version,
    receipt as receipt_module,
    renderer as renderer_module,
    rollback as rollback_module,
)
from scripts.site_deploy.githubapi import ApiError, GitHubClient

RESOLVED_SCHEMA = "site-deploy-resolved/v1"
RECEIPT_ARTIFACT_PATTERN = re.compile(r"^site-deploy-receipt-(?P<run>\d+)-(?P<attempt>\d+)$")
RECEIPT_FILE = "receipt.json"
SITE_URL = "https://benchbox.dev"
ROUTES_MANIFEST = Path("deploy/routes.yml")


def _client() -> GitHubClient:
    return GitHubClient(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", ""))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _github_output(pairs: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def receipt_artifact_names(names: list[str], run_id: int) -> list[str]:
    found: list[tuple[int, str]] = []
    for name in names:
        match = RECEIPT_ARTIFACT_PATTERN.match(name)
        if match and int(match.group("run")) == run_id:
            found.append((int(match.group("attempt")), name))
    return [name for _, name in sorted(found, reverse=True)]


def _gh(*args: str) -> str:
    try:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        raise OSError(f"gh {' '.join(args[:3])} failed: {exc.stderr.strip()}") from exc


def gh_download(repo: str, run_id: int, name: str, destination: Path) -> None:
    _gh("run", "download", str(run_id), "--repo", repo, "-n", name, "-D", str(destination))


def gh_receipt_loader(repo: str) -> Any:
    def load(run_id: int, expected_sha256: str | None = None) -> bytes:
        listing = _gh(
            "api",
            "--paginate",
            f"repos/{repo}/actions/runs/{run_id}/artifacts",
            "--jq",
            ".artifacts[] | select(.expired == false) | .name",
        )
        for name in receipt_artifact_names(listing.split(), run_id):
            with tempfile.TemporaryDirectory(prefix="site-receipt-") as directory:
                gh_download(repo, run_id, name, Path(directory))
                raw = (Path(directory) / RECEIPT_FILE).read_bytes()
            if expected_sha256 is None or receipt_module.receipt_sha256(raw) == expected_sha256:
                return raw
        raise OSError(f"no retained receipt artifact of run {run_id} matches the recorded digest")

    return load


def _ancestry(repo_dir: Path) -> Any:
    return lambda ancestor, descendant: candidate_module.is_ancestor(repo_dir, ancestor, descendant)


def _parent(deployed: generation.Deployed | None) -> dict[str, Any] | None:
    if deployed is None:
        return None
    return {
        "run_id": deployed.run_id,
        "generation": deployed.generation,
        "receipt_sha256": deployed.receipt_sha256,
        "trunk_sha": deployed.trunk_sha,
        "release_tag": deployed.release_tag,
        "corpus_sha": deployed.corpus_sha,
        "artifact_sha256": deployed.artifact_sha256,
        "newer_unreceipted": deployed.newer_unreceipted,
    }


def _unknown_current(client: GitHubClient, loader: Any, target: dict[str, Any]) -> dict[str, Any]:
    newest = deployments.newest_deployment_id(
        client, int(os.environ["GITHUB_RUN_ID"]) if "GITHUB_RUN_ID" in os.environ else None
    )
    try:
        base = generation.read_deployed(client, loader, allow_bootstrap=True, require_good=False)
    except generation.GenerationAuthorityError:
        base = None
    base_generation = base.generation if base else int(target["generation"])
    parent = {
        "unknown": True,
        "run_id": None,
        "generation": base_generation,
        "basis_run_id": base.run_id if base else None,
        "newest_deployment_id": newest,
        "receipt_sha256": None,
        "trunk_sha": None,
        "release_tag": None,
        "corpus_sha": None,
        "artifact_sha256": None,
    }
    deployed = {
        "unknown": True,
        "run_id": None,
        "generation": base_generation,
        "receipt_sha256": None,
        "trunk_sha": None,
        "release_tag": None,
        "corpus_sha": None,
        "artifact_sha256": None,
        "ui_version": None,
        "snapshot_version": None,
        "link_baseline": {},
    }
    return {"parent": parent, "deployed": deployed, "newest_deployment_id": newest}


def _resolve_rollback(args: argparse.Namespace, client: GitHubClient, loader: Any) -> dict[str, Any]:
    recorded = rollback_module.recorded_shas(client, args.rollback_run_id)
    if not recorded:
        raise rollback_module.RollbackError(
            f"no receipt of run {args.rollback_run_id} is recorded on a github-pages deployment"
        )
    raw = loader(args.rollback_run_id, recorded[0])
    target = receipt_module.validate_receipt(json.loads(raw))
    rollback = {
        "run_id": args.rollback_run_id,
        "phase": args.rollback_phase,
        "receipt_sha256": receipt_module.receipt_sha256(raw),
    }
    restored_renderer = receipt_module.renderer_of(target)
    outcome = {
        "selection": {
            "renderer": restored_renderer,
            "policy": "receipt",
            "reason": f"rollback restores the {restored_renderer} artifact recorded in the target receipt",
        },
        "trunk_sha": target["trunk_sha"],
        "release_tag": target["release_tag"],
        "release_sha": target["release_sha"],
        "certifying_run_id": target.get("certifying_run_id"),
        "candidate_corpus": target["corpus_sha"],
        "candidate_artifact": target["artifact"]["sha256"],
        "rollback": rollback,
        "current_unknown": bool(args.current_unknown),
        "newest_deployment_id": None,
    }
    if args.current_unknown:
        if args.rollback_phase == "ui-first":
            raise rollback_module.RollbackError(
                "ui-first needs the current generation's artifact; an unknown current generation supports only full"
            )
        unknown = _unknown_current(client, loader, target)
        return {
            **outcome,
            "decision": generation.Decision(
                generation.DEPLOY,
                "rollback with an unknown current generation; current versions come from the live snapshot",
            ),
            "deployed": None,
            "deployed_record": unknown["deployed"],
            "parent_record": unknown["parent"],
            "newest_deployment_id": unknown["newest_deployment_id"],
        }
    deployed = generation.read_deployed(client, loader, allow_bootstrap=False, require_good=False)
    if args.rollback_phase == "ui-first" and deployed is not None and deployed.renderer != restored_renderer:
        raise rollback_module.RollbackError(
            f"ui-first would put the {restored_renderer} root 404.html into the deployed {deployed.renderer} "
            "artifact; roll back with the full phase"
        )
    decision = generation.generation_gate(
        candidate_trunk=target["trunk_sha"],
        candidate_tag=target["release_tag"],
        candidate_corpus=target["corpus_sha"],
        candidate_artifact=target["artifact"]["sha256"],
        deployed=deployed,
        mode="rollback",
        is_ancestor=_ancestry(args.repo_dir),
    )
    return {**outcome, "decision": decision, "deployed": deployed}


def _resolve_forward(args: argparse.Namespace, client: GitHubClient, loader: Any) -> dict[str, Any]:
    tag = candidate_module.latest_release_tag(candidate_module.release_tags(args.repo_dir))
    release_sha = candidate_module.tag_commit(args.repo_dir, tag)
    from scripts.site_deploy import routes as routes_module

    manifest = routes_module.load_manifest(args.repo_dir / ROUTES_MANIFEST)
    try:
        selection = renderer_module.select_for_commit(manifest.renderer_policy, args.repo_dir, release_sha)
    except renderer_module.RendererError as exc:
        raise candidate_module.CandidateError(f"renderer selection for {tag} failed: {exc}") from exc
    shas = candidate_module.first_parent_shas(args.repo_dir, "HEAD")
    found = candidate_module.find_candidate(client, shas, tag)
    bootstrap = args.bootstrap or args.mode == "preview"
    deployed = generation.read_deployed(client, loader, allow_bootstrap=bootstrap)
    decision = generation.generation_gate(
        candidate_trunk=found.trunk_sha,
        candidate_tag=tag,
        deployed=deployed,
        mode=args.mode,
        is_ancestor=_ancestry(args.repo_dir),
    )
    return {
        "selection": selection.to_dict(),
        "decision": decision,
        "deployed": deployed,
        "trunk_sha": found.trunk_sha,
        "release_tag": tag,
        "release_sha": release_sha,
        "certifying_run_id": found.certifying_run_id,
        "candidate_corpus": None,
        "rollback": None,
        "current_unknown": False,
        "newest_deployment_id": None,
    }


def visual_comparison_required(deployed: generation.Deployed | None, renderer: str, release_sha: str) -> bool:
    if deployed is None:
        return renderer == renderer_module.ASTRO
    return deployed.renderer != renderer or deployed.release_sha != release_sha


def visual_approval_binding(release_sha: str, candidate_sha256: str, baseline_sha256: str) -> str:
    return f"{release_sha}+{candidate_sha256}+{baseline_sha256}"


def command_resolve(args: argparse.Namespace) -> int:
    if args.current_unknown and args.mode != "rollback":
        raise rollback_module.RollbackError("--current-unknown applies only to rollback mode")
    client = _client()
    loader = gh_receipt_loader(client.repo)
    outcome = (
        _resolve_rollback(args, client, loader) if args.mode == "rollback" else _resolve_forward(args, client, loader)
    )
    decision = outcome["decision"]
    deployed = outcome["deployed"]
    selected = outcome["selection"]["renderer"]
    deployed_renderer = deployed.renderer if deployed else None
    visual_required = args.mode != "rollback" and visual_comparison_required(deployed, selected, outcome["release_sha"])
    resolved = {
        "schema": RESOLVED_SCHEMA,
        "mode": args.mode,
        "action": decision.action,
        "reason": decision.reason,
        "trunk_sha": outcome["trunk_sha"],
        "release_tag": outcome["release_tag"],
        "release_sha": outcome["release_sha"],
        "certifying_run_id": outcome["certifying_run_id"],
        "candidate_corpus": outcome["candidate_corpus"],
        "candidate_artifact": outcome.get("candidate_artifact"),
        "bootstrap": bool(args.bootstrap),
        "deployed": outcome.get("deployed_record") or (asdict(deployed) if deployed else None),
        "parent": outcome.get("parent_record") or _parent(deployed),
        "rollback": outcome["rollback"],
        "current_unknown": outcome["current_unknown"],
        "newest_deployment_id": outcome["newest_deployment_id"],
        "renderer": selected,
        "renderer_selection": outcome["selection"],
        "deployed_renderer": deployed_renderer,
        "visual_required": visual_required,
    }
    _write_json(args.output, resolved)
    _github_output(
        {
            "action": decision.action,
            "trunk_sha": resolved["trunk_sha"],
            "release_tag": resolved["release_tag"],
            "release_sha": resolved["release_sha"],
            "renderer": selected,
            "visual_required": "true" if visual_required else "false",
        }
    )
    print(f"{decision.action}: {decision.reason}")
    print(f"renderer {selected}: {outcome['selection']['reason']}")
    return 1 if decision.action == generation.REFUSE else 0


def command_recheck(args: argparse.Namespace) -> int:
    resolved = _read_json(args.resolved)
    client = _client()
    if resolved.get("current_unknown"):
        own_run = int(os.environ["GITHUB_RUN_ID"]) if "GITHUB_RUN_ID" in os.environ else None
        newest = deployments.newest_deployment_id(client, own_run)
        if newest != resolved["newest_deployment_id"]:
            print(
                f"refuse: newest github-pages deployment changed since resolution ({resolved['newest_deployment_id']} -> {newest})"
            )
            return 1
        print("deploy: newest github-pages deployment unchanged since resolution")
        return 0
    loader = gh_receipt_loader(client.repo)
    rollback = resolved["mode"] == "rollback"
    deployed = generation.read_deployed(
        client, loader, allow_bootstrap=resolved["bootstrap"], require_good=not rollback
    )
    decision = generation.recheck_decision(
        resolved_receipt_sha256=resolved["deployed"]["receipt_sha256"] if resolved["deployed"] else None,
        deployed=deployed,
        candidate_trunk=resolved["trunk_sha"],
        candidate_tag=resolved["release_tag"],
        candidate_corpus=resolved.get("candidate_corpus"),
        mode=resolved["mode"],
        is_ancestor=_ancestry(args.repo_dir),
        candidate_artifact=resolved.get("candidate_artifact"),
    )
    print(f"{decision.action}: {decision.reason}")
    return 0 if decision.action == generation.DEPLOY else 1


def _site_route_paths(assembly: dict[str, Any]) -> list[str]:
    return [route["path"] for route in assembly["routes"]]


def command_gates(args: argparse.Namespace) -> int:
    from scripts.site_deploy import checksums, gates as gates_module

    resolved = _read_json(args.resolved)
    assembly = _read_json(args.assembly)
    renderer = receipt_module.renderer_of(assembly)
    if renderer != receipt_module.renderer_of(resolved):
        raise renderer_module.RendererError(
            f"the assembly renderer {renderer} differs from the resolved {receipt_module.renderer_of(resolved)}"
        )
    corpus_sha = args.corpus_sha or gates_module.corpus_tree_sha(args.repo_root, resolved["trunk_sha"])
    deployed = resolved["deployed"]
    live_version = None
    if deployed and deployed.get("unknown"):
        if args.deployed_snapshot is None or not args.deployed_snapshot.is_file():
            raise rollback_module.RollbackError("an unknown current generation needs the live snapshot download")
        live_version = mixed_version.snapshot_version(args.deployed_snapshot)
        deployed = {**deployed, "ui_version": live_version, "snapshot_version": live_version}
    inputs = gates_module.GateInputs(
        repo_root=args.repo_root,
        site_dir=args.site_dir,
        work_dir=args.out_dir / "gate-work",
        trunk_sha=resolved["trunk_sha"],
        corpus_sha=corpus_sha,
        mode=resolved["mode"],
        deployed=deployed,
        deployed_snapshot=args.deployed_snapshot,
        rollback_phase=(resolved["rollback"] or {}).get("phase", "full"),
        ui_version=args.ui_version,
        release_tag=resolved["release_tag"],
        renderer=renderer,
        file_owners=assembly.get("file_owners"),
    )
    gates = gates_module.run_gates(inputs)
    if live_version is not None:
        gates["live_versions"] = {"ui_upper_bound": live_version, "snapshot": live_version}
    sha = gates_module.write_gates(args.out_dir / "gates.json", gates)
    _write_json(
        args.out_dir / "probe-checksums.json", checksums.checksum_manifest(args.site_dir, _site_route_paths(assembly))
    )
    for name, result in gates["results"].items():
        print(f"{result['status']:>7}  {name}: {str(result['detail']).splitlines()[0] if result['detail'] else ''}")
    print(f"gates.json sha256 {sha}")
    return 0 if gates["ok"] else 1


def command_finalize(args: argparse.Namespace) -> int:
    from scripts.site_deploy import probe as probe_module

    out = args.out_dir
    resolved = _read_json(out / "resolved.json")
    assembly = _read_json(out / "route-assembly.json")
    gates_raw = (out / "gates.json").read_bytes()
    gates = json.loads(gates_raw)
    gates["gates_sha256"] = receipt_module.receipt_sha256(gates_raw)
    checksums = _read_json(out / "probe-checksums.json")
    probes = probe_module.probe(args.base_url, checksums, out / "probe-work", attempts=args.attempts, delay=args.delay)
    run_id = args.run_id if args.run_id is not None else int(os.environ.get("GITHUB_RUN_ID", "0"))
    deployment_id = None
    if not args.no_status:
        deployment_id = deployments.find_run_deployment_id(_client(), run_id)
    versions = gates["results"]["mixed_version"].get("versions", {})
    parent = resolved["parent"]
    if parent and parent.get("unknown") and gates.get("live_versions"):
        parent = {**parent, "live_versions": gates["live_versions"]}
    built = receipt_module.build_receipt(
        mode=resolved["mode"],
        target=args.target,
        run_id=run_id,
        deployment_id=deployment_id,
        trunk_sha=resolved["trunk_sha"],
        release_tag=resolved["release_tag"],
        release_sha=resolved["release_sha"],
        corpus_sha=gates["corpus_sha"],
        assembly=assembly,
        artifact_name=args.artifact_name or f"site-deploy-artifact-{run_id}",
        versions=versions,
        gates=gates,
        probes=probes,
        parent=parent,
        certifying_run_id=resolved["certifying_run_id"],
        rollback=resolved["rollback"],
    )
    raw = receipt_module.canonical_bytes(built)
    sha = receipt_module.receipt_sha256(raw)
    receipt_dir = out / "receipt"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / RECEIPT_FILE).write_bytes(raw)
    print(f"receipt sha256 {sha} generation {built['generation']} probes_ok={probes['ok']}")
    return 0 if probes["ok"] else 1


def command_record(args: argparse.Namespace) -> int:
    raw = (args.out_dir / "receipt" / RECEIPT_FILE).read_bytes()
    built = receipt_module.validate_receipt(json.loads(raw))
    if not isinstance(built["deployment_id"], int):
        raise deployments.DeploymentLookupError("the receipt carries no deployment id to record against")
    if not receipt_module.is_last_known_good(built):
        raise deployments.DeploymentLookupError("the receipt is not last-known-good; only passing deploys are recorded")
    client = _client()
    deployments.post_receipt_status(
        client,
        built["deployment_id"],
        receipt_module.receipt_sha256(raw),
        built["run_id"],
        f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{client.repo}/actions/runs/{built['run_id']}",
        args.base_url,
    )
    print(f"recorded receipt of run {built['run_id']} on deployment {built['deployment_id']}")
    return 0


def command_fetch_run(args: argparse.Namespace) -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise rollback_module.RollbackError("GITHUB_REPOSITORY is required")
    raw = gh_receipt_loader(repo)(args.run_id, args.receipt_sha256)
    built = receipt_module.validate_receipt(json.loads(raw))
    args.receipt_dir.mkdir(parents=True, exist_ok=True)
    (args.receipt_dir / RECEIPT_FILE).write_bytes(raw)
    if args.tree_dir is not None:
        gh_download(repo, args.run_id, built["artifact"]["name"], args.tree_dir)
        if args.verify_tree:
            artifacts.verify_tree(args.tree_dir, built["artifact"]["sha256"])
    print(f"fetched run {args.run_id} receipt sha256 {receipt_module.receipt_sha256(raw)}")
    return 0


def command_visual_binding(args: argparse.Namespace) -> int:
    resolved = _read_json(args.out_dir / "resolved.json")
    assembly = _read_json(args.out_dir / "route-assembly.json")
    baseline = (resolved.get("deployed") or {}).get("artifact_sha256")
    if not baseline:
        raise artifacts.ArtifactError("no deployed artifact digest to bind the visual comparison to")
    candidate = assembly["tree_sha256"]
    artifacts.verify_tree(args.candidate, candidate)
    artifacts.verify_tree(args.baseline, baseline)
    binding = visual_approval_binding(resolved["release_sha"], candidate, baseline)
    _write_json(
        args.out_dir / "visual-binding.json",
        {
            "binding": binding,
            "release_tag": resolved["release_tag"],
            "release_sha": resolved["release_sha"],
            "candidate_sha256": candidate,
            "baseline_sha256": baseline,
        },
    )
    _github_output({"binding": binding})
    print(f"visual approval binding {binding}")
    return 0


def command_rollback_prepare(args: argparse.Namespace) -> int:
    resolved = _read_json(args.resolved)
    restore = rollback_module.load_restore(args.receipt, args.restored_tree)
    expected = (resolved.get("rollback") or {}).get("receipt_sha256")
    if not expected or restore.receipt_sha256 != expected:
        raise rollback_module.RollbackError(
            f"downloaded receipt sha256 {restore.receipt_sha256} does not match the resolved {expected}"
        )
    routes = restore.receipt["routes"]
    if args.phase == "ui-first":
        if args.current_tree is None or args.current_receipt is None:
            raise SystemExit("--current-tree and --current-receipt are required for the ui-first phase")
        current_sha = (resolved.get("deployed") or {}).get("artifact_sha256")
        if not current_sha:
            raise rollback_module.RollbackError("resolved.json carries no deployed artifact digest for ui-first")
        artifacts.verify_tree(args.current_tree, current_sha)
        current = rollback_module.load_restore(args.current_receipt, args.current_tree)
        if current.receipt_sha256 != (resolved.get("deployed") or {}).get("receipt_sha256"):
            raise rollback_module.RollbackError("the current receipt is not the deployed generation's receipt")
        digest = artifacts.compose_ui_first(args.current_tree, args.restored_tree, args.site_dir)
        composed_results = args.site_dir / artifacts.RESULTS_DIR
        composed_digest = compute_tree_digest(composed_results)[0]
        current_corpus = resolved["deployed"]["corpus_sha"]
        restored_results = []
        for route in restore.receipt["routes"]:
            if route["path"] != "/results/":
                continue
            pins = artifacts.explorer_pins(composed_results, args.out_dir / "pins-work", route.get("source_sha"))
            pins["snapshot"]["corpus_sha"] = current_corpus
            lanes = route.get("lane_sha256") or {f"{route['path']}:results": ""}
            restored_results.append(
                {
                    **route,
                    "lane_sha256": dict.fromkeys(lanes, composed_digest),
                    "corpus_sha": current_corpus,
                    "pins": pins,
                }
            )
        routes = [route for route in current.receipt["routes"] if route["path"] != "/results/"] + restored_results
        files = sum(1 for path in args.site_dir.rglob("*") if path.is_file())
    else:
        if args.site_dir.exists():
            shutil.rmtree(args.site_dir)
        shutil.copytree(args.restored_tree, args.site_dir)
        digest = restore.receipt["artifact"]["sha256"]
        files = restore.receipt["artifact"]["total_files"]
    total = sum(path.stat().st_size for path in args.site_dir.rglob("*") if path.is_file())
    corpus_sha = restore.receipt["corpus_sha"]
    if args.phase == "ui-first":
        corpus_sha = resolved["deployed"]["corpus_sha"]
    renderers = {receipt_module.renderer_of(route) for route in routes}
    if len(renderers) != 1:
        raise rollback_module.RollbackError(f"the restored routes mix renderers {sorted(renderers)}")
    assembly = {
        "renderer": renderers.pop(),
        "routes": routes,
        "tree_sha256": digest,
        "total_bytes": total,
        "total_files": files,
    }
    _write_json(args.out_dir / "route-assembly.json", assembly)
    _write_json(
        args.out_dir / "restore.json",
        {
            "restored_run_id": restore.receipt["run_id"],
            "restored_receipt_sha256": restore.receipt_sha256,
            "ui_version": restore.receipt["versions"]["ui_expected"],
            "corpus_sha": corpus_sha,
            "phase": args.phase,
        },
    )
    print(f"restored run {restore.receipt['run_id']} phase {args.phase} tree sha256 {digest}")
    return 0


def command_preview(args: argparse.Namespace) -> int:
    from scripts.site_deploy import parity, probe as probe_module, publish

    out = args.out_dir
    resolved = _read_json(out / "resolved.json")
    assembly = _read_json(out / "route-assembly.json")
    gates = _read_json(out / "gates.json")
    checksums = _read_json(out / "probe-checksums.json")
    versions = gates["results"]["mixed_version"].get("versions", {})
    report = parity.parity_report(args.legacy_site, args.site_dir, out / "parity-work")
    parity.write_report(out / "parity.json", report)
    drill = publish.run_drill(
        legacy_tree=args.legacy_site,
        routes_tree=args.site_dir,
        route_paths=_site_route_paths(assembly),
        trunk_sha=resolved["trunk_sha"],
        release_tag=resolved["release_tag"],
        release_sha=resolved["release_sha"],
        corpus_sha=gates["corpus_sha"],
        routes_assembly=assembly,
        versions=versions,
        gates=gates,
        work_dir=out / "drill-work",
        receipts_dir=out / "preview-receipts",
    )
    if args.production_url:
        drill["production_comparison"] = probe_module.compare_live(args.production_url, checksums)
        _write_json(out / "production-parity.json", drill["production_comparison"])
    _write_json(out / "preview-drill.json", drill)
    print(json.dumps({"ok": drill["ok"], "steps": drill["steps"]}, indent=2))
    return 0 if drill["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="site_deploy")
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve")
    resolve.add_argument("--mode", choices=generation.MODES, required=True)
    resolve.add_argument("--repo-dir", type=Path, default=Path("."))
    resolve.add_argument("--rollback-run-id", type=int)
    resolve.add_argument("--rollback-phase", choices=("full", "ui-first"), default="full")
    resolve.add_argument("--bootstrap", action="store_true")
    resolve.add_argument("--current-unknown", action="store_true")
    resolve.add_argument("--output", type=Path, required=True)
    resolve.set_defaults(handler=command_resolve)

    recheck = commands.add_parser("recheck")
    recheck.add_argument("--resolved", type=Path, required=True)
    recheck.add_argument("--repo-dir", type=Path, default=Path("."))
    recheck.set_defaults(handler=command_recheck)

    gates = commands.add_parser("gates")
    gates.add_argument("--repo-root", type=Path, required=True)
    gates.add_argument("--site-dir", type=Path, required=True)
    gates.add_argument("--resolved", type=Path, required=True)
    gates.add_argument("--assembly", type=Path, required=True)
    gates.add_argument("--out-dir", type=Path, required=True)
    gates.add_argument("--deployed-snapshot", type=Path)
    gates.add_argument("--corpus-sha")
    gates.add_argument("--ui-version", type=int)
    gates.set_defaults(handler=command_gates)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--out-dir", type=Path, required=True)
    finalize.add_argument("--base-url", default=SITE_URL)
    finalize.add_argument("--target", default="github-pages")
    finalize.add_argument("--run-id", type=int)
    finalize.add_argument("--attempts", type=int, default=6)
    finalize.add_argument("--delay", type=float, default=10.0)
    finalize.add_argument("--artifact-name")
    finalize.add_argument("--no-status", action="store_true")
    finalize.set_defaults(handler=command_finalize)

    record = commands.add_parser("record")
    record.add_argument("--out-dir", type=Path, required=True)
    record.add_argument("--base-url", default=SITE_URL)
    record.set_defaults(handler=command_record)

    fetch = commands.add_parser("fetch-run")
    fetch.add_argument("--run-id", type=int, required=True)
    fetch.add_argument("--receipt-sha256")
    fetch.add_argument("--receipt-dir", type=Path, required=True)
    fetch.add_argument("--tree-dir", type=Path)
    fetch.add_argument("--verify-tree", action="store_true")
    fetch.set_defaults(handler=command_fetch_run)

    binding = commands.add_parser("visual-binding")
    binding.add_argument("--out-dir", type=Path, required=True)
    binding.add_argument("--candidate", type=Path, required=True)
    binding.add_argument("--baseline", type=Path, required=True)
    binding.set_defaults(handler=command_visual_binding)

    prepare = commands.add_parser("rollback-prepare")
    prepare.add_argument("--receipt", type=Path, required=True)
    prepare.add_argument("--restored-tree", type=Path, required=True)
    prepare.add_argument("--current-tree", type=Path)
    prepare.add_argument("--current-receipt", type=Path)
    prepare.add_argument("--phase", choices=("full", "ui-first"), default="full")
    prepare.add_argument("--resolved", type=Path, required=True)
    prepare.add_argument("--site-dir", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    prepare.set_defaults(handler=command_rollback_prepare)

    preview = commands.add_parser("preview")
    preview.add_argument("--site-dir", type=Path, required=True)
    preview.add_argument("--legacy-site", type=Path, required=True)
    preview.add_argument("--out-dir", type=Path, required=True)
    preview.add_argument("--production-url")
    preview.set_defaults(handler=command_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        ApiError,
        candidate_module.CandidateError,
        generation.GenerationAuthorityError,
        deployments.DeploymentLookupError,
        artifacts.ArtifactError,
        mixed_version.VersionError,
        receipt_module.ReceiptError,
        rollback_module.RollbackError,
        renderer_module.RendererError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"refuse: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
