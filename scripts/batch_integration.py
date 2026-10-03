#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLI_DESCRIPTION = (
    "Feature-batch branch integration: one shared base, one integrator, bound receipts.\n"
    "\n"
    "A feature batch prepares members separately and lands them through a single\n"
    "shared integration branch. This helper makes that discipline mechanical:\n"
    "\n"
    "* ``start`` records one shared base (ref + OID + timestamp) for the whole\n"
    "  batch in per-worktree git config. Integration timestamps and ancestry are\n"
    "  always evaluated against that recorded base, never the current tip of a\n"
    "  moving ref. The helper never refreshes the base itself.\n"
    "* ``verify`` checks the three integration gates: the recorded base (moved or\n"
    "  not — reported, never auto-fixed), single-integrator authorship since the\n"
    "  base, and member-head ancestry in the integration head.\n"
    "* ``receipt`` binds per-item acceptance evidence (produced tracker-side) to\n"
    "  the exact integration head it was evaluated against, with branch-history\n"
    "  timestamps (first commit / first merge since the base, the observable\n"
    "  proxies for first-prepare / first-integration). A moved head or\n"
    "  base invalidates the binding instead of silently carrying it forward.\n"
    "\n"
    "Member preparation evidence never certifies the integrated tree: acceptance\n"
    "must name the integration head, and the receipt refuses any other head.\n"
)

CONFIG_PREFIX = "benchbox.batch"
DELIVERY_RECEIPT_SCHEMA = "batch_delivery_receipt_v1"


class BatchError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=False, text=True, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise BatchError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def _config_set(repo: Path, key: str, value: str) -> None:
    _git(repo, "config", "--worktree", "extensions.worktreeConfig", "true")
    _git(repo, "config", "--worktree", f"{CONFIG_PREFIX}.{key}", value)


def _config_delete(repo: Path, key: str) -> None:
    proc = subprocess.run(
        ["git", "config", "--worktree", "--unset", f"{CONFIG_PREFIX}.{key}"],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode not in (0, 5):
        raise BatchError(f"git config --unset {CONFIG_PREFIX}.{key} failed: {proc.stderr.strip()[:200]}")


def _config_get(repo: Path, key: str) -> str | None:
    proc = subprocess.run(
        ["git", "config", "--worktree", "--get", f"{CONFIG_PREFIX}.{key}"],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def record_start(
    repo: Path,
    batch_id: str,
    members: list[str],
    base_ref: str = "origin/develop",
) -> dict:
    if _config_get(repo, "id") is not None:
        raise BatchError("batch start already recorded for this worktree; refusing overwrite")
    base_oid = _git(repo, "rev-parse", f"{base_ref}^{{commit}}")
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _config_set(repo, "id", batch_id)
    _config_set(repo, "base-ref", base_ref)
    _config_set(repo, "base-oid", base_oid)
    _config_set(repo, "started-at", started_at)
    _config_set(repo, "members", json.dumps(sorted(set(members))))
    _config_set(repo, "sealed", "1")
    return {
        "batch_id": batch_id,
        "base_ref": base_ref,
        "base_oid": base_oid,
        "started_at": started_at,
        "members": sorted(set(members)),
    }


def reset_batch(repo: Path) -> None:
    _config_delete(repo, "sealed")
    for key in ("id", "base-ref", "base-oid", "started-at", "members"):
        _config_delete(repo, key)


def read_batch(repo: Path) -> dict | None:
    batch_id = _config_get(repo, "id")
    if batch_id is None or _config_get(repo, "sealed") != "1":
        return None
    members_raw = _config_get(repo, "members") or "[]"
    try:
        members = json.loads(members_raw)
    except ValueError:
        members = []
    return {
        "batch_id": batch_id,
        "base_ref": _config_get(repo, "base-ref"),
        "base_oid": _config_get(repo, "base-oid"),
        "started_at": _config_get(repo, "started-at"),
        "members": members if isinstance(members, list) else [],
    }


def verify_base(repo: Path, record: dict) -> dict:
    current = _git(repo, "rev-parse", f"{record['base_ref']}^{{commit}}")
    return {"recorded_oid": record["base_oid"], "current_oid": current, "moved": current != record["base_oid"]}


def committers_since_base(repo: Path, base_oid: str, head: str) -> list[str]:
    out = _git(repo, "log", "--first-parent", f"{base_oid}..{head}", "--format=%cn <%ce>")
    return sorted(set(out.splitlines()) if out else [])


def verify_single_integrator(repo: Path, base_oid: str, integrator: str, head: str) -> list[str]:
    return [committer for committer in committers_since_base(repo, base_oid, head) if committer != integrator]


def member_ancestry(repo: Path, members: object, integration_head: str) -> dict[str, bool]:
    if not isinstance(members, list):
        raise BatchError("members manifest must be a list")
    result: dict[str, bool] = {}
    for member in members:
        if not isinstance(member, dict):
            raise BatchError(f"member entry must be an object: {member!r}")
        sha = str(member.get("head") or "")
        if not sha:
            result[str(member.get("id", "?"))] = False
            continue
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, integration_head],
            cwd=repo,
            check=False,
            capture_output=True,
            timeout=60,
        )
        result[str(member.get("id", sha[:12]))] = proc.returncode == 0
    return result


def normalize_members(members: object) -> list[dict[str, str]]:
    if not isinstance(members, list):
        raise BatchError("members manifest must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            raise BatchError(f"member entry must be an object: {member!r}")
        member_id = member.get("id")
        head = member.get("head")
        if not isinstance(member_id, str) or not member_id or not isinstance(head, str) or not head:
            raise BatchError(f"member entry requires non-empty string id and head: {member!r}")
        if member_id in seen:
            raise BatchError(f"duplicate member id in manifest: {member_id!r}")
        seen.add(member_id)
        normalized.append({"id": member_id, "head": head})
    return sorted(normalized, key=lambda member: member["id"])


def normalize_dependencies(value: object, member_ids: set[str]) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BatchError("internal_implementation_dependencies must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for edge in value:
        if not isinstance(edge, dict):
            raise BatchError(f"internal dependency must be an object: {edge!r}")
        member = edge.get("member")
        depends_on = edge.get("depends_on")
        evidence = edge.get("evidence")
        if not isinstance(member, str) or not isinstance(depends_on, str):
            raise BatchError(f"internal dependency endpoints must be member IDs: {edge!r}")
        if member not in member_ids or depends_on not in member_ids or member == depends_on:
            raise BatchError(f"internal dependency endpoints must be distinct manifested members: {edge!r}")
        if not isinstance(evidence, str) or not evidence.strip():
            raise BatchError(f"internal dependency requires non-empty evidence: {edge!r}")
        identity = (str(member), str(depends_on))
        if identity in seen:
            raise BatchError(f"duplicate internal dependency: {identity!r}")
        seen.add(identity)
        normalized.append({"member": str(member), "depends_on": str(depends_on), "evidence": evidence.strip()})
    return normalized


def branch_timestamps(repo: Path, base_oid: str, head: str) -> dict:
    first = _git(repo, "log", "--reverse", "--format=%H %cI", f"{base_oid}..{head}").splitlines()
    merges = _git(repo, "log", "--reverse", "--merges", "--format=%H %cI", f"{base_oid}..{head}").splitlines()
    return {
        "first_commit_since_base": first[0] if first else None,
        "first_merge_since_base": merges[0] if merges else None,
        "commit_count": len(first),
    }


def delivery_receipt(repo: Path, member_heads: list[dict], acceptance: dict) -> dict:
    if not isinstance(acceptance, dict):
        raise BatchError("acceptance must be a JSON object")
    record = read_batch(repo)
    if record is None or not record.get("base_oid"):
        raise BatchError("no batch start recorded; run start before receipt")
    normalized_members = normalize_members(member_heads)
    if not normalized_members:
        raise BatchError("empty member manifest binds nothing; refusing vacuous receipt")
    recorded = set(record.get("members") or [])
    manifested = {member["id"] for member in normalized_members}
    if manifested != recorded:
        raise BatchError(
            f"member set {sorted(manifested)} != recorded start {sorted(recorded)}; "
            "late and dropped members invalidate the binding"
        )
    integrator = acceptance.get("integrator")
    if not integrator:
        raise BatchError("acceptance names no integrator; single-integrator gate cannot pass")
    head = _git(repo, "rev-parse", "HEAD")
    offenders = verify_single_integrator(repo, record["base_oid"], str(integrator), head)
    if offenders:
        raise BatchError(f"work applied by someone other than the integrator: {offenders}")
    items = acceptance.get("items")
    if not isinstance(items, dict):
        raise BatchError("acceptance items must be an object keyed by manifested member id")
    missing_items = sorted(manifested - set(items))
    extra_items = sorted(set(items) - manifested)
    if missing_items or extra_items:
        raise BatchError(
            f"acceptance item set must exactly match manifested members; missing={missing_items}, extra={extra_items}"
        )
    unaccepted = sorted(mid for mid in manifested if items[mid] != "pass")
    if unaccepted:
        raise BatchError(f"members without passing acceptance: {unaccepted}")
    dependencies = normalize_dependencies(acceptance.get("internal_implementation_dependencies"), manifested)
    if acceptance.get("integration_head") != head:
        raise BatchError("acceptance names a different integration head; re-evaluate, never carry forward")
    base_check = verify_base(repo, record)
    if base_check["moved"]:
        raise BatchError("recorded base moved; re-record the start before binding acceptance")
    ancestry = member_ancestry(repo, normalized_members, head)
    missing = sorted(name for name, present in ancestry.items() if not present)
    if missing:
        raise BatchError(f"member heads missing from integration head: {missing}")
    return {
        "schema": DELIVERY_RECEIPT_SCHEMA,
        "batch_id": record["batch_id"],
        "base": {"ref": record["base_ref"], "oid": record["base_oid"]},
        "integration_head": head,
        "started_at": record["started_at"],
        "history": branch_timestamps(repo, record["base_oid"], head),
        "members": normalized_members,
        "member_ancestry": ancestry,
        "integrator": str(integrator),
        "acceptance": {member_id: items[member_id] for member_id in sorted(items)},
        "internal_implementation_dependencies": dependencies,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="record the shared batch base")
    start.add_argument("--batch-id", required=True)
    start.add_argument("--member", action="append", default=[], dest="members")
    start.add_argument("--base-ref", default="origin/develop")

    sub.add_parser("reset", help="clear a batch start record after a crashed start")
    verify = sub.add_parser("verify", help="check base, integrator, and ancestry gates")
    verify.add_argument("--integrator", required=True)
    verify.add_argument("--members-json", type=Path, required=True)

    receipt = sub.add_parser("receipt", help="bind acceptance to the integration head")
    receipt.add_argument("--members-json", type=Path, required=True)
    receipt.add_argument("--acceptance-json", type=Path, required=True)
    receipt.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.worktree.resolve()

    try:
        if args.command == "start":
            print(json.dumps(record_start(repo, args.batch_id, args.members, args.base_ref), indent=2))
            return 0
        if args.command == "reset":
            reset_batch(repo)
            print("reset batch start record")
            return 0
        if args.command == "verify":
            record = read_batch(repo)
            if record is None:
                raise BatchError("no batch start recorded")
            head = _git(repo, "rev-parse", "HEAD")
            members = json.loads(args.members_json.read_text(encoding="utf-8"))
            report = {
                "base": verify_base(repo, record),
                "offending_committers": verify_single_integrator(repo, record["base_oid"], args.integrator, head),
                "member_ancestry": member_ancestry(repo, members, head),
            }
            print(json.dumps(report, indent=2))
            ok = (
                not report["base"]["moved"]
                and not report["offending_committers"]
                and all(report["member_ancestry"].values())
            )
            return 0 if ok else 1
        members = json.loads(args.members_json.read_text(encoding="utf-8"))
        acceptance = json.loads(args.acceptance_json.read_text(encoding="utf-8"))
        result = delivery_receipt(repo, members, acceptance)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0
    except BatchError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
