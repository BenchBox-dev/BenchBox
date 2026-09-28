# Decision: Raise the native merge queue response timeout

Date: 2026-09-28
Status: Accepted and applied
Destination: `BenchBox-dev/BenchBox`, `develop-squash-only` ruleset `15611785`

## Context

PR #2439 was removed from the native merge queue at the 60-minute response
deadline. Its merge-group workflows all completed successfully, but the
required `ci-required-result` job finished after 76 minutes. The delay came
from the heavy merge-group lane and runner contention, not a failing check.

Evidence from the queue certification run:

- Queue head: `7eedb6d1e916554eed880926b07cd306b8e503b6`
- Develop PR workflow: run `36486167634`, completed successfully at
  `2026-09-28T22:43:19Z`
- Documentation workflow: run `36486167612`, completed successfully at
  `2026-09-28T22:34:56Z`
- The entry was removed at the 60-minute response deadline before the final
  required aggregate completed.

## Decision

Raise `check_response_timeout_minutes` from `60` to `120` in ruleset
`15611785`. Keep `SQUASH`, `ALLGREEN`, `min_entries_to_merge: 1`, the five-entry
build and merge limits, and zero wait unchanged. The 120-minute value provides
44 minutes of observed headroom while still bounding a stalled merge group.

Update the repository's drift checker and operator documentation to match the
live ruleset. The drift checker remains fail closed for any other protected
queue change.

## Rollback

If queue latency or stalled runners make the longer window unacceptable, restore
the timeout to 60 only after measuring the full merge-group duration and
confirming that required checks fit within the response deadline. Do not change
the other queue parameters as part of that rollback.
