---
develop_sha: c44fdfc457886d9340b75d86ecb6e29796fdbb98
measured_at_sha: fc6dd5958b1deffa468e01852a392a29585d11eb
checked_sha: fc6dd5958b1deffa468e01852a392a29585d11eb
integrated_reviewed_sha: 06ede89eca3c5b1b7722cf3f7af16b3beb411f6e
---

# Results Explorer release-readiness closeout — 2026-09-04

## Verdict

The curated preview remains safe to describe as a curated preview, not as
broad Database Leaderboards readiness. The current source and the live
certification evidence close the original provenance, CI, documentation, and
browser-contract findings, but this closeout cannot certify a clean release:
two Vitest tests timed out, the required local browser server could not bind in
this sandbox, the focused Python run could not bind its test fixtures, and the
live pair is still a v7 snapshot served to source that expects v10. Those
defects are outside this branch's allowed product-code scope.

The live certification at `fc6dd5958` is reused for the deployed artifact,
privacy, independent math oracles, CSP meta behavior, and the Chromium sample.
Its Firefox/WebKit runs remain one advisory smoke sample each; they do not
promote those browsers to blocking coverage.

## Pins and evidence boundary

| Surface | Current evidence |
|---|---|
| Integrated/reviewed report head | `git rev-parse HEAD` = `06ede89eca3c5b1b7722cf3f7af16b3beb411f6e`; branch `feat/explorer-evidence-closeout`; this is the integrated closeout content reviewed by this report. |
| Measured evidence tree | `measured_at_sha`/`checked_sha` = `fc6dd5958b1deffa468e01852a392a29585d11eb`; the measurements and certification evidence were run against this historical tree. |
| Develop | `git rev-parse origin/develop` = `c44fdfc457886d9340b75d86ecb6e29796fdbb98`; this report's `develop_sha` is that exact 40-character value. |
| Launch | PR #1933 / v0.4.0 launch is already landed; `https://benchbox.dev/results/` was live in the independent certification. |
| Certified live pair | At `fc6dd5958`, Pages HTML and DuckDB were HTTP 200, internally matched read-model v7, and the deployed JS required v7. Source at current develop expects v10. |
| Certified local browser sample | Independent certification used port `60076`, PID `34745`, generated fixture directory `results-explorer/test-fixtures/.generated/data`, and fixture SHA-256 `58801fa40a810cdc6e2337d4f87461b4871e460559cd42edb1340ea9ec655aa1`. This closeout did not reuse that server. |
| Current attempted local browser run | Requested port `60123` and the current worktree's generated fixture directory. Fixture generation and build passed; sandbox policy returned `listen EPERM`, so no local browser result is claimed. |
| Raw evidence | Kept outside Git: `/tmp/explorer-closeout-e2e.log`, `/tmp/explorer-closeout-pytest.log`, `/tmp/explorer-closeout-typecheck.log`, `/tmp/explorer-closeout-build.log`, plus the independent certification logs named in its Pin matrix. |

## Original 2.x to closeout mapping

The historical adversarial report uses 2.x numbering. This report retains the
closeout contract's D1-D16/N1-N4 numbering and maps every historical entry,
including the grouped 2.18b entry:

| Closeout ID | Historical finding |
|---|---|
| D1 | 2.1 missing manifest promotion |
| D2 | 2.2 discarded `unofficial-research` provenance |
| D3 | 2.3 invalid trust-label coercion |
| D4 | 2.4 empty manifest without hash verification |
| D5 | 2.6 manifest-only PR bypass |
| D6 | 2.8 fork comment token failure risk |
| D7 | 2.9 skipped CI gates counted as pass |
| D8 | 2.10 snapshot-invariants gate absent |
| D9 | 2.12 stale prune-publishing instruction |
| D10 | 2.13 deploy-path and trigger drift |
| D11 | 2.14 stripped default-branch paths |
| D12 | 2.15 slim-corpus ADR drift |
| D13 | 2.16 QA overwrite/sealed-audit hazard |
| D14 | 2.17 false `bench.results` view security mechanism |
| D15 | 2.18 fixture, route, and URL-sync drift |
| D16 | 2.23 missing explorer CSP / browser runtime security boundary |
| N1 | 2.5 publisher URI, dedup, and companion handling passed review |
| N2 | 2.7 PR-controlled validator self-green risk |
| N3 | 2.11 stale `make validate-imports` target |
| N4 | 2.18b grouped doc drifts; 2.19 naming collision; 2.20 trust vocabulary; 2.21 empty TrustBadge; 2.22 test-directory naming |

The original adversarial report remains immutable. Historical claims are not
treated as current evidence unless the matrix below cites a current source,
test, or the independent certification.

## Closure matrix

| ID and lineage | Current owner TODO | Implementation PR/SHA | Source path | Automated rung | Live/rendered check | Severity | Disposition |
|---|---|---|---|---|---|---|---|
| **D1** — 2.1 | `remediate-submission-trust-label-enforcement` | PR #1843 / `0a1ebf84c` | `scripts/generate_corpus_inventory.py:85-118`; `benchbox/validation/bundle.py:993-1073` | Submission and pipeline tests; current focused run blocked after 437 passes by socket restrictions | Current code distinguishes absent maintainer sidecars from community manifests; contributor validation requires a manifest | P2 | fixed |
| **D2** — 2.2 | `remediate-submission-trust-label-enforcement` | PR #1843 / `0a1ebf84c`; current fail-closed compliance fields at `fc6dd5958` | `_project/scripts/explorer_pipeline/models.py:108-138`; `pipeline.py` | Privacy/ranking/submission tests; independent oracle found 55/55 rank agreements | Live certification confirms ranking math, but not a new v10 rebuild | P2 | fixed, with v10 rebuild residual owned by Explorer publication |
| **D3** — 2.3 | `remediate-submission-trust-label-enforcement` | PR #966 / `99b513fcd` | `benchbox/core/publishing/bundle_publisher.py:90-102` | Publisher label tests included in repository test coverage | No live publisher mutation performed | P2 | fixed |
| **D4** — 2.4 | `remediate-submission-trust-label-enforcement` | PR #966 / `99b513fcd` | `benchbox/validation/bundle.py:794-816` | Submission validation tests; empty/incomplete manifests now produce errors | No deployment claim needed; validation is source-controlled | P2 | fixed |
| **D5** — 2.6 | `remediate-submission-trust-label-enforcement` | PR #1881 / `f166e4941`; workflow parity `6529861dc` | `.github/workflows/validate-submission.yml:1-20,100-145` | Workflow contract tests; trusted base checkout and merge-SHA validation are present | No hosted PR was generated in this worker-only run | P2 | fixed |
| **D6** — 2.8 | `remediate-submission-trust-label-enforcement` | `033806e4d` | `.github/workflows/validate-submission.yml:1-20,25-34` | Workflow contract and comment-security tests | External fork execution not reproduced here | P2 | fixed by trusted `pull_request_target` design |
| **D7** — 2.9 | `remediate-ci-required-gate-integrity` | PR #962 / `f28a15ffa` | `.github/workflows/pr.yml:20-34,1086-1226` | CI workflow contract tests; `packaging-needed` and `viz-needed` are job outputs | No CI rerun requested or authorized; source wiring is current | P1 | fixed |
| **D8** — 2.10 | `remediate-ci-required-gate-integrity` | PR #962 / `f28a15ffa` | `.github/workflows/docs.yml:97-118`; `Makefile:494` | Snapshot-invariant script and docs workflow gate are present | Live certification independently recomputed deployed metrics; next v10 publish must rerun the gate | P2 | fixed |
| **D9** — 2.12 | `remediate-prune-publishing-doc-hazard` | PR #961 / `c4e72e7fd` | `docs/design/future-state/prune-publishing-subsystem/README.md:3-24` | Source/doc inspection | Rendered doc now labels the proposal completed and says not to delete live publish code | P1 | fixed |
| **D10** — 2.13 | `remediate-explorer-deploy-path-reconciliation` | PR #1679 / `c78db2e37` | `.github/workflows/docs.yml:3-17,79-118`; release curation in `Makefile:1080-1118` | Workflow/source contract inspection | Live Pages pair was observed by certification; it is consistent but stale against v10 source | P2 | accepted with owner Explorer publication; expiry/review before the next UI deploy (2026-09-18) |
| **D11** — 2.14 | `remediate-explorer-deploy-path-reconciliation` | PR #993 lineage; `c78db2e37` | `CONTRIBUTING.md:44`; current develop tree | Branch-presence and audit-SHA checks | Current default is develop and contains referenced paths; release branch curation remains a separate documented boundary | P2 | superseded with evidence: default-branch premise no longer holds |
| **D12** — 2.15 | `remediate-governance-and-doc-drift` | Current ADR/doc remediation is present on `fc6dd5958` | `docs/development/adr/adr-published-results-slim-corpus-branch.md`; `.github/workflows/sync-results-data-to-published.yml` | Published-results workflow/allowlist tests | No live branch mutation | P2 | fixed |
| **D13** — 2.16 | `remediate-governance-and-doc-drift` | PR #996 / `0c1f671e3` | `docs/operations/results-explorer-qa.md:192-212,490-515` | QA-plan contract is source-readable | Current plan names the next unused pass and keeps screenshots/logs out of Git | P2 | fixed |
| **D14** — 2.17 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 / `c3155c16a` | `docs/operations/results-explorer-qa.md:446-451` | Query route test pins read-only rejection; Python/browser contract suites | Independent Chromium certification passed worker CSP and the read-only runtime sample | P3 | fixed |
| **D15** — 2.18 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 / `c3155c16a` | `docs/operations/results-explorer-qa.md:5,283-292,314` | Fixture generator verification; route and URL-state tests | Current fixture generation produced 12 logical results and verified determinism; independent Chromium run passed | P3 | fixed |
| **D16** — 2.23 | `explorer-csp-frame-ancestors-meta-cleanup`; publication owner for headers | PR #972 / `7a601522f`; meta cleanup PR #1013 / `edf2292a2` | `results-explorer/index.html`; built `dist/index.html`; Pages response headers | Worker CSP test passed; privacy scan found 0 public path leaks across 391 bundles and 13 live tables | Live Pages has meta CSP but no HTTP CSP, COOP, COEP, or X-Frame-Options; meta cannot provide `frame-ancestors` | P3 | accepted with owner Publication/GitHub Pages; expiry/review 2026-10-04 |
| **N1** — 2.5 | None; non-defect historical control | None | `benchbox/core/publishing/store.py`; `benchbox/validation/bundle.py:551-617` | Static safety review and validator tests | No traversal/dedup defect reproduced; certification privacy scan passed | P3 | superseded with evidence: original control passed and remains bounded |
| **N2** — 2.7 | `remediate-submission-trust-label-enforcement` | `033806e4d` / current trusted-base workflow | `.github/workflows/validate-submission.yml:25-145` | Workflow contract tests | No fork PR run here; source now executes validators from trusted base and rejects unauthorized validator changes | P3 | fixed |
| **N3** — 2.11 | `remediate-ci-required-gate-integrity` | PR #962 / `f28a15ffa` | `Makefile:950` | Make target resolves to `lint-imports`; source check | No deployment relevance | P3 | fixed |
| **N4** — 2.18b, 2.19–2.22 | `remediate-governance-and-doc-drift`; `remediate-explorer-trust-label-vocabulary` | PRs #964, #974; current source at `fc6dd5958` | QA/ADR/token-scan/admin/runbook docs; `TrustBadge.tsx:1-128`; test paths | Source and focused test coverage; current suite reached 1,272 passing Vitest tests before two timeouts | Rendered/live certification supports the trust badge and route contract; Firefox/WebKit remain advisory samples | P3 | fixed with accepted coverage limits noted |

## Verification record

| Required command/check | Result |
|---|---|
| `npm test -- --run` | **Failed:** 1,272 passed, 8 skipped, 2 timed out: `PlatformIndex.test.tsx` row expansion and `Query.test.tsx` off-page selection. Product code is outside scope; no fix was made. First attempt also exposed a sandbox-only UV-cache permission error; rerun used `UV_CACHE_DIR=/tmp/benchbox-explorer-closeout-uv-cache`. |
| `npm run typecheck` | **Passed**; `/tmp/explorer-closeout-typecheck.log`. |
| `npm run build` | **Passed**; 242 modules, 15.36s in the standalone run; `/tmp/explorer-closeout-build.log`. |
| `npm run test:e2e:full` | **Not reached:** fixture generation and build passed, then the isolated server failed `listen EPERM` on requested port `60123`; `/tmp/explorer-closeout-e2e.log`. No existing server was reused. Independent certification provides the separate port-60076 Chromium blocking result, plus one Firefox and one WebKit smoke sample. |
| Focused Python command | **Environment-blocked after 437 passed:** four hosted-submission fixtures and the Explorer smoke test require local binds and received `PermissionError: [Errno 1] Operation not permitted`; `/tmp/explorer-closeout-pytest.log`. The required command was run with task-local UV cache and lock directory only. |
| Pages curl check | **Environment-blocked:** `curl` could not resolve `benchbox.dev` (`curl: (6) Could not resolve host`). The independent certification captured the live pair over HTTPS at the same develop pin. |
| Independent math/privacy/browser evidence | Certification at `fc6dd5958`: 138/138 geomeans, 138/138 percentile rows, 55/55 rank rows, 35/35 ranking-direction cohorts; zero public path leaks; Chromium blocking green; Firefox/WebKit 16 smoke tests each. |
| `make audit-sha-check FILE=_project/audits/results-explorer-release-readiness-closeout-2026-09-04.md` | Run after this file is written; must pass before commit. |

## L2/L3 review and residual ownership

L2 blind-spot review: the remaining risk classes are not ordinary frontend
green/red status. They are external socket permissions, deployment cache
transition from v7 to v10, missing HTTP response headers that GitHub Pages
cannot supply, and ungraduated browser coverage. The first two reproduced
frontend timeouts are concrete defects, not blind spots; they need separate
product/test TODOs and are not silently downgraded here.

L3 reframe: the decision is launch safety for a curated preview, not a claim
that the public corpus is a complete or cross-browser Database Leaderboard.
The safe current claim is therefore conditional: the already-live v7 pair is
internally consistent and privacy/math-certified, while the next source-v10
publication must rebuild and validate its snapshot before deployment.

No new TODO was created in this worker run because the required todo-db MCP
doctor/take path returned an approval-policy error before a tracker claim could
be acquired. The concrete remaining defects are named above for the manager to
create or route through the tracker using the distinct requested actor; no
sibling item was claimed or released.

Disposition count: fixed 16; accepted 2; superseded 2; still blocking 0 in the
historical D/N matrix. Current closeout gate remains **not certified** until
the two new frontend timeouts and the environment-blocked required runs are
resolved or independently attested.
