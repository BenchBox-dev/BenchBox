# Value-digest cross-engine independence: decision (DEFER)

Source TODO: `correctness-gate-value-digest-fidelity-followups` w5
(open_question: gating=false, default=defer with blockers enumerated).

## Context

The bounded correctness-gate value oracle stores 18 reference digests produced by
running benchbox-on-DuckDB-1.3.2 and freezing them
(`benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json`). As
documented at the digest primitive (`benchbox/core/results/result_digest.py`) and in
the reference JSON provenance, this makes the oracle a **regression snapshot vs a
DuckDB-pinned baseline**, not an independent value oracle: a conceptual value bug
present at freeze time is enshrined, not caught.

The strongest available independence upgrade is a **cross-engine digest-agreement
check**: assert that a second SQL engine already in CI (PostgreSQL or DataFusion)
produces the SAME stream-0 digests as DuckDB at SF=1 / pinned seed for the 18 gate
queries. Two independent engines agreeing on full result values is real evidence of
value correctness, not a self-snapshot.

## Decision: DEFER

We DO NOT add a cross-engine digest-agreement check in this change. We record the
concrete blockers that must be resolved first, so the deferral is dispatchable rather
than vague.

### Blockers (must be neutralized before a cross-engine digest can agree)

1. **Value+TYPE coupling (the primary blocker).** `compute_result_digest` is a
   value+type-rendering digest: an `int` renders exactly (`"37734107"`) while a
   `float`/`Decimal` of the same value renders at fixed precision (`"37734107.0000"`),
   so they hash differently (pinned in
   `tests/unit/test_correctness_gate_value_oracle.py::test_digest_couples_value_with_numeric_type`).
   DuckDB and a second engine routinely return different Python types for the same
   logical column (e.g. an `AVG` as `float` on one engine, `Decimal` on another), so
   the digests would mismatch on type rendering alone. Type-canonicalization (TODO w2)
   is a prerequisite and is intentionally NOT done while the oracle is single-engine.

2. **Date / timestamp rendering.** Several gate queries project dates
   (e.g. `l_shipdate`, `o_orderdate`). `calculate_checksum` renders each cell with
   `str(...)`, so a `datetime.date` vs an ISO `str` vs an engine-native temporal type
   render to different tokens. Engines must be normalized to one temporal string form
   before any cross-engine digest can agree.

3. **Decimal scale / trailing-zero rendering.** Even at the same precision, engines
   differ in returned decimal scale (`37734107.00` vs `37734107.000`); the
   significant-figure normalization absorbs some of this but not the integer-vs-fixed
   split in (1).

4. **NULL-as-None vs NULL-as-NaN.** SQL `NULL` arrives as `None` from most engines but
   as `float('nan')` from some Arrow/pandas decoders (ClickHouse). `calculate_checksum`
   renders `None -> "NULL"` but `nan -> "nan"`, so a NULL-bearing column would mismatch
   across engines purely on NULL rendering. (The 18 gate result sets are NULL-free
   today, but a cross-engine check would have to be NULL-rendering-stable to be sound
   generally.)

5. **Engine-wide emission is computed-but-never-compared.** `compute_result_digest`
   is already called on the shared DBAPI path
   (`benchbox/platforms/base/sql_execution.py`) in addition to
   `benchbox/platforms/duckdb.py`, so a second engine already emits a digest. It is
   harmless today (`_stored_value_digest` only returns a reference for tpch SF=1, so a
   non-DuckDB digest is never compared), but combined with blockers (1)–(4) it is a
   latent trap: enabling comparison before normalization guarantees spurious RED.

### Why not ship it now

Shipping a cross-engine gate before (1)–(4) are normalized would produce a flaky gate
that goes RED on a correct tree (spurious type/date/NULL mismatches) — the opposite of
the oracle's purpose. Per the TODO anti-pattern: *do not enable cross-engine digest
comparison before the digest is type/engine-stable.*

### Re-open criteria

Revisit when: (a) the digest is made type-stable and temporal/NULL rendering is
canonicalized to one engine-agnostic form, and (b) a second engine's SF=1 / pinned-seed
run is available in CI as a non-blocking sample. At that point a bounded cross-engine
agreement check (DuckDB vs DataFusion, in-process, no service container) is the
lowest-friction first step — scoped as a non-blocking sample, not a full N-engine
matrix (the full matrix remains owned by the `tpchavoc-*-engine-equivalence-sampling`
efforts).
