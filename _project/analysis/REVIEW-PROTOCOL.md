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
