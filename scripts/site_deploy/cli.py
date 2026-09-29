"""Command line for the site-deploy workflow.

Run as ``python -m scripts.site_deploy <command>``. Every command reads and writes
plain files; commands that feed later workflow steps also append ``key=value``
lines to ``$GITHUB_OUTPUT`` when ``--github-output`` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts import assemble_public_site as assembler
from scripts.site_deploy import candidate, generation, pipeline, probe, receipt, rollback, state
from scripts.site_deploy.github import GitHubError, gh_api

REPO_ROOT = Path(__file__).resolve().parents[2]


def _download_artifact(repo: str, artifact_id: int) -> bytes:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"], check=False, capture_output=True
    )
    if result.returncode != 0:
        raise GitHubError(f"artifact {artifact_id} download failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _emit(args: argparse.Namespace, values: dict[str, Any]) -> None:
    text = "".join(
        f"{key}={str(value).lower() if isinstance(value, bool) else value}\n" for key, value in values.items()
    )
    if getattr(args, "github_output", False) and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(text)


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return receipt.read_receipt(path)


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    sub.add_argument("--github-output", action="store_true", help="append outputs to $GITHUB_OUTPUT")


def _add_pins(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--manifest", type=Path, default=Path("site/routes.yml"))
    sub.add_argument("--repo-slug", default=os.environ.get("GITHUB_REPOSITORY", ""))
    sub.add_argument("--trunk-ref", default="origin/develop")
    sub.add_argument(
        "--trunk-sha", default="", help="pin the trunk commit instead of selecting the newest eligible one"
    )
    sub.add_argument("--release-tag", default="", help="pin the release tag instead of the latest vX.Y.Z")
    sub.add_argument("--corpus-ref", default=pipeline.DEFAULT_CORPUS_REF)
    sub.add_argument(
        "--identity-mode",
        choices=(pipeline.IDENTITY_CI, pipeline.IDENTITY_SKIP),
        default=pipeline.IDENTITY_CI,
        help="'skip' bypasses the merge-queue ci.yml proof and is accepted for preview runs only",
    )
    sub.add_argument("--previous-receipt", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="site-deploy", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prev = commands.add_parser("previous", help="fetch the receipt of the currently deployed site-deploy run")
    _add_common(prev)
    prev.add_argument("--repo-slug", default=os.environ.get("GITHUB_REPOSITORY", ""))
    prev.add_argument("--out", type=Path, required=True)
    prev.add_argument("--allow-foreign-writer", action="store_true")

    cand = commands.add_parser("candidate", help="report whether a trunk commit passed the merge queue")
    _add_common(cand)
    cand.add_argument("--repo-slug", default=os.environ.get("GITHUB_REPOSITORY", ""))
    cand.add_argument("--trunk-ref", default="origin/develop")
    cand.add_argument("--sha", default="")

    plan = commands.add_parser("plan", help="pin inputs and decide whether the run may proceed")
    _add_common(plan)
    _add_pins(plan)
    plan.add_argument("--target", choices=("preview", "production"), required=True)
    plan.add_argument("--out", type=Path, required=True)

    for name in ("prepare", "dry-run"):
        cmd = commands.add_parser(name, help="assemble, gate, and write the candidate receipt and artifact")
        _add_common(cmd)
        _add_pins(cmd)
        cmd.add_argument("--target", choices=("preview", "production"), required=(name == "prepare"), default="preview")
        cmd.add_argument("--out-dir", type=Path, required=True)
        cmd.add_argument("--work-dir", type=Path, default=None)
        cmd.add_argument("--waive-cache-window", action="store_true")
        cmd.add_argument("--skip-gate", action="append", default=[], choices=pipeline.ALL_GATES)
        cmd.add_argument("--shared-env", action="store_true")
        if name == "dry-run":
            cmd.add_argument("--probe-attempts", type=int, default=1)

    pr = commands.add_parser("probe", help="fetch every receipt route and compare served bytes")
    _add_common(pr)
    pr.add_argument("--base-url", default="")
    pr.add_argument("--serve", type=Path, default=None, help="serve this directory locally and probe it instead")
    pr.add_argument("--receipt", type=Path, required=True)
    pr.add_argument("--attempts", type=int, default=1)
    pr.add_argument("--delay", type=float, default=20.0)
    pr.add_argument("--out", type=Path, required=True)

    fin = commands.add_parser("finalize", help="record deployment and probe outcomes in the receipt")
    _add_common(fin)
    fin.add_argument("--receipt", type=Path, required=True)
    fin.add_argument("--probes", type=Path, required=True)
    fin.add_argument("--out", type=Path, required=True)
    fin.add_argument("--deployment-confirmed", action="store_true")
    fin.add_argument("--pages-url", default="")

    rp = commands.add_parser("rollback-plan", help="verify a prior receipt is last-known-good and older")
    _add_common(rp)
    rp.add_argument("--repo-slug", default=os.environ.get("GITHUB_REPOSITORY", ""))
    rp.add_argument("--target-run-id", type=int, required=True)
    rp.add_argument("--previous-receipt", type=Path, required=True)
    rp.add_argument("--out", type=Path, required=True)
    rp.add_argument("--target-receipt-out", type=Path, required=True)
    rp.add_argument("--live-unconfirmed", action="store_true")

    rs = commands.add_parser("rollback-stage", help="verify and extract the retained artifact of a prior receipt")
    _add_common(rs)
    rs.add_argument("--target-receipt", type=Path, required=True)
    rs.add_argument("--previous-receipt", type=Path, required=True)
    rs.add_argument("--archive", type=Path, required=True)
    rs.add_argument("--out-dir", type=Path, required=True)
    rs.add_argument("--target", choices=("preview", "production"), required=True)
    rs.add_argument("--waive-cache-window", action="store_true")

    rec = commands.add_parser("record", help="attach the receipt index to the Pages Deployment")
    _add_common(rec)
    rec.add_argument("--repo-slug", default=os.environ.get("GITHUB_REPOSITORY", ""))
    rec.add_argument("--receipt", type=Path, required=True)
    rec.add_argument("--sha", required=True)
    rec.add_argument("--run-started-at", required=True)
    rec.add_argument("--log-url", required=True)
    return parser


def _plan_from_args(args: argparse.Namespace, previous: dict[str, Any] | None, manifest: assembler.RouteManifest):
    api = gh_api if args.repo_slug and args.identity_mode == pipeline.IDENTITY_CI else None
    return pipeline.make_plan(
        repo_root=args.repo_root,
        manifest=manifest,
        previous=previous,
        trunk_sha=args.trunk_sha or None,
        release_tag=args.release_tag or None,
        corpus_ref=args.corpus_ref,
        trunk_ref=args.trunk_ref,
        identity_mode=args.identity_mode,
        api=api,
        repo_slug=args.repo_slug,
    )


def _cmd_previous(args: argparse.Namespace) -> int:
    live, foreign = state.find_live_record(args.repo_slug, gh_api)
    if foreign and not args.allow_foreign_writer:
        print(
            "::error::a deployment from another writer is newer than the last site-deploy receipt; "
            "confirm the live site and re-run with allow_foreign_writer"
        )
        _emit(args, {"found": False, "foreign_writer": True})
        return 1
    if live is None or live.run_id is None:
        _emit(args, {"found": False, "foreign_writer": foreign})
        print("no previous site-deploy receipt")
        return 0
    data = state.fetch_receipt(
        args.repo_slug, live.run_id, gh_api, _download_artifact, allow_failed_run=not live.verified
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(receipt.dumps(data), encoding="utf-8")
    _emit(
        args,
        {"found": True, "foreign_writer": foreign, "previous_run_id": live.run_id, "previous_verified": live.verified},
    )
    print(f"previous receipt: run {live.run_id} ({live.description})")
    return 0


def _cmd_candidate(args: argparse.Namespace) -> int:
    tip = assembler._verify_commit(args.repo_root, args.trunk_ref)  # noqa: SLF001
    history = generation.first_parent_shas(args.repo_root, tip, pipeline.TRUNK_HISTORY_LIMIT)
    if args.sha:
        runs = candidate.fetch_runs_for_sha(args.repo_slug, args.sha, gh_api)
        verdict = candidate.check_candidate(args.sha, runs, history)
    else:
        found = candidate.select_latest_eligible(candidate.fetch_merge_group_runs(args.repo_slug, gh_api), history)
        if found is None:
            print("no eligible trunk commit found", file=sys.stderr)
            return 1
        verdict = found
    print(json.dumps(verdict.to_dict(), indent=2))
    _emit(args, {"sha": verdict.sha, "eligible": verdict.eligible})
    return 0 if verdict.eligible else 1


def _cmd_plan(args: argparse.Namespace) -> int:
    manifest = assembler.load_manifest(args.manifest)
    plan = _plan_from_args(args, _load_json(args.previous_receipt), manifest)
    pipeline.write_json(args.out, plan.to_dict())
    print(json.dumps(plan.to_dict(), indent=2))
    _emit(
        args,
        {
            "trunk_sha": plan.generation.trunk_sha,
            "release_tag": plan.generation.release_tag,
            "corpus_sha": plan.generation.corpus_sha,
            "verdict": plan.decision.verdict.value,
            "allowed": plan.decision.allowed,
        },
    )
    if plan.decision.verdict is generation.Verdict.REFUSE and args.target == "production":
        print("::error::" + "; ".join(plan.decision.reasons))
        return 1
    return 0


def _cmd_prepare(args: argparse.Namespace) -> int:
    manifest = assembler.load_manifest(args.manifest)
    previous = _load_json(args.previous_receipt)
    plan = _plan_from_args(args, previous, manifest)
    if args.target == "production" and not plan.decision.allowed:
        print("::error::" + "; ".join(plan.decision.reasons))
        return 1
    work_dir = args.work_dir or args.out_dir.parent / f"{args.out_dir.name}-work"
    prepared = pipeline.prepare_candidate(
        repo_root=args.repo_root,
        manifest=manifest,
        plan=plan,
        out_dir=args.out_dir,
        work_dir=work_dir,
        target=args.target,
        previous_receipt=previous,
        waive_cache_window=args.waive_cache_window,
        skip_gates=frozenset(args.skip_gate),
        isolate_envs=not args.shared_env,
    )
    pipeline.write_json(args.out_dir / "gates.json", [g.to_dict() for g in prepared.gates])
    for gate in prepared.gates:
        print(f"{'PASS' if gate.ok else 'FAIL'} {gate.name}: {gate.detail}")
    _emit(
        args,
        {
            "artifact_sha256": prepared.receipt["artifact"]["sha256"],
            "tree_digest": prepared.receipt["artifact"]["tree_digest"],
            "gates_ok": prepared.ok,
        },
    )
    if not prepared.ok:
        print("::error::pre-deploy gates failed")
        return 1
    return 0


def _cmd_dry_run(args: argparse.Namespace) -> int:
    code = _cmd_prepare(args)
    if code != 0:
        return code
    receipt_path = args.out_dir / receipt.RECEIPT_NAME
    candidate_receipt = receipt.read_receipt(receipt_path)
    mounts = [route["mount"] for route in candidate_receipt["routes"]]
    with probe.serve_directory(args.out_dir / "site") as base_url:
        summary = probe.probe_with_retries(
            base_url, receipt_path, mounts, attempts=args.probe_attempts, delay_seconds=1.0
        )
    final = receipt.finalize_receipt(
        candidate_receipt,
        probes=summary,
        deployment={"confirmed": False, "mode": "local-static-server"},
        observed_at=pipeline.utc_now(),
    )
    (args.out_dir / "receipt.final.json").write_text(receipt.dumps(final), encoding="utf-8")
    print(f"probes: ok={summary['ok']} checked={summary['checked']} matched={summary['matched']}")
    print(f"receipt: {args.out_dir / 'receipt.final.json'} status={final['status']}")
    for error in summary["errors"]:
        print(f"::error::{error}")
    return 0 if summary["ok"] else 1


def _cmd_probe(args: argparse.Namespace) -> int:
    data = receipt.read_receipt(args.receipt)
    mounts = [route["mount"] for route in data["routes"]]
    if bool(args.base_url) == bool(args.serve):
        raise pipeline.PipelineError("give exactly one of --base-url or --serve")
    if args.serve:
        with probe.serve_directory(args.serve) as local_url:
            summary = probe.probe_with_retries(local_url, args.receipt, mounts, attempts=1)
    else:
        summary = probe.probe_with_retries(
            args.base_url, args.receipt, mounts, attempts=args.attempts, delay_seconds=args.delay
        )
    pipeline.write_json(args.out, summary)
    print(f"probes: ok={summary['ok']} checked={summary['checked']} matched={summary['matched']}")
    for error in summary["errors"]:
        print(f"::error::{error}")
    _emit(args, {"probes_ok": summary["ok"]})
    return 0 if summary["ok"] else 1


def _cmd_finalize(args: argparse.Namespace) -> int:
    data = receipt.read_receipt(args.receipt)
    probes = json.loads(args.probes.read_text(encoding="utf-8"))
    final = receipt.finalize_receipt(
        data,
        probes=probes,
        deployment={"confirmed": bool(args.deployment_confirmed), "pages_url": args.pages_url},
        observed_at=pipeline.utc_now(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(receipt.dumps(final), encoding="utf-8")
    _emit(args, {"status": final["status"]})
    print(f"receipt status: {final['status']}")
    return 0 if final["status"] in (receipt.STATUS_LIVE_VERIFIED, receipt.STATUS_PREVIEW_VERIFIED) else 1


def _cmd_rollback_plan(args: argparse.Namespace) -> int:
    target_receipt = state.fetch_receipt(args.repo_slug, args.target_run_id, gh_api, _download_artifact)
    args.target_receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.target_receipt_out.write_text(receipt.dumps(target_receipt), encoding="utf-8")
    decision, _, _ = rollback.plan_rollback(
        repo_root=args.repo_root,
        target_receipt=target_receipt,
        deployed_receipt=receipt.read_receipt(args.previous_receipt),
        live_unconfirmed=args.live_unconfirmed,
    )
    pipeline.write_json(args.out, decision.to_dict())
    print(json.dumps(decision.to_dict(), indent=2))
    _emit(args, {"verdict": decision.verdict.value, "allowed": decision.allowed})
    if decision.verdict is generation.Verdict.REFUSE:
        print("::error::" + "; ".join(decision.reasons))
        return 1
    return 0


def _cmd_rollback_stage(args: argparse.Namespace) -> int:
    rolled = rollback.stage_rollback(
        target_receipt=receipt.read_receipt(args.target_receipt),
        deployed_receipt=receipt.read_receipt(args.previous_receipt),
        archive=args.archive,
        out_dir=args.out_dir,
        target=args.target,
        waive_cache_window=args.waive_cache_window,
    )
    _emit(args, {"artifact_sha256": rolled["artifact"]["sha256"]})
    print(f"staged rollback of {rolled['rollback']['restored_receipt_id']} ({rolled['artifact']['sha256'][:12]})")
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    data = receipt.read_receipt(args.receipt)
    if (
        data["status"] not in (receipt.STATUS_LIVE_VERIFIED, receipt.STATUS_PROBE_FAILED)
        or data["target"] != "production"
    ):
        print(f"::error::refusing to index a {data['target']} receipt with status {data['status']!r}")
        return 1
    deployment_id = state.find_run_deployment(args.repo_slug, gh_api, args.sha, args.run_started_at)
    if deployment_id is None:
        print("::error::no github-pages deployment found for this run")
        return 1
    description = receipt.deployment_description(
        generation.Generation.from_dict(data["generation"]),
        data["workflow"]["run_id"],
        data["artifact"]["sha256"],
        verified=data["status"] == receipt.STATUS_LIVE_VERIFIED,
    )
    state.record_deployment_status(args.repo_slug, deployment_id, description, args.log_url)
    print(f"recorded deployment {deployment_id}: {description}")
    return 0


COMMANDS = {
    "previous": _cmd_previous,
    "candidate": _cmd_candidate,
    "plan": _cmd_plan,
    "prepare": _cmd_prepare,
    "dry-run": _cmd_dry_run,
    "probe": _cmd_probe,
    "finalize": _cmd_finalize,
    "rollback-plan": _cmd_rollback_plan,
    "rollback-stage": _cmd_rollback_stage,
    "record": _cmd_record,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (
        pipeline.PipelineError,
        assembler.ManifestError,
        assembler.RouteOwnershipError,
        receipt.ReceiptError,
        GitHubError,
        FileNotFoundError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
