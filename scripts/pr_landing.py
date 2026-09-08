#!/usr/bin/env python3
"""One cohesive revision/readiness/queue/follow-up helper behind the Make PR targets.

Session history shows the failure modes this closes: queued-branch push
rejection after readiness was armed, unpublished fixes riding along, wrong-PR
operations from an inferred branch, and late-fix merges ahead of corrections.
The contract:

* Every mutation names the exact repository, PR number/node, expected head,
  branch, and worktree. A PR resolved from a reused branch name alone is
  refused (wrong-PR protection).
* Readiness is withdrawn (auto-merge disabled and verified) before the first
  edit. If the merge wins the race, the helper stops and preserves commits
  for a correctly identified follow-up instead of modifying a closed PR.
* Ready requires local/remote head agreement on the exact expected head, no
  unpublished work, completed review evidence on that head, required checks
  green at that head, and no durable hold. Enqueue re-checks the remote head
  immediately before arming; a head change invalidates readiness.
* Feature-batch readiness additionally binds batch id/version, member set,
  owner generation, and integration head; late members or content edits
  invalidate it. Member SHAs must be ancestors of the integration head.
* Follow-up state (pre-PR assembly through post-merge) persists with an
  explicit owner and next action; retries are bounded to evidenced transient
  failures on unchanged heads; terminal state is explicit, never inferred
  from an empty PR list.

All GitHub access goes through an injectable runner so tests replay races
with fake hosted events. The live runner shells out to `gh`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

HOLD_LABEL = "no-auto-merge"
REQUIRED_CONTEXTS: tuple[str, ...] = (
    "ci-required-result",
    "Results Explorer browser gate",
    "ruleset-drift",
)
MAX_RERUNS_PER_JOB = 1
MAX_REENTRIES_PER_HEAD = 1


class LandingError(RuntimeError):
    """A refused or failed landing transition with an actionable message."""


class WrongPR(LandingError):
    """The resolved PR does not match the declared branch/head identity."""


class MergedRace(LandingError):
    """The PR merged or closed while we were preparing a revision."""


def state_dir(repo: Path) -> Path:
    override = os.environ.get("BENCHBOX_PR_LANDING_DIR")
    if override:
        return Path(override).expanduser()
    import hashlib

    slug = hashlib.sha1(str(repo.resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".benchbox" / "pr-landing" / slug


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True, timeout=60)
    return proc.stdout.strip()


@dataclass
class GitIdentity:
    repo: str
    branch: str
    worktree: str
    head: str
    base: str | None
    upstream: str | None


def git_identity(repo: Path) -> GitIdentity:
    """Exact local identity for revision and readiness transitions."""
    branch = _git(repo, "branch", "--show-current")
    if not branch:
        raise LandingError("detached HEAD has no branch identity; refuse to guess the PR")
    try:
        upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except subprocess.CalledProcessError:
        upstream = None
    try:
        base = _git(repo, "rev-parse", "origin/develop")
    except subprocess.CalledProcessError:
        base = None
    return GitIdentity(
        repo=str(repo.resolve()),
        branch=branch,
        worktree=_git(repo, "rev-parse", "--show-toplevel"),
        head=_git(repo, "rev-parse", "HEAD"),
        base=base,
        upstream=upstream,
    )


Runner = Callable[[list[str]], tuple[int, str]]


def live_run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=120, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def resolve_pr(run: Runner, repo_full: str, branch: str) -> dict | None:
    """Resolve the open develop PR for *branch*, refusing cross-branch matches."""
    rc, out = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo_full,
            "--base",
            "develop",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url,headRefName,headRefOid",
        ]
    )
    if rc != 0:
        raise LandingError(f"gh pr list failed for branch {branch!r}")
    try:
        matches = json.loads(out or "[]")
    except ValueError as exc:
        raise LandingError(f"unparseable gh pr list output: {exc}") from exc
    if not isinstance(matches, list):
        raise LandingError("gh pr list returned a non-list payload; refusing to guess")
    if not matches:
        return None
    pr = matches[0]
    if pr.get("headRefName") != branch:
        raise WrongPR(
            f"resolved PR #{pr.get('number')} points at {pr.get('headRefName')!r}, "
            f"not declared branch {branch!r}; refusing wrong-PR operation"
        )
    return pr


def unpublished_work(repo: Path) -> list[str]:
    """Local commits or edits not yet on the upstream branch."""
    problems: list[str] = []
    if _git(repo, "status", "--porcelain=v1"):
        problems.append("uncommitted working-tree changes")
    try:
        ahead = int(_git(repo, "rev-list", "--count", "@{u}..HEAD") or 0)
        behind = int(_git(repo, "rev-list", "--count", "HEAD..@{u}") or 0)
    except subprocess.CalledProcessError:
        return problems + ["no upstream tracking branch to compare"]
    if ahead:
        problems.append(f"{ahead} local commit(s) not pushed to upstream")
    if behind:
        problems.append(f"upstream is {behind} commit(s) ahead of local HEAD")
    return problems


def withdraw_readiness(run: Runner, repo_full: str, pr_number: int) -> dict:
    """Disable auto-merge and verify it stays disabled before any revision.

    Never adds or removes hold labels: user/maintainer holds are theirs to
    manage. If the PR already merged or closed, raises MergedRace so the
    caller stops modifying and preserves commits for a follow-up.
    """
    rc, out = run(["gh", "pr", "view", "--repo", repo_full, str(pr_number), "--json", "state,autoMergeRequest,labels"])
    if rc != 0:
        raise LandingError(f"gh pr view failed for PR #{pr_number}")
    try:
        pr = json.loads(out or "{}")
    except ValueError as exc:
        raise LandingError(f"unparseable gh pr view output: {exc}") from exc
    if str(pr.get("state", "")).upper() in ("MERGED", "CLOSED"):
        raise MergedRace(
            f"PR #{pr_number} is {pr.get('state')}; merge won the race. "
            "Stop modifying; preserve commits for a correctly identified follow-up."
        )
    if pr.get("autoMergeRequest"):
        rc, out = run(["gh", "pr", "merge", "--repo", repo_full, "--disable-auto", str(pr_number)])
        if rc != 0:
            raise LandingError(f"could not disable auto-merge on PR #{pr_number}: {out.strip()[:200]}")
        rc, out = run(["gh", "pr", "view", "--repo", repo_full, str(pr_number), "--json", "autoMergeRequest"])
        try:
            reverified = json.loads(out or "{}")
        except ValueError as exc:
            raise LandingError(f"unparseable re-verification output: {exc}") from exc
        if reverified.get("autoMergeRequest"):
            raise LandingError(f"auto-merge still armed on PR #{pr_number} after disable; refusing revision")
        return {"pr": pr_number, "withdrew": "auto-merge", "verified": True}
    return {"pr": pr_number, "withdrew": "nothing-armed", "verified": True}


@dataclass
class ReadyEvidence:
    """Evidence the ready transition verifies (never inferred from snapshots)."""

    expected_head: str
    review_decision: str
    dispositions_complete: bool
    check_runs: list
    required: tuple = REQUIRED_CONTEXTS
    hold_labels: list | None = None
    soundness_paths_changed: bool = False
    maintainer_approved: bool = False
    batch: dict | None = None


def checks_green_at_head(check_runs: list, required: tuple, head: str) -> list[str]:
    """Required contexts must be latest-success bound to *head*, not just green."""
    failures: list[str] = []
    for name in required:
        matches = [run for run in check_runs if run.get("name") == name]
        if not matches:
            failures.append(f"{name}: no check run observed")
            continue
        latest = max(matches, key=lambda run: str(run.get("started_at") or ""))
        if latest.get("head_sha") != head:
            failures.append(f"{name}: latest run bound to {str(latest.get('head_sha'))[:12]}, not expected head")
        elif latest.get("status") != "completed" or latest.get("conclusion") != "success":
            failures.append(f"{name}: {latest.get('status')}/{latest.get('conclusion')}")
    return failures


def check_batch_binding(repo: Path, batch: dict, integration_head: str) -> list[str]:
    """Batch readiness: members present, writers quiescent, head current."""
    failures: list[str] = []
    for key in ("batch_id", "members", "owner_generation"):
        if not batch.get(key):
            failures.append(f"batch binding lacks {key}")
    if batch.get("integration_head") != integration_head:
        failures.append("batch integration head moved since readiness was evaluated")
    if batch.get("active_writers"):
        failures.append(f"member writers still active: {batch['active_writers']!r}")
    for member in batch.get("members") or []:
        sha = member.get("head")
        if not sha:
            failures.append(f"member {member.get('id', '?')} has no prepared head")
            continue
        try:
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, integration_head],
                cwd=repo,
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            failures.append(f"member {member.get('id', '?')} head {sha[:12]} not in integration head")
    return failures


def ready_failures(
    identity: GitIdentity,
    remote_head: str,
    evidence: ReadyEvidence,
    repo: Path,
) -> list[str]:
    """All reasons the PR must not be enqueued yet. Empty means ready."""
    failures: list[str] = []
    if identity.head != evidence.expected_head:
        failures.append(f"local head {identity.head[:12]} != expected {evidence.expected_head[:12]}")
    if remote_head != evidence.expected_head:
        failures.append(f"remote head {remote_head[:12]} != expected {evidence.expected_head[:12]}")
    failures.extend(f"unpublished work: {problem}" for problem in unpublished_work(repo))
    if evidence.review_decision != "APPROVED":
        failures.append(f"review decision is {evidence.review_decision!r}, not APPROVED")
    if not evidence.dispositions_complete:
        failures.append("review dispositions incomplete (every top-level finding needs evidence)")
    failures.extend(checks_green_at_head(evidence.check_runs, evidence.required, evidence.expected_head))
    holds = evidence.hold_labels or []
    if HOLD_LABEL in holds:
        failures.append(f"durable hold label {HOLD_LABEL!r} present; a human removes it, never this helper")
    if evidence.soundness_paths_changed and not evidence.maintainer_approved:
        failures.append("soundness paths changed without maintainer approval")
    if evidence.batch is not None:
        failures.extend(check_batch_binding(repo, evidence.batch, evidence.expected_head))
    return failures


def enqueue_pr(run: Runner, repo_full: str, pr_number: int, expected_head: str, remote_head: str) -> dict:
    """Arm queue enrollment after a final expected-head check.

    The helper re-reads the remote head immediately before arming and refuses
    on mismatch, then passes `--match-head-commit` so admission itself is an
    atomic compare-and-set on the expected head. A push landing between the
    check and admission is refused server-side rather than armed.
    """
    if remote_head != expected_head:
        raise LandingError(
            f"remote head moved to {remote_head[:12]} during enqueue; "
            "readiness is invalid, re-evaluate instead of arming"
        )
    rc, out = run(
        [
            "gh",
            "pr",
            "merge",
            "--repo",
            repo_full,
            "--auto",
            "--squash",
            "--match-head-commit",
            expected_head,
            str(pr_number),
        ]
    )
    if rc != 0:
        raise LandingError(f"enqueue refused for PR #{pr_number}: {out.strip()[:300]}")
    return {"pr": pr_number, "enqueued": True, "note": "API success is not proof of merge"}


# ---------------------------------------------------------------------------
# Queue-aware local publication policy (native-queue-local-landing)
# ---------------------------------------------------------------------------
def stale_base_decision(*, queue_verified: bool, conflict: bool) -> str:
    """Whether an ancestry-behind branch may publish without a refresh merge.

    * conflict -> "resolve-conflict-first" (always; no refresh can fix it).
    * verified native queue -> "publish-without-refresh": queue integration
      tests the speculative merge, so an author-side refresh only destroys a
      nearly-complete gate to no benefit.
    * otherwise -> "require-current": the conservative ancestry fallback when
      the queue is absent, unreadable, unsupported, or misconfigured.
    """
    if conflict:
        return "resolve-conflict-first"
    if queue_verified:
        return "publish-without-refresh"
    return "require-current"


# ---------------------------------------------------------------------------
# Resumable follow-up ownership (pr-followup-resumable-ownership)
# ---------------------------------------------------------------------------
TERMINAL_OUTCOMES = ("merged", "closed-merged", "abandoned", "superseded")


@dataclass
class FollowupState:
    """Bounded continuation state. Terminal outcomes are explicit, never inferred."""

    owner: str
    session: str
    scope: str
    pr: int | None = None
    head: str | None = None
    phase: str = "review"
    processed: list | None = None
    attempts: int = 0
    reentries: int = 0
    due_at: str | None = None
    next_action: str = ""
    terminal: str | None = None


def followup_path(directory: Path, key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return directory / f"{safe}.json"


def record_followup(directory: Path, key: str, state: FollowupState) -> Path:
    """Atomically persist continuation state (crash-safe via rename).

    Refuses to overwrite another owner's record: same-principal sessions may
    rotate `session`, but a different `owner` must use its own key.
    """
    for field in ("owner", "session", "scope"):
        if not getattr(state, field, None):
            raise LandingError(f"followup state lacks required field {field!r}")
    directory.mkdir(parents=True, exist_ok=True)
    path = followup_path(directory, key)
    existing = load_followup(directory, key)
    if existing is not None and existing.owner != state.owner:
        raise LandingError(f"followup {key!r} is owned by {existing.owner!r}; refusing cross-owner overwrite")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def coerce_followup(data: object) -> FollowupState:
    """Build state from untrusted input, refusing missing required fields."""
    if not isinstance(data, dict):
        raise LandingError("followup state must be an object")
    try:
        state = FollowupState(**{k: data.get(k) for k in FollowupState.__dataclass_fields__})
    except TypeError as exc:
        raise LandingError(f"followup state has an unexpected shape: {exc}") from exc
    for field in ("owner", "session", "scope"):
        if not getattr(state, field, None):
            raise LandingError(f"followup state lacks required field {field!r}")
    return state


def load_followup(directory: Path, key: str) -> FollowupState | None:
    path = followup_path(directory, key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return coerce_followup(data)
    except LandingError:
        return None


def resume_followup(state: FollowupState) -> dict:
    """Route to the owned next action. Missing/unknown state is never 'done'."""
    if state.terminal is not None:
        if state.terminal not in TERMINAL_OUTCOMES:
            return {"status": "invalid-terminal", "next_action": "re-verify terminal evidence with owner"}
        return {"status": state.terminal, "next_action": ""}
    if not state.next_action:
        return {"status": "unknown", "next_action": "re-verify PR/head state; an empty queue is not completion"}
    return {"status": state.phase, "next_action": state.next_action}


def allow_retry(state: FollowupState, kind: str, head: str) -> dict:
    """Bound retries to evidenced transient failures on unchanged heads."""
    if state.head != head:
        return {"allowed": False, "reason": "head changed; re-evaluate instead of retrying"}
    if kind == "rerun":
        if state.attempts >= MAX_RERUNS_PER_JOB:
            return {"allowed": False, "reason": "rerun budget exhausted; escalate with owner"}
        return {"allowed": True, "reason": "one rerun of the failed job on the unchanged head"}
    if kind == "requeue":
        if state.reentries >= MAX_REENTRIES_PER_HEAD:
            return {"allowed": False, "reason": "re-entry budget exhausted; escalate with owner"}
        return {"allowed": True, "reason": "one queue re-entry on the unchanged head"}
    return {"allowed": False, "reason": f"unknown retry kind {kind!r}"}


def consume_retry(directory: Path, key: str, kind: str, head: str) -> dict:
    """Decide a retry AND persist the consumed budget atomically.

    A pure decision function would authorize the same retry forever; consuming
    here makes the second identical call observe the spent budget.
    """
    state = load_followup(directory, key)
    if state is None:
        raise LandingError(f"no followup {key!r} recorded; record state before retrying")
    decision = allow_retry(state, kind, head)
    if not decision["allowed"]:
        return decision
    if kind == "rerun":
        state.attempts += 1
    else:
        state.reentries += 1
    record_followup(directory, key, state)
    return {**decision, "remaining": True}


def bound_withdraw(run: Runner, repo_full: str, branch: str, pr_number: int) -> dict:
    """Withdraw readiness only for the PR owned by *branch*.

    A branch that owns no PR yet (pre-PR assembly) may name an explicit PR;
    a branch that owns one refuses any other number, so a stale or mistaken
    `--pr` can never disarm another PR.
    """
    owned = resolve_pr(run, repo_full, branch)
    if owned is not None and owned.get("number") != pr_number:
        raise WrongPR(f"branch {branch} owns PR #{owned.get('number')}, not PR #{pr_number}")
    return withdraw_readiness(run, repo_full, pr_number)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="BenchBox-dev/BenchBox")
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="record the start-revision identity")
    start.add_argument("--branch", default=None)

    sub.add_parser("withdraw", help="withdraw readiness before a revision").add_argument(
        "--pr", type=int, required=True
    )

    ready = sub.add_parser("ready", help="verify readiness and enqueue on success")
    ready.add_argument("--pr", type=int, required=True)
    ready.add_argument("--expected-head", required=True)
    ready.add_argument("--evidence-json", type=Path, required=True)
    ready.add_argument("--arm", action="store_true", help="enqueue when all checks pass")

    policy = sub.add_parser("queue-policy", help="stale-base publication decision")
    policy.add_argument("--queue-verified", action="store_true")
    policy.add_argument("--conflict", action="store_true")

    rec = sub.add_parser("followup-record", help="persist continuation state")
    rec.add_argument("--key", required=True)
    rec.add_argument("--state-json", type=Path, required=True)

    res = sub.add_parser("followup-resume", help="print the owned next action")
    res.add_argument("--key", required=True)

    retry = sub.add_parser("followup-allow-retry", help="bounded retry decision")
    retry.add_argument("--key", required=True)
    retry.add_argument("--kind", required=True, choices=["rerun", "requeue"])
    retry.add_argument("--head", required=True)
    args = parser.parse_args(argv)

    repo = args.worktree.resolve()
    try:
        if args.command == "start":
            identity = git_identity(repo)
            branch = args.branch or identity.branch
            pr = resolve_pr(live_run, args.repo, branch)
            record = {
                "identity": asdict(identity),
                "pr": (pr or {}).get("number"),
                "remote_head": (pr or {}).get("headRefOid"),
            }
            print(json.dumps(record, indent=2))
            return 0
        if args.command == "withdraw":
            identity = git_identity(repo)
            print(json.dumps(bound_withdraw(live_run, args.repo, identity.branch, args.pr), indent=2))
            return 0
        if args.command == "ready":
            identity = git_identity(repo)
            pr = resolve_pr(live_run, args.repo, identity.branch)
            if pr is None or pr.get("number") != args.pr:
                raise WrongPR(f"branch {identity.branch} does not own PR #{args.pr}")
            evidence_data = json.loads(args.evidence_json.read_text(encoding="utf-8"))
            evidence = ReadyEvidence(
                expected_head=args.expected_head,
                review_decision=evidence_data.get("review_decision", "REVIEW_REQUIRED"),
                dispositions_complete=bool(evidence_data.get("dispositions_complete")),
                check_runs=evidence_data.get("check_runs", []),
                hold_labels=evidence_data.get("hold_labels", []),
                soundness_paths_changed=bool(evidence_data.get("soundness_paths_changed")),
                maintainer_approved=bool(evidence_data.get("maintainer_approved")),
                batch=evidence_data.get("batch"),
            )
            failures = ready_failures(identity, str(pr.get("headRefOid") or ""), evidence, repo)
            if failures:
                print("NOT READY:")
                for failure in failures:
                    print(f"  - {failure}")
                return 1
            if args.arm:
                print(
                    json.dumps(
                        enqueue_pr(live_run, args.repo, args.pr, args.expected_head, str(pr.get("headRefOid") or "")),
                        indent=2,
                    )
                )
            else:
                print(f"READY at {args.expected_head[:12]} (enqueue withheld without --arm)")
            return 0
        if args.command == "queue-policy":
            print(stale_base_decision(queue_verified=args.queue_verified, conflict=args.conflict))
            return 0
        directory = state_dir(repo)
        if args.command == "followup-record":
            try:
                data = json.loads(args.state_json.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LandingError(f"unreadable state file: {exc}") from exc
            path = record_followup(directory, args.key, coerce_followup(data))
            print(f"recorded {path}")
            return 0
        state = load_followup(directory, args.key)
        if state is None:
            print("unknown: no continuation state; re-verify, never assume done")
            return 2
        if args.command == "followup-resume":
            print(json.dumps(resume_followup(state), indent=2))
            return 0
        print(json.dumps(consume_retry(directory, args.key, args.kind, args.head), indent=2))
        return 0
    except (LandingError, MergedRace, WrongPR) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
