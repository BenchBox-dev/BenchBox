---
sqlglot_version: 30.18.0
upstream_sha: 5cfb5997a99010940138670adf3d6b34ac5a0a08
status: upstream-followup-posted
type: bug
target_dialect: sqlite
benchbox_workaround: benchbox/utils/dialect_utils.py:_fix_sqlite_unsupported_syntax
filed: true
tracker_url: https://github.com/tobymao/sqlglot/issues/2592#issuecomment-5653487646
prior_issue: https://github.com/tobymao/sqlglot/issues/2592
---

# Title

SQLite generator does not lower `EXTRACT(... FROM date)` to `STRFTIME` (revisit of #2592)

# Body

## Description

`EXTRACT(YEAR FROM d)` is left verbatim when the write dialect is `sqlite`.
SQLite has no EXTRACT function. For a bare projection over ISO date TEXT,
`CAST(STRFTIME('%Y', d) AS INTEGER)` produces the expected calendar year;
the semantic limitations below prevent treating it as a universal replacement.

A prior issue [#2592](https://github.com/tobymao/sqlglot/issues/2592) was closed
as not planned. The maintainer raised a date-representation concern and invited
a well-crafted PR. [#7152](https://github.com/tobymao/sqlglot/issues/7152) also
reported the extraction gap; its maintainer response invited contributions for
remaining cases. Prefer following up on that history rather than filing a
duplicate report. This preparation reproduces on 30.6.0, 30.18.0 and upstream
commit `5cfb5997a99010940138670adf3d6b34ac5a0a08`.

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

## Actual output (sqlglot 30.18.0)

```sql
SELECT EXTRACT(YEAR FROM d) FROM t
```

SQLite rejects this with `Parse error: near "FROM"`.

## Scope

The bounded reproducer covers YEAR/MONTH/DAY on DATE columns represented as
ISO date TEXT in SQLite, DATE casts, nested COALESCE, duplicate values, NULLs,
leap days and century boundaries. The related DuckDB DATE_PART form currently
parses as Anonymous rather than Extract and needs separate parser work.

## Semantic questions before implementing

The basic STRFTIME replacement is not a complete translation contract:

- A TIMESTAMP cast remains a SQLite numeric-affinity cast. Wrapping
  `CAST('2020-06-01 12:00:00' AS TIMESTAMP)` in STRFTIME produces year -4707,
  not 2020. A DATE cast already generates DATE(...) on current main, but that
  does not solve timestamp casts.
- Casting the extracted year to INTEGER changes surrounding arithmetic:
  `CAST(STRFTIME('%Y', DATE('2020-06-01')) AS INTEGER) / 3 > 673` is false in
  SQLite. PostgreSQL EXTRACT has a numeric result, so the source expression is
  true. A bare projection test misses this difference.
- EXTRACT also accepts intervals in source dialects. Timestamp timezone
  semantics and dates outside SQLite's documented range need explicit limits.

Agree on handling source result types and unsupported input types before
submitting a generic generator patch. Do not silently change all extraction
to floating point or hide precision differences in the comparator.

## Version

- `sqlglot==30.6.0`, `30.18.0`, and the upstream SHA above
- Standalone execution reproducer: `_project/sqlglot-upstream/repros/sqlite_extract.py`
- The script executes SQLite with explicit expected results, not PostgreSQL.
  DuckDB execution independently checked the two surrounding-expression
  counterexamples; it is not presented as PostgreSQL execution evidence.

## Notes

BenchBox currently works around this with a regex post-processor (`_fix_sqlite_unsupported_syntax`). Happy to contribute a fix or test case.
