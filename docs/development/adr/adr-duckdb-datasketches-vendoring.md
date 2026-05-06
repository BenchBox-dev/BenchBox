# ADR: DuckDB datasketches extension — vendoring vs HLL fallback

## Status

Accepted (2026-05-06). Path: **smoke + monitor**, do not vendor.

**Maintenance protocol**: Re-review if `extension-smoke.yml` catches
family drift more than once per quarter, or if the upstream
community-extensions repo formally drops a family BenchBox depends on.

## Date

2026-05-06

## Context

The DuckDB community `datasketches` extension is loaded on demand via
`INSTALL datasketches FROM community`. Blind-spot
`2026-05-02-155524` recorded that the extension build silently dropped
the `theta` and `frequent_items` families between PR #114 morning and an
audit later that day -- both families are referenced by four ops in
`benchbox/core/write_primitives/catalog/operations.yaml`. The artifact
the extension resolves to is opaque (commit hash only), and the build
pipeline upstream is owned by duckdb-community-extensions, not BenchBox.

`scripts/duckdb_datasketches_smoke.py` and the `extension-smoke.yml`
CI workflow now probe one representative function per family on every
relevant primitive/script/workflow/dependency PR plus a daily cron, so
future drift is caught at PR or within 24h rather than at benchmark time.

## Options Considered

### A. Vendor `_binaries/datasketches/`

Pin a known-good extension build per platform under `_binaries/`,
bypass `INSTALL ... FROM community`, and load from disk.

- Pro: full version control; immune to upstream rebuilds.
- Pro: reproducible benchmark runs across the BenchBox release window.
- Con: ~5 MB per platform per supported DuckDB version in the artifact
  tree (4-6 platforms × 2-3 DuckDB versions = 40-90 MB before
  compression).
- Con: BenchBox does not currently vendor any DuckDB extension; this
  introduces a new artifact-management surface (where do new builds
  come from? who refreshes them?).
- Con: pinning hides upstream regressions instead of routing them to
  upstream repair.

### B. Fall back to HLL-only sketch coverage

Drop the four `theta` / `frequent_items` ops from `operations.yaml`
and rely on HLL for distinct-counting where any community engine ships
HLL.

- Pro: matches the Redshift sketch ceiling already documented.
- Pro: zero artifact weight.
- Con: BenchBox has CPC + REQ + KLL + HLL working today (PR #182);
  rolling back to HLL-only is a real coverage regression for the
  cross-engine sketch story.
- Con: Theta sketches' intersection support has no equivalent in HLL;
  any benchmark exercising set intersection loses signal.

### C. Smoke + monitor (chosen)

Keep `INSTALL ... FROM community`. Run the daily smoke. If a family
disappears, the smoke fires, and we file an issue against
duckdb-community-extensions. If the upstream fix lands fast (the
2026-05-02 audit suggests builds change daily), that is sufficient. If
it does not, escalate to A (vendor) or B (drop) per the maintenance
trigger.

- Pro: zero artifact weight; routes regressions upstream where they can
  be fixed for everyone.
- Pro: matches BenchBox's existing posture for community extensions.
- Con: a benchmark run during a drift window will still fail; the
  smoke catches it but does not heal it.
- Con: relies on upstream responsiveness. The issue filed under w4
  is the durability test for this assumption.

## Decision

**Option C.** The 2026-05-02 evidence is one drop event in nine months
of operation; current measurement frequency is "daily cron + relevant
PR." If the cron flips red repeatedly across consecutive weeks the
maintenance trigger above promotes us to A or B; until then, smoke +
monitor is enough.

The four affected ops stay in `operations.yaml` (per
`must_preserve` on the source TODO) and are documented as "blocked on
upstream extension stability" in
`docs/benchmarks/write-primitives-sketch-functions.md`.

## Consequences

- BenchBox carries one new CI workflow and one new script.
- Releases cut during a drift window will exclude `theta` and
  `frequent_items` results for DuckDB until the smoke goes green
  again. Other engines' sketch coverage is unaffected.
- If we ever need to revisit, the smoke output (with extension version
  printed on every run) doubles as the longitudinal evidence.

## Appendix: upstream issue draft

Smoke against extension version `2e38607` (2026-05-06) confirms drift:

```text
extension_version: 2e38607
theta: FAIL (Catalog Error: Scalar Function with name datasketch_theta does not exist!)
frequent_items: FAIL (Catalog Error: Scalar Function with name datasketch_frequent_items does not exist!)
cpc: OK
req: OK
kll: OK
hll: OK
```

Suggested issue title: "datasketches community build drops theta and
frequent_items families".

Suggested body: link to BenchBox's
`scripts/duckdb_datasketches_smoke.py`, list the dropped families,
quote the Catalog Errors above, ask whether the omission is
intentional (cmake guard, missing dep) or a build regression and
whether a fix or workaround is planned. Filing this issue is a manual
step under the TODO's w4 -- this appendix is the durable record of the
evidence so the issue can be filed from any commit's checkout, not
just the one where the drift was first observed.
