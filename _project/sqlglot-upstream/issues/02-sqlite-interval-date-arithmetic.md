---
sqlglot_version: 30.6.0
status: drafted
type: bug
target_dialect: sqlite
benchbox_workaround: benchbox/utils/dialect_utils.py:_fix_sqlite_unsupported_syntax
filed: false
---

# Title

SQLite generator emits `INTERVAL '...' DAY` for date arithmetic, but SQLite has no INTERVAL type

# Body

## Description

When transpiling date arithmetic from `postgres` (or any dialect with `INTERVAL` support) to `sqlite`, SQLGlot emits the `INTERVAL` literal verbatim. SQLite has no `INTERVAL` keyword and rejects the resulting SQL. The canonical SQLite form for date arithmetic is the modifier-string variant of `DATE()`, `DATETIME()`, etc., e.g. `DATE('2025-01-01', '+5 days')`.

## Reproducer

```python
import sqlglot

sql = "SELECT DATE '2025-01-01' + INTERVAL '5' DAY"
out = sqlglot.transpile(sql, read="postgres", write="sqlite")[0]
print(out)
```

## Expected output

Something equivalent to:

```sql
SELECT DATE('2025-01-01', '+5 days')
```

## Actual output (sqlglot 30.6.0)

```sql
SELECT DATE('2025-01-01') + INTERVAL '5' DAY
```

SQLite rejects this with `Parse error: near "INTERVAL"`.

## Scope

This affects all `INTERVAL '<n>' (DAY|MONTH|YEAR)` expressions when targeting SQLite, including TPC-H Q1, Q4, Q6, Q12, Q14, Q15, Q20 and broadly any analytical workload with date-bounded predicates.

## Version

- `sqlglot==30.6.0`
- Python 3.12
- Reproduced via the harness at https://github.com/joeharris76/BenchBox/blob/develop/_project/sqlglot-upstream/repros/repro_all.py

## Notes

BenchBox currently works around this with a regex post-processor (`_fix_sqlite_unsupported_syntax`). We are happy to contribute a fix or test case if helpful.
