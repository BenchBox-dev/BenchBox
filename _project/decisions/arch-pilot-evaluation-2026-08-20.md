# Decision: architecture-pilot scores after #1736 and #1737

Date: 2026-08-20
Status: Accepted. This record scores the two landed architecture-simplification
pilots. It does not fold Databricks, migrate more benchmark families, delete
import-linter allowlist entries, or introduce `benchbox.runtime`.
Observed tip: `origin/develop` `895157a56` (#1787).

Related: `_project/decisions/architecture-support-tier-commitment.md`;
`docs/development/adr/adr-runtime-composition-boundary.md` (#1728);
SQL execute fold #1736; SSB family-plugin seam #1737; follow-up fixes #1769.

## Scores

| Pilot | Score | Meaning |
|---|---|---|
| SQL execute/validate (`#1736`) | **Go-narrow** | One more cheap twin is allowed: fold Databricks onto the core mixin, *or* finish the mixin so Redshift no longer needs an `execute_query` override. Not both in one PR. Not a third SQL adapter. |
| SSB family plugin (`#1737`) | **Stop** | Do not copy `phases()` / `result_metadata()` onto AMPLab, ClickBench, or any other family until a runtime consumer exists. Do not extract packages. |

These scores replace the open question left by session `01a00021`. They do not
reopen the eight `arch-simplification` TODOs, which are already `done`.

## SQL — why go-narrow, not go or stop

`#1736` folded Redshift onto `CursorValidationQueryExecutionMixin`. That matches
the ADR's home layer (core kernel). It did not make the mixin the sole execute
path:

- Redshift still overrides `execute_query` to attach plan-capture fields after
  `super().execute_query(...)` (`benchbox/platforms/redshift.py`).
- Databricks still owns a full `execute_query` body
  (`benchbox/platforms/databricks/adapter.py`).
- The platform helper `execute_sql_query` in
  `benchbox/platforms/base/sql_execution.py` remains.

The ADR forbids folding production cloud adapters without naming those deltas.
Redshift named them. Databricks has not. A Databricks fold is the remaining
cheap twin; a mixin-completion PR that absorbs the Redshift post-hooks is the
alternative. Doing both in one change mixes two failure modes.

This score is not a license to delete `get_platform_adapter` from
`benchbox/core/runner/runner.py`. That import is the composition allowlist
item, independent of the SQL primitive.

## SSB — why stop

`#1737` registered `FAMILY_PLUGIN_IMPORTS["ssb"]` and `SSBFamily` with
`phases()` and `result_metadata()`. The only in-tree call of `family.phases()`
is the plugin unit test. Runner metadata still comes from
`collect_normalized_result_metadata` / `apply_normalized_result_metadata` on
the result object, not from the family plugin.

Copying the interface onto another family would look like progress and would
not reduce extension cost. A later timed measurement of AMPLab or ClickBench is
allowed only as an evidence appendix, not as a migration.

## What is next (and what is not)

Authorized after this record, one at a time:

1. **SQL go-narrow:** Databricks fold *or* mixin completion, as above.
2. **Not next:** runner `AdapterFactory` injection / allowlist deletion. That
   remains the composition program's higher-leverage shrink, but it is not the
   successor of these two pilots. It needs its own TODO and must not be opened
   as "the thing after the scores."
3. **Not next:** a third `BaseBenchmark`, a public `benchmark_loader` package,
   or `benchbox.runtime`.

A later decision may change a score only with new evidence: mixin deltas
closed, a runtime consumer of `phases()` / `result_metadata()`, or a measured
family-migration cost table.

## What this item does not do

- No production adapter fold.
- No import-linter ignore deletion.
- No new architecture TODOs in this record.
- No claim that `#1736` / `#1737` unfinished work is a defect in those PRs.
  They landed as pilots. The gap is the missing score, which this file is.
