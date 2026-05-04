---
sqlglot_version: 30.6.0
status: drafted
type: bug
target_dialect: mysql
also_affects: singlestore
benchbox_workaround: benchbox/sql_compat/rules/query_source/h2odb_variants.py
filed: false
related: https://github.com/tobymao/sqlglot/issues/3257
---

# Title

MySQL generator decorates `PERCENTILE_CONT WITHIN GROUP (ORDER BY x)` with synthetic `CASE WHEN x IS NULL` clause that engines reject

# Body

## Description

When the write dialect is `mysql`, SQLGlot adds a synthetic `CASE WHEN <col> IS NULL THEN 1 ELSE 0 END, <col>` to the `WITHIN GROUP (ORDER BY ...)` clause of `PERCENTILE_CONT`. The standard ANSI form should round-trip; the synthetic NULL-sort decorator is rejected by SingleStore's MySQL-compatible parser (and is not required by the SQL standard for the percentile expression).

## Reproducer

```python
import sqlglot

sql = "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) FROM t"
out = sqlglot.transpile(sql, read="postgres", write="mysql")[0]
print(out)
```

## Expected output

```sql
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) FROM t
```

## Actual output (sqlglot 30.6.0)

```sql
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CASE WHEN x IS NULL THEN 1 ELSE 0 END, x) FROM t
```

SingleStore (MySQL wire-protocol) responds with a parser error on the `CASE` inside `WITHIN GROUP`.

## Scope

`PERCENTILE_CONT` is a SQL standard ordered-set aggregate; this affects any analytical query using percentiles when the write dialect is `mysql`. In our corpus this surfaces in H2ODB Q9 and would surface in any benchmark or production query on SingleStore using `PERCENTILE_CONT`.

## Where it likely originates

`add_within_group_for_percentiles` (the rewrite rule referenced indirectly in https://github.com/tobymao/sqlglot/issues/3257) appears to be the source of the decorator. That issue covers a different downstream failure on Snowflake, but the underlying rule may be over-applying.

## Version

- `sqlglot==30.6.0`
- Python 3.12
- Reproduced via the harness at https://github.com/joeharris76/BenchBox/blob/develop/_project/sqlglot-upstream/repros/repro_all.py

## Notes

BenchBox currently bypasses SQLGlot for this query and ships a verbatim ANSI variant. Happy to contribute a fix or test case.
