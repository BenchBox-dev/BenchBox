---
date: 2026-08-15
develop_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
measured_at_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
checked_sha: e03c75382be312c1368ef98fd53f1e5ac68fe4bc
verdict: policy
---

# Public-site visual baseline policy — 2026-08-15

## Decision

The public-site visual suite uses **protected-develop CI artifacts** as its
baseline. Raw screenshots are never committed to Git. A baseline is valid only
when all of the following are true:

- it was produced by the protected `develop` push workflow after the complete
  visual suite passed;
- its manifest binds the source commit SHA, route, viewport, browser project,
  fixture/read-model identity, and screenshot digest;
- a pull request compares against the exact base SHA's artifact, never against
  a mutable live site or an arbitrary latest run;
- a missing, stale, or unverifiable baseline fails the relevant visual gate
  rather than silently becoming a new baseline; the one-time bootstrap
  exception applies only while no protected baseline artifact exists at all,
  and that run may capture but cannot compare;
- baseline refresh occurs only from a successful protected `develop` run after
  review, and the previous artifact remains available for rollback.

PR failures may upload screenshots, traces, and a diff report as short-lived
review artifacts. Those artifacts are diagnostic only and must not become the
next baseline without the protected-develop refresh path.

## Current implementation boundary

The repository now provides the route/viewport capture and digest-comparison
harness in `results-explorer/e2e/captures/public-site-pages.spec.ts`. It still
does not provide the protected-develop baseline upload or exact-base artifact
retrieval. The implementation work must add those two pieces before calling
the suite blocking. Until then, existing Chromium functional coverage remains
the only blocking browser gate.

## Required matrix

The initial matrix is Chromium at 390, 768, 1280, and 1600 CSS pixels across
stable public landing, documentation/blog, and Results Explorer routes. Dynamic
content must use the deterministic fixture/read-model inputs already used by
the Explorer harness. Fonts, animation, clock, and network-dependent content
must be controlled or excluded from the comparison.

## Retention and rollback

- Protected baseline artifacts: retain for at least 30 days and bind to the
  source SHA in the manifest.
- PR diagnostic artifacts: retain for 3 days, matching the existing browser
  workflow reports.
- Rollback: select the preceding successful protected-develop artifact whose
  manifest matches the base SHA; never overwrite a baseline in place.

The bootstrap exception is closed automatically after the first protected
`develop` push uploads `public-site-visual-baseline`. From then on, an exact
base-SHA lookup failure is a hard visual-gate error.
