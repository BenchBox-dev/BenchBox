# Post-merge attribution policy

Recorded 2026-09-08 (incident #2073, wrongly attributed revert). This file
sets the unknown-attribution policy once; new failure-ID classes escalate
to a loud failure instead of silently changing attribution behavior.

## Verdicts (`scripts/post_merge_signature.py attribute`)

- `revert`, basis `test-path`/`import`: evidence ties a new failure to the
  blamed SHA (owning test file/stem in the diff, or a file the failing test
  imports). Only these revert.
- `revert`, basis `no-extractable-path`: no test path extractable
  (job-level/lint failures). Fail-closed revert is kept: an unactionable
  signature must not leave develop red by default.
- `advisory`, basis `cleared`: every extractable failing test path clears
  the SHA. The workflow comments instead of reverting.
- `escalate`, basis `unrecognized-class`: an ID form no classifier
  understands. The workflow fails loudly for human classification; nothing
  reverts until the classifier is extended and the verdict recomputed.

## Workflow routing (`.github/workflows/develop-post-merge.yml`)

Revert requires `action == 'revert'` exactly (a previous `!= 'advisory'`
condition would have reverted on any new value, including `escalate`).
`advisory` routes to the advisory comment; `escalate` fails the job with
the unrecognized IDs. The verdict records `sha` and `attribution_basis`
so evidence applies only to the blamed commit it was computed against.

## Escalation procedure

1. Read `unrecognized_ids` from the workflow's attribution payload.
2. Classify each ID (new JUnit writer form, new job descriptor, or junk).
3. Extend `classify_failure_id` with a regression test replaying the ID.
4. Re-run attribution on the same SHA before any revert.
