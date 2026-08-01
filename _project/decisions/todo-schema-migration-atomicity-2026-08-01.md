# TODO schema migration atomicity

Status: accepted, 2026-08-01

## Decision

Every TODO schema revision must land with all four parts of one reviewable
contract: the `SCHEMA_VERSION` bump, a contiguous non-empty `MIGRATIONS` entry,
the wrapper's `TODO_SCHEMA_VERSION`, and an inventory entry that records both
deployment order and sanitized migration evidence. The always-required
`ci-paths` job checks that contract without connecting to any tracker backend.

The hosted primary is migrated with the candidate CLI before the schema bump is
merged. Sanitized confirmation is then committed as the current revision's
`deployment_evidence`. Connection details, database URLs, and tokens never
belong in the inventory or CI output.

## Failure behavior

Schema skew remains fail closed. A newer CLI refuses an older database and
directs the operator to `todo migrate`; an older CLI refuses a newer database
and directs the operator to upgrade the CLI. Read commands do not bypass these
checks. Unknown revisions are never inferred, auto-downgraded, or written.

This preserves the safety behavior that exposed the revision-4 cutover outage
while preventing an unpaired future bump from passing required CI. It does not
claim that a static file proves remote state: the evidence is an auditable,
secret-free release assertion whose correctness remains the migrator's
responsibility.

## Rejected alternatives

- Allow reads through schema skew: rejected because even nominal reads can
  depend on columns or invariants absent from the connected revision.
- Auto-migrate on connect: rejected because it turns read-only commands into
  implicit hosted writes and removes the deliberate deployment checkpoint.
- Query the hosted tracker in CI: rejected because pull-request CI must not
  receive production credentials or mutate production state.
