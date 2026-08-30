# Handoff: Unblock Optimal Tuning Corpus — FK-Aware Drop Ordering + Adversarial Review → PR

**Revision:** 1, written 2026-08-29 19:45 UTC. Prior handoff is the SF1 repopulation takeover from `agy` `a344e6e2-918f-4808-b058-0f15760445dc` (now PR #1945). Every SHA, branch, file-head, and workflow result below was queried while writing; where a claim is advice rather than verified fact, it says so.

## 1. Objective

Unblock the **optimal tuning corpus** defined in `_project/planning/plan-optimal-tuning-corpus.md` (22 cells, only where `tuned` is expected to help per §2 criteria) by fixing the single-run FK-aware drop ordering bug that blocks every `duckdb --tuning tuned` cell, then adversarially review the completed SF1 repopulation changes, implement any Required/Critical findings, and submit the combined result as a PR.

This handoff is **actionable** — the next agent should make the fixes, review, fix the review findings, and open the PR. Do not merely re-plan.

## 2. Current State — Verified 2026-08-29 19:40 UTC

### Git

| ref | SHA | subject |
|---|---|---|
| `origin/develop` | `fe49b67d` | docs(blog): lead voice guides... (#1942) |
| `origin/chore/repopulate-results-explorer-corpus-sf1` | `d44c154bb` | fix(results-data): validate published corpus bundles |
| `chore/repopulate-results-explorer-corpus-sf1` (local, wt `BenchBox.wt-repopulate-results-explorer-corpus-sf1`) | `d44c154bb` | same |
| `chore/tuning-corpus-optimal` (local, wt `BenchBox.wt-tuning-corpus-optimal`) | `d44c154bb` | same (reset from `fe49b67d` via `git reset --hard d44c154bb`) |
| PR **#1945** | `chore/repopulate-results-explorer-corpus-sf1 → develop` | 151 bundles / 24 cohorts, `validate_corpus` OK, Explorer `results.duckdb` built | https://github.com/BenchBox-dev/BenchBox/pull/1945 |

**Primary clone** (`/Users/joe/Developer/BenchBox`) is clean at `fe49b67d`.

**Worktree `BenchBox.wt-tuning-corpus-optimal`** (the one you are in):
```
HEAD: d44c154bb
ls results-data/bundles | wc -l: 296 (151 primary + manifests)
corpus-inventory.json: 151 bundles, 24 cohorts, validate_corpus: All 24 OK
plan file: _project/planning/plan-optimal-tuning-corpus.md (22 cells, §4 matrix)
tuning templates: duckdb 9, databricks 5 (+ liquid variants), dataframe 3 optimized
```

**Worktree `BenchBox.wt-repopulate-results-explorer-corpus-sf1`**:
```
HEAD: d44c154bb (after published-validation fix that removed write_primitives)
PR #1945 head: d44c154bb
Previous SHA e5bad0f16 had 157 bundles (included write_primitives 0.01/0.1/1.0 which were pruned as 0ms/invalid in d44c154)
```

### Tuning Corpus Plan (ready)

`_project/planning/plan-optimal-tuning-corpus.md` defines the 22-cell matrix (only where `tuned_template` rank 2 and `rendered_via != "none"`):

- **DuckDB 9 benchmarks** at SF1 (+ SF10 where scale exists): `tpch`, `tpcds`, `ssb`, `tpchavoc`, `amplab`, `h2odb`, `clickbench`, `read_primitives`, `joinorder` via `duckdb/<benchmark>_tuned.yaml` (`post_load:duckdb_ctas_sort`)
- **Spark (databricks alias) 4 benchmarks** at SF1/SF10: `tpch`, `tpcds`, `ssb`, `tpchavoc` via `databricks/<benchmark>_tuned.yaml` + `*_liquid_tuned.yaml`
- **DataFrame 3** at `tpch` SF1 only: `polars`, `pandas`, `pyspark` via explicit `examples/tunings/dataframe/polars_optimized.yaml` etc. (no auto-discovery)

Explicitly **excluded**: `datafusion`, `sqlite`, `clickhouse-local`/`chdb`, `dask-df`/`modin-df` (no `tuned_template` → `basic_constraints` only), and all SF0.01/SF0.1 for tuned.

### Blocker — Reproduced

First tuned probe fails:

```bash
cd ../BenchBox.wt-tuning-corpus-optimal
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs \
  uv run -- benchbox run --platform duckdb --benchmark tpch --scale 1 --tuning tuned --phases generate,load,power
```

Tail:
```
Creating database schema... Applying unified tuning configuration... ✅
❌ Tuning: No tuning metadata found in database
❌ Table orders: expected ~1.2M rows, found 0 ...
❌ Benchmark execution failed: Dependency Error: Cannot drop entry "supplier" because there are entries that depend on it.
   table "partsupp" depends on table "supplier".
   table "lineitem" depends on table "supplier".
   Use DROP...CASCADE
```

**Root cause (single-run, not second-run reuse):**
- `_create_schema_with_tuning` ([base/data_loading.py:2980](/Users/joe/Developer/BenchBox/benchbox/platforms/base/data_loading.py:2980)) creates all 8 TPC-H tables with FKs from `duckdb/tpch_tuned.yaml:5` (`foreign_keys.enabled: true`).
- `DataLoader._load_file_based_data` loads tables in FK-safe order (`get_fk_ordered_table_names()` from #1189) — `supplier` before `partsupp`/`lineitem` — correct for `COPY`.
- Immediately after each table's `COPY`, it calls `PlatformAdapter.apply_ctas_sort` ([base/sorted_ingestion.py:119](/Users/joe/Developer/BenchBox/benchbox/platforms/base/sorted_ingestion.py:119)) → `DuckDB._build_duckdb_ctas_sort_sql` ([duckdb.py:119](/Users/joe/Developer/BenchBox/benchbox/platforms/duckdb.py:119)) → `core.tuning.generators.duckdb.DuckDBDDLGenerator.generate_ctas_ddl(..., or_replace=True)` → `CREATE OR REPLACE TABLE "supplier" AS SELECT ... ORDER BY ...`.
- `CREATE OR REPLACE` is implicit `DROP` + `CREATE`. The `DROP` hits the live FK from `partsupp`/`lineitem` declared in step 1, even though `supplier` loaded first. This is **TODO `fk-aware-drop-ordering-20260717`** (`_project/todo-db-export/items.jsonl:792`) — `w0` notes: "NOT a schema-recreation issue ... the real failure is inside a SINGLE run: ... `apply_ctas_sort`'s `CREATE OR REPLACE` implicitly drops the parent while a dependent FK still references it."

The 325 `tuned` bundles were purged 2026-07-16 per `results-data/REGENERATION.md:8` because `tuning_config` never reached adapters on the direct CLI path (#1176, `tests/unit/platforms/test_tuning_config_forwarding.py:4`). The forwarding fix now delivers `tuning_config`, so the FK graph exists and the bug surfaces.

## 3. What Remains — Ordered

### A. Fix the FK-aware CTAS-sort drop (Required)

**TODO:** `fk-aware-drop-ordering-20260717` — `planning` state, 4 work units:

- **w0 (repro, you are here):** Reproduce a SINGLE tuned run where sort targets a parent with FK dependents (`duckdb/tpch_tuned.yaml` sorts `SUPPLIER`, referenced by `LINEITEM`/`PARTSUPP`). Do not test a second CLI invocation — `handle_existing_database` either reuses wholesale or deletes the whole file, never per-table `DROP`.
  ```bash
  rm -rf /tmp/drop-order-check && \
  uv run -- python -m benchbox.cli.main run --platform duckdb --benchmark tpch --scale 0.01 \
    --tuning examples/tunings/duckdb/tpch_tuned.yaml --non-interactive --output /tmp/drop-order-check
  # Expected before fix: "Cannot drop entry" error
  ```
- **w1:** Make `apply_ctas_sort`'s `CREATE OR REPLACE` FK-aware in the shared helper, not per-adapter copies. Options: drop FK constraints referencing the target table before the CTAS and re-add after, or defer sorting of parent tables until dependents are loaded (reverse of `get_fk_ordered_table_names`). Must handle cycles as `get_fk_ordered_table_names` does. Scope: `benchbox/core/schema_primitives.py`, `benchbox/platforms/base/sorted_ingestion.py`, `benchbox/platforms/duckdb.py` (and audit postgres-family adapters per `w3`).
- **w2:** Regression tests — (1) tuned single-run load with FK+sort on a referenced parent succeeds *and* (2) the FK remains enforced after (violating `INSERT` must fail, per `test_fk_constraint_is_actually_enforced_after_load` pattern). Unit test for reverse-topo order for `tpch`/`ssb`/`coffeeshop`.
- **w3:** Audit other FK-enforcing adapters' recreation paths for the same class.

**Verification for w0-w1:**
```bash
rm -rf /tmp/drop-order-check && uv run -- python -m benchbox.cli.main run --platform duckdb --benchmark tpch --scale 0.01 --tuning examples/tunings/duckdb/tpch_tuned.yaml --non-interactive --output /tmp/drop-order-check
uv run -- python -m pytest tests/unit/core tests/unit/platforms -q
```

### B. Execute the Optimal Tuning Corpus Sweep (per plan §6)

After w1 lands, run the 22-cell matrix **serialized** (DuckDB → Spark → DataFrame) with `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs` and `generate,load,power` only:

```bash
# DuckDB tuned SF1/SF10 (9 benchmarks)
for bench in tpch tpcds ssb tpchavoc amplab h2odb clickbench read_primitives joinorder; do
  for scale in 1 10; do
    # skip invalid combos: clickbench/joinorder only 1.0, amplab/h2odb only 1.0; SF10 only where prior SF10 exists
    BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs uv run -- benchbox run --platform duckdb --benchmark $bench --scale $scale --tuning tuned --phases generate,load,power --compression zstd:9 --non-interactive --quiet
  done
done
# Spark (databricks alias) SF1/SF10
for bench in tpch tpcds ssb tpchavoc; do for scale in 1 10; do BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs uv run -- benchbox run --platform spark --benchmark $bench --scale $scale --tuning tuned --phases generate,load,power --compression zstd:9 --non-interactive --quiet; done; done
# DataFrame SF1 only, explicit paths
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs uv run -- benchbox run --platform polars --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/polars_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs uv run -- benchbox run --platform pandas --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/pandas_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs uv run -- benchbox run --platform pyspark --benchmark tpch --scale 1 --tuning examples/tunings/dataframe/pandas_optimized.yaml --phases generate,load,power --compression zstd:9 --non-interactive --quiet
```

Pre-check:
```bash
uv run -- pytest tests/unit/platforms/test_tuning_config_forwarding.py -k test_from_config_forwards_tuning_kwargs -q
```

### C. Stage, Validate, and Publish (per plan §7)

For each new `~/Developer/benchmark_runs/results/*_tuned*20260829*.json` with `summary.queries.total > 0`, `summary.timing.geometric_mean_ms > 0`, `tuning_validation_status in {applied_verified,applied_unverified}` and `has_tuning=true`:

1. `cp` to `results-data/bundles/` + sibling `<stem>.tuning.json` (already emitted) + sidecar `<stem>.manifest.json` with `{"result_source":"internal","funding":"unspecified"}` for `maintainer-run` trust.
2. Gates:
```bash
uv run -- python scripts/generate_corpus_inventory.py --write
uv run -- python results-data/validate_corpus.py  # every (benchmark,scale) ≥3 platforms; tuned is a facet within each cohort
uv run -- python _project/scripts/explorer_publish.py build --data-dir results-data --output results-explorer/dist/data  # expect 151→~173 bundles, tuning_mode facet appears
```
3. The tuned bundles will appear under `tuning_mode: tuned` in Explorer (`results-explorer/src/components/TuningBadge.tsx`, `ComparabilityReceipt.tsx`).

### D. Adversarial Review of Completed Changes (Required)

1. Load the `code` skill: `read_skill("code")` → run its **review** action against the diff since `d44c154bb` (the 151-bundle baseline). Scope: all changes in this worktree (FK-aware fix + staged bundles + inventory + plan).
2. Fix **every** Critical and Required finding; nits/considerations are optional per `code` skill rubric.
3. Re-run `make pr-preflight` once (the full gate per `AGENTS.md:Verification and close-out`), then proceed.

### E. Submit as PR (per AGENTS.md:WRITE-CLOSEOUT-001)

- Branch is already `chore/tuning-corpus-optimal` (from `d44c154bb`). Do **not** retarget to `develop` — the tuning corpus builds on the SF1 repopulation.
- Commit: `chore(data): optimal tuning corpus — FK-aware CTAS sort + 22 tuned cells (SF1/SF10 where helpful)`
- Close-out: `make pr-open` (withholds auto-merge), not `pr-ready`. Auto-merge is withheld until `make pr-ready` per the guide; the reviewer decides.
- Within an authorized write workflow, do not stop before `make pr-open` unless the prompt forbids publication or a gate fails (then keep the commit and report the blocker).

## 4. Rules and Boundaries

- Primary clone `/Users/joe/Developer/BenchBox` is read-only. You are in `../BenchBox.wt-tuning-corpus-optimal` — `make agent-write-preflight` already passed. Never `git worktree prune` in a container mounting `.git`.
- Python is `uv`-only (`uv run`, `uv add`, `uv sync`).
- `AGENTS.md` authority order and `[REVIEW-AUTH-001]` (reviews are read-only unless a later user message authorizes remediation) still apply, but this handoff **is** that later authorization to remediate, review, and publish.
- Do not add `tuned` for `datafusion`/`sqlite`/`clickhouse-local`/`dask-df` — they would be `basic_constraints` mislabeled as `tuned`. Do not run SF0.01/SF0.1 for tuned.
- Do not use `DROP ... CASCADE` as a blanket on platforms where it widens blast radius (per TODO anti-pattern) — prefer FK-constraint drop/re-add or ordering.
- Live cloud/Docker not needed; `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs` is the external root (announce command, max runtime, log path, stop condition per `AGENTS.md` UAT section).

## 5. Evidence Snapshot (copy-pasteable, verified while writing)

```bash
cd ../BenchBox.wt-tuning-corpus-optimal
git rev-parse HEAD  # d44c154bb
git status --porcelain  # clean
ls results-data/bundles | wc -l  # 296 (151 primary + manifests)
cat results-data/corpus-inventory.json | python3 -c "import json; j=json.load(open('results-data/corpus-inventory.json')); print(len(j['bundles']))"  # 151
uv run -- python results-data/validate_corpus.py  # All 24 cohorts OK
gh pr view 1945 --json headRefOid,url  # headRefOid d44c154bb, url https://github.com/BenchBox-dev/BenchBox/pull/1945
cat _project/planning/plan-optimal-tuning-corpus.md | head -n 30
uv run -- benchbox tuning show tuned --platform duckdb --benchmark tpch  # Source: .../duckdb/tpch_tuned.yaml, Mode: tuned
```

## 6. What the Next Agent Should Do (in order)

1. Reproduce w0 (single `duckdb tpch SF0.01 --tuning tuned` to `/tmp/drop-order-check`, expect `Cannot drop entry supplier`).
2. Implement w1 (FK-aware CTAS-sort), w2 (regression tests), w3 (audit postgres-family). Keep `get_fk_ordered_table_names` behavior unchanged.
3. Re-run w0 — it must pass — and `uv run -- python -m pytest tests/unit/core tests/unit/platforms -q`.
4. Execute the 22-cell tuned sweep (§3B) serialized, stage with gates (§3C), rebuild Explorer, verify `tuning_mode` facet.
5. Run `code` skill adversarial review on the diff since `d44c154bb`, fix all Critical/Required, re-run `make pr-preflight` once.
6. Commit and `make pr-open` on `chore/tuning-corpus-optimal` (do not stop before `pr-open`).
