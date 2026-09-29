"""Plan, prepare, and verify a site deployment.

``plan`` pins the inputs and decides whether a run may proceed. ``prepare``
assembles every route from its pinned commit, runs the pre-deploy gates, and writes
the candidate receipt and retained artifact. ``finalize`` records what the probes
saw. The same code serves the preview (dry-run) and production paths.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import assemble_public_site as assembler
from scripts.site_deploy import candidate, gates, generation, receipt
from scripts.site_deploy.github import Api

IDENTITY_CI = "ci"
IDENTITY_SKIP = "skip"
DEFAULT_CORPUS_REF = "origin/published-results"
TRUNK_HISTORY_LIMIT = 2000
ALL_GATES = (
    "privacy",
    "cross-route-links",
    "explorer-compat",
    "explorer-mixed-versions",
    "snapshot-digest",
    "corpus-bijection",
    "validator-parity",
)


class PipelineError(RuntimeError):
    """A deploy input or gate failed; the run must stop."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def workflow_context(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    return {
        "run_id": env.get("GITHUB_RUN_ID", "local"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", "1"),
        "sha": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
        "actor": env.get("GITHUB_ACTOR", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
    }


@dataclass
class Plan:
    refs: dict[str, assembler.ResolvedRef]
    generation: generation.Generation
    identity: dict[str, Any]
    decision: generation.Decision
    previous: generation.DeployedState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trunk_sha": self.generation.trunk_sha,
            "release_tag": self.generation.release_tag,
            "release_sha": self.refs["release"].sha,
            "corpus_sha": self.generation.corpus_sha,
            "trunk_index": self.generation.trunk_index,
            "identity": self.identity,
            "decision": self.decision.to_dict(),
        }


def resolve_corpus_sha(repo_root: Path, corpus_ref: str) -> str:
    if assembler.SHA_RE.match(corpus_ref):
        return corpus_ref
    try:
        return assembler._verify_commit(repo_root, corpus_ref)  # noqa: SLF001 - shared git helper
    except assembler.ManifestError as exc:
        raise PipelineError(f"cannot resolve corpus ref {corpus_ref!r}: {exc}") from exc


def select_trunk(
    repo_root: Path, *, trunk_ref: str, api: Api | None, repo_slug: str, mode: str, pinned: str | None
) -> tuple[str, dict[str, Any]]:
    """Choose the trunk commit and the evidence that it is eligible."""
    tip = assembler._verify_commit(repo_root, trunk_ref)  # noqa: SLF001
    history = generation.first_parent_shas(repo_root, tip, TRUNK_HISTORY_LIMIT)
    if mode == IDENTITY_SKIP:
        sha = pinned or tip
        return sha, {"mode": IDENTITY_SKIP, "sha": sha}
    if api is None:
        raise PipelineError("candidate identity checks need GitHub API access")
    if pinned:
        runs = candidate.fetch_runs_for_sha(repo_slug, pinned, api)
        verdict = candidate.check_candidate(pinned, runs, history)
    else:
        runs = candidate.fetch_merge_group_runs(repo_slug, api)
        found = candidate.select_latest_eligible(runs, history)
        if found is None:
            raise PipelineError("no trunk commit in recent history has a successful merge-queue ci.yml run")
        verdict = found
    if not verdict.eligible:
        raise PipelineError(f"trunk commit {verdict.sha[:12]} is not an eligible candidate: {verdict.reasons}")
    return verdict.sha, {"mode": IDENTITY_CI, **verdict.to_dict()}


def verify_release_identity(
    repo_root: Path, *, release: assembler.ResolvedRef, trunk_sha: str, api: Api | None, repo_slug: str, mode: str
) -> dict[str, Any]:
    """The release tag's commit must sit on trunk at or before the trunk pin and have passed the queue."""
    if mode == IDENTITY_SKIP:
        return {"mode": IDENTITY_SKIP, "tag": release.label, "sha": release.sha}
    relation = generation.git_relation(repo_root, release.sha, trunk_sha)
    if relation not in (generation.Relation.SAME, generation.Relation.ANCESTOR):
        raise PipelineError(
            f"release tag {release.label} ({release.sha[:12]}) is not on trunk at or before {trunk_sha[:12]}"
        )
    if api is None:
        raise PipelineError("candidate identity checks need GitHub API access")
    history = generation.first_parent_shas(repo_root, trunk_sha, TRUNK_HISTORY_LIMIT)
    verdict = candidate.check_candidate(release.sha, candidate.fetch_runs_for_sha(repo_slug, release.sha, api), history)
    if not verdict.eligible:
        raise PipelineError(f"release tag {release.label} is not an eligible candidate: {verdict.reasons}")
    return {"mode": IDENTITY_CI, "tag": release.label, **verdict.to_dict()}


def make_plan(
    *,
    repo_root: Path,
    manifest: assembler.RouteManifest,
    previous: dict[str, Any] | None,
    trunk_sha: str | None = None,
    release_tag: str | None = None,
    corpus_ref: str = DEFAULT_CORPUS_REF,
    trunk_ref: str = "origin/develop",
    identity_mode: str = IDENTITY_CI,
    api: Api | None = None,
    repo_slug: str = "",
) -> Plan:
    if identity_mode not in (IDENTITY_CI, IDENTITY_SKIP):
        raise PipelineError(f"unknown identity mode {identity_mode!r}")
    trunk, trunk_evidence = select_trunk(
        repo_root, trunk_ref=trunk_ref, api=api, repo_slug=repo_slug, mode=identity_mode, pinned=trunk_sha
    )
    overrides = {"trunk": trunk}
    if release_tag:
        overrides["release"] = release_tag
    try:
        refs = assembler.resolve_refs(repo_root, manifest, overrides)
    except assembler.ManifestError as exc:
        raise PipelineError(str(exc)) from exc
    release_evidence = verify_release_identity(
        repo_root, release=refs["release"], trunk_sha=trunk, api=api, repo_slug=repo_slug, mode=identity_mode
    )
    corpus_sha = resolve_corpus_sha(repo_root, corpus_ref)
    gen = generation.Generation(
        trunk_sha=trunk,
        trunk_index=generation.trunk_index(repo_root, trunk),
        release_tag=refs["release"].label,
        corpus_sha=corpus_sha,
    )
    deployed = receipt.deployed_state_from_receipt(previous) if previous else None
    relations = generation.relations_for(repo_root, gen, deployed.generation) if deployed else None
    decision = generation.decide_deploy(gen, deployed, relations)
    return Plan(
        refs=refs,
        generation=gen,
        identity={"trunk": trunk_evidence, "release": release_evidence},
        decision=decision,
        previous=deployed,
    )


@dataclass
class Prepared:
    site_dir: Path
    archive: Path
    receipt: dict[str, Any]
    gates: list[gates.GateResult]
    identity: receipt.TreeIdentity
    mounts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)


def _results_route(manifest: assembler.RouteManifest) -> assembler.Route | None:
    return next((r for r in manifest.routes if r.kind == assembler.KIND_EXPLORER), None)


def run_gates(
    *,
    repo_root: Path,
    manifest: assembler.RouteManifest,
    assembly: assembler.ManifestAssembly,
    plan: Plan,
    work_dir: Path,
    previous_receipt: dict[str, Any] | None,
    waive_cache_window: bool,
    skip: frozenset[str],
    rebuild: Callable[[Path, Path], Path],
) -> tuple[list[gates.GateResult], dict[str, Any]]:
    """Run every applicable gate (none short-circuits) and return the Explorer facts."""
    site_dir = assembly.site_dir
    mounts = [r.mount for r in manifest.routes]
    spa = [r.mount for r in manifest.routes if r.spa]
    results: list[gates.GateResult] = []
    explorer: dict[str, Any] = {}

    def add(result: gates.GateResult) -> None:
        results.append(result)

    def guarded(name: str, fn: Callable[[], gates.GateResult]) -> None:
        if name in skip:
            add(gates.GateResult(name, True, "skipped by operator (preview only)"))
            return
        try:
            add(fn())
        except Exception as exc:  # noqa: BLE001 - a crashing gate is a failed gate
            add(gates.GateResult(name, False, f"{type(exc).__name__}: {exc}"))

    guarded("privacy", lambda: gates.gate_privacy(site_dir))
    guarded("cross-route-links", lambda: gates.gate_links(site_dir, mounts, spa))

    route = _results_route(manifest)
    if route is None:
        return results, explorer
    trunk_root = assembly.ref_roots[route.ref]
    snapshot = site_dir / route.mount.strip("/") / "data" / "results.duckdb"
    guarded("explorer-compat", lambda: gates.gate_explorer_compat(site_dir, route.mount.strip("/")))

    candidate_versions: tuple[int, int] | None = None
    try:
        candidate_versions = (
            gates.read_ui_read_model_version(trunk_root),
            gates.read_snapshot_read_model_version(snapshot),
        )
        explorer = {
            "ui_read_model_version": candidate_versions[0],
            "snapshot_read_model_version": candidate_versions[1],
            "db_sha256": receipt.sha256_file(snapshot),
        }
    except Exception as exc:  # noqa: BLE001
        add(gates.GateResult("explorer-mixed-versions", False, f"cannot read read-model versions: {exc}"))
    else:
        previous_versions = receipt.explorer_versions_from_receipt(previous_receipt) if previous_receipt else None
        guarded(
            "explorer-mixed-versions",
            lambda: gates.gate_mixed_versions(
                previous_versions, candidate_versions, waive_cache_window=waive_cache_window
            ),
        )

    def digest_gate() -> gates.GateResult:
        scratch = work_dir / "rebuild"
        outcome = gates.gate_db_digest(snapshot, lambda: rebuild(trunk_root, scratch))
        if outcome.ok:
            explorer["db_canonical_digest"] = outcome.data.get("digest")
        return outcome

    guarded("snapshot-digest", digest_gate)
    guarded(
        "corpus-bijection",
        lambda: gates.gate_corpus_bijection(
            corpus_sha=plan.generation.corpus_sha,
            bundles_dir=trunk_root / "results-data" / "bundles",
            snapshot=snapshot,
            ledger_seed=trunk_root / "publication" / "ledger-seed.json",
        ),
    )
    base = plan.previous.generation.trunk_sha if plan.previous else None
    guarded(
        "validator-parity",
        lambda: gates.gate_validator_parity(base_sha=base, trunk_sha=plan.generation.trunk_sha),
    )
    return results, explorer


def make_rebuild(work_dir: Path, trunk: assembler.ResolvedRef, isolate_envs: bool) -> Callable[[Path, Path], Path]:
    """Rebuild the Explorer snapshot from the pinned corpus, in the trunk build environment."""

    def rebuild(trunk_root: Path, scratch: Path) -> Path:
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        assembler._run_command(  # noqa: SLF001
            (
                "uv",
                "run",
                "--frozen",
                "--",
                "python",
                "_project/scripts/explorer_publish.py",
                "build",
                "--data-dir",
                "results-data/",
                "--output",
                str(scratch),
            ),
            trunk_root,
            assembler._step_env(work_dir, trunk, isolate_envs),  # noqa: SLF001
        )
        return scratch / "results.duckdb"

    return rebuild


def prepare_candidate(
    *,
    repo_root: Path,
    manifest: assembler.RouteManifest,
    plan: Plan,
    out_dir: Path,
    work_dir: Path,
    target: str,
    previous_receipt: dict[str, Any] | None = None,
    waive_cache_window: bool = False,
    skip_gates: frozenset[str] = frozenset(),
    isolate_envs: bool = True,
    runner: assembler.Runner = assembler._run_command,  # noqa: SLF001
    prebuilt_roots: Mapping[str, Path] | None = None,
    rebuild: Callable[[Path, Path], Path] | None = None,
    workflow: dict[str, Any] | None = None,
) -> Prepared:
    """Assemble from the plan's pins, run the gates, and write the candidate receipt."""
    if skip_gates and target != "preview":
        raise PipelineError("gates can only be skipped in preview runs")
    if plan.identity["trunk"].get("mode") == IDENTITY_SKIP and target != "preview":
        raise PipelineError("candidate identity checks can only be skipped in preview runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    site_dir = out_dir / "site"
    overrides = {name: ref.sha for name, ref in plan.refs.items()}
    assembly = assembler.assemble_from_manifest(
        repo_root=repo_root,
        manifest=manifest,
        site_dir=site_dir,
        work_dir=work_dir,
        overrides=overrides,
        runner=runner,
        isolate_envs=isolate_envs,
        prebuilt_roots=prebuilt_roots,
    )
    gate_results, explorer = run_gates(
        repo_root=repo_root,
        manifest=manifest,
        assembly=assembly,
        plan=plan,
        work_dir=work_dir,
        previous_receipt=previous_receipt,
        waive_cache_window=waive_cache_window,
        skip=skip_gates,
        rebuild=rebuild or make_rebuild(work_dir, plan.refs["trunk"], isolate_envs),
    )
    identity = receipt.tree_identity(site_dir)
    archive = out_dir / receipt.ARCHIVE_NAME
    archive_sha = receipt.write_deterministic_tar(site_dir, archive)
    mounts = [r.mount for r in manifest.routes]
    checksums = receipt.build_probe_set(site_dir, identity, mounts)
    ctx = workflow or workflow_context()
    quarantine = (
        (plan.previous.quarantined_trunk_shas, plan.previous.quarantined_release_tags)
        if plan.previous
        else (frozenset(), frozenset())
    )
    run_id = ctx.get("run_id", "local")
    candidate_receipt = receipt.new_receipt(
        receipt_id=f"site-deploy-{run_id}-{ctx.get('run_attempt', '1')}",
        operation="deploy",
        target=target,
        generation=plan.generation,
        routes=[
            {
                "id": item.route.id,
                "mount": item.route.mount,
                "kind": item.route.kind,
                "ref": item.ref.name,
                "label": plan.refs[item.route.ref].label,
                "source_sha": item.ref.sha,
                "files": item.files,
            }
            for item in assembly.routes
        ],
        identity_evidence=plan.identity,
        identity=identity,
        archive_sha256=archive_sha,
        explorer=explorer,
        gates=[g.to_dict() for g in gate_results],
        checksums=checksums,
        quarantine=quarantine,
        workflow=ctx,
        created_at=utc_now(),
    )
    (out_dir / receipt.RECEIPT_NAME).write_text(receipt.dumps(candidate_receipt), encoding="utf-8")
    return Prepared(site_dir, archive, candidate_receipt, gate_results, identity, mounts)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
