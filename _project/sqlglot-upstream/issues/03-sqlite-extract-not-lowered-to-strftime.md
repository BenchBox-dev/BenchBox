---
sqlglot_version: 30.6.0
status: drafted
type: bug
target_dialect: sqlite
benchbox_workaround: benchbox/utils/dialect_utils.py:_fix_sqlite_unsupported_syntax
filed: false
prior_issue: https://github.com/tobymao/sqlglot/issues/2592
---

# Title

SQLite generator does not lower `EXTRACT(... FROM date)` to `STRFTIME` (revisit of #2592)

# Body

## Description

`EXTRACT(YEAR FROM d)` is left verbatim when the write dialect is `sqlite`. SQLite has no `EXTRACT` function — the canonical equivalent is `CAST(STRFTIME('%Y', d) AS INTEGER)` (and `'%m'`, `'%d'`, etc. for `MONTH` and `DAY`).

A prior issue (https://github.com/tobymao/sqlglot/issues/2592, 2023) reported the same gap and was closed without a linked fix. This issue re-reports against `sqlglot==30.6.0` with a current minimal reproducer.

## Reproducer

```python
import sqlglot

sql = "SELECT EXTRACT(YEAR FROM d) FROM t"
out = sqlglot.transpile(sql, read="postgres", write="sqlite")[0]
print(out)
```

## Expected output

Something equivalent to:

```sql
SELECT CAST(STRFTIME('%Y', d) AS INTEGER) FROM t
```

## Actual output (sqlglot 30.6.0)

```sql
SELECT EXTRACT(YEAR FROM d) FROM t
```

SQLite rejects this with `Parse error: near "FROM"`.

## Scope

`YEAR`, `MONTH`, `DAY` at minimum. Affects every TPC-H/TPC-DS query that uses `EXTRACT` against a date column when targeting SQLite.

## Version

- `sqlglot==30.6.0`
- Python 3.12
- Reproduced via the harness at https://github.com/joeharris76/BenchBox/blob/develop/_project/sqlglot-upstream/repros/repro_all.py

## Notes

BenchBox currently works around this with a regex post-processor (`_fix_sqlite_unsupported_syntax`). Happy to contribute a fix or test case.
