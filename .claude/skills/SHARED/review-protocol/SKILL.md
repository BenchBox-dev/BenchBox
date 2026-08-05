---
name: review-protocol
description: Shared protocol for review-shaped actions, authorization scope, defect routing, L1/L2/L3 planning-depth layers, and local-only capture.
---

# Review Protocol

Governs code reviews, audits, research, compare, to-spec, security reviews, and L1/L2/L3 planning-depth layers (including blind-spot audits). If a wrapper conflicts with this file, this file wins.

## 1. Scope [REVIEW-AUTH-001]

Review-shaped actions are read-only plus local capture. They may read code, run analyses, produce findings, and write capture files to designated TODO/blind-spot/audit/decision/handoff locations.

A single request that bundles review with fixing or remediation remains review-only: the immediate action reports findings with zero tracked worktree-content changes. Do not interpret the bundle as permission to review and then edit locally in the same turn. Only a later user message, sent after the findings and explicitly authorizing implementation, permits remediation.

They must not, as a side effect:

- Commit any file.
- Push to a remote.
- Open PRs or run `make pr-open` / `gh pr create`.
- Enable auto-merge.
- Chain into write-shaped skills without explicit user authorization in a separate turn.

A later request to fix/address review findings is write authorization; follow the normal project commit/PR flow.

Capture authorizes only the local file write. Final terminal action is a chat line such as `Recorded: <path>`; the user decides whether to PR.

For verification, run only commands the review scope demands. Long output goes to a temp log; cite paths/lines, do not paste large source blocks or command output.

## 2. Defect Gate [REVIEW-DEFECT-001]

Before classifying a finding, ask: if left as-is, will the observed code behave incorrectly, leak data, or miss a performance budget?

If yes, it is a defect. Defects belong in the severity table/action items and may become a TODO/fix only after authorization. They do not belong in blind-spots. Treat uncertain cases as defects; over-capturing TODOs is safer than degrading blind-spot signal.

## 3. Planning-Depth Layers (L1/L2/L3) [REVIEW-DEPTH-001]

Use before committing to a plan or interpretation, in both review-shaped and generative actions.

1. **L1 — Obvious answer:** state the straightforward solution/finding first.
2. **L2 — Blind-spot audit:** after findings, ask what class of issue the framework misses, what a domain expert would notice, and what production-use assumption is hidden. In review-shaped actions, route L2 through Section 4 (L2 Audit Scope) below; in generative actions, apply the question inline (no capture).
3. **L3 — Problem reframe:** before commitment, ask whether the stated problem is the real constraint or an upstream symptom. Document any reframe.

## 4. L2 Audit Scope [REVIEW-L2-001]

Layer 2 asks what class of issue the review framework failed to catch. It captures framework gaps, not the instance-level defects already found.

- Findings already in the severity table stay there.
- Critical/Required defects need an owner/action item even if L2 also captures a broader class.
- New concrete defects found during L2 become Required action items, not blind-spots.

## 5. Capture and Project Bindings [REVIEW-CAPTURE-001]

Projects provide storage locations/specs and sweep workflows. This protocol governs behavior; project docs govern storage format. Do not duplicate behavior rules in storage docs.

Projects without their own binding: capture findings drafts out-of-tree to `~/.todo-db/finding-drafts/<project-id>/` as `YYYY-MM-DD-HHMMSS-<slug>.md` with the standard frontmatter (`id`, `date`, `status`, `finding_kind`, `review_context`, `related_paths`, `suggested_sweep`, `todo_id`) and record the path in chat; promote via the tracker's deferral/finding flow when available.

## 6. Semantic Parity [REVIEW-PARITY-001]

This compressed skill is the cross-project behavioral contract. A project may
maintain a longer protocol for rationale and storage bindings, but that form
must carry these stable policy IDs and preserve their semantics:

- `REVIEW-AUTH-001`
- `REVIEW-DEFECT-001`
- `REVIEW-DEPTH-001`
- `REVIEW-L2-001`
- `REVIEW-CAPTURE-001`
- `REVIEW-PARITY-001`

Wording and section layout may differ. Missing IDs or contradictory semantics
are drift; until reconciled, this canonical skill wins for agent behavior and
the project document wins only for project-specific storage details.
