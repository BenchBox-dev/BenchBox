---
name: review-protocol
description: Shared protocol for review-shaped actions, authorization scope, defect routing, L1/L2/L3 planning-depth layers, local-only capture, and plan prior-decision reconciliation.
---

# Review Protocol

Governs reviews, audits, research, comparisons, to-spec work, security reviews,
and L1/L2/L3 planning. This file wins if a wrapper conflicts with it.

For an adversarial review, also read
`references/adversarial-review.md`. The selected domain wrapper supplies its
own rubric.

## 1. Scope [REVIEW-AUTH-001]

Review-shaped actions are read-only except for local capture. They may inspect
artifacts, run analyses, report findings, and write only to designated TODO,
blind-spot, audit, decision, or handoff locations.

A request that combines review and remediation remains review-only. Report the
findings without changing tracked worktree content. Remediation requires a
later user message, sent after the findings, that explicitly authorizes it.

An internal quality check within an authorized write action is verification,
not review, when it stays in scope and adds no permissions. A user-requested
review or audit remains review-shaped.

A named write-shaped action that inspects before changing state, such as a
sweep, backlog clearance, iteration, batch, or closeout, is not review-shaped
when the request explicitly invokes its write behavior. A request only to
inspect, review, or audit that action remains review-shaped.

Review-shaped actions must not:

- Commit any file.
- Push to a remote.
- Open PRs or run `make pr-open` / `gh pr create`.
- Enable auto-merge.
- Chain into write-shaped skills without authorization in a later turn.

A later request to fix review findings is a repository write action. Follow
`SHARED/change-framework/SKILL.md`, including its branch, commit, push, and
draft-PR workflow unless the user requires local-only work or another
publication mode.

Capture authorizes only the local file write. End with `Recorded: <path>`; the
user decides whether to open a PR.

Run only commands required by the review scope. Save long output to a temporary
log and cite relevant paths and lines instead of pasting large excerpts.

## 2. Defect Gate [REVIEW-DEFECT-001]

Before classification, ask whether the observed code would behave incorrectly,
leak data, or miss a performance budget if left unchanged.

If yes, classify it as a defect. Put defects in the severity table and action
items, never in blind-spots. Create a TODO or fix only after authorization.
Route uncertain concrete cases through defect action items rather than
blind-spots. Mark their evidence incomplete and make the action item the needed
verification. Do not assign Critical without source, contract, reproduction, or
equivalent runtime evidence.

## 3. Planning-Depth Layers (L1/L2/L3) [REVIEW-DEPTH-001]

Apply these layers before committing to a plan or interpretation:

1. **L1 — Obvious answer:** state the straightforward solution/finding first.
2. **L2 — Blind-spot audit:** after findings, ask what issue class the
   framework misses, what a domain expert would notice, and which production
   assumption is hidden. For reviews, apply Section 4. For generative actions,
   ask inline without capture.
3. **L3 — Problem reframe:** ask whether the stated problem is the real
   constraint or an upstream symptom. Record any reframe.

## 4. L2 Audit Scope [REVIEW-L2-001]

Layer 2 captures gaps in the review framework, not defects already found.

- Findings already in the severity table stay there.
- Critical/Required defects need an owner/action item even if L2 also captures a broader class.
- New concrete defects found during L2 become Required action items, not blind-spots.

## 5. Capture and Project Bindings [REVIEW-CAPTURE-001]

This protocol governs behavior. Project documentation governs storage formats,
locations, and sweep workflows; it must not duplicate behavioral rules.

For projects without their own binding:

1. Save `~/.todo-db/finding-drafts/<project-id>/YYYY-MM-DD-HHMMSS-<slug>.md`.
2. Add frontmatter: `id`, `date`, `status`, `finding_kind`, `review_context`, `related_paths`, `suggested_sweep`, and `todo_id`.
3. Report the path. Promote through the tracker's deferral or finding flow when available.

## 6. Semantic Parity [REVIEW-PARITY-001]

This skill is the cross-project behavioral contract. A longer project protocol
may add rationale and storage bindings, but it must preserve these policy IDs
and their semantics:

- `REVIEW-AUTH-001`
- `REVIEW-DEFECT-001`
- `REVIEW-DEPTH-001`
- `REVIEW-L2-001`
- `REVIEW-CAPTURE-001`
- `REVIEW-PARITY-001`
- `REVIEW-PLAN-RECON-001`

Wording and layout may differ. Missing IDs or contradictory semantics are
drift. Until reconciled, this skill governs behavior and the project document
governs only project-specific storage.

## 7. Plan prior-decision reconciliation [REVIEW-PLAN-RECON-001]

Claim-against-code checking is necessary and not sufficient for plan reviews.
Before judging a plan's steps, enumerate the recorded decision surfaces the
plan's scope touches:

- future-state index and its priority tiers
- migration gates in design docs
- readiness and evidence documents
- open tracker items at the relevant priority

The plan must cite each one or explicitly supersede it. An unexplained
demotion of recorded priority, or a dropped open gate, is a plan defect.
