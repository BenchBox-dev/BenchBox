# Decision: TPC-DS legacy stream ordering and RNG handling

Date: 2026-10-09
Status: Decided and in place.
Related: `_project/decisions/tpcds-legacy-stream-and-rng-2026-10-09.md`,
`benchbox/core/tpcds/streams.py`, `benchbox/core/tpcds/power_test.py`,
`benchbox/core/tpcds/throughput_test.py`, `benchbox/core/tpcds/benchmark/runner.py`,
`benchbox/core/dataframe/query_resolution.py`, `benchbox/core/tpcds/c_tools.py`.

## Context

TPC-DS stream generation historically relied on Python-level permutation logic and
process-global RNG seeding (`random.seed`) rather than calling official `dsqgen -STREAMS`.
Item `tpcds-throughput-permutation-compliance` resolved this for the primary throughput
path by adopting `dsqgen -STREAMS`. However, legacy permutations and RNG calls remain across
several callers. This decision record documents the current state, caller matrix, empirical
divergence from official TPC-DS specification ordering, options considered, and approved
dispositions.

## Caller Matrix

| Caller | File and Line (Live Head) | Stream ID & Seed Behavior | Query Ordering & Substitution Strategy |
|---|---|---|---|
| Power Test | `benchbox/core/tpcds/power_test.py:212,373` | Calls `create_standard_streams(..., num_streams=1)`. Uses `stream_id` (default 0), seed `seed + stream_id`. | Uses Python `TPCDSPermutationGenerator` (deterministic swap seeded with 19620718). Does NOT match official `dsqgen` Appendix D stream 0. |
| Throughput Fallback | `benchbox/core/tpcds/throughput_test.py:308` | Reached only when `enable_preflight=False`. Default path (`line 236`) uses official `dsqgen -STREAMS`. | Calls `create_standard_streams` fallback with legacy permutation and per-stream Python parameter generation. |
| Stream Files Exporter | `benchbox/core/tpcds/benchmark/runner.py:645,674` | `generate_streams(num_streams, rng_seed)`. 0-based stream index. | Emits legacy stream query files. Line 674 writes header `-- Compliant with TPC-DS specification` (non-compliant historical label). |
| DataFrame Query Resolution | `benchbox/core/dataframe/query_resolution.py:146,257` | Line 146 (`get_tpcds_legacy_queries`) uses seed `42 + stream_id`. Line 257 (`_resolve_tpcds_dataframe_queries`) calls `create_standard_streams` with `base_seed = 42 + stream_id`. | Legacy 99-query ordering mapped to DataFrame implementations; parameter overrides bound via `production_binding.py`. |
| Global RNG Calls | `benchbox/core/tpcds/streams.py:52,112`, `benchbox/core/tpcds/c_tools.py:463` | `random.seed(seed)` mutates Python process-wide global random state. | Affects any concurrent caller in the same process relying on Python's built-in `random` module. |

## Empirical Evidence

A direct comparison of legacy stream 0 against official `dsqgen` stream 0 was measured
using `uv run` on the bundled binaries and generator tools:

```bash
uv run -- python -c "
from benchbox.core.tpcds.streams import create_standard_streams, generate_dsqgen_streams
from benchbox.core.tpcds.queries import TPCDSQueryManager
import hashlib

qm = TPCDSQueryManager()
sm = create_standard_streams(query_manager=qm, num_streams=1, base_seed=42)
legacy_s0 = sm.generate_streams()[0]
legacy_ids = [sq.query_id for sq in legacy_s0]

dsqgen_s0 = generate_dsqgen_streams(num_streams=1, scale_factor=1.0, seed=42)[0]
dsqgen_ids = [sq.query_id for sq in dsqgen_s0]

print('Differing query positions:', sum(1 for l, d in zip(legacy_ids, dsqgen_ids) if l != d), 'out of', len(legacy_ids))
print('Legacy Query 0 SHA256:', hashlib.sha256(legacy_s0[0].sql.encode()).hexdigest())
print('DSQGen Query 0 SHA256:', hashlib.sha256(dsqgen_s0[0].sql.encode()).hexdigest())
"
```

Results:
- Total query entries: 103 queries (99 base queries plus multi-part variants 14, 23, 24, 39).
- Total unique query IDs: 99 across both generators.
- Differing positions: 103 out of 103 positions differ between legacy stream 0 and official `dsqgen` stream 0.
- Legacy Stream 0 first 10 query IDs: `[31, 29, 20, 25, 21, 23, 23, 19, 17, 27]`
- DSQGen Stream 0 first 10 query IDs: `[96, 7, 75, 44, 39, 39, 80, 32, 19, 25]`
- Legacy Query 0 (Q31) SQL text SHA-256: `22e6b7bc6068c3834cb063501366a10a321db3645fcee3be0075f520df493041`
- DSQGen Query 0 (Q96) SQL text SHA-256: `9e19c62679e98ea9d3edd661b7b7504cb23451725af167f52cb5e04d91da1e39`

The legacy stream order is completely distinct from the official TPC-DS specification Appendix D sequence.

## Options Considered

1. **Option A (Retain legacy and disclose honestly):** Retain existing default ordering and seeds. Document clearly that default Power runs and DataFrame queries execute the legacy permutation, not official Appendix D order.
2. **Option B (Correct in place):** Replace the legacy Python permutation algorithm with official Appendix D order directly in `create_standard_streams`.
3. **Option C (Adopt official `dsqgen -STREAMS` output everywhere):** Unify all paths under `generate_dsqgen_streams`.

## Decision

- **Approved: Option A for every default path.**
  No default ordering, seed, or substitution changes are made to existing default paths. Power@Size for TPC-DS retains its legacy permutation to preserve comparability with existing corpus results and historical baselines. Guides and documentation must state this explicitly and must not claim conformance with official Appendix D order for default Power runs.
- **Approved: Opt-in official path for specification run sequence only.**
  Under the opt-in flag `tpcds_spec_run_sequence` (implemented in Item 8), Power runs official `dsqgen` stream 0 and Throughput runs official `dsqgen -STREAMS`. This provides full specification conformance without breaking existing default baselines.
- **Rejected: Option C for default Power, DataFrame, and stream file export.**
  Option C would invalidate longitudinal Power@Size comparability across the published corpus, and DataFrame engines lack native `dsqgen` binary execution capabilities.

## What This Does Not Do

- Does not alter default query ordering, seeds, or parameters in `power_test.py`, `throughput_test.py`, or `query_resolution.py`.
- Does not modify Query 46 behavior or parameter templates (`_q46` in `parameter_adapters.py` and `q46_expression_impl`/`q46_pandas_impl` in `queries.py` remain unchanged).
- Does not reopen completed tracker items `tpcds-throughput-permutation-compliance` or `dataframe-parameter-substitution-parity`. Live code supports the throughput compliance claim via `_pregenerate_stream_queries` and DataFrame parameter binding via `production_binding.bind_power_stream_queries`.

## Recommended Follow-ups (Recorded, not created as tasks)

1. Remove the misleading `-- Compliant with TPC-DS specification` comment header from `benchbox/core/tpcds/benchmark/runner.py:674`.
2. Replace process-wide `random.seed` calls in `streams.py` and `c_tools.py` with an isolated instance (`random.Random(seed)`).
3. Evaluate a future major-version migration of default Power@Size to official `dsqgen` stream 0.
