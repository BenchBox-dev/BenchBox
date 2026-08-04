# Audit evidence provenance

Reference for the SHA fields in `_project/audits/*.md`. The rules here are
enforced mechanically by `_project/scripts/audit_sha_check.py` (`make
audit-sha-check`), which is the authority; this page explains what each field
means and why the distinctions matter.

This lives outside `docs/development/agent-review-protocol.md` because it is a
records convention for one directory, not review behaviour every session must
carry. The protocol file counts against the agent instruction byte budget
enforced by `_project/scripts/agent_instruction_audit.py`; reference material
that a session reads on demand does not belong in that surface.

## Field conventions

`_project/audits/*.md` uses distinct SHA fields for distinct claims:

| Convention | Meaning | Numeric measurement binding |
|---|---|---|
| `develop_sha` | Develop base or lineage the audit describes | Necessary, but not sufficient for measured results |
| `checked_sha` | Exact non-base tree under test | `measured_at_sha` must match it |
| Test-result counts | Passed, failed, skipped, or timed-out totals | Require `measured_at_sha` |
| Inventory counts | Counted tests, queries, bundles, findings, comments, and similar entities | Require `measured_at_sha` |
| Dates, versions, PR/issue references | Narrative identifiers, not empirical results | Do not require fabricated measurement provenance |

## Binding numbers to the tree that produced them

`measured_at_sha` binds the original numeric evidence to the exact commit that
produced it. It equals `checked_sha` when that field exists, otherwise
`develop_sha`. A later spot replay does not replace or refresh the original
measurement: record its commit as `replay_sha` and describe exactly what was
rerun in `replay_scope`. The replay commit must descend from the measured
commit, and both must be reachable from the audit's committed tree when the
record is validated. If a replay contradicts a number, correct the claim using
new evidence instead of using `replay_sha` to bless the stale value.
