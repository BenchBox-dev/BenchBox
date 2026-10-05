# Results Explorer - browser testing

**Audience:** Maintainers making changes to `results-explorer/` and release
drivers who need to know what browser coverage exists and what still must be
checked by hand.

This note is the operational counterpart to
[`browser-test-architecture.md`](browser-test-architecture.md). The architecture
note records *why* the suite is shaped the way it is; this note records *what
to run, when to run it, and what to do when it fails*.

## What's covered by automation

The Playwright suite under `results-explorer/e2e/` runs against the built
explorer (`dist/`) served via the static test server at
`results-explorer/scripts/serve-browser-tests.mjs`. Fixtures are generated
per run into `results-explorer/test-fixtures/.generated/` - the curated
public corpus is never modified.

Routes and behaviours with at least one browser-functional test:

| Route / surface | Happy path | Failure path |
| --- | --- | --- |
| Home | ✅ | - |
| BenchmarkIndex | ✅ | - |
| PlatformIndex | ✅ | - |
| ResultDetail | ✅ | ✅ (unreachable `results.duckdb`, sidecar fetch failure, unknown id) |
| Compare | ✅ (deep link, share URL, sticky-bar flow) | ✅ (benchmark mismatch, scale mismatch, unknown id) |
| Query workbench | ✅ (sort, column toggle, starter query, CSV + JSON download) | ✅ (read-only write surfaces error) |
| NotFound | ✅ (unknown `/results/...` path renders the 404 card) | - |
| DuckDB-WASM attach | ✅ (cold load, `waitForDataLoaded`) | ✅ (RG-2 range-read capability via test server) |

## Running the suite locally

Prerequisites: a Python toolchain with `uv`, Node 20+, and the explorer's
dependencies installed. `test:e2e:install` is a one-time step that installs
Chromium, Firefox, and WebKit. `test:e2e:chromium` is the deterministic local
and CI entrypoint. `test:e2e:full` runs the full browser matrix locally.

```bash
cd results-explorer
npm ci
npm run test:e2e:install
npm run test:e2e:chromium
npm run test:e2e:full
```

On a clean machine, `npm run test:e2e:chromium:setup` wraps the one-time
browser install plus the same deterministic Chromium run.

Each browser script regenerates the fixture corpus and rebuilds `dist/`
before Playwright starts the static server, so the command stays aligned
with the shipped harness contract. `npm run test:e2e:full` is the
one-command local convenience path; CI stays split into per-browser jobs
so Chromium can block independently while Firefox/WebKit remain
non-blocking `@smoke`.

Cross-browser smoke passes:

```bash
npm run test:e2e:firefox
npm run test:e2e:webkit
```

Failure artifacts (traces, screenshots, video, HTML report) land under
`results-explorer/test-results/` and `results-explorer/playwright-report/`
and are both gitignored.

## Public-site visual baseline policy

The public-site visual comparison is advisory until the public site is in
production and feeds no required status context.

The full public-site visual suite is broader than the Explorer's current
functional gate. Its baseline policy is recorded in
`_project/audits/public-site-visual-baseline-policy-2026-08-15.md`:
raw screenshots stay out of Git, protected `develop` produces SHA-bound
baseline artifacts, and pull requests compare against the exact base-SHA
artifact. Missing or unverifiable baselines fail closed; a PR diagnostic
artifact is never promoted directly to a baseline. The capture harness at `results-explorer/e2e/captures/public-site-pages.spec.ts`
and Pages-shaped server are reusable building blocks. `.github/workflows/docs.yml`
uploads the protected baseline from `develop` and retrieves the exact
base-SHA artifact for pull requests. A changed public-site
tree cannot pass without that comparison. `Public-site visual acceptance`
reports on every develop PR; it skips the build only when
the former documentation input paths are unaffected.

Develop has no merge queue and no `merge_group` runs
(`_project/decisions/merge-queue-retirement-2026-10-03.md`): a pull request
merges by squash through auto-merge once the required checks are green on its
exact head. Pull requests keep a short retry when downloading the baseline.

If a protected `develop` push was dropped or its baseline expired, dispatch
Documentation on `develop` with `baseline_source_sha` set to the exact base
SHA shown by the failing PR:

```bash
gh workflow run docs.yml --ref develop -f baseline_source_sha=<full-protected-develop-base-sha>
```

The dispatch validates that the SHA is an ancestor of protected `develop`,
checks out that exact tree, and uploads a SHA-named artifact. The downloader
verifies the protected run and manifest source SHA. Wait for its visual job to
finish, then rerun the failed workflow. A PR diagnostic artifact cannot serve
as recovery input.

An intentional visual change or route/viewport addition needs explicit
maintainer acceptance. After reviewing the PR's `public-site-visual-diagnostics-*`
artifact, set the repository variable `APPROVED_HEAD_SHA` to the PR's complete
head SHA and set `APPROVAL_REASON` to a nonempty review note, then rerun the
failed workflow. The approval applies only when both values are present and the
approved SHA exactly equals GitHub's current PR head SHA. It may accept changed
digests and unexpected new captures, but it never accepts a capture missing
from the current matrix. Clear both variables after the approved run so only
one reviewed head occupies the repository-wide approval slot.

The PR-head slot is the only approval slot. `ci.yml` triggers only on
`pull_request`, and its compare step reads only `APPROVED_HEAD_SHA`,
`APPROVAL_REASON` and the PR head SHA.

This approval does not replace a baseline. The protected `develop` push or its
validated `workflow_dispatch` run uploads the SHA-bound baseline after the
reviewed PR merges. PR diagnostic artifacts remain short-lived and non-promotable.

### Intentional visual changes while the site moves to Astro

Several changes alter what the current site renders before the switch to Astro:

- converting reStructuredText pages to MyST;
- replacing the autodoc API reference with authored pages;
- adopting shared design tokens.

The comparison is advisory until the public site is in production
([merge-queue governance](../operations/merge-queue-governance.md)).
Until then, a changed capture does not block the merge, but it is still
reviewed. The procedure has two phases.

**Advisory phase (now).** For a PR whose comparison reports changed captures:

1. Download the PR run's `public-site-visual-diagnostics-*` artifact.
2. For each changed route and viewport, compare the current capture with the
   baseline. Confirm the change is the one the PR intends and that nothing else
   on the page moved.
3. Record the review in the PR: the run id, each changed capture as
   route and width, and one line per capture saying why the change is expected.

A change nobody intended is a defect. Fix it in the PR; do not record it as
expected.

**Gating phase (after the check is required again).** Review the PR run's
diagnostics, set `APPROVED_HEAD_SHA` to the PR head SHA and `APPROVAL_REASON` to
the review note, then re-run the failed job. Clear both variables afterwards.
This is the only approval slot.

**Missing exact-SHA baseline.** Dispatch Documentation on `develop` with
`baseline_source_sha`, as shown above. Wait for its visual job, then re-run the
failed job. A PR diagnostic artifact is never a substitute.

### Renderer-switch pull request

The Astro build is captured ahead of the switch by the non-required
`Public-site visual Astro dry run` job in `ci.yml`, locally by
`make site-build site-visual-capture`. It captures the same route and viewport
matrix from `website/dist` with `PUBLIC_SITE_VISUAL_RENDERER=astro`, uploads
`public-site-visual-astro-<run id>`, and never compares or replaces a baseline.
Each manifest records its `renderer`. If a route or viewport changes, update
the matrix in `public-site-pages.spec.ts` in the same change.

When the baseline and the current capture come from different renderers, the
comparison reports every capture as changed and passes only through the
exact-head approval described above. A missing capture still fails. The
comparison is never skipped, disabled or loosened.

**What the switch pull request changes.**

1. `docs.yml`: the `build` job produces the Astro site instead of assembling
   the Sphinx site (the `Assemble public site` step and the upload named
   `Upload assembled site for visual acceptance`), and the
   `Capture public site` step of `public-site-visual-regression` sets
   `PUBLIC_SITE_VISUAL_RENDERER: astro`. The push run on `develop` then
   publishes an Astro baseline for the merge commit.
2. `ci.yml`: the `docs-build` job and the `Capture public site` step of the
   `Public-site visual regression` job make the same change, so the pull
   request captures the Astro build against the Sphinx baseline of its exact
   base.
3. `public-site-pages.spec.ts`: the guard that restricts
   `PUBLIC_SITE_VISUAL_RENDERER=astro` to the capture phase stays in place. The
   workflows' compare step leaves `PUBLIC_SITE_VISUAL_RENDERER` unset, so it
   defaults to `sphinx` and the astro renderer reaches the comparison through
   the captured manifest. The guard therefore blocks only a local single-pass
   or compare run with `PUBLIC_SITE_VISUAL_RENDERER=astro`; lift it only for
   that local use, after the renderer cutover.

**Approval and baseline.** The decision record requires an exact-head approval
for the PR head, with queue position never substituting for it. Develop has no
merge queue, so there is no second slot.

1. PR head. Review the PR run's `public-site-visual-diagnostics-*` artifact
   against the Sphinx baseline. Set `APPROVED_HEAD_SHA` to the PR head SHA and
   `APPROVAL_REASON` to the review note, then re-run the failed job.
2. After the merge, the `Documentation` push run on `develop` must capture the
   Astro build and upload `public-site-visual-baseline-<merge commit>`. Confirm
   the artifact exists and that its `manifest.json` has `"renderer": "astro"`.
   If the push was dropped, dispatch Documentation with `baseline_source_sha`
   set to the merge commit.
3. Clear the approval variables. Hold other site-changing PRs until step 2
   is confirmed, because they need the Astro baseline for their exact base.

### Site-deploy comparison

A site-deploy run whose release commit or renderer differs from the deployed
one captures the release-sourced pages of the last production artifact and of
the assembled candidate with the same spec and compares them before the deploy
job may start (see
[the site deploy runbook](../operations/site-deploy.md#visual-comparison-before-deploy)).
The approval rule is the one above, in a separate pair of repository variables
named in that runbook: the approved value must equal the binding of the release
commit, the candidate artifact and the production baseline, and the reason must
be nonempty. The PR slot never applies to a deploy, and a deploy
approval never applies to a PR.

## What CI gates

The `explorer-e2e` job in [`.github/workflows/ci.yml`](https://github.com/BenchBox-dev/BenchBox/blob/develop/.github/workflows/ci.yml)
(Chromium full suite, blocking) runs on **pull requests**
when the change touches the explorer unit (with the `explorer` unit result
always reporting; the job is skipped when no relevant files change).

- **Blocking:** `chromium` job - full suite must pass.
- **Non-blocking:** `firefox-smoke` and `webkit-smoke` jobs - `@smoke`-tagged
  subset only, `continue-on-error: true`. These graduate to blocking once the
  flake data collected during w9 of
  `implement-results-explorer-browser-functional-tests` supports it.

All three jobs upload Playwright reports on failure with a 3-day retention
so maintainers can download a full trace from the PR checks page. The CI
jobs call the same shared browser scripts that maintainers run locally,
rather than re-encoding fixture/build/test sequencing in the workflow.

## Manual release check

Automation does not replace the short cross-browser pass a maintainer should
run before shipping a meaningful explorer change. "Meaningful" means any PR
that touches routing, `src/db.ts`, a page component, or the pipeline that
produces `results.duckdb`.

Check the following in Chrome, Firefox, and Safari - one pass each, not a
full regression run:

1. **Home** - header, counts, recent-results table render; deep link into a
   benchmark index from the browse-by-benchmark card works.
2. **BenchmarkIndex** - the SF filter updates the URL; each platform row
   links to a ResultDetail.
3. **ResultDetail** - run header, badges, and timings table render; "Compare
   this result" deep-links into Compare.
4. **Compare** - two-platform compare renders side-by-side cards; Share URL
   button copies the current URL; hard-block error renders cleanly for a
   mismatched cohort.
5. **Query** - schema-driven table renders; a starter query populates the
   SQL textarea; Download CSV and Download JSON both emit a file.
6. **NotFound** - an unknown `/results/...` path renders the 404 card and
   the "Back to Results" recovery link.

Focus on layout, font rendering, scroll behaviour, and clipboard/download
permissions - the parts that Playwright covers functionally but cannot
judge visually.

## When a CI run fails

1. Open the failed job, download the `playwright-report-*` artifact, and
   open `index.html` in a browser. The trace viewer is the fastest path to
   understanding the failure.
2. If the failure is browser-specific and reproduces locally, keep the
   browser-specific fix scoped to that browser.
3. If the failure does not reproduce locally, capture it as a flaky-test
   TODO rather than re-running the PR until it passes. See w9 of the parent
   TODO for the flake-triage pattern.

## Adding new tests

- Put happy paths under `results-explorer/e2e/routes/` and tag the primary
  spec per route with `@smoke`.
- Put failure paths under `results-explorer/e2e/failures/`. Assertions must
  target user-visible error states (a visible heading or message), not just
  thrown exceptions or console output.
- Put server/runtime contract checks that are not user failure paths
  under `results-explorer/e2e/capability/` (e.g. the RG-2 range-read
  gate in `capability/range-read-budget.spec.ts`).
- If a test depends on fixture data that does not yet exist, add a variant
  to `results-explorer/scripts/generate-browser-fixtures.mjs` - do not
  mutate the curated public corpus.
- If a test needs failure injection, prefer Playwright's `page.route()`,
  `context.setOffline`, permission grants, and download events. Do not
  introduce a production-code test seam.
