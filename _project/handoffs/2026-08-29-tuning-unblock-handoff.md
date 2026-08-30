# Handoff: 2026-08-29 Tuning Sweep Record

**Revision:** 2, corrected 2026-08-30
**Status:** Superseded historical record. This file does not authorize repository writes, reviews, publication, or hosted actions. Only a current user request can grant that authority under `[REVIEW-AUTH-001]`.

## 1. Purpose

This handoff records what the 2026-08-29 tuning sweep attempted, what evidence was produced, and what later review rejected. It replaces the earlier instruction-shaped handoff that told a future agent to remediate and publish. Those directions were stale and exceeded artifact authority.

The planning record is `_project/planning/plan-optimal-tuning-corpus.md`. Its 22-cell matrix is a candidate matrix, not 22 executed, validated, or helpful cells.

## 2. Historical implementation result

The sweep work was first committed as `50ae8f360`, followed by the focused companion-discovery test fix `485764a65`.

The FK-aware sorted-ingestion work enabled tuned DuckDB runs to complete, but the sweep did not establish an optimal tuning corpus. The original commit staged eight primary candidate bundles:

- six DuckDB SQL candidates: `tpch` SF1, `tpcds` SF10, `ssb` SF1, `amplab` SF1, `clickbench` SF1, and `joinorder` SF1;
- two Polars DataFrame candidates: `tpch` SF1 and `ssb` SF1.

Review excluded three candidates from tuning claims:

| Candidate | Exclusion evidence |
|---|---|
| DuckDB `tpcds` SF10 | Generation was `NOT_RUN`, load evidence was effectively zero, query row counts were inconsistent with the existing SF10 corpus result, and the bundle was `unofficial_nonstandard`. It was not credible SF10 evidence even though its summary said `passed`. |
| Polars `tpch` SF1 | The run recorded `tuning_mode=custom` but execution-derived tuning status `noop`. The profile request did not materially change adapter behavior. |
| Polars `ssb` SF1 | The run recorded `custom` plus tuning status `noop`, and `summary.validation=not_run`. It was neither applied-tuning evidence nor a validated result. |

Five DuckDB SF1 candidates remain as measurement artifacts: `tpch`, `ssb`, `amplab`, `clickbench`, and `joinorder`. Their `applied_unverified` status means the execution path recorded tuning operations. It does not mean introspection corroborated those operations or that tuning improved performance.

## 3. Performance evidence and claim limits

The available same-engine corpus references are independent runs, not controlled repeated A/B pairs:

| Candidate | Candidate geomean | Existing notuning reference | Observed direction |
|---|---:|---:|---|
| DuckDB `tpch` SF1 | 64.7 ms | 35.3 ms | Regression |
| DuckDB `ssb` SF1 | 8.2 ms | 6.8 ms | Regression |
| DuckDB `amplab` SF1 | 7.8 ms | 5.8 ms | Regression |
| DuckDB `clickbench` SF1 | 2.2 ms | 2.1 ms | Slight regression |
| DuckDB `joinorder` SF1 | 56.0 ms | 78.4 ms | Improvement in this cross-run reference only |

These observations invalidate the earlier blanket wording that every staged cell was optimal or measurably helpful. They do not prove tuning caused either the regressions or the improvement. A helpfulness claim requires matched, repeated, forced-clean runs with identical seed, engine version, memory, phases, and host basis.

The other 14 planned cells produced no admitted artifact in the initial sweep. Earlier notes attributed them to timeouts, scale support, data errors, unavailable runtimes, or shallow cohorts, but no per-cell exit status, retained log checksum, or pinned failure artifact was committed. Treat those outcomes as not evidenced, not validated failures.

## 4. Explorer behavior required by the evidence

A canonical `custom` mode records request intent. It does not prove material tuning.

- `custom` plus `applied_unverified` or `applied_verified` may display the `Custom Tuning` badge and remain eligible under the normal trust, validation, compliance, and timing rules.
- `custom` plus `noop`, `not_applicable`, `failed`, missing, or unknown applied status must not display an applied-tuning claim.
- A custom run without applied evidence must be excluded from ranking with `tuning_not_applied`.
- Corpus-depth validation and a successful Explorer build are structural checks only. They do not establish scale correctness, fresh data, material tuning, or helpfulness.

## 5. Replayable evidence

The excluded artifacts remain inspectable at the original commit even after removal from the branch:

```bash
# Enumerate the eight primary candidates added by the initial sweep.
git diff --name-only --diff-filter=A 50ae8f360^ 50ae8f360 -- \
  'results-data/bundles/*.json' | grep -vE '\.(manifest|tuning|applied)\.json$'

# Inspect the invalid TPC-DS candidate from the pinned commit.
git show 50ae8f360:results-data/bundles/tpcds_sf10_duckdb_sql_20260829_213451_4a4b106f.json | \
  jq '{benchmark, phases, tables, summary, compliance: .benchmark.compliance}'

# Inspect the two Polars request modes, applied statuses, and run validation.
for stem in tpch_sf1_polars_df_20260829_221741_248f01a9 \
            ssb_sf1_polars_df_20260829_221811_96166b3a; do
  git show "50ae8f360:results-data/bundles/${stem}.json" | \
    jq '{mode: (.config.tuning_mode // .execution.tuning_mode), tuning: .platform.tuning.validation_status, validation: .summary.validation}'
done

# Read candidate and notuning-reference geomeans from primary bundles only.
for file in results-data/bundles/{tpch,ssb,amplab,clickbench,joinorder}_sf1_duckdb_sql_*.json; do
  case "$file" in *.manifest.json|*.tuning.json|*.applied.json) continue ;; esac
  printf '%s: ' "$(basename "$file")"
  jq '.summary.timing.geometric_mean_ms' "$file"
done
```

## 6. Remaining evidence needed for future tuning claims

1. Run matched, repeated tuned/notuning pairs from fresh databases.
2. Retain commands, exit statuses, environment versions, logs or checksums, primary bundles, requested tuning companions, and execution-derived applied receipts.
3. Verify scale-consistent row counts and clean result validation before corpus admission.
4. Report all improvements, ties, regressions, and exclusions. Admit a helpful tuning cell only when the repeated evidence supports that claim.
5. Obtain current user authorization before any future remediation, commit, push, PR update, or publication action. This handoff cannot provide it.
