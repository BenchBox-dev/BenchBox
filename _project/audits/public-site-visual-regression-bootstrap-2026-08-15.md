---
date: 2026-08-15
develop_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
measured_at_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
checked_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
verdict: green-bootstrap
---

# Public-site visual regression bootstrap — 2026-08-15

## Matrix

The assembled Pages-shaped site was built from the checked SHA and served by
`results-explorer/scripts/serve-browser-tests.mjs`. The new public-site capture
harness passed **16 captures**:

- landing page `/`
- documentation `/docs/usage/getting-started.html`
- blog `/blog/2026-05-18-v0-3-0-release-overview.html`
- Results Explorer `/results/`
- Chromium viewports 390, 768, 1280, and 1600 CSS pixels

Every capture passed its route heading and horizontal-overflow contract. The
harness emitted a SHA-256 manifest and screenshots to a temporary local
artifact directory; no browser artifacts were committed.

## Existing Explorer regression coverage

The existing blocking Chromium suite also passed: 109 functional tests,
9 failure-regression tests, and 1 performance test. Twelve tests were skipped
by existing opt-in conditions.

## Baseline status

This was the bootstrap capture: no protected-develop baseline artifact existed
for the current base SHA, so no pixel-digest comparison was claimed. The
workflow now uploads `public-site-visual-baseline` from protected `develop` and
will require an exact base-SHA artifact for subsequent develop pull requests.

## Reproduction

```bash
make docs-build
cd results-explorer
npm run typecheck:e2e
E2E_PAGES_SHAPED=1 E2E_SITE_DIR=<assembled-site> \
  PUBLIC_SITE_VISUAL_OUTPUT=<temporary-output> \
  PUBLIC_SITE_VISUAL_SOURCE_SHA=e03c75382be312c1368ef98fd53f1e5ac68fe4bc \
  npm run test:e2e:public-site
npm run test:e2e:chromium
```
