---
develop_sha: 86a8794579f2edb2f1bad07ea177550ef5f8067c
measured_at_sha: 86a8794579f2edb2f1bad07ea177550ef5f8067c
checked_sha: 86a8794579f2edb2f1bad07ea177550ef5f8067c
published_results_sha: 086cb68d585a188585774b91d039ae7f243e4cde
live_snapshot_sha256: 1aac8c08acf3f102f39e1bdb7dc37bc074fceb74ee8309c5479bebea4e45a9ed
---

# Results Explorer release-readiness closeout — 2026-09-07

## Verdict

The curated preview remains safe to describe as a curated preview, not as
broad Database Leaderboards readiness. Every D1–D16/N1–N4 finding from the
17c0c098a adversarial assessment is owned below with current-tree evidence:
16 fixed, 2 accepted with owner and unreached expiry, 2 superseded with
evidence, 0 still blocking in the historical matrix.

All three Sep-4 blockers are resolved: the two Vitest timeouts
(`PlatformIndex` row expansion, `Query` off-page selection) pass at this
tree (37 and 35 tests green, 1334 total with 0 failures); the live pair is
aligned at read-model v10 across snapshot, deployed JS, and source contract;
and the local browser server binds cleanly on an isolated port in this
environment. No new defects were reproduced; no new TODO was required.

## Re-validation performed before implementation

Each Sep-4 requirement was re-checked against the current tree before reuse:

- Sep-4 pins (`fc6dd5958`/`c44fdfc45`) are stale: develop has since merged
  #2047 (Explorer evidence integration), #2049, #2053, #2054, #2060, #2062,
  #2064, #2065, #2069, and #2076. The prior closeout branch's three commits
  were verified content-subsets of #2047's integration and dropped; this
  report measures `86a879457` directly.
- All seven dependency TODOs are `done` in live tracker state.
- Every matrix source path was confirmed present at this tree; workflow
  wiring for D5–D8 was re-grepped (same lines as Sep-4).
- D10 and D16 accepted-with-expiry dispositions still apply: expiries
  2026-09-18 and 2026-10-04 are not reached. D16 was re-probed live today.
- The pinned Sep-4 oracle replay script fail-closes on the current tree by
  design (corpus drift since `c44fdfc45`); current-tree math evidence is the
  fresh independent recomputation recorded below, not the old measurement.

## Pins and evidence boundary

| Surface | Current evidence |
|---|---|
| Measured/checked tree | `86a8794579f2edb2f1bad07ea177550ef5f8067c` (`origin/develop` at fetch time); worktree `BenchBox.wt-explorer-evidence-closeout`, branch `feat/explorer-evidence-closeout`. |
| Published corpus | `origin/published-results` = `086cb68d585a188585774b91d039ae7f243e4cde`. |
| Live pair | `https://benchbox.dev/results/` HTTP 200, title "BenchBox Results Explorer"; DuckDB HTTP 200, 8663040 bytes, SHA-256 `1aac8c08…4e45a9ed` — identical bytes to the Sep-5 recertification, `last-modified Sat, 05 Sep 2026`. Snapshot `metadata` = 10; source `EXPECTED_READ_MODEL_VERSION` = 10; 199 results rows. |
| Local browser run | Isolated server `127.0.0.1:64710`, fresh deterministic fixtures (`test-fixtures/.generated/data/results.duckdb`, SHA-256 `9d30c7d0…05b`, generator determinism check passed). No existing server reused. |
| Raw evidence | Kept outside Git: `/tmp/explorer-closeout-20260907-{vitest,pytest,privacy,fixtures,build,chromium,firefox,webkit,oracle}.log`, live HTML/snapshot copies. Probe script `/tmp/explorer-closeout-oracle-20260907.py` (throwaway, stdlib + duckdb only). |

## Closure matrix

Historical 2.x numbering maps to D/N IDs exactly as the Sep-4 report; lineage
is unchanged, so only current evidence and any disposition change are noted.
All dispositions carry over unless stated.

| ID and lineage | Current owner TODO | Implementation PR/SHA | Current evidence (2026-09-07 tree unless noted) | Severity | Disposition |
|---|---|---|---|---|---|
| **D1** — 2.1 | `remediate-submission-trust-label-enforcement` | PR #1843 | Paths present; submission/pipeline suites green in the 449-test focused run | P2 | fixed |
| **D2** — 2.2 | `remediate-submission-trust-label-enforcement` | PR #1843 | Oracle recompute below confirms ranking math on the live v10 snapshot | P2 | fixed |
| **D3** — 2.3 | `remediate-submission-trust-label-enforcement` | PR #966 | Path present; publisher label tests in the green suites | P2 | fixed |
| **D4** — 2.4 | `remediate-submission-trust-label-enforcement` | PR #966 | Validation is source-controlled; covered by submission suites | P2 | fixed |
| **D5** — 2.6 | `remediate-submission-trust-label-enforcement` | PR #1881 | `validate-submission.yml` trusted-base wiring re-grepped; no hosted PR generated in this run | P2 | fixed |
| **D6** — 2.8 | `remediate-submission-trust-label-enforcement` | `033806e4d` | `pull_request_target` at `validate-submission.yml:4` with fork-safety comment; external fork run not reproduced here | P2 | fixed by trusted-base design |
| **D7** — 2.9 | `remediate-ci-required-gate-integrity` | PR #962 | `packaging-needed`/`viz-needed` outputs re-grepped in `pr.yml:32-33,1086,1128` | P1 | fixed |
| **D8** — 2.10 | `remediate-ci-required-gate-integrity` | PR #962 | Snapshot-invariant gate re-grepped in `docs.yml:97-118`; live metrics independently recomputed | P2 | fixed |
| **D9** — 2.12 | `remediate-prune-publishing-doc-hazard` | PR #961 | Rendered doc still labels the proposal completed | P1 | fixed |
| **D10** — 2.13 | `remediate-explorer-deploy-path-reconciliation` | PR #1679 | Live pair observed consistent at v10; next UI deploy must review before 2026-09-18 | P2 | accepted with owner Explorer publication |
| **D11** — 2.14 | `remediate-explorer-deploy-path-reconciliation` | PR #993 lineage | Default branch verified `develop` today via API; premise still does not hold | P2 | superseded with evidence |
| **D12** — 2.15 | `remediate-governance-and-doc-drift` | Current ADR + sync workflow | Paths present; allowlist tests green | P2 | fixed |
| **D13** — 2.16 | `remediate-governance-and-doc-drift` | PR #996 | QA plan names the next unused pass; screenshots/logs stay out of Git | P2 | fixed |
| **D14** — 2.17 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 | Read-only route rejection pinned by tests; Chromium sample green | P3 | fixed |
| **D15** — 2.18 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 | Fixture generation deterministic today; route/URL-state tests green | P3 | fixed |
| **D16** — 2.23 | Publication/GitHub Pages | PRs #972/#1013 | Re-probed today: no HTTP CSP/COOP/COEP/X-Frame-Options; multiline meta CSP present in live HTML; framing gap documented in source; review by 2026-10-04 | P3 | accepted with owner |
| **N1** — 2.5 | None (control) | None | No traversal/dedup defect reproduced; privacy suites green | P3 | superseded with evidence |
| **N2** — 2.7 | `remediate-submission-trust-label-enforcement` | `033806e4d` | Trusted-base execution verified in source; no fork PR run here | P3 | fixed |
| **N3** — 2.11 | `remediate-ci-required-gate-integrity` | PR #962 | `lint-imports` resolves | P3 | fixed |
| **N4** — 2.18b, 2.19–2.22 | `remediate-governance-and-doc-drift`; trust-vocabulary owner | PRs #964, #974 | Full Vitest suite green (1334 passed); Firefox/WebKit advisory smokes green | P3 | fixed with accepted coverage limits noted |

## Verification record

| Required command/check | Result |
|---|---|
| `npm test -- --run` (results-explorer) | **Passed:** 93 files, 1334 tests passed, 8 skipped, 0 failed, 0 timeouts. Former-timeout files green: `PlatformIndex.test.tsx` (37), `Query.test.tsx` (35). |
| `npm run typecheck` | **Passed**, exit 0. |
| `npm run build` | **Passed**, 2.12s. |
| Isolated e2e, `127.0.0.1:64710` | **Passed:** Chromium 174 passed/12 skipped + 9 failure-paths + 1 perf (all latency budgets met); Firefox 16/16; WebKit 16/16. Fresh deterministic fixtures; no server reused. |
| Focused Python command (verification 2) | **Passed:** 449 passed, exit 0 — pipeline, explorer, build/receipt contracts, submission validation, hosted submission, explorer smoke. No socket errors. |
| Privacy invariants | **Passed:** 128 tests across anonymization, corpus privacy invariant, and privacy rejection. |
| Independent math oracle (live snapshot) | **Passed:** 27/27 cohort rank orders agree; 136/136 per-platform percentile sets agree (same linear-interpolation definition as `transformer._compute_percentile`); 27 cohorts / 199 metadata rows / 136 rankable rows; 0 divergences. |
| Pages curl check (verification 3) | **Passed:** `/results/` 200 with title "BenchBox Results Explorer"; `results.duckdb` 200, digest matches Sep-5 recertification bytes. |
| Pinned Sep-4 replay | **Fail-closed by design** on the current tree (corpus drift); current-tree math evidence is the oracle row above. Not a defect. |
| `make audit-sha-check FILE=_project/audits/results-explorer-release-readiness-closeout-2026-09-07.md` | Run after this file is written; must pass before commit. |

## L2/L3 review and residual ownership

L2 blind-spot review: the remaining risk classes are external-permission
flakiness (none observed in this environment), deployment cache transition
(no transition pending — live bytes equal the recertified v10 snapshot),
ungraduated Firefox/WebKit coverage (still advisory smokes by documented
policy, not a silent gap), and the two accepted HTTP-header/deploy-path
residuals with owners and expiries above.

L3 reframe: the decision remains launch safety for a curated preview, not a
claim of complete cross-browser Database Leaderboard maturity. The safe
current claim: source at `86a879457`, live v10 pair internally consistent
and privacy/math-certified, all historical findings owned.

Disposition count: fixed 16; accepted 2 (D10, D16, both with owner and
unreached expiry); superseded 2 (D11, N1); still blocking 0. No new TODO
was required: no new defect was reproduced. Closeout gate: **certified**
for the curated preview under the stated expiries; Firefox/WebKit promotion
and broad-leaderboard claims remain out of scope.

<!--
Local verification log (human `todo-db verify-run` attestation input):
- `npm test -- --run` → 1334 passed, 8 skipped
- `npm run typecheck` → exit 0; `npm run build` → exit 0
- e2e @ 127.0.0.1:64710 → Chromium 174+9+1, Firefox 16/16, WebKit 16/16
- Python focused → 449 passed; privacy → 128 passed
- Live digest 1aac8c08…4e45a9ed; metadata v10; source expects v10
-->
