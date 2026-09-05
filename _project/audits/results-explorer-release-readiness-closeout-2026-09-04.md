---
develop_sha: c44fdfc457886d9340b75d86ecb6e29796fdbb98
measured_at_sha: fc6dd5958b1deffa468e01852a392a29585d11eb
checked_sha: fc6dd5958b1deffa468e01852a392a29585d11eb
independent_review_anchor_sha: 28bb89d157cdf819a43038257e13f6a1239f4f40
---

# Results Explorer release-readiness closeout — 2026-09-04

## Verdict

The curated preview remains safe to describe as a curated preview, not as
broad Database Leaderboards readiness. The current source and the live
certification evidence close the original provenance, CI, and browser-contract
findings, but N4.1b and N4.1d remain accepted documentation/workflow residuals
and this closeout cannot certify a clean release:
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
| Independent-review integration anchor | `independent_review_anchor_sha` = `28bb89d157cdf819a43038257e13f6a1239f4f40`; the exact integration head independently reviewed before this remediation. It is neither the SHA of this edited file nor a measurement run. From the committed remediation checkout, `git merge-base --is-ancestor 28bb89d157cdf819a43038257e13f6a1239f4f40 HEAD && test "$(git diff --name-only 28bb89d157cdf819a43038257e13f6a1239f4f40 HEAD)" = "_project/audits/results-explorer-release-readiness-closeout-2026-09-04.md"` verifies descent from the reviewed integration content and confines the post-review change to this closeout. |
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
| N4.1a | 2.18b strategy drift |
| N4.1b | 2.18b workflow-trigger drift |
| N4.1c | 2.18b token-scan drift |
| N4.1d | 2.18b ruleset drift |
| N4.1e | 2.18b runbook monthly-schedule drift |
| N4.1f | 2.18b runbook on-demand-dispatch drift |
| N4.2 | 2.19 publish naming collision |
| N4.3 | 2.20 trust vocabulary |
| N4.4 | 2.21 empty TrustBadge |
| N4.5 | 2.22 test-directory naming |

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
| **D11** — 2.14 | `remediate-explorer-deploy-path-reconciliation` | PR #993 lineage; `c78db2e37` | `CONTRIBUTING.md:44`; `origin/develop:.github/workflows/docs.yml`; `origin/develop:.github/workflows/results-explorer-browser.yml`; `_project/audits/results-explorer-evidence/d11-live-evidence-2026-09-04.txt` | Read-only `git ls-tree` confirmed all three named develop paths and the related ADR/token-scan/admin/runbook paths | Retained live reads report default branch `develop`; the `main` branch endpoint returns branch `release`, commit `4ad1d727903328702c93abf139902cee42dc3890`, and `/tree/main` renders with status 200 at `/tree/release` | P2 | superseded with evidence: the live default branch is `develop` and the requested `/tree/main` rendering resolves to `release`, so the original default-main premise does not hold |
| **D12** — 2.15 | `remediate-governance-and-doc-drift` | Current ADR/doc remediation is present on `fc6dd5958` | `docs/development/adr/adr-published-results-slim-corpus-branch.md`; `.github/workflows/sync-results-data-to-published.yml` | Published-results workflow/allowlist tests | No live branch mutation | P2 | fixed |
| **D13** — 2.16 | `remediate-governance-and-doc-drift` | PR #996 / `0c1f671e3` | `docs/operations/results-explorer-qa.md:192-212,490-515` | QA-plan contract is source-readable | Current plan names the next unused pass and keeps screenshots/logs out of Git | P2 | fixed |
| **D14** — 2.17 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 / `c3155c16a` | `docs/operations/results-explorer-qa.md:446-451` | Query route test pins read-only rejection; Python/browser contract suites | Independent Chromium certification passed worker CSP and the read-only runtime sample | P3 | fixed |
| **D15** — 2.18 | `remediate-qa-and-browser-test-doc-accuracy` | PR #964 / `c3155c16a` | `docs/operations/results-explorer-qa.md:5,283-292,314` | Fixture generator verification; route and URL-state tests | Current fixture generation produced 12 logical results and verified determinism; independent Chromium run passed | P3 | fixed |
| **D16** — 2.23 | `explorer-csp-frame-ancestors-meta-cleanup`; publication owner for headers | PR #972 / `7a601522f`; meta cleanup PR #1013 / `edf2292a2` | `results-explorer/index.html`; built `dist/index.html`; Pages response headers | Worker CSP test passed; privacy scan found 0 public path leaks across 391 bundles and 13 live tables | Live Pages has meta CSP but no HTTP CSP, COOP, COEP, or X-Frame-Options; meta cannot provide `frame-ancestors` | P3 | accepted with owner Publication/GitHub Pages; expiry/review 2026-10-04 |
| **N1** — 2.5 | None; non-defect historical control | None | `benchbox/core/publishing/store.py`; `benchbox/validation/bundle.py:551-617` | Static safety review and validator tests | No traversal/dedup defect reproduced; certification privacy scan passed | P3 | superseded with evidence: original control passed and remains bounded |
| **N2** — 2.7 | `remediate-submission-trust-label-enforcement` | `033806e4d` / current trusted-base workflow | `.github/workflows/validate-submission.yml:25-145` | Workflow contract tests | No fork PR run here; source now executes validators from trusted base and rejects unauthorized validator changes | P3 | fixed |
| **N3** — 2.11 | `remediate-ci-required-gate-integrity` | PR #962 / `f28a15ffa` | `Makefile:950` | Make target resolves to `lint-imports`; source check | No deployment relevance | P3 | fixed |
| **N4.1a** — 2.18b strategy evidence | `remediate-governance-and-doc-drift` | current integration tree | `docs/development/benchbox-results-platform-strategy.md:481-484` names `exporter.py`, `bundle_publisher.py`, and `store.py`, and identifies the deleted prototype as historical | Current-source inspection | No rendered evidence required for this documentation correction | P3 | fixed |
| **N4.1b** — 2.18b workflow triggers | `remediate-governance-and-doc-drift` | current integration tree | `.github/workflows/results-explorer-browser.yml:3-28,39-62` shows `release`/`develop` branches, no `pull_request.paths`, and explicit non-PR handling for push/dispatch; `.github/workflows/docs.yml:3-23`; `docs/development/results-explorer-browser-testing.md:67-79` | Current-source inspection | No live workflow run was claimed | P3 | accepted residual — CI/workflow owner must reconcile the trigger and required-check contract outside this allowlist; next action is to update `.github/workflows/results-explorer-browser.yml` and its related documentation before calling this fixed |
| **N4.1c** — 2.18b token-scan job set | `remediate-governance-and-doc-drift` | current integration tree | `docs/operations/results-explorer-token-scan.md:121-137` includes `medium-test`; `.github/workflows/develop-post-merge.yml:512-524` defines the four expected jobs | Current-source inspection | No live post-merge run was claimed | P3 | fixed |
| **N4.1d** — 2.18b ruleset aggregate count | `remediate-governance-and-doc-drift` | current integration tree | `docs/operations/repo-admin-settings.md:70-79` lists the `ci-required-result` needs contract but omits `publication-reconciliation`; `.github/workflows/pr.yml:1417-1441` requires and exports `publication-reconciliation` | Current-source inspection | No live ruleset mutation or hosted run was claimed | P3 | accepted residual — CI/governance documentation owner must reconcile `docs/operations/repo-admin-settings.md` with `.github/workflows/pr.yml` outside this allowlist; next action is to update that admin documentation before calling this fixed |
| **N4.1e** — 2.18b runbook monthly schedule | `remediate-governance-and-doc-drift` | current integration tree | `docs/operations/results-phase-2-runbook.md:37-42` describes a monthly refresh; `.github/workflows/seed-corpus.yml:8-13` defines `schedule` with cron `0 7 1 * *` | Current-source inspection | The runbook's monthly claim agrees with the authoritative workflow schedule | P3 | fixed |
| **N4.1f** — 2.18b runbook on-demand dispatch | `remediate-governance-and-doc-drift` | current integration tree | `docs/operations/results-phase-2-runbook.md:39-42` describes an on-demand refresh; `.github/workflows/seed-corpus.yml:14-20` defines `workflow_dispatch` and its input | Current-source inspection | The runbook's on-demand claim agrees with the authoritative workflow dispatch trigger | P3 | fixed |
| **N4.2** — 2.19 publish naming collision | `remediate-governance-and-doc-drift` | current integration tree | `docs/development/benchbox-results-platform-strategy.md:499-504`; `docs/reference/cli/submit.md:123-132`; D9 evidence at `docs/design/future-state/prune-publishing-subsystem/README.md:3-24` | Current-source inspection | No live/rendered evidence is needed for terminology and the former prune hazard is closed by D9 | P3 | fixed |
| **N4.3** — 2.20 trust vocabulary | `remediate-explorer-trust-label-vocabulary` | current integration tree | `results-explorer/src/components/TrustBadge.tsx:8-17,27-74`; `results-explorer/src/components/__tests__/TrustBadge.test.tsx:104-128` | TrustBadge unit coverage explicitly iterates all publisher labels | No live/rendered evidence is claimed | P3 | fixed |
| **N4.4** — 2.21 empty TrustBadge | `remediate-explorer-trust-label-vocabulary` | current integration tree | `results-explorer/src/components/TrustBadge.tsx:76-119`; `results-explorer/src/components/__tests__/TrustBadge.test.tsx:96-102` | Unit test requires a visible neutral `Unknown` badge for `trustLabel=""` | No live/rendered evidence is claimed | P3 | fixed |
| **N4.5** — 2.22 test-directory naming | `remediate-governance-and-doc-drift` | current integration tree | `tests/unit/scripts/explorer_pipeline/README.md:1-20`; `tests/unit/scripts/test_explorer_build_contract.py:1-58`; `docs/development/adr/adr-explorer-cli-surface.md:230-256` | Current-source inspection of relocated test paths and migration ADR | No live/rendered evidence is needed for path naming | P3 | fixed |

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
| `UV_CACHE_DIR=/tmp/benchbox-explorer-evidence-audit-uv-cache make audit-sha-check FILE=_project/audits/results-explorer-release-readiness-closeout-2026-09-04.md` | PASS — `OK _project/audits/results-explorer-release-readiness-closeout-2026-09-04.md: develop_sha=c44fdfc457886d9340b75d86ecb6e29796fdbb98 target_ref=origin/develop measured_at_sha=fc6dd5958b1deffa468e01852a392a29585d11eb`. |

### Retained independent-oracle replay

The retained result artifact is
`_project/audits/results-explorer-evidence/independent-oracle-2026-09-04.json`.
The commands below are executable replay instructions for the retained
historical evidence; they are not a new live check. The managed-dependency
command is the primary replay:

```bash
uv run --no-project --with duckdb --with pyyaml -- python _project/audits/results-explorer-evidence/replay_independent_oracle.py --snapshot /tmp/results.duckdb --measurement-sha c44fdfc457886d9340b75d86ecb6e29796fdbb98 --snapshot-url https://benchbox.dev/results/data/results.duckdb --output /tmp/independent-oracle.json
```

Controlled fallback, only when the import probe succeeds:

```bash
if python3 -c 'import duckdb, yaml'; then
  python3 _project/audits/results-explorer-evidence/replay_independent_oracle.py --snapshot /tmp/results.duckdb --measurement-sha c44fdfc457886d9340b75d86ecb6e29796fdbb98 --snapshot-url https://benchbox.dev/results/data/results.duckdb --output /tmp/independent-oracle.json
else
  echo "python3 fallback unavailable: duckdb and/or yaml import failed" >&2
fi
```

## D11 live-evidence record

The Manager-retained read-only transcript at
`_project/audits/results-explorer-evidence/d11-live-evidence-2026-09-04.txt`
records the commands at `2026-09-04T23:13:13Z`. It reports:

- `gh api repos/BenchBox-dev/BenchBox --jq .default_branch` => `develop`.
- `gh api -i repos/BenchBox-dev/BenchBox/branches/main` => HTTP 200; JSON
  branch name `release`, commit
  `4ad1d727903328702c93abf139902cee42dc3890`, and HTML URL ending in
  `/tree/release`.
- The requested GitHub `/tree/main` URL => status 200 and effective URL ending
  in `/tree/release`; the title is `GitHub - BenchBox-dev/BenchBox at release ·
  GitHub`.
- `git ls-tree` on `origin/develop` lists `CONTRIBUTING.md`, both named
  workflow paths, and the related ADR, token-scan, admin, and runbook paths.

Disposition: superseded with evidence. The live default branch is `develop` and
the requested `/tree/main` rendering resolves to `release`, so the original
default-main premise does not hold.

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

Disposition count: fixed 23; accepted 4; superseded 2; still blocking 0 in the
historical D/N matrix. Current closeout gate remains **not certified** until
the two new frontend timeouts and the environment-blocked required runs are
resolved or independently attested.
