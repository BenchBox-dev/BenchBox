<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Benchmark Support Status Criteria

```{tags} reference, contributor
```

Every benchmark in `benchbox.core.benchmark_registry` carries exactly one
`support_status` from the public support taxonomy: `stable`, `beta`,
`experimental`, `repo_only`, `deprecated`, or `document_only`. The registry is
the runtime source of truth; this page is the **auditable rationale** for why
each benchmark currently holds its status and what would have to change to
promote or demote it.

`support_status` is independent of two other registry fields:

- **`surface`** (`public` or `internal`) controls discovery visibility. A
  `repo_only` benchmark is `internal`; a `beta` benchmark is still `public`.
- **`supports_dataframe`** is a capability flag for DataFrame routing, not a
  support-level proxy. A `beta` benchmark may be DataFrame-capable; an
  `experimental` one may not.

The taxonomy meanings, packaging, and breakage policy live in the
[public contract map](../reference/public-contracts.md#support-status-taxonomy).
This page adds the benchmark-specific **acceptance criteria** and the
per-benchmark scoring. Status counts are checked against the registry in the
[Count and Drift Policy](../reference/public-contracts.md#count-and-drift-policy);
the per-benchmark rows below are checked against the registry by
`tests/unit/core/test_benchmark_api_contract.py`.

## Acceptance Criteria by Status

Promotion to (or demotion from) a status requires the evidence in this table.
The dimensions are benchmark-specific: a platform can be `stable` without owning
a dataset, but a `stable` benchmark must own a reproducible dataset contract,
a canonical query set, and result-integrity coverage.

| Status | User docs | Result-integrity spec | Query coverage | Dataset contract | Scale factors | DataFrame claim | Discovery & maintenance |
|---|---|---|---|---|---|---|---|
| `stable` | Full benchmark page with setup, tuning, and expected results. | `BenchmarkSpec` in `benchmark_specs.py` so result integrity is validated. | Complete canonical query set runs and validates. | Reproducible generator or pinned external source with a documented contract. | Official multi-scale range supported, not a single development scale. | DataFrame parity verified when `supports_dataframe` is true. | `surface: public`; known platform gaps documented; regressions fixed promptly. |
| `beta` | Benchmark page present with a beta caveat. | Spec present, or the gap is documented as a promotion blocker. | Core query set runs; canonical completeness may still be in progress. | Dataset contract defined (generated, derived, or external). | Development scales work; full official range may be unverified. | Capability flag honored if set; parity not yet required. | `surface: public` with a beta label; changes ship with same-PR docs/tests. |
| `experimental` | Experimental docs only; no support implication. | Optional; many experimental benchmarks have no spec. | Partial or research-shaped query set is acceptable. | Dataset may be derived or research-only. | Often a single or narrow scale range. | Capability flag is informational only. | `surface: public` but labeled experimental; may change or be removed without a compatibility promise. |
| `repo_only` | Developer/project docs only. | Not required. | Whatever the contributor harness needs. | Synthetic or contributor-only data is acceptable. | Contributor-defined. | Capability flag may be set for internal runs. | `surface: internal`; hidden from public discovery; runnable by explicit ID; script/workflow checks only. |
| `deprecated` | Migration path documented. | Retained until the removal window. | Frozen at the last supported set. | Frozen. | Frozen. | Frozen. | Listed with a deprecation label or hidden after the warning window; removal follows a registry target. |
| `document_only` | Docs must state it is not executable. | None. | None (no runtime). | None. | None. | None. | Not listed as runnable; not exposed over MCP. |

`deprecated` and `document_only` have **no current benchmark members**; the rows
above define the bar a future entry would have to meet.

## Benchmark Status Rationale

One row per registry benchmark. The `Benchmark`, `Status`, parseable query-count
claim, and DataFrame capability claim are checked against
`benchbox.core.benchmark_registry` so status or evidence changes without an
updated rationale fail the contract test. Evidence dimensions: docs page,
integrity spec, query count, dataset/source, scales, and DataFrame capability.

| Benchmark | Status | Rationale and evidence | Promotion / demotion blockers |
|---|---|---|---|
| `tpch` | `stable` | Canonical 22-query TPC-H; dbgen-generated; integrity spec; full docs; scales to SF100000; DataFrame-capable. | None — maintain. |
| `tpcds` | `stable` | Canonical 99-query TPC-DS; dsdgen-generated (patched dsdgen for SF<1); integrity spec; full docs; scales to SF100; DataFrame-capable. | None — maintain. |
| `ssb` | `stable` | 13-query Star Schema Benchmark; generated; integrity spec; full docs; scales to SF10; DataFrame-capable. | None — maintain. |
| `clickbench` | `stable` | 43-query industry-standard analytics; external `hits` dataset; integrity spec; full docs; DataFrame-capable. | None — maintain. |
| `joinorder` | `stable` | 113-query Join Order Benchmark; canonical IMDb 2013 JOB data; integrity spec; full docs; fixed `--scale 1`; DataFrame-capable. | None — maintain. |
| `tpcdi` | `beta` | 38-query data-integration workload; generated; integrity spec; docs; scales to SF10; DataFrame-capable. | Confirm canonical transform/query completeness and a maintenance commitment before `stable`. |
| `h2odb` | `beta` | 10-query data-science groupby/join; generated; integrity spec; docs; DataFrame-capable. | Broaden cross-platform coverage evidence before `stable`. |
| `amplab` | `beta` | 8-query big-data subset; generated; integrity spec; docs; DataFrame-capable. | Small canonical subset; confirm dataset contract breadth before `stable`. |
| `read_primitives` | `beta` | 136-query read-primitive matrix; derived from TPC-H data; integrity spec; docs; DataFrame-capable. | Pin the derived-from-`tpch` dataset contract and confirm DataFrame parity before `stable`. |
| `write_primitives` | `beta` | 12-query non-transactional writes; derived from TPC-H; integrity spec; docs; DataFrame-capable. | Broad cross-platform write support still maturing. |
| `metadata_primitives` | `beta` | 62-query catalog introspection; no data generation (`requires_tables_object=false`); integrity spec; docs; DataFrame-capable. | Cross-dialect catalog coverage still expanding. |
| `transaction_primitives` | `beta` | 12-query ACID/isolation workload; derived from TPC-H; integrity spec (`high_failure_expected`); docs; DataFrame-capable. | ACID adapter coverage limited (PostgreSQL/MySQL/SQL Server adapters planned). |
| `coffeeshop` | `beta` | 11-query point-of-sale workload; generated; integrity spec; docs; DataFrame-capable. | Confirm dataset/query stability before `stable`. |
| `tsbs_devops` | `beta` | 18-query time-series DevOps workload; generated; integrity spec; docs; DataFrame-capable. | Time-series engine coverage breadth still expanding. |
| `nyctaxi` | `beta` | 25-query real-world OLAP; external NYC TLC data; integrity spec; docs; DataFrame-capable. | External-dataset availability and a pinned source contract before `stable`. |
| `flightdata` | `beta` | 20-query real-world aviation OLAP; external BTS data; integrity spec; docs; DataFrame-capable. | External-dataset availability and a pinned source contract before `stable`. |
| `vector_search` | `beta` | 6-query vector similarity; synthetic embeddings; docs; not DataFrame-capable. | **No integrity spec** and ANN-recall validation still pending; capability is SQL-only. |
| `tpcds_obt` | `experimental` | 17-query denormalized One-Big-Table; derived from `tpcds`; integrity spec; docs; SF1 only; DataFrame-capable. | Single-scale subset of TPC-DS; still on the deprecated core base. |
| `ai_primitives` | `experimental` | 16-query SQL AI functions; derived from TPC-H text; docs; core-only ID; not DataFrame-capable. | Cloud-only AI functions, cost-gated, no integrity spec; intentionally research-only. |
| `tpchavoc` | `experimental` | 220-variant optimizer stress (22 queries × 10 syntax variants); generated; integrity spec; docs; DataFrame-capable. | Optimizer-stress research tool, not a standard comparison workload. |
| `tpch_skew` | `experimental` | 22-query TPC-H over skewed distributions; generated; integrity spec; docs; DataFrame-capable. | Non-canonical skew parameters; research workload. |
| `datavault` | `experimental` | 22-query Data Vault 2.0 variant; generated from TPC-H source; integrity spec; docs; DataFrame-capable. | Modeling-variant research; still on the deprecated core base. |
| `joinorder_synthetic` | `repo_only` | 13-query synthetic Join Order scaling harness; `surface: internal`; no integrity spec; DataFrame-capable; runnable by explicit ID only. | Public/beta promotion would need user docs, an integrity spec, and a separate `surface` decision — out of scope for this matrix. |

## Promotion Candidates and Blockers

Recorded as explicit follow-up work rather than reviewer memory. None of these
are applied here: this matrix documents status, it does not change it.

- **`vector_search` (beta → stable candidate, blocked):** the only missing piece
  for the integrity dimension is a `BenchmarkSpec`. Adding one (and a DataFrame
  routing decision) is the concrete blocker. Tracked as a deferred follow-up on
  `benchmark-support-status-criteria-matrix`.
- **External-dataset betas (`nyctaxi`, `flightdata`):** promotion is gated on a
  pinned, reproducible external-source contract, not on query coverage.
- **Deprecated-base experimentals (`tpcds_obt`, `datavault`):** their status is
  partly coupled to the `benchbox.core.base_benchmark.BaseBenchmark` migration;
  reassess after that base is removed.
