from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import dedup, selection
from .retry import ALL_ABSENT, FAILURE, INTEGRITY, PENDING, SUCCESS, UNREPORTED
from .selection import Attempt, Step
from .verdict import Finding, Placement, Verdict, place

DESCRIPTION_LIMIT = 140
STATES = {selection.PASS: SUCCESS, selection.FAIL: FAILURE, selection.PENDING: PENDING}


@dataclass(frozen=True)
class Final:
    state: str
    description: str
    body: str
    review: dict[str, Any] | None
    reviewer: str | None
    pending_cause: str | None = None


def _clip(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _finding_line(finding: Finding) -> str:
    detail = f"\n  {finding.detail}" if finding.detail else ""
    return f"- **{finding.severity}** `{finding.file}:{finding.line}`: {finding.title}{detail}"


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"**{title}**", "", *lines, ""] if lines else []


def _header(plan: Mapping[str, Any], state: str) -> list[str]:
    lines = [f"### {plan['status_context']}: {state} for `{plan['head_sha']}`", ""]
    if plan.get("mode") == "shadow":
        lines += ["Shadow mode: this result is advisory and does not replace the required `oracle-review` check.", ""]
    lines += ["This result supersedes those for earlier heads; their open review threads still apply.", ""]
    if plan.get("tier"):
        lines += [f"Tier: {plan['tier']} ({'; '.join(plan.get('tier_reasons', []))}).", ""]
    return lines


def _reviewer_line(plan: Mapping[str, Any], name: str | None) -> list[str]:
    spec = next((item for item in plan["chain"] if item["name"] == name), None)
    if spec is None:
        return []
    return [f"Reviewer: {name} ({spec['harness']} {spec['model']}, effort {spec['effort']}).", ""]


def _absences(attempts: list[Attempt], step: Step) -> list[str]:
    lines = [f"- {attempt.reviewer}: absent ({attempt.absence})" for attempt in attempts if attempt.outcome == "absent"]
    attempted = {attempt.reviewer for attempt in attempts}
    lines += [f"- {reason}" for reason in step.reasons if reason.split(":", 1)[0] not in attempted]
    return lines


def _review_payload(plan: Mapping[str, Any], body: str, placement: Placement) -> dict[str, Any]:
    return {
        "commit_id": plan["head_sha"],
        "event": "COMMENT",
        "body": body,
        "comments": [
            {
                "path": finding.file,
                "line": finding.line,
                "side": "RIGHT",
                "body": f"**{finding.severity}**: {finding.title}\n\n{finding.detail}".rstrip()
                + f"\n\n{dedup.marker(finding)}",
            }
            for finding in placement.inline
        ],
    }


def finalize(
    plan: Mapping[str, Any],
    step: Step,
    errors: list[str],
    attempts: list[Attempt],
    verdicts: Mapping[int, Verdict],
    commentable: Mapping[str, frozenset[int]],
) -> Final:
    if errors:
        body = "\n".join(
            [*_header(plan, PENDING), *_section("Result withheld: the run's artifacts failed validation", errors)]
        )
        review = _review_payload(plan, body, Placement((), ())) if plan.get("findings_delivery") == "review" else None
        return Final(PENDING, "result withheld: artifacts failed validation", body, review, None, INTEGRITY)
    pending_cause = ALL_ABSENT
    if step.kind == selection.REVIEW:
        reason = f"{step.reviewer.name if step.reviewer else 'a reviewer'}: selected but did not report"
        step = Step(selection.PENDING, None, (*step.reasons, reason))
        pending_cause = UNREPORTED
    state = STATES[step.kind]
    reviewer = step.reviewer.name if step.reviewer else None
    terminal = next(
        (attempt for attempt in attempts if attempt.reviewer == reviewer and attempt.outcome == step.kind),
        None,
    )
    verdict = verdicts.get(terminal.slot) if terminal is not None else None
    repeated: tuple[Finding, ...] = ()
    if verdict is None:
        placement = Placement((), ())
    else:
        fresh, repeated = dedup.split(verdict.findings, plan.get("open_findings", ()))
        placement = place(fresh, commentable)
    blocking = verdict.blocking(tuple(plan["blocking"])) if verdict else ()
    if state == SUCCESS:
        description = f"{reviewer}: no blocking findings"
    elif state == FAILURE:
        description = f"{reviewer}: {len(blocking)} blocking finding(s)"
    else:
        description = "pending: " + "; ".join(step.reasons or ("no reviewer available",))
    delivery = plan.get("findings_delivery", "comment")
    findings_lines = [_finding_line(finding) for finding in placement.inline]
    other_lines = [_finding_line(finding) for finding in placement.summary]
    lines = [*_header(plan, state), *_reviewer_line(plan, reviewer)]
    if verdict is not None and verdict.summary:
        lines += [verdict.summary, ""]
    if delivery == "comment":
        lines += _section("Findings on diff lines", findings_lines)
    lines += _section("Findings outside the diff", other_lines)
    if any(finding in blocking for finding in placement.summary):
        lines += ["Blocking findings outside the diff still fail the review.", ""]
    lines += _section(
        "Findings already open as review threads, not posted again",
        [f"- **{finding.severity}** `{finding.file}`: {finding.title}" for finding in repeated],
    )
    if plan.get("scope") == "changed":
        lines += [f"Scope: files changed since head `{plan['reviewed_head']}` was reviewed.", ""]
    lines += _section("Reviewers not available", _absences(attempts, step))
    body = "\n".join(lines).rstrip() + "\n"
    has_content = bool(placement.inline or placement.summary or state != SUCCESS)
    review = _review_payload(plan, body, placement) if delivery == "review" else None
    cause = pending_cause if state == PENDING else None
    return Final(state, _clip(description), body if has_content else "", review, reviewer, cause)


def carried(plan: Mapping[str, Any], outcome: str) -> Final:
    reviewed_head = plan["reviewed_head"]
    description = f"carried from {reviewed_head[:12]}: only prose changed"
    lines = [
        *_header(plan, outcome),
        f"Only prose files outside soundness paths changed since head `{reviewed_head}` was reviewed, so its"
        f" {outcome} result is carried to this head without running a reviewer. Its open review threads still"
        " apply.",
        "",
    ]
    body = "\n".join(lines).rstrip() + "\n"
    review = {"commit_id": plan["head_sha"], "event": "COMMENT", "body": body, "comments": []}
    return Final(outcome, _clip(description), body, review if plan.get("findings_delivery") == "review" else None, None)


def fixed(state: str, description: str) -> Final:
    return Final(state, _clip(description), "", None, None)


def status_payload(plan: Mapping[str, Any], final: Final, target_url: str) -> dict[str, Any]:
    return {
        "state": final.state,
        "context": plan["status_context"],
        "description": final.description,
        "target_url": target_url,
    }
