# Batch tracker contract (BenchBox side)

How a BenchBox feature batch binds to todo-db items, and what the tracker
must provide before parallel member preparation is safe.

## Binding (works today, serial workflow)

- One batch = one named delivery with a member list recorded in the frozen
  process baseline (`feature_batch_preregistration`) and in the integration
  worktree config (`scripts/batch_integration.py start`).
- Members are implemented serially under one integrator on one shared
  branch (`docs/agent/batch-feature-delivery.md`): `take` → implement
  within `only_modify` scope → `check_scope` → commit → `progress` with
  file+test evidence → `finish`.
- Claims are exclusive per principal: the integrator holds at most one
  member claim at a time and never force-releases another owner's claim.
- Cross-item dependencies stay tracker-managed; the branch provides the
  shared base, never a shortcut around dependency order.
- Ledger: `.todo-batch/` entries per the upstream batch reference, verified
  ignored via `git check-ignore`, never committed.

## Prepared delivery (requires upstream support)

Parallel member worktrees plus canonical claim handoff, multi-member
delivery records, and dependency-as-delivered transitions need a
`prepared` batch mechanism in the canonical tracker. Verified absent as
of todo-db `8fe1cb7` (upstream `references/batch.md` specifies the serial
loop only; no `prepared` state in the MCP surface). Until that lands:

- No parallel member worktrees, no canonical claim handoff, no
  `_project/analysis/batch-source-delivery.json` (a receipt without a
  canonical delivery is fabrication).
- The concrete upstream change/review plan: prepared-member states,
  per-member scope exclusivity enforced at claim time, delivery-scoped
  evidence binding, and a claim-handoff verb with owner generation — owned
  by the todo-db repository, reviewed there.
- When it lands: pin the delivering todo-db SHA in `skill-sync.yaml`,
  regenerate mirrors with `make skill-sync`, and adopt member worktrees
  behind `scripts/batch_integration.py verify` (ancestry + single-owner
  gates already exist).
