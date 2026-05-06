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

### Wrapper-call-shape convention

Any new repro for an item that lives in
`benchbox/utils/dialect_utils.py:translate_sql_query` MUST exercise both:

- `read=<target>, write=<target>` — direct dialect probe.
- `read="postgres", write=<target>` — wrapper / cross-dialect probe.
  BenchBox normalizes Netezza-style SQL into postgres before the SQLGlot
  call, so the wrapper's actual `read=` argument at the helper's call
  site is `postgres`.

A single-dialect probe is not a valid retirement gate: the 2026-05-04
`_restore_group_order_by_all_keyword` retirement TODO was filed against
a `read=duckdb` PASS while the wrapper path still emits `ORDER BY "ALL"`
on the same sqlglot version. Both probes must PASS before any post-fixup
in `dialect_utils.translate_sql_query` is retired. Per-repro audit
verdicts on coverage are recorded in the
[Audit verdicts](#repro-coverage-audit) section below.

### Repro coverage audit

Verdicts after the 2026-05-06 sweep (TODO
`sqlglot-repro-harness-wrapper-call-shape`):

| Repro | Read/Write pair exercised      | Production call site read/write | Verdict |
|-------|--------------------------------|--------------------------------- |---------|
| 1     | duckdb->duckdb + postgres->duckdb | postgres->duckdb              | OK -- both probes present after this TODO. |
| 2     | postgres->sqlite               | postgres->sqlite                 | OK -- BenchBox runs SQLite via the postgres-normalized wrapper path. |
| 3     | postgres->sqlite               | postgres->sqlite                 | OK -- same wrapper path as #2. |
| 5     | postgres->mysql                | postgres->mysql                  | OK -- MySQL output goes through the postgres-normalized wrapper. |
| 6     | dialect lookup (no transpile)  | n/a (capability check)           | OK -- shape-agnostic, no read/write pair to validate. |

## Current verdict (sqlglot 30.6.0)

| # | Item | Tier | Repro result | BenchBox workaround | Action |
|---|------|------|--------------|---------------------|--------|
| 1 | DuckDB `GROUP/ORDER BY ALL` quoted under `identify=True` | B (verify) | PASS for `read=duckdb`; **FAIL for `read=postgres,write=duckdb`** (the path BenchBox actually exercises) | `dialect_utils._restore_group_order_by_all_keyword` | **Keep workaround.** PR #3756 fixed direct DuckDB only; cross-dialect path still emits `ORDER BY "ALL"` on `sqlglot==30.6.0`. Do not file (narrower repro warranted before). |
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
- DuckDB `ORDER BY ALL` parsing: [#3755](https://github.com/tobymao/sqlglot/issues/3755) closed by [#3756](https://github.com/tobymao/sqlglot/pull/3756) (merged in v25.6.0). Our repro confirms the fix covers the `identify=True` case for `read="duckdb", write="duckdb"`. The fix does **not** cover the `read="postgres", write="duckdb"` path BenchBox uses for Netezza/Postgres-shaped TPC sources — that still emits `ORDER BY "ALL"` on `sqlglot==30.6.0`, which is why the BenchBox post-fixup stays.
- SQLite `EXTRACT`: prior [#2592](https://github.com/tobymao/sqlglot/issues/2592) (2023, closed without linked fix).

## Pre-flight before filing

1. Re-run the harness to confirm `FAIL` lines still reproduce on the latest published `sqlglot` version. Update the `sqlglot_version` frontmatter in each draft to match the version you reproduce against.
2. Skim each draft for tone — they are written in a neutral, evidence-led voice; no advocacy, no project promotion beyond a single offer line.
3. File one issue per draft. The drafts already include the harness URL so maintainers can run our repro against any version.
4. After filing, set `filed: true` and add a `tracker_url:` line to each draft's frontmatter.

## Follow-up TODOs (not part of this prep)

- Extend `repros/repro_all.py` to also exercise `read="postgres", write="duckdb"` for the `GROUP/ORDER BY ALL` case. The current single-dialect repro mis-classified item #1 as fully fixed by PR #3756; a cross-dialect probe would have flagged the narrower remaining gap. Until the harness covers BenchBox's actual call shape, retirement decisions for this row should be made by hand against `dialect_utils.translate_sql_query`, not the harness alone.
- If maintainers accept the QuestDB dialect contribution offer, the
  rewriter in `benchbox/platforms/questdb_rewriter.py` becomes the natural
  starting point.
