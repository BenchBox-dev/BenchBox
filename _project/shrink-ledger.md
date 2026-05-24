# BenchBox Core Python Shrink Ledger

This legacy single-file ledger is retained only as a pointer for older branch
history. The retired 66% target is no longer operative.

Current shrink accounting uses one PR-body fragment per slice under
`_project/shrink-ledger/`, rolled up with:

```bash
make shrink-rollup
```

The active control document is `_project/goal-shrink-core-code.md`; the
recorded objective is 12,000-19,000 credited maintained-Python lines, with
credit counted only after fragments merge to `develop`.
