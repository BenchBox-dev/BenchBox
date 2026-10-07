from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import attempts as attempt_files, dedup, github, report, retry, runner, selection
from .absence import ERROR, Absence
from .brief import BRIEF_TEMPLATE, build_brief, write_private
from .classifier import ChangedFile, classify
from .diff import commentable_lines, select_files
from .policy import Policy, Reviewer, Tier, load_policy
from .selection import SelectionInput
from .verdict import VERDICT_SCHEMA

PLAN_FILE = "plan.json"
BRIEF_FILE = "brief.md"
DIFF_FILE = "diff.patch"
WORKFLOW_FILE = "oracle-review-shadow.yml"
WORKFLOW_SOURCE = Path(".github/workflows") / WORKFLOW_FILE
DEVELOP_REF = "refs/heads/develop"
NEW_DIFF_ACTIONS = ("opened", "synchronize")
REVIEW = "review"
SUCCESS = "success"
FORK = "fork"
SKIP = "skip"
CARRY = "carry"
SCOPELESS_TIER = "very-high"
PROSE_SUFFIXES = (".md", ".mdx", ".rst", ".txt")


def _now() -> datetime:
    return datetime.now(UTC)


def _output(values: Mapping[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(lines)
    sys.stdout.write(lines)


def _summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _pr_number(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", value or ""):
        raise SystemExit(f"oracle-review-shadow: invalid pull request number {value!r}")
    return int(value)


def _event() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def _soundness_predicate() -> Any:
    from _project.scripts.soundness_paths import is_soundness_path

    return is_soundness_path


def _base_plan(policy: Policy, repo: str, pr: int, run_id: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "mode": policy.mode,
        "status_context": policy.status_context,
        "findings_delivery": policy.findings_delivery,
        "repo": repo,
        "pr": pr,
        "run_id": run_id,
        "base_sha": "",
        "head_sha": "",
        "decision": SKIP,
        "decision_reason": "",
        "tier": None,
        "tier_reasons": [],
        "blocking": [],
        "chain": [],
        "diversity_exempt": [],
        "excluded_families": [],
        "brief_mode": "oversize",
        "scope": "full",
        "reviewed_head": None,
        "reviewed_files": {},
        "open_findings": {},
        "max_attempts": policy.max_attempts,
        "pool_blocked_until": {},
        "manual": False,
        "created_at": _now().isoformat(),
    }


IMPLEMENTATION_DIGEST = hashlib.sha256(
    b"".join(path.read_bytes() for path in sorted(Path(__file__).parent.glob("*.py")))
).hexdigest()


def _identities(repo: str, head_sha: str, files: list[ChangedFile]) -> dict[str, str]:
    try:
        tree = github.get_json(f"repos/{repo}/git/trees/{head_sha}?recursive=1")
        modes = {} if tree.get("truncated") else {entry["path"]: entry["mode"] for entry in tree["tree"]}
    except (github.GitHubError, KeyError, TypeError, ValueError):
        modes = {}
    return {
        item.path: f"{'removed' if item.removed else modes.get(item.path, '')}:{item.sha}"
        if item.sha and (item.removed or item.path in modes)
        else ""
        for item in files
    }


def _reusable(
    reviewed: retry.Reviewed | None,
    basis: str | None,
    scoped: list[ChangedFile],
    tier: Tier,
    current: dict[str, str],
) -> tuple[retry.Reviewed | None, list[ChangedFile]]:
    if reviewed is None or basis is None or reviewed.basis != basis or not all(current.values()):
        return None, scoped
    if current == reviewed.files:
        return reviewed, []
    if reviewed.outcome == retry.SUCCESS and tier.name != SCOPELESS_TIER and set(reviewed.files) <= set(current):
        return reviewed, [item for item in scoped if reviewed.files.get(item.path) != current[item.path]]
    return reviewed, scoped


def _merge_base(repo: str, base_sha: str, head_sha: str) -> str | None:
    try:
        merge_base = github.get_json(f"repos/{repo}/compare/{base_sha}...{head_sha}")["merge_base_commit"]["sha"]
    except (github.GitHubError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(merge_base, str) or re.fullmatch(r"[0-9a-f]{40}", merge_base) is None:
        return None
    return merge_base


def review_basis(merge_base: str, tier: Tier, policy: Policy, excluded: Iterable[str], policy_text: str) -> str:
    material = {
        "merge_base": merge_base,
        "tier": tier.name,
        "blocking": list(tier.blocking),
        "chain": [reviewer.to_json() for reviewer in policy.chain(tier.name)],
        "excluded_families": sorted(excluded),
        "policy": policy_text,
        "brief": BRIEF_TEMPLATE,
        "schema": VERDICT_SCHEMA,
        "implementation": IMPLEMENTATION_DIGEST,
        "workflow": hashlib.sha256(WORKFLOW_SOURCE.read_bytes()).hexdigest() if WORKFLOW_SOURCE.is_file() else "",
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{tier.name}:{merge_base}:{digest}"


def _finish_plan(out_dir: Path, plan: dict[str, Any]) -> int:
    _write_json(out_dir / PLAN_FILE, plan)
    post = plan["decision"] in (REVIEW, SUCCESS, FORK, CARRY)
    _output(
        {
            "decision": plan["decision"],
            "post": "true" if post else "false",
            "pr": str(plan["pr"]),
            "head_sha": plan["head_sha"],
            "tier": plan["tier"] or "",
        }
    )
    _summary(f"oracle-review-shadow plan for #{plan['pr']}: {plan['decision']} ({plan['decision_reason']})")
    return 0


def command_plan(args: argparse.Namespace) -> int:
    policy = load_policy(Path(args.policy))
    repo = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = _event()
    if event_name == "workflow_dispatch" and os.environ.get("GITHUB_REF") != DEVELOP_REF:
        print("oracle-review-shadow: error: dispatch runs only from develop", file=sys.stderr)
        return 2
    pr = _pr_number(args.pr)
    out_dir = Path(args.out)
    plan = _base_plan(policy, repo, pr, run_id)
    pull = github.get_json(f"repos/{repo}/pulls/{pr}")
    plan["base_sha"] = pull["base"]["sha"]
    plan["head_sha"] = pull["head"]["sha"]
    if pull["state"] != "open":
        plan["decision_reason"] = "the pull request is not open"
        return _finish_plan(out_dir, plan)
    if pull["base"]["ref"] != "develop":
        plan["decision_reason"] = "the pull request does not target develop"
        return _finish_plan(out_dir, plan)
    if pull.get("draft"):
        plan["decision_reason"] = "the pull request is a draft"
        return _finish_plan(out_dir, plan)
    event_head = (event.get("pull_request") or {}).get("head", {}).get("sha")
    if event_head and event_head != plan["head_sha"]:
        plan["decision_reason"] = "a newer head exists; its own run reviews it"
        return _finish_plan(out_dir, plan)
    files = [ChangedFile.from_api(item) for item in github.get_paginated(f"repos/{repo}/pulls/{pr}/files?per_page=100")]
    if github.get_json(f"repos/{repo}/pulls/{pr}")["head"]["sha"] != plan["head_sha"]:
        plan["decision_reason"] = "the head moved while the plan read it; its own run reviews it"
        return _finish_plan(out_dir, plan)
    labels = [label["name"] for label in pull.get("labels", [])]
    classification = classify(files, labels, policy, _soundness_predicate())
    plan["tier"] = classification.tier
    plan["tier_reasons"] = list(classification.reasons)
    if not classification.soundness:
        plan["decision"] = SUCCESS
        plan["decision_reason"] = "no soundness path changed"
        return _finish_plan(out_dir, plan)
    if (pull["head"].get("repo") or {}).get("full_name") != repo:
        plan["decision"] = FORK
        plan["decision_reason"] = "fork: owner review"
        return _finish_plan(out_dir, plan)
    manual = event_name in ("issue_comment", "workflow_dispatch")
    action = event.get("action", "")
    new_diff = event_name == "pull_request_target" and (
        action in NEW_DIFF_ACTIONS or (action == "edited" and "base" in (event.get("changes") or {}))
    )
    try:
        previous = github.latest_state(repo, pr)
    except (github.GitHubError, KeyError, ValueError) as exc:
        if manual:
            plan["decision_reason"] = f"the retry state could not be read: {exc}"
            return _finish_plan(out_dir, plan)
        previous = None
    now = _now()
    rerun = retry.decide_rerun(
        manual=manual, new_diff=new_diff, head_sha=plan["head_sha"], previous=previous, now=now, rules=policy.retry
    )
    if not rerun.allowed:
        plan["decision_reason"] = rerun.reason
        return _finish_plan(out_dir, plan)
    tier = policy.tiers[classification.tier or "very-high"]
    in_scope = set(classification.soundness_paths)
    scoped = [
        item for item in files if any(path in in_scope or not path.endswith(PROSE_SUFFIXES) for path in item.paths)
    ]
    current = _identities(repo, plan["head_sha"], scoped)
    merge_base = _merge_base(repo, plan["base_sha"], plan["head_sha"])
    excluded = selection.excluded_families(labels, policy)
    policy_text = Path(args.policy).read_text(encoding="utf-8")
    basis = review_basis(merge_base, tier, policy, excluded, policy_text) if merge_base else None
    reviewed = previous.reviewed if previous and action != "edited" else None
    reviewed, changed = _reusable(reviewed, basis, scoped, tier, current)
    plan["reviewed_files"] = current
    plan["review_basis"] = basis or ""
    try:
        plan["open_findings"] = dedup.open_fingerprints(github.review_threads(repo, pr), policy.bot_login)
    except (github.GitHubError, KeyError, ValueError) as exc:
        _summary(f"oracle-review-shadow: open review threads could not be read, so none are suppressed: {exc}")
    previous_json = previous.to_json() if previous else None
    if reviewed is not None and not changed:
        plan.update(
            {
                "decision": CARRY,
                "decision_reason": f"only prose changed since head {reviewed.head_sha} was reviewed",
                "reviewed_head": reviewed.head_sha,
                "manual": manual,
                "previous_state": previous_json,
            }
        )
        return _finish_plan(out_dir, plan)
    full_diff = github.get_diff(repo, pr)
    partial = len(changed) < len(scoped)
    diff_text = full_diff
    if partial and full_diff is not None:
        diff_text = select_files(full_diff, frozenset(path for item in changed for path in item.paths))
        if set(commentable_lines(diff_text)) != {item.path for item in changed}:
            partial, diff_text, changed = False, full_diff, scoped
    brief = build_brief(
        repo=repo,
        pr=pr,
        base_sha=plan["base_sha"],
        head_sha=plan["head_sha"],
        tier=tier.name,
        blocking=tier.blocking,
        files=changed if partial else files,
        diff_text=diff_text,
        max_bytes=policy.brief_max_bytes,
        reviewed_head=reviewed.head_sha if partial and reviewed else None,
        unchanged=[item for item in scoped if item not in changed] if partial else [],
        untracked=[item for item in files if item not in scoped] if partial else [],
    )
    write_private(out_dir / BRIEF_FILE, brief.text)
    write_private(out_dir / DIFF_FILE, full_diff or "")
    plan.update(
        {
            "decision": REVIEW,
            "decision_reason": rerun.reason,
            "blocking": list(tier.blocking),
            "chain": [reviewer.to_json() for reviewer in policy.chain(tier.name)],
            "diversity_exempt": list(tier.diversity_exempt),
            "excluded_families": sorted(excluded),
            "brief_mode": brief.mode,
            "manual": manual,
            "scope": "changed" if partial else "full",
            "reviewed_head": reviewed.head_sha if partial and reviewed else None,
            "pool_blocked_until": {
                pool: moment.isoformat()
                for pool, moment in (previous.pool_blocked_until.items() if previous else ())
                if moment > now
            },
            "previous_state": previous_json,
        }
    )
    return _finish_plan(out_dir, plan)


def _selection(plan: Mapping[str, Any]) -> SelectionInput:
    return SelectionInput.from_plan(plan, _now())


def command_select(args: argparse.Namespace) -> int:
    plan = _read_json(Path(args.plan))
    loaded = attempt_files.load(Path(args.attempts_dir), plan, os.environ["GITHUB_RUN_ID"])
    step, errors = attempt_files.decide(_selection(plan), loaded)
    chosen = (
        step.reviewer
        if not errors and step.kind == selection.REVIEW and len(loaded.attempts) == args.slot - 1
        else None
    )
    _output({"reviewer": chosen.name if chosen else "", "harness": chosen.harness if chosen else ""})
    _summary(f"slot {args.slot}: {chosen.name if chosen else step.kind} {'; '.join(errors)}".rstrip())
    return 0


def _chain_reviewer(plan: Mapping[str, Any], name: str) -> Reviewer:
    for item in plan["chain"]:
        if item["name"] == name:
            return Reviewer.from_json(item)
    raise SystemExit(f"oracle-review-shadow: {name!r} is not in this run's reviewer chain")


def command_review(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    plan = _read_json(plan_path)
    reviewer = _chain_reviewer(plan, args.reviewer)
    if reviewer.harness != args.harness:
        raise SystemExit(f"oracle-review-shadow: {reviewer.name} does not run on the {args.harness} job")
    brief_path = plan_path.parent / BRIEF_FILE
    brief_path.chmod(0o600)
    prompt = brief_path.read_text(encoding="utf-8") if plan["brief_mode"] != "oversize" else ""
    outcome = runner.review(
        reviewer,
        workspace=Path(args.workspace),
        head_sha=plan["head_sha"],
        prompt=prompt,
        scratch=Path(args.scratch),
        now=_now(),
    )
    artifact = attempt_files.build_artifact(
        run_id=os.environ["GITHUB_RUN_ID"],
        pr=plan["pr"],
        head_sha=plan["head_sha"],
        slot=args.slot,
        reviewer=reviewer.name,
        verdict=outcome.verdict,
        missing=outcome.missing,
        diagnostic=outcome.diagnostic,
    )
    _write_json(Path(args.out_dir) / attempt_files.artifact_name(args.slot), artifact)
    state = "verdict" if outcome.missing is None else f"absent ({outcome.missing.kind}: {outcome.missing.detail})"
    _summary(f"slot {args.slot}: {reviewer.name} {state}")
    return 0


def command_ensure_attempt(args: argparse.Namespace) -> int:
    plan = _read_json(Path(args.plan))
    path = Path(args.out_dir) / attempt_files.artifact_name(args.slot)
    if path.is_file():
        return 0
    artifact = attempt_files.build_artifact(
        run_id=os.environ["GITHUB_RUN_ID"],
        pr=plan["pr"],
        head_sha=plan["head_sha"],
        slot=args.slot,
        reviewer=args.reviewer,
        verdict=None,
        missing=Absence(ERROR, "the reviewer job did not finish"),
    )
    _write_json(path, artifact)
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    plan = _read_json(Path(args.plan))
    out_dir = Path(args.out_dir)
    run_url = (
        f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{plan['repo']}/actions/runs/{plan['run_id']}"
    )
    if plan["run_id"] != os.environ["GITHUB_RUN_ID"]:
        raise SystemExit("oracle-review-shadow: the plan belongs to another run")
    now = _now()
    if plan["decision"] == SUCCESS:
        final = report.fixed(retry.SUCCESS, "no soundness path changed")
    elif plan["decision"] == FORK:
        final = report.fixed(retry.PENDING, "fork: owner review")
    elif plan["decision"] == CARRY:
        previous = retry.State.from_json(plan["previous_state"])
        assert previous.reviewed is not None
        final = report.carried(plan, previous.reviewed.outcome)
        state = retry.next_state(
            previous=previous,
            pr=plan["pr"],
            head_sha=plan["head_sha"],
            outcome=final.state,
            manual=bool(plan["manual"]),
            now=now,
            pool_blocked_until=previous.pool_blocked_until,
        )
        _write_json(out_dir / "state" / github.STATE_FILE, state.to_json())
    else:
        selection_input = _selection(plan)
        loaded = attempt_files.load(Path(args.attempts_dir), plan, os.environ["GITHUB_RUN_ID"])
        step, errors = attempt_files.decide(selection_input, loaded)
        diff_path = Path(args.plan).parent / DIFF_FILE
        commentable = commentable_lines(diff_path.read_text(encoding="utf-8")) if diff_path.is_file() else {}
        final = report.finalize(plan, step, errors, loaded.attempts, loaded.verdicts, commentable)
        previous = plan.get("previous_state")
        state = retry.next_state(
            previous=retry.State.from_json(previous) if previous else None,
            pr=plan["pr"],
            head_sha=plan["head_sha"],
            outcome=final.state,
            manual=bool(plan["manual"]),
            now=now,
            pool_blocked_until=selection.pool_resets(selection_input, loaded.attempts),
            pending_cause=final.pending_cause,
            reviewed=retry.Reviewed(
                plan["head_sha"], plan.get("review_basis", ""), final.state, plan.get("reviewed_files", {})
            ),
        )
        _write_json(out_dir / "state" / github.STATE_FILE, state.to_json())
    _write_json(out_dir / "status.json", report.status_payload(plan, final, run_url))
    if final.body and (plan["findings_delivery"] == "comment" or final.review is None):
        _write_json(out_dir / "comment.json", {"body": final.body})
    if final.review is not None:
        _write_json(out_dir / "review.json", final.review)
    _output(
        {
            "state": final.state,
            "comment": "true" if (out_dir / "comment.json").is_file() else "false",
            "review": "true" if final.review is not None else "false",
            "has_state": "true" if (out_dir / "state" / github.STATE_FILE).is_file() else "false",
        }
    )
    _summary(f"oracle-review-shadow #{plan['pr']} {plan['head_sha']}: {final.state}: {final.description}")
    if final.body:
        _summary(final.body)
    return 0


def command_sweep(args: argparse.Namespace) -> int:
    policy = load_policy(Path(args.policy))
    repo = os.environ["GITHUB_REPOSITORY"]
    now = _now()
    dispatched = 0
    for pull in github.get_paginated(f"repos/{repo}/pulls?state=open&base=develop&per_page=100"):
        if dispatched >= policy.retry.sweep_max_dispatches:
            break
        if pull.get("draft") or (pull["head"].get("repo") or {}).get("full_name") != repo:
            continue
        state = github.latest_state(repo, pull["number"])
        if state is None or not retry.due_for_retry(state, pull["head"]["sha"], now, policy.retry):
            continue
        github.dispatch(repo, WORKFLOW_FILE, pull["number"])
        dispatched += 1
        _summary(f"retry dispatched for #{pull['number']}")
    _summary(f"oracle-review-shadow sweep dispatched {dispatched} retr{'y' if dispatched == 1 else 'ies'}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle-review-shadow")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--policy", required=True)
    plan.add_argument("--pr", required=True)
    plan.add_argument("--out", required=True)
    plan.set_defaults(handler=command_plan)
    select = commands.add_parser("select")
    select.add_argument("--plan", required=True)
    select.add_argument("--attempts-dir", required=True)
    select.add_argument("--slot", type=int, required=True)
    select.set_defaults(handler=command_select)
    review = commands.add_parser("review")
    review.add_argument("--plan", required=True)
    review.add_argument("--slot", type=int, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--harness", required=True)
    review.add_argument("--workspace", required=True)
    review.add_argument("--scratch", required=True)
    review.add_argument("--out-dir", required=True)
    review.set_defaults(handler=command_review)
    ensure = commands.add_parser("ensure-attempt")
    ensure.add_argument("--plan", required=True)
    ensure.add_argument("--slot", type=int, required=True)
    ensure.add_argument("--reviewer", required=True)
    ensure.add_argument("--out-dir", required=True)
    ensure.set_defaults(handler=command_ensure_attempt)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--plan", required=True)
    finalize.add_argument("--attempts-dir", required=True)
    finalize.add_argument("--out-dir", required=True)
    finalize.set_defaults(handler=command_finalize)
    sweep = commands.add_parser("sweep")
    sweep.add_argument("--policy", required=True)
    sweep.set_defaults(handler=command_sweep)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
