# Correctness-review reproducibility protocol

Adversarial correctness reviews in this repo (e.g. the bounded-correctness-gate
review #830 and the oracle-coverage-map review #834) are run against a moving
`develop`. Two separate reviews went stale because the SHA they reviewed advanced
underneath them before the findings were written up, so the analysis described code
that no longer matched `origin/develop`. This note makes that failure mode hard to
repeat.

## Required when writing up an adversarial correctness review

1. **Pin the reviewed SHA.** Record the exact commit you reviewed
   (`git rev-parse HEAD`) at the top of the analysis, not "develop".
2. **Re-check ancestry at write time.** Before publishing the finding, run:

   ```sh
   git fetch origin develop
   git merge-base --is-ancestor <reviewed-sha> origin/develop && echo "still current" || echo "STALE: develop advanced"
   ```

   If the reviewed SHA is no longer an ancestor of `origin/develop` (i.e. develop
   was rebased/force-moved) or material files changed, re-review against the new
   tip or against a tag, and update the pinned SHA.
3. **Prefer a tag for long-lived reviews.** For reviews that will be cited later,
   review against an immutable tag rather than a branch tip.

## Provenance stamping of generated analysis artifacts

Generated correctness artifacts under `_project/analysis/` carry generation
provenance (date + git SHA) so a reader can tell whether the artifact predates
current `develop`:

- `oracle-coverage-map.md` is stamped by
  `_project/scripts/generate_oracle_coverage_map.py` in a **leading HTML-comment
  region that the drift check ignores** (see `_strip_provenance` /
  `check_artifacts`). The volatile SHA/date therefore lives *outside* the
  drift-compared body, so `make oracle-coverage-map-check` does not churn on every
  commit while readers still get a real "last generated" stamp.
- Hand-written divergence analyses (e.g. `cross-surface-oracle-independence.md`)
  should carry a short `Reviewed-at:` provenance line with the pinned SHA when they
  record a point-in-time correctness claim.

The rule for any generated artifact that has a drift/`--check` guard: **never put a
volatile value (git SHA, timestamp) inside the compared body** — put it in a region
the comparison strips or normalizes, or the guard will fail on every commit.

### Squash-merge orphans a PR-branch SHA — do not stamp it as provenance

A provenance SHA is only useful if a reader can resolve it later. **Squash-merge
discards every PR-branch commit**: when a PR lands as a single squashed commit on
`develop`, the PR-branch HEAD that was current at generation time becomes
unreachable from any ref (`git cat-file` reports "bad object"). A generated artifact
that stamped `revision: <PR-branch HEAD>` therefore points at a commit that no longer
exists. (Reproduced on `oracle-coverage-map.md`, whose `revision: ddd96c47…` stamp
was orphaned by the squash that landed #867 as `e4a04484`; the same squash-orphaning
is why review briefs sometimes cite pre-squash merge SHAs that are absent on develop.)

Rule for provenance stamps on generated analysis artifacts: **use a value that
survives a squash** — a develop-reachable SHA (e.g. the merge-base with
`origin/develop`), a **content hash** of the generated body, or a plain
"regenerate to verify" note — never the volatile PR-branch HEAD. The stamp still must
live in the drift-ignored region (above), so it never churns `--check`.
`oracle-coverage-map.md` now stamps a content hash of its own body plus a
regenerate-to-verify instruction instead of a branch SHA.

## Self-snapshot vs independent oracle — do not over-read a green value gate

A "value-level" or "value+cardinality" correctness gate is only as strong as its
reference. When the reference was produced by running the system under test and frozen
(e.g. the TPC-H value digests in
`benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json`, a
frozen benchbox-on-DuckDB snapshot), the gate is a **regression snapshot vs a pinned
baseline**, not an independent correctness oracle: it catches *change* from the frozen
answer, but a conceptual value bug present at *freeze time* is enshrined, not caught.

When reviewing or describing such a gate, state plainly whether its reference is
**independent** of the system under test or **self-referential** (a frozen self-snapshot
or a cross-surface comparison that shares a spec). The oracle coverage map carries this
as an explicit `Independence` column (`independent` / `semi-independent` /
`self-referential`) so a reader cannot mistake a green self-referential cell for proof
of value correctness. Do not let a green "value-level" cell imply "values proven correct
against an authority" when the authority is the system itself.
