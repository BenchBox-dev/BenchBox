---
develop_sha: 542590b66a0cec74280d863f4e9d5ea6e48a9f50
measured_at_sha: 542590b66a0cec74280d863f4e9d5ea6e48a9f50
measurement_scope: "PR #1219 head tree"
---
# Historical hosted TODO tracker measurement (2026-07-18)

This record binds the live hosted-backend import totals to the exact PR #1219
head tree that produced them. The later acceptance audit is based on a newer
tree and therefore links here instead of attributing these counters to its
own `measured_at_sha`.

- Hosted import: **32,595 rows**, **82 data batches**, **44s wall** through the
  Hrana bulk path.
- The same run used a 4s local-SQLite control and compared the resulting
  report and statistics.

The live credentialed run is historical evidence only; this file does not
claim that the hosted primary was re-run during the later audit replay.
