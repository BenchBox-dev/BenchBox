---
date: 2026-09-04
develop_sha: c44fdfc457886d9340b75d86ecb6e29796fdbb98
measured_at_sha: c44fdfc457886d9340b75d86ecb6e29796fdbb98
checked_sha: c44fdfc457886d9340b75d86ecb6e29796fdbb98
verdict: certified-with-residuals
---

# Results Explorer independent certification — 2026-09-04

## Verdict

The live Pages pair at `https://benchbox.dev/results/` is internally consistent:
HTML title **BenchBox Results Explorer**, snapshot read-model **v7**, and the
deployed index bundle requires **v7**. Independent oracles recomputed geomean,
percentiles, and ranking direction from that snapshot and agreed with stored
columns. Chromium's blocking suite passed on an isolated local server; Firefox
and WebKit `@smoke` passed on the same server. That smoke pass is one sample,
not promotion evidence.

Current `origin/develop` source expects read-model **v10**
(`EXPLORER_READ_MODEL_VERSION` / `EXPECTED_READ_MODEL_VERSION`). Publishing the
current Explorer UI without rebuilding the snapshot would fail closed. GitHub
Pages still emits no CSP/COOP/COEP/`X-Frame-Options` HTTP headers; the
explorer's `connect-src 'self'` control is the HTML `<meta>` tag. One focused
Python failure is an unrelated CLI color-code assertion.

## Pin matrix

Measured at 2026-09-04T20:09:19Z unless noted. Commands are recorded so a later
reader can replay the pin, not copy these numbers as living state.

| Identity | Command | Value |
|---|---|---|
| Worktree | `git rev-parse --show-toplevel` | `<redacted local worktree>` |
| Branch | `git rev-parse --abbrev-ref HEAD` | `feat/explorer-evidence-certification` |
| HEAD / `origin/develop` | `git rev-parse HEAD`; `git rev-parse origin/develop` | `c44fdfc457886d9340b75d86ecb6e29796fdbb98` |
| Origin | `git remote get-url origin` | `https://github.com/BenchBox-dev/BenchBox.git` |
| Live HTML | `curl -sS -D - -o /tmp/explorer-evidence-cert-results.html https://benchbox.dev/results/` | HTTP/2 200; `etag: "6a9ad571-a94"`; `last-modified: Fri, 04 Sep 2026 14:28:01 GMT`; `cache-control: max-age=600`; `accept-ranges: bytes`; `content-length: 2708`; `age` 511 then 0 on refresh; title `BenchBox Results Explorer` |
| Live snapshot | `curl -sS -D - -o /tmp/explorer-evidence-cert-results.duckdb https://benchbox.dev/results/data/results.duckdb` | HTTP/2 200; `etag: "6a9ad571-843000"`; same last-modified; `cache-control: max-age=600`; `accept-ranges: bytes`; `content-length: 8663040` |
| Snapshot digest | `shasum -a 256 /tmp/explorer-evidence-cert-results.duckdb` | `3bce914eae9f9bb3dceea490af4f47f8b14ad084cb46aeb7a4f624208b1d5795` |
| Live read-model | `SELECT read_model_version FROM metadata` on the downloaded file | `7` (138 `results` rows) |
| Live JS expected version | search deployed `/results/assets/index-BHBGgHhE.js` for `UI requires v` | requires **7** (`const Ha=7` in that bundle) |
| Source expected version | `_project/scripts/explorer_pipeline/contract.py` / `results-explorer/src/db.ts` | **10** |
| Live index JS | `curl -sS -D - https://benchbox.dev/results/assets/index-BHBGgHhE.js` | HTTP/2 200; `etag: "6a9ad571-61bd0"`; `content-length: 400336`; same last-modified as HTML/DB |
| Playwright | `npx playwright --version` in `results-explorer/` | 1.62.1 |
| Chromium | launched via `@playwright/test` | 151.0.7922.34 |
| Firefox | launched via `@playwright/test` | 153.0 |
| WebKit | launched via `@playwright/test` | 26.5 |
| Isolated e2e server | `node scripts/serve-browser-tests.mjs --port 60076 --host 127.0.0.1` | PID 34745; cwd `results-explorer/`; fixture dir `results-explorer/test-fixtures/.generated/data`; served DuckDB SHA-256 `58801fa40a810cdc6e2337d4f87461b4871e460559cd42edb1340ea9ec655aa1`; `Content-Length: 7352320`; title `BenchBox Results Explorer` |

The default Playwright port 4319 was not used. PID 34745 was confirmed with
`lsof -nP -iTCP:60076` as the listener. Other `serve-browser-tests.mjs`
processes on this machine (ports 4387 and 63732, different worktrees) were
left untouched.

Logs (not in Git): `/tmp/explorer-evidence-cert-pin.log`,
`/tmp/explorer-evidence-cert-oracle.json`,
`/tmp/explorer-evidence-cert-pytest.log`,
`/tmp/explorer-evidence-cert-chromium.log`,
`/tmp/explorer-evidence-cert-firefox.log`,
`/tmp/explorer-evidence-cert-webkit.log`.

## CSP, headers, and privacy

Live GitHub Pages HTML/JS/DuckDB responses carried `server: GitHub.com`,
`access-control-allow-origin: *`, `cache-control: max-age=600`, and
`accept-ranges: bytes`. They did **not** carry `Content-Security-Policy`,
`X-Frame-Options`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Embedder-Policy`,
`Referrer-Policy`, or `Permissions-Policy`. That is a hosting-layer limit:
GitHub Pages cannot set those headers.

The explorer ships this CSP as a `<meta>` tag. Live and local `dist/index.html`
matched:

```
default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'unsafe-inline'; worker-src 'self' blob:; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; object-src 'none'; base-uri 'self'
```

`frame-ancestors` is intentionally absent from the meta tag (ignored in meta
delivery). The local e2e server **does** send
`Cross-Origin-Embedder-Policy: require-corp` and
`Cross-Origin-Opener-Policy: same-origin`; production Pages does not.

Chromium `e2e/capability/worker-csp.spec.ts` passed: a DuckDB
`read_csv_auto('https://example.invalid/...')` attempt produced a visible error
and zero remote requests.

Privacy scan (detector `find_public_path_leaks`; field paths only, no path
values):

| Surface | Files / rows | Leak hits |
|---|---|---|
| `results-data/bundles/**/*.json` | 391 files | 0 |
| Live snapshot VARCHAR/JSON columns | 13 tables | 0 |

## Independent oracles

Recomputed from `query_display_timings.display_ms` using
`tests/parity/generate_visualization_fixtures.py` (`geomean_ms`,
`platform_percentile_stats` / `compute_percentile`) and an independent
competition ranker (ties share rank; next rank skips by group size). Production
`transformer.py` / `chartMath.ts` were not used as the oracle.

| Check | Compared | Agree | Diverge | Notes |
|---|---|---|---|---|
| `display_geomean_ms` vs `geomean_ms(timings)` | 138 results | 138 | 0 | 4 results independently null and stored null |
| ranking `percentile_p50/p90/p95/p99` vs `platform_percentile_stats` | 138 ranking rows | 138 | 0 | 4 independently null |
| stored `rank` vs independent competition rank | 55 rankable rows across 35 cohorts | 55 | 0 | 83 unrankable rows stored `rank=NULL` |
| ranking direction | 35 cohorts | 35 | 0 | `primary_order` in {`asc`,`desc`}; `primary_metric` in {`display_geomean_ms`,`power_score`}; rank-1 is the extreme in the declared direction |

Spot check: `compute_percentile([10, 20, 30, 100, 200], 90) == 160.0`.

The live snapshot is v7. These agreements certify the **deployed** corpus, not
a v10 rebuild from current source.

### Retained replay evidence

The prior oracle result was present at the time of remediation, but its
executable command was not recorded. The retained replacement is
`_project/audits/results-explorer-evidence/independent-oracle-2026-09-04.json`.
It identifies the retrieval locator, digest
`3bce914eae9f9bb3dceea490af4f47f8b14ad084cb46aeb7a4f624208b1d5795`, and
measurement SHA `c44fdfc457886d9340b75d86ecb6e29796fdbb98`; it contains field
paths only and no private path values.

The snapshot bytes are not stored in Git because repository policy excludes
generated binary snapshots. The retained JSON result, script, manifest fields,
and checksum make that limitation explicit but cannot guarantee that the live
locator will continue serving the historical bytes.

The URL below is only a retrieval locator. This command downloads its current
bytes and verifies the retained digest and size before replay. If the live URL
changes, verification must fail; new bytes must not be relabeled as the 2026-09-04
measurement.

```bash
curl --fail --location --output /tmp/results.duckdb https://benchbox.dev/results/data/results.duckdb && \
  printf '%s  %s\n' 3bce914eae9f9bb3dceea490af4f47f8b14ad084cb46aeb7a4f624208b1d5795 /tmp/results.duckdb | shasum -a 256 --check - && \
  test "$(wc -c < /tmp/results.duckdb | tr -d ' ')" = 8663040 && \
  uv run --no-project --with duckdb --with pyyaml -- python _project/audits/results-explorer-evidence/replay_independent_oracle.py --snapshot /tmp/results.duckdb --output /tmp/independent-oracle.json
```

For an already retrieved copy, the script repeats the digest and size checks
before opening DuckDB or scanning bundles. Controlled fallback, only when the
import probe succeeds:

```bash
if python3 -c 'import duckdb, yaml'; then
  python3 _project/audits/results-explorer-evidence/replay_independent_oracle.py --snapshot /tmp/results.duckdb --output /tmp/independent-oracle.json
else
  echo "python3 fallback unavailable: duckdb and/or yaml import failed" >&2
fi
```

Before snapshot verification or DuckDB access, the replay now requires a clean
checkout, the locally available measurement/source commit
`c44fdfc457886d9340b75d86ecb6e29796fdbb98`, the canonical
`results-data/bundles` root, and source/helper plus bundle content unchanged
from that commit. The retained JSON records SHA-256 identities for all five
imported repository files and for the complete bundle tree. It was recomputed
from the preserved pinned snapshot and verified inputs: 138/138 geomeans,
138/138 percentile rows, 55 rankable rows across 35 cohorts, zero
ranking-direction failures, and zero privacy leaks across 13 snapshot tables
and 391 JSON bundle files.

Wrong-snapshot negative control (must fail without creating the output):

```bash
printf 'wrong snapshot\n' > /tmp/results-wrong.duckdb
rm -f /tmp/oracle-wrong-snapshot.json
if uv run --no-project --with duckdb --with pyyaml -- python \
  _project/audits/results-explorer-evidence/replay_independent_oracle.py \
  --snapshot /tmp/results-wrong.duckdb --output /tmp/oracle-wrong-snapshot.json; then
  echo "ERROR: wrong snapshot was accepted" >&2
  exit 1
fi
test ! -e /tmp/oracle-wrong-snapshot.json
```

Changed-input negative control (commits one helper change in a disposable clone
so the checkout is clean, then must fail the c44 input-identity guard before
reading the snapshot):

```bash
replay_negative_dir="$(mktemp -d /tmp/benchbox-replay-negative.XXXXXX)"
git clone --local --no-hardlinks . "$replay_negative_dir/repo"
printf '\n# changed-input negative control\n' >> \
  "$replay_negative_dir/repo/tests/parity/generate_visualization_fixtures.py"
git -C "$replay_negative_dir/repo" add tests/parity/generate_visualization_fixtures.py
git -C "$replay_negative_dir/repo" \
  -c user.name="$(git config user.name)" \
  -c user.email="$(git config user.email)" \
  commit --no-verify -m 'test: change replay helper input'
if uv run --no-project --with duckdb --with pyyaml -- python \
  "$replay_negative_dir/repo/_project/audits/results-explorer-evidence/replay_independent_oracle.py" \
  --snapshot /tmp/results.duckdb --output "$replay_negative_dir/should-not-exist.json"; then
  echo "ERROR: changed helper was accepted" >&2
  exit 1
fi
test ! -e "$replay_negative_dir/should-not-exist.json"
```

## Submission cases

Default-filter focused pytest (see Verification) includes hosted-submission
fast tests. Additional contract paths:

| Suite | Command | Result |
|---|---|---|
| Vendor / fork / companion / allowlist / fail-open / trusted checkout / comment security | `uv run -- python -m pytest tests/unit/workflows/test_validate_submission_*.py tests/unit/scripts/explorer_pipeline/test_privacy_rejection.py tests/unit/scripts/explorer_pipeline/test_ranking.py -q` | 65 passed |
| Directory-scoped validator + hosted-submit develop contract + corpus trust boundary | `uv run -- python -m pytest tests/integration/test_submission_validation.py tests/integration/test_hosted_submit_validator_contract.py tests/unit/workflows/test_corpus_trust_boundary.py -q --override-ini "addopts="` | 18 passed |

No real credentials were used. `validate-submission.yml` and dataframe adapters
were not edited.

## Browser matrix

Isolated server: PID 34745, `127.0.0.1:60076`, fixture SHA above.
`CI` was unset so Playwright reused that listener
(`reuseExistingServer` is false when `CI` is set).

| Project | Command | Result | Promotion status |
|---|---|---|---|
| Chromium blocking | `env -u CI E2E_PORT=60076 npm run test:e2e:chromium:run` | 168 passed + 12 skipped (main); 9 passed (`e2e/failures/`); 1 passed (`e2e/performance.spec.ts`). Worker CSP passed. Performance budgets met (DuckDB-WASM cold init P95 811ms / 6000ms). | Blocking gate. This run is green. |
| Firefox `@smoke` | `env -u CI E2E_PORT=60076 npx playwright test --project=firefox --workers=1` | 16 passed in 42.3s | Advisory. One green sample; do not promote. |
| WebKit `@smoke` | `env -u CI E2E_PORT=60076 npx playwright test --project=webkit --workers=1` | 16 passed in 37.3s | Advisory. One green sample; do not promote. |

Evidence was Playwright test results against the built `dist/` and fixture
corpus, not injected JavaScript, synthetic `popstate`, or synthetic key events
as the sole proof.

## Classified failures and skips

| Item | Class | Owner | Evidence | Disposition |
|---|---|---|---|---|
| `tests/integration/test_throughput_stream_count.py::test_run_official_rejects_explicit_streams_one` | product (test vs colored CLI) | CLI throughput tests | Asserted `'streams must be >= 2' in result.output`; Click emitted bold ANSI around `2`. Rejection still occurred (`SystemExit(1)`). Unrelated to Explorer. | Residual. Out of Explorer certification scope; do not treat as Explorer red. |
| Live Pages missing CSP/COOP/COEP/`X-Frame-Options` HTTP headers | policy (hosting) | Publication / GitHub Pages | Header capture on `/results/`, JS, and DuckDB. Meta CSP present and equal to current `dist/index.html`. | Residual. Framing protection cannot be meta-delivered. |
| Source read-model v10 vs live pair v7 | infrastructure (publish lag) | Explorer publication | Live JS requires 7; snapshot metadata is 7; source constants are 10 (PR #2030 client-link columns). | Residual. Next UI deploy must ship a rebuilt snapshot or the UI fail-closes. |
| RG-2 10% range-read budget test skipped | product (wasm runtime) | Explorer / duckdb-wasm | `test.skip` in `range-read-budget.spec.ts`: duckdb-wasm still issues a whole-file GET. Diagnostic Accept-Ranges + 416 tests passed on the isolated server. Live DuckDB also sends `accept-ranges: bytes`. | Residual. Tracked as `enable-duckdb-wasm-http-range-reads-for-registered-urls`. |
| 10 opt-in capture specs skipped | policy | Explorer QA | Require capture env flags; screenshots stay out of Git. | Expected skip. |
| `e2e/routes/pages-artifact.spec.ts` skipped | policy | Publication | Needs `E2E_PAGES_SHAPED=1` and `E2E_SITE_DIR` pointing at an assembled `site/`. Live HTML/DB were pinned over HTTPS instead. | Residual for assembled-artifact route restoration; not a silent drop. |

No WebKit or Firefox failures on this run. Prior WebKit timeouts are not
restated as current defects.

## Verification

| Command | Result | Log |
|---|---|---|
| `uv run -- python -m pytest tests/integration tests/uat/test_explorer_smoke.py tests/unit/scripts/explorer_pipeline -q` | 1 failed, 1418 passed, 10 skipped in 169.43s. Failure classified above. | `/tmp/explorer-evidence-cert-pytest.log` |
| `cd results-explorer && npm run test:e2e:chromium` (fixtures + build already run; `chromium:run` on port 60076) | Chromium blocking green | `/tmp/explorer-evidence-cert-chromium.log` |
| Firefox / WebKit `@smoke` on port 60076 | both 16 passed | `/tmp/explorer-evidence-cert-firefox.log`, `/tmp/explorer-evidence-cert-webkit.log` |
| Independent geomean / percentile / ranking-direction recompute | 138/138 geomean, 138/138 percentile, 55/55 ranks, 0 direction failures | `_project/audits/results-explorer-evidence/independent-oracle-2026-09-04.json` |
| `UV_CACHE_DIR=/tmp/benchbox-explorer-evidence-audit-uv-cache make audit-sha-check FILE=_project/audits/results-explorer-release-certification-independent-oracles-2026-09-04.md` | PASS — `OK _project/audits/results-explorer-release-certification-independent-oracles-2026-09-04.md: develop_sha=c44fdfc457886d9340b75d86ecb6e29796fdbb98 target_ref=origin/develop measured_at_sha=c44fdfc457886d9340b75d86ecb6e29796fdbb98`. | — |

Default pytest marker filter (`not slow and not stress and not live_integration and not resource_heavy`) applied to the focused Python command.

## Residuals that need a decision

1. Whether the next Explorer publish must rebuild the DuckDB snapshot to v10
   before the current UI is deployed (recommended: yes; otherwise the UI
   refuses the live v7 file).
2. Whether GitHub Pages / Fastly should add `X-Frame-Options` or header CSP.
   The meta tag cannot provide `frame-ancestors`.
3. Whether `test_run_official_rejects_explicit_streams_one` should strip ANSI
   before asserting. Not an Explorer defect.
4. Firefox and WebKit stay advisory until consecutive-green evidence exists.
   This run is one green sample each.
