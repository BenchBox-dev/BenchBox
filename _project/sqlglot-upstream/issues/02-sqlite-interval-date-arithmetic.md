---
sqlglot_version: 30.6.0
status: needs-semantic-validation
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

The expected result must preserve the source expression's result type as well
as its calendar value. PostgreSQL DATE plus INTERVAL returns a timestamp; for
this literal day-arithmetic example, the candidate SQLite representation is:

```sql
SELECT DATETIME('2025-01-01', '+5 days')
```

## Actual output (sqlglot 30.6.0)

```sql
SELECT DATE('2025-01-01') + INTERVAL '5' DAY
```

SQLite rejects this with `Parse error: near "INTERVAL"`.

## Scope

This reproducer covers binary addition of a DATE literal and a day interval.
Do not extrapolate it to all interval expressions: DATE_ADD function calls can
take a different translation path. Month/year rollover, fractional seconds,
timezones and typed columns need separate execution evidence. The existing
BenchBox DATE(...) repair does not establish the expected timestamp semantics.

## Version

- `sqlglot==30.6.0`
- Python 3.12
- Reproduced via the harness at https://github.com/joeharris76/BenchBox/blob/develop/_project/sqlglot-upstream/repros/repro_all.py

## Notes

BenchBox currently works around this with a regex post-processor (`_fix_sqlite_unsupported_syntax`). We are happy to contribute a fix or test case if helpful.
