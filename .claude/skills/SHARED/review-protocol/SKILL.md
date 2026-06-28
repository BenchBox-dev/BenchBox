---
name: review-protocol
description: Shared protocol for review-shaped actions, authorization scope, defect routing, L2 audit handling, and local-only capture.
---

# Review Protocol

Governs code reviews, audits, research, compare, to-spec, security reviews, and L2 blind-spot audits. If a wrapper conflicts with this file, this file wins.

## Scope

Review-shaped actions are read-only plus local capture. They may read code, run analyses, produce findings, and write capture files to designated TODO/blind-spot/audit/decision/handoff locations.

They must not, as a side effect:

- Commit any file.
- Push to a remote.
- Open PRs or run `make pr-open` / `gh pr create`.
- Enable auto-merge.
- Chain into write-shaped skills without explicit user authorization in a separate turn.

A later request to fix/address review findings is write authorization; follow the normal project commit/PR flow.

Capture authorizes only the local file write. Final terminal action is a chat line such as `Recorded: <path>`; the user decides whether to PR.

For verification, run only commands the review scope demands. Long output goes to a temp log; cite paths/lines, do not paste large source blocks or command output.

## Defect Gate

Before classifying a finding, ask: if left as-is, will the observed code behave incorrectly, leak data, or miss a performance budget?

If yes, it is a defect. Defects belong in the severity table/action items and may become a TODO/fix only after authorization. They do not belong in blind-spots. Treat uncertain cases as defects; over-capturing TODOs is safer than degrading blind-spot signal.

## L2 Audit Scope

Layer 2 asks what class of issue the review framework failed to catch. It captures framework gaps, not the instance-level defects already found.

- Findings already in the severity table stay there.
- Critical/Required defects need an owner/action item even if L2 also captures a broader class.
- New concrete defects found during L2 become Required action items, not blind-spots.

## Project Bindings

Projects provide storage locations/specs and sweep workflows. This protocol governs behavior; project docs govern storage format. Do not duplicate behavior rules in storage docs.
