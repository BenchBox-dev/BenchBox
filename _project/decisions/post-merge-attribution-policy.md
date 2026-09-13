# Post-merge attribution policy

Recorded 2026-09-13 after the #2073 misattributed revert. The post-merge
workflow may propose an automatic revert only when the failure is new, the
failing commit is still the live `develop` target, predecessor evidence is
available, and the failing test or job has a positive changed-subsystem
ownership match.

## Evidence contract

Every non-green attribution artifact records:

- the immutable failing commit, workflow run, and associated pull request;
- failing test IDs and job identifiers;
- current and predecessor source-input identities;
- the predecessor run and signature evidence;
- the ownership match and its basis; and
- classification, owner, and next action.

Failure classes are `code-regression`, `external-ref-drift`,
`environment/transient-failure`, `stale-run`, and `unknown`. Temporal
adjacency is not ownership evidence. Missing, unmappable, stale, or
conflicting evidence remains red and updates the idempotent
`incident:develop-red` issue. A passing exact-commit rerun is transient; a
changed external source identity without ownership is external-reference
drift; an exact ownership match is the only automatic-revert class.

Before a revert retry or close, the workflow checks the live `develop` target
and inspects the proposed inverse diff. A revert that introduces another
failure is not approved automatically. Incident keys derive from the sorted
failure signature, so reruns update one incident instead of opening
duplicates.

The dotted-JUnit classname normalization is provided by PR #2071 and is not
duplicated here.
