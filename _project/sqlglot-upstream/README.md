# SQLGlot upstream contribution prep

Drafted bug reports and a feature request for the SQLGlot project, plus the
minimal reproducer harness that pins each defect to a specific SQLGlot
version. **Nothing here has been filed upstream yet.** The drafts under
`issues/` are intended for human review before opening on
https://github.com/tobymao/sqlglot/issues.

## Layout

| Path | What it is |
|------|------------|
| `repros/repro_all.py` | Single-file Python harness covering all candidates; pinned to `sqlglot==30.6.0` |
| `issues/02-sqlite-interval-date-arithmetic.md` | Drafted bug report (Tier A) |
| `issues/03-sqlite-extract-not-lowered-to-strftime.md` | Drafted bug report (Tier B confirmed) |
| `issues/05-mysql-percentile-cont-extra-case-decorator.md` | Drafted bug report (Tier A) |
| `issues/06-questdb-dialect-feature-request.md` | Drafted feature request (Tier A) |

## Run the harness

```bash
uv run --with sqlglot==30.6.0 python _project/sqlglot-upstream/repros/repro_all.py
```

Exit code is zero only if every defect has been resolved upstream; any
remaining `FAIL` lines indicate the workaround in BenchBox is still load-bearing.

## Current verdict (sqlglot 30.6.0)

| # | Item | Tier | Repro result | BenchBox workaround | Action |
|---|------|------|--------------|---------------------|--------|
| 1 | DuckDB `GROUP/ORDER BY ALL` quoted under `identify=True` | B (verify) | **PASS** (no longer reproduces) | `dialect_utils._restore_group_order_by_all_keyword` | **Retire workaround in BenchBox.** Do not file. |
| 2 | SQLite `DATE + INTERVAL` not lowered to date modifier | A | FAIL | `dialect_utils._fix_sqlite_unsupported_syntax` | File: `issues/02-sqlite-interval-date-arithmetic.md` |
| 3 | SQLite `EXTRACT` not lowered to `STRFTIME` | B (verify) | FAIL | `dialect_utils._fix_sqlite_unsupported_syntax` | File: `issues/03-sqlite-extract-not-lowered-to-strftime.md` (refs prior #2592) |
| 4 | Postgres `date + integer` not promoted to `INTERVAL` | D | n/a (AST-ambiguous) | `dialect_utils.fix_postgres_date_arithmetic` | Do not file. Keep as BenchBox pre-processor. |
| 5 | MySQL `PERCENTILE_CONT` extra `CASE WHEN x IS NULL` decorator | A | FAIL | `h2odb_variants.MYSQL_Q9_SQL` | File: `issues/05-mysql-percentile-cont-extra-case-decorator.md` |
| 6 | QuestDB dialect missing | A | FAIL (no dialect) | `platforms/questdb_rewriter.py` | File: `issues/06-questdb-dialect-feature-request.md` |
| 7 | Netezza / Vertica missing | C | n/a (existing issues) | `dialect_utils.normalize_dialect_for_sqlglot` | Comment on existing tracker issues; no new issues. |

## What's filed already upstream

- Netezza: open feature requests
  [#6040](https://github.com/tobymao/sqlglot/issues/6040),
  [#1289](https://github.com/tobymao/sqlglot/issues/1289); failed PRs
  [#7402](https://github.com/tobymao/sqlglot/pull/7402),
  [#5637](https://github.com/tobymao/sqlglot/pull/5637).
- Vertica: closed-without-merge PRs
  [#7277](https://github.com/tobymao/sqlglot/pull/7277),
  [#3351](https://github.com/tobymao/sqlglot/pull/3351),
  [#3325](https://github.com/tobymao/sqlglot/pull/3325).
- DuckDB `ORDER BY ALL` parsing: [#3755](https://github.com/tobymao/sqlglot/issues/3755) closed by [#3756](https://github.com/tobymao/sqlglot/pull/3756) (merged). Our repro confirms this fix also covers the `identify=True` case.
- SQLite `EXTRACT`: prior [#2592](https://github.com/tobymao/sqlglot/issues/2592) (2023, closed without linked fix).

## Pre-flight before filing

1. Re-run the harness to confirm `FAIL` lines still reproduce on the latest published `sqlglot` version. Update the `sqlglot_version` frontmatter in each draft to match the version you reproduce against.
2. Skim each draft for tone — they are written in a neutral, evidence-led voice; no advocacy, no project promotion beyond a single offer line.
3. File one issue per draft. The drafts already include the harness URL so maintainers can run our repro against any version.
4. After filing, set `filed: true` and add a `tracker_url:` line to each draft's frontmatter.

## Follow-up TODOs (not part of this prep)

- Retire `_restore_group_order_by_all_keyword` and its branch in `translate_sql_query` once we drop support for `sqlglot < 30.<release-where-#3756-landed>`. The PASS in our repro means this code is no longer load-bearing on currently pinned versions.
- If maintainers accept the QuestDB dialect contribution offer, the
  rewriter in `benchbox/platforms/questdb_rewriter.py` becomes the natural
  starting point.
