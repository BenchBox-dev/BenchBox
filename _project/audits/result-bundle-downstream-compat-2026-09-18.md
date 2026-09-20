---
date: 2026-09-18
develop_sha: ed49070107c79cea3a9a8f52ffce9458beb3f64c
measured_at_sha: ed49070107c79cea3a9a8f52ffce9458beb3f64c
checked_sha: ed49070107c79cea3a9a8f52ffce9458beb3f64c
---

# Result-bundle downstream-compat audit with adversarial reconciliation

Scope: `change` — four `develop` commits at `ed4907010` plus downstream
consumers (seed corpus `results-data/`, `benchbox/validation/bundle.py`,
`benchbox/core/publishing/` and result-schema surfaces, explorer publication
`_project/scripts/explorer_pipeline/` and `results-explorer/`).

Four commits: `358799f11` (#2030 client-platform link locality + statement
overhead), `024bfce05` (#2178 per-table load timings), `56f928bc9` (#2177
databricks no-clustering default for untuned), `be195b573` (#2122
`plan_max_depth` threading into the plans companion builder).

## 1. Reviewer panel and responder status

Panel dispatched per the isolation protocol from pinned detached worktrees at
`ed4907010` with a private brief (removed after the run):

- `[agy]` (Soft Read-Only Tier-1, `gemini-3.7-flash-high`, plan mode) —
  **failed/absent**: headless run auto-denied a `command` tool permission and
  produced zero output (`/tmp/rbc-agy-review.log`). No findings to tabulate.
  This named reviewer is absent; per panel quorum rules that absence is a gate
  blocker, not a silent substitution. There is no second opinion, so every
  `[muse]` verdict below is a solo finding, not consensus.
- `[muse]` (Hard Read-Only Tier-2, `muse-spark-1.2`, high effort) —
  **responded**: verdict **Ship with caveats** (`/tmp/rbc-muse-review.log`).
  Ten findings (P1–P8 reassessed plus two new) with `file:line` evidence.

Both worktrees verified clean (`git status --porcelain` empty) before removal;
no findings were dropped for dirtiness.

## 2. Draft claims under test

P1 submission-validation blind spot (`bundle.py` `REQUIRED_TOP_KEYS` 64–95);
P2 two `validate_corpus.py` files (`results-data/` real vs `scripts/`
orphaned reading `manifest.json` `result_id`/`submitted_at`); P3 Databricks
retroactive mislabeling (pre-`56f928bc9` z_order vs none); P4 `load_ms`
produced-not-consumed; P5 triplicated field knowledge (`transformer.py`,
`localResult.ts` `SUPPORTED_SCHEMA_VERSIONS`, e2e fixture parser); P6
hand-duplicated read-model version (`db.ts:89`
`EXPECTED_READ_MODEL_VERSION=10` vs `contract.py`
`EXPLORER_READ_MODEL_VERSION`); P7 docs/CHANGELOG gaps (no entries
#2178/#2177/#2122/#2030, no Tables Block in `result-formats.md`, clustering
undocumented); P8 uneven seed-corpus `load_ms` (47 carriers, no
not-measured-vs-zero marker). Reassurance: additive/default-only, readers use
`.get()`, no live corpus/explorer footprint for the Sept-18 changes,
client_link followed the full contract process.

## 3. Reconciliation table

One row per finding; `[agy]` has no rows (absent). All evidence re-verified
against the pinned tree (primary clone at `ed4907010`), not the brief
snapshot. Dispositions follow `review-response.md` (ACCEPT, NARROW,
ALREADY_FIXED, DEFER, REBUT).

| reviewer | severity | location | disposition | evidence | remediation |
|---|---|---|---|---|---|
| [muse] | Major | `benchbox/validation/bundle.py:64`, `benchbox/core/results/schema.py:111-124` | NARROW (P1: shape checks, not required-key expansion) | `REQUIRED_TOP_KEYS = ("version","run","benchmark","platform","summary","queries")` is minimal by design; `OPTIONAL_KEYS` already admits `environment/tables/...`; no `_validate_environment/_validate_tables/_validate_client_link` or `load_ms` shape check exists. Missing optional fields correctly pass; malformed ones also pass. | Add narrow shape validators for new optional extensions (`environment.client_link`, `tables.*.load_ms`/`rows`, `platform.config` clustering) that fail on wrong type but allow absence; keep `REQUIRED_TOP_KEYS` unchanged. Correction 2026-09-18: the clustering field lives at `platform.config.databricks_clustering_strategy` (flattened out of `platform_info["configuration"]`), not `platform.tuning`, per external review of the implementation. Target the post-rename key via `result_schema_version_value()` (see 2199-P1). Excluded scope re-homed: expanding `REQUIRED_TOP_KEYS` is killed — it would break the additive/optional contract, since presence of optional blocks is not a compat signal. |
| [muse] | Minor | `scripts/validate_corpus.py:28`, `results-data/validate_corpus.py:1-40` | ACCEPT (P2: delete orphan) | `scripts/validate_corpus.py:28` requires `manifest.json` fields (`result_id`,`submitted_at`,`query_count`) for a `manifest.json` the pipeline no longer emits; the file's only self-reference is its own usage line, while CI/workflows/tests invoke only `results-data/validate_corpus.py` (`.github/workflows/corpus-drift-check.yml:82`, `sync-results-data-to-published.yml:57`, `tests/unit/scripts/test_corpus_cohort_depth.py:35`). Dead code, not an active mis-gate. | Delete `scripts/validate_corpus.py` (or mark deprecated legacy) and remove any doc references; prove with `make compat-docs-check` or docs/link check plus the corpus-depth unit test. |
| [muse] | Minor | `benchbox/platforms/databricks/adapter.py:354,367`, `benchbox/core/tuning/interface.py:1028` | DEFER (P3: provenance-cutoff design) | Default `"none"` (`interface.py:1028`, fallback `adapter.py:367`) conflates pre-fix absence with explicit post-fix `"none"`; no `tuning_policy_generation`/cutoff is stored, so readers cannot distinguish them. Blast radius is the Databricks untuned cohort, not all platforms. | Follow-on TODO: provenance/cutoff marker scheme for pre-fix Databricks bundles (candidate carrier: `export.benchbox_version`; do not design here). Docs cutoff note rides with the P7 docs remediation. |
| [muse] | Minor | `benchbox/core/results/schema.py:1555-1572`, `benchbox/core/results/loader.py:276-279` | DEFER (P4: consume-vs-defer decision) | `024bfce05` produces per-table `load_ms` (`schema.py:1570-1572`) and `loader.py:278` extracts it, but `transformer.py` never reads `tables`, no explorer projection exists, and read-model v10 adds no `load_ms` view. Canonical seed corpus: 47/244 bundles carry `load_ms` (forward-only rollout). |
| [muse] | Minor→Nit | `results-explorer/src/lib/localResult.ts:5`, `_project/scripts/explorer_pipeline/transformer.py:36,307`, `benchbox/core/results/schema_policy.py:183` | DEFER (P5: shared contract) | `SUPPORTED_SCHEMA_VERSIONS = {"2.0","2.1","2.2"}` hand-duplicates `EXPLORER_INPUT_SCHEMA_POLICY`; e2e fixtures hard-code `"2.2"`. Drift risk is currently caught by `test_check_explorer_compat.py`, so severity is Nit. | Follow-on TODO: shared Python/TS bundle-field contract test (generate the TS constant from `schema_policy.py` or a single `schema-versions.json`; keep the compat test). |
| [muse] | Nit | `results-explorer/src/db.ts:89`, `_project/scripts/explorer_pipeline/contract.py:44`, `results-explorer/src/lib/__tests__/db-remediation-pin.test.ts` | REBUT (P6: parity check exists) | Draft claimed "no check"; the pin test spawns `explorer_publish.py build-contract` and asserts `contract.read_model_version == CURRENT_READ_MODEL_VERSION == _EXPECTED_FOR_TEST`. Both constants are 10 today. The check is test-time, not build-time, but it exists — the draft premise is factually wrong. | None. Optional hardening (generate `db.ts` constant at `npm run gen`) is not required; keep the pin test running in `pr-preflight`. |
| [muse] | Minor | `CHANGELOG.md:8-22`, `docs/reference/result-formats.md:242-261` | ACCEPT (P7: docs + changelog) | `grep` for `2178|2177|2122|2030` in `CHANGELOG.md` is empty (`[Unreleased]` lacks all four); `result-formats.md` documents `environment.client_link` (lines 242–261) but `grep databricks_clustering_strategy` is empty and no Tables Block section exists (`tables` block is impl-defined in `schema.py:1555` only). | Backfill `CHANGELOG.md` under `[Unreleased]`; add Tables Block subsection (`tables.{table}.rows/load_ms`, absence-means-not-measured) and `platform.config` / `databricks_clustering_strategy` values; mirror clustering in `docs/platforms/databricks.md`. Prove with docs/link check. |
| [muse] | Nit | `benchbox/core/results/schema.py:1570`, `benchbox/core/results/loader.py:278-279`, `results-data/bundles/*.json` | NARROW (P8: one docs sentence) | Unevenness verified (47/244 carriers), but absence already is the sentinel: `loader.py:278` uses `stats.get("load_ms")` (tolerant) and `round(load_ms,1)` keeps explicit `0.0` distinguishable from missing. No zero-vs-missing confusion in the producer. | Document absence-means-not-measured in the new Tables Block; the canonical inventory count is maintained with the corpus audit. Excluded scope re-homed: a code marker is killed — the reader already distinguishes both states. |
| [muse] | — | reassurance paragraph | NARROW (caveat on footprint) | Additive/`.get()`-tolerant holds (`transformer.py` `.get()`, `localResult.ts` `stringOrNull`, `loader.py` tolerant); v10 bump with `warn-and-continue` policy substantiates the contract process. But "no live footprint" overstates: the v10 snapshot must be rebuilt to surface the new `client_*` columns — until then the explorer shows NULLs without crashing (forward-compatible by design). | Fold the rebuild note into the P7 docs remediation (`contract.py:44` v10). |
| [muse] | Minor | `benchbox/core/results/schema.py:1044`, `benchbox/platforms/base/result_capture.py:1026-1036` | DEFER (new: companion truncation contract) | `plan_max_depth` threads only through `build_plans_payload()`/`QueryPlanDAG.to_dict(max_depth)` into `.plans.json`, never top-level (so `REQUIRED_TOP_KEYS` correctly ignores it), but truncation is silent — no `max_depth`/`truncated` marker and no `result-formats.md` companion documentation (`grep plan_max_depth docs/` empty). | Follow-on TODO with the P4 decision: document `plan_max_depth` companion semantics and surface a truncation marker, or explicitly defer. |
| [muse] | Minor | `benchbox/platforms/base/adapter.py:622-657`, `benchbox/core/runner/runner.py:503-504`, `benchbox/core/results/schema.py:912` | DEFER (new: same class as P4) | `phases.statistics.per_table_ms` is produced when `stats_per_table_timing` is set and consumed nowhere except raw-bundle inspection; `transformer.py` never reads `phases.statistics`. | Decide together with P4 in the read-model v11 follow-on. |
| [muse] | — | PR #2199 interaction P1 (`7aeed9498:benchbox/validation/bundle.py:77-78,777-782`) | DEFER (verify post-merge) | Rename commit (unmerged branch `fix/result-schema-version-rename @ 7aeed9498`) renames `REQUIRED_TOP_KEYS` to `result_schema_version` with fallback/discard logic via `result_schema_version_value()` (`result_schema_version → version → schema_version`). Draft P1 remediation targeting `"version"` would be stale post-merge. | P1 remediation must reference the post-rename helper/key; confirm the fallback/discard logic post-merge of #2199. |
| [muse] | — | PR #2199 interaction P5 (`7aeed9498:benchbox/validation/bundle.py:24-33`, `7aeed9498:results-explorer/src/lib/localResult.ts:5,74`) | DEFER (verify post-merge) | Helper centralized in `schema_policy.py:137`, but `bundle.py:24-33` keeps an `ImportError` inline duplicate for the slim `published-results` branch, and `localResult.ts:74` reads `result_schema_version ?? version` while line 5 still hard-codes versions — partial parity, fourth name added. | Follow-on TODOs: dedup the `bundle.py` inline fallback against the helper; bring `localResult.ts` to parity with the Python helper. Blocked on the #2199 merge. |
| [muse] | — | PR #2199 interaction P7 (`7aeed9498` stat, `benchbox/core/results/schema_specs.yaml:1-2`, exporter `benchbox_version`) | DEFER (docs post-merge) | The rename commit touches 17 files with no docs/CHANGELOG entries; renamed key, new `export.benchbox_version`, and `schema_specs.yaml canonical_key_order` arrive undocumented. | Follow-on TODO: docs for the renamed key plus `export.benchbox_version` plus `canonical_key_order`; fallback-matrix contract test (`result_schema_version` vs legacy `version` vs `schema_version` vs missing). |

No reviewer disagreement to preserve beyond draft-vs-`[muse]`
narrowing/rebuttal above (P1 severity, P6 existence of check, P8 marker);
`[agy]` offered no second opinion either way.

## 4. Validator solution-fit note (P1)

Per the validators binding: the submission validator's guaranteed invariant
is required-top-level presence, not optional-block shape. Known false
negatives: malformed `environment.client_link`, `tables.*.load_ms`, or
`platform.config` clustering pass today. Maintenance trigger: any new
optional bundle block ships without a shape validator unless this audit's
P1 remediation is applied. The smaller sufficient solution is the NARROW
remedy (shape validators for the three new extensions); expanding
`REQUIRED_TOP_KEYS` is the larger change that the same requirement does not
need. No solution-fit flag beyond this: nothing here duplicates existing
enforcement or freezes incidental shape.

## 5. Blind spots and reframe (attributed to `[muse]`, verified)

L2 missing: `phases.statistics.per_table_ms` (tabulated above — promoted to
a DEFER row, not left as a blind spot); silent `plan_max_depth` companion
truncation (same); `environment.client_link.collection_error_message` is a
fixed-template diagnostic (`result-formats.md:259`) whose PII/redaction
assurance the draft did not assess — carried as a probe inside the P1 shape
validator for `client_link` (fixed template + no raw identifiers). L3
reframe, adopted: the contract is "optional extensions must be validated
for shape, not presence" — the P1 NARROW remedy implements exactly this.

## 6. Routing and next steps

- To `result-bundle-compat-integrate-fixes` (small, file-scoped):
  P2 ACCEPT (delete `scripts/validate_corpus.py`), P7 ACCEPT (CHANGELOG +
  Tables Block + clustering docs, pre-rename keys), P1 NARROW (shape
  validators referencing the post-rename helper), P8/reassurance doc notes
  (ride P7). Post-#2199 compatibility is mandatory for each fix.
- To `result-bundle-compat-followon-todos` (design decisions): P3
  provenance cutoff, P4/per_table_ms read-model v11 scoping, P5 shared
  contract test, plan_max_depth companion contract, all three 2199
  interaction rows (fallback-matrix test, rename docs, TS parity, inline
  dedup).
- Blockers: `[agy]` absent (named-reviewer gate blocker — no independent
  second opinion); PR #2199 unmerged (all 2199 rows blocked on
  `fix/result-schema-version-rename @ 7aeed9498`); P1/P7 remediations must
  be written against the post-rename shape.
- Responder report: `[muse]` responded (Ship with caveats);
  `[agy]` failed (headless `command`-permission auto-denial, zero output);
  nothing dropped for worktree dirtiness.

## 7. Implementation-review addendum (2026-09-18)

The fixes above (commit `395c9b5`) were adversarially reviewed by an
external panel: `[claude]` (`claude-sonnet-5`, high effort) responded with
**Do not ship**; `[agy]` failed absent (same headless permission denial).
All `[claude]` findings were verified against producer code and dispositioned:

- Major, clustering bundle path (`platform.tuning` vs `platform.config`):
  **ACCEPT** — the adapter writes the strategy inside
  `platform_info["configuration"]`
  (`benchbox/platforms/databricks/adapter.py:693-719`), which
  `_extract_platform_config` flattens into `platform.config`
  (`benchbox/core/results/schema.py:1731`), while `platform.tuning` comes
  from `_build_tuning_summary` and never holds the key. Validator, docs,
  CHANGELOG, and this audit corrected to `platform.config`.
- Major, `client_link` phantom field (`link_status` vs `collection_status`):
  **ACCEPT** — the producer dataclass is `ClientLinkEnvironment`
  (`benchbox/core/results/environment.py:193-207`); the reviewed code had
  taken the explorer read-model column name for the bundle field name.
  Validator now checks `collection_status` (required when the block is
  present), `source`, nullable region/cloud/error strings, and the
  `statement_overhead_ms` shape; tests mirror the real contract.
- Minor, unchecked `tables.{table}.rows`: **ACCEPT** — numeric check added.
- Nit, re-run test count: **ACCEPT** — re-run recorded with the fix commit.

Corpus-gate evidence (this fix commit):
`uv run -- python scripts/validate_submission.py results-data/bundles/` →
244 bundles, 51 errors, 2 warnings — byte-identical counts to the
pre-change baseline, and zero errors mention `client_link`, `tables.*`,
`platform.config`, or `databricks_clustering_strategy`. The new
validators are silent on the entire real corpus.

Recorded: `/Users/joe/Developer/BenchBox.wt-result-bundle-compat/_project/audits/result-bundle-downstream-compat-2026-09-18.md`
