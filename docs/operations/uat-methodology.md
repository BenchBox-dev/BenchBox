# UAT methodology helpers

Operational notes for authors of sweep-shape UATs (those that produce a
multi-bundle corpus, e.g. the 2026-05-02 multi-platform sweep).

## Validator-clean rate roll-up

The UAT validate phase walks a results directory or explicit result-path
list, runs `benchbox.validation.bundle` on each bundle in-process, and
emits a TSV with one row per bundle plus per-platform / per-benchmark
validator-clean rates. Use `make uat-validate` instead of reconciling
execute success counts against a packaging log by hand.

### When to run it

Any UAT that captures more than one result JSON (a "corpus-shaped" UAT).
Single-bundle UATs already get the same signal from submission dry-run
validation. Run it after execute (to surface bundle quality alongside
the run-side pass count) and again before final reporting when you need
fresh per-platform / per-benchmark numbers.

### Invocation

```bash
# Roll up an entire sweep results directory:
make uat-validate RESULTS_DIR=~/Developer/benchmark_runs/results OUTPUT_TSV=uat-rollup.tsv

# Direct module form, useful inside scripts:
uv run -- python -m tests.uat._cli validate \
    --results-dir ~/Developer/benchmark_runs/results \
    --output-tsv uat-rollup.tsv
```

### TSV columns

| Column             | Meaning                                                                |
| ------------------ | ---------------------------------------------------------------------- |
| `platform`         | `platform.name` from the bundle (`-` if missing).                      |
| `benchmark`        | `benchmark.id`.                                                        |
| `scale`            | `benchmark.scale_factor` as a string.                                  |
| `result_path`      | The bundle path passed to the validator.                               |
| `validator_status` | `clean` / `warning_only` / `error` / `refused-by-cli` (see below).     |
| `error_count`      | Number of validator errors.                                            |
| `warning_count`    | Number of validator warnings.                                          |
| `first_error`      | First error string (truncated to a single line) or empty when `clean`. |

### Status values

- `clean` — `benchbox.validation.bundle` produced 0 errors and 0 warnings.
- `warning_only` — 0 errors, ≥1 warning. Submittable, but worth a glance.
- `error` — ≥1 error. Bundle would be rejected by published-results CI.
- `refused-by-cli` — `benchbox submit` refuses the bundle on its
  TPC-DS compliance guardrail
  (`benchmark.compliance_class` in `unofficial_subscale` /
  `unofficial_nonstandard`). The bundle validator is not run against
  these because they cannot be packaged for submission.

### Footer rates

Lines starting with `#` summarise per-platform and per-benchmark
clean rates. `refused-by-cli` is **excluded** from the denominator
because those bundles are out of scope for the validator. They remain
visible per-row.

A typical headline read of the footer:

```
# overall: total=376 submittable=364 clean=205 warning_only=0 error=159 refused-by-cli=12 validator_clean_rate=56.3%
# platform=DuckDB: total=42 submittable=42 clean=9 validator_clean_rate=21.4%
# benchmark=tpcds: total=84 submittable=72 clean=22 validator_clean_rate=30.6%
```

A platform or benchmark cluster below 50% is the trigger to file a
defect TODO, per the success-metrics convention in the UAT methodology
remediation spec
(`_project/specs/uat-methodology-blind-spot-remediation.md` §2 Finding 2).
