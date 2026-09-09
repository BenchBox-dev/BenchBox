#!/usr/bin/env python3
"""Feature-batch branch integration: one shared base, one integrator, bound receipts.

A feature batch prepares members separately and lands them through a single
shared integration branch. This helper makes that discipline mechanical:

* ``start`` records one shared base (ref + OID + timestamp) for the whole
  batch in per-worktree git config. Integration timestamps and ancestry are
  always evaluated against that recorded base, never the current tip of a
  moving ref. The helper never refreshes the base itself.
* ``verify`` checks the three integration gates: the recorded base (moved or
  not — reported, never auto-fixed), single-integrator authorship since the
  base, and member-head ancestry in the integration head.
* ``receipt`` binds per-item acceptance evidence (produced tracker-side) to
  the exact integration head it was evaluated against, with branch-history
  timestamps (first commit / first merge since the base, the observable
  proxies for first-prepare / first-integration). A moved head or
  base invalidates the binding instead of silently carrying it forward.

Member preparation evidence never certifies the integrated tree: acceptance
must name the integration head, and the receipt refuses any other head.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PREFIX = "benchbox.batch"


class BatchError(RuntimeError):
    """A refused or failed batch integration transition."""


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
    """Record the shared integration base for the whole batch (w0/w2)."""
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
    """Clear a batch start record (audited recovery from a crashed start).

    Deletes the seal FIRST so an interrupted reset can never leave a sealed
    record with half-cleared fields: any crash past the first delete reads
    as absent, never as valid.
    """
    _config_delete(repo, "sealed")
    for key in ("id", "base-ref", "base-oid", "started-at", "members"):
        _config_delete(repo, key)


def read_batch(repo: Path) -> dict | None:
    """Read the recorded batch start, or None when absent or unsealed.

    A crash between the individual config writes leaves no `sealed` marker;
    such partial records fail closed instead of binding half a start.
    """
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
    """Compare the recorded base against the current tip (reported, never fixed)."""
    current = _git(repo, "rev-parse", f"{record['base_ref']}^{{commit}}")
    return {"recorded_oid": record["base_oid"], "current_oid": current, "moved": current != record["base_oid"]}


def committers_since_base(repo: Path, base_oid: str, head: str) -> list[str]:
    """Distinct committer identities on the first-parent chain base..head.

    Committer (who applied), not author (who wrote), and first-parent only:
    legitimate member merges preserve member authorship/committer off-chain,
    while any commit applied directly to the integration branch — member or
    rogue — records its writer as a first-parent committer. The head is
    passed in (never re-resolved) so all receipt gates evaluate one revision.
    """
    out = _git(repo, "log", "--first-parent", f"{base_oid}..{head}", "--format=%cn <%ce>")
    return sorted(set(out.splitlines()) if out else [])


def verify_single_integrator(repo: Path, base_oid: str, integrator: str, head: str) -> list[str]:
    """Offending committers when anyone but the integrator applied work (w3)."""
    return [committer for committer in committers_since_base(repo, base_oid, head) if committer != integrator]


def member_ancestry(repo: Path, members: object, integration_head: str) -> dict[str, bool]:
    """Whether each member prepared head is an ancestor of the integration head."""
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


def branch_timestamps(repo: Path, base_oid: str, head: str) -> dict:
    """Branch-history timestamps: first commit and first merge since the base.

    These are the observable proxies for first-prepare / first-integration,
    named as what they are: a first commit is not proof of preparation, and
    a first merge is not proof of integration. Ranges are pinned to one
    resolved *head* so a concurrent commit cannot mix an old integration
    head with new history.
    """
    first = _git(repo, "log", "--reverse", "--format=%H %cI", f"{base_oid}..{head}").splitlines()
    merges = _git(repo, "log", "--reverse", "--merges", "--format=%H %cI", f"{base_oid}..{head}").splitlines()
    return {
        "first_commit_since_base": first[0] if first else None,
        "first_merge_since_base": merges[0] if merges else None,
        "commit_count": len(first),
    }


def delivery_receipt(repo: Path, member_heads: list[dict], acceptance: dict) -> dict:
    """Bind tracker-side per-item acceptance to the exact integration head.

    Refuses when the acceptance head differs from HEAD, when the member set
    differs from the recorded start (late or dropped members), when any
    member lacks passing acceptance, when anyone but the named integrator
    applied work, when a member head is missing from the integration head,
    or when the base moved without a re-recorded start.
    """
    record = read_batch(repo)
    if record is None or not record.get("base_oid"):
        raise BatchError("no batch start recorded; run start before receipt")
    if not member_heads:
        raise BatchError("empty member manifest binds nothing; refusing vacuous receipt")
    recorded = set(record.get("members") or [])
    manifested = set(str(member.get("id", "?")) for member in member_heads if isinstance(member, dict))
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
    items = acceptance.get("items", {}) or {}
    unaccepted = sorted(mid for mid in manifested if not items.get(mid))
    if unaccepted:
        raise BatchError(f"members without passing acceptance: {unaccepted}")
    if acceptance.get("integration_head") != head:
        raise BatchError("acceptance names a different integration head; re-evaluate, never carry forward")
    base_check = verify_base(repo, record)
    if base_check["moved"]:
        raise BatchError("recorded base moved; re-record the start before binding acceptance")
    ancestry = member_ancestry(repo, member_heads, head)
    missing = sorted(name for name, present in ancestry.items() if not present)
    if missing:
        raise BatchError(f"member heads missing from integration head: {missing}")
    return {
        "batch_id": record["batch_id"],
        "base": {"ref": record["base_ref"], "oid": record["base_oid"]},
        "integration_head": head,
        "started_at": record["started_at"],
        "history": branch_timestamps(repo, record["base_oid"], head),
        "member_ancestry": ancestry,
        "integrator": str(integrator),
        "acceptance": items,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
