# Astro spike report

Date: 2026-10-03
Status: GO, approved under standing approval S1 of the
[Astro site ADR](adr-astro-unified-site.md). See [Approval](#approval).

## Recommendation

GO. Starlight runs inside a custom shared shell (D6 resolved: no custom docs
layout). Move CI and `website/` to Node 22 (D10 follow-up, as the ADR allows).

## What was built

The spike is in `website/`. It is not wired into CI.

- **Stack:** Astro 7.3.5 and Starlight 0.42.5, all dependencies pinned exactly,
  with a lockfile and `build.format: 'file'`.
- **Content:** a content loader reads `docs/` at build time, so no copies are
  committed (D4).
- **Conversion:** a remark plugin handles the MyST subset the samples use, and
  docutils converts the one `.rst` sample.
- **Shared shell:** header, theme toggle and search, with three Starlight
  component overrides.
- **Tooling:** a Pages-like local server and a Playwright and axe harness, both
  spike tooling for item 20 to replace.

## Scope points

| # | Scope | Result | Evidence |
| --- | --- | --- | --- |
| 1 | `docs/benchmarks/industry-benchmarks.rst` with toctree and `:doc:` | Built at its URL | Needed `toctree`, `tags` and `:doc:` handlers; list of converter handlers below |
| 2 | `docs/usage/getting-started.md` | Built at its URL | docutils-style heading ids were needed to keep 7 fragments |
| 3 | Blog post `2026-05-18-v0-3-0-release-overview` | Built at `/blog/2026-05-18-v0-3-0-release-overview.html` | ablog sidebar and the Atom feed were not attempted (item 33) |
| 4 | Authored API contract page | Built at its real URL `/docs/reference/python-api/additional-utilities.html`; `#benchbox.utils.scale_factor.format_scale_factor` resolves | Only that symbol is authored, so the page's other 56 content ids are absent until item 34 |
| 5 | Generated query page | `/docs/benchmarks/queries/tpch/q1.html` | Needs the generator run as its own step (item 32) |
| 6 | Landing hero | Built at `/`, same copy | Only the hero was in scope. The full page's 10 section ids (`install`, `features`, `benchmarks` and others) must be kept by item 35. The Prism CDN is dropped (G-g), so the hero code has no highlighting yet |
| 7 | Explorer at `/results/` with deep links | Pass | Built in CI order and copied unchanged; `404.html` carries the same deep-link fallback |
| 8 | Shared header and theme | Pass | Key `benchbox:theme`, same values and writes as `landing/shared/site-theme.js` and the Explorer; a dark choice carries across docs, landing and Explorer |
| 9 | Back/forward, worker and WASM in Chromium | Pass, including docs → `/results/` → back → forward and Explorer-internal navigation | Back/forward kept URL, title and scroll; `/results/platforms/` and query-string URLs restored; DuckDB WASM, worker and snapshot loaded with no page errors |
| 10 | Pagefind over docs and blog | Pass | Indexed docs and blog only (5 sample pages); loaded only when search opens (279 KB) |

## Narrow screens

The shared header wraps to two rows below 40rem. At 320, 375 and 1280 px, all
six sample pages have:

- no horizontal overflow;
- no overlapping header controls and none outside the viewport;
- zero serious or critical axe findings in light and dark themes.

At 375 px the theme control works by click and by arrow keys, and Starlight's
menu button opens the sidebar. Wide tables wrap instead of scrolling, which
fixed an axe `scrollable-region-focusable` finding.

## Explorer suites

The Explorer source is unchanged in the spike.

- **Unit tests:** `npm run typecheck` is clean, and `npm test -- --run` gives
  1,673 passed and 8 skipped in 110 files.
- **Chromium end-to-end, local:** 177 passed, 13 skipped and 4 failed.
  - Two of the failures passed on re-run.
  - One needs mounted external-corpus data (`@uat-external-corpus`).
  - One (`accessibility-regressions.spec.ts:5`) failed again locally. This
    runner has Chromium build 1194, while Playwright 1.63 expects 1243.
- **What this shows:** the Explorer source is byte-identical to develop, so
  these local results are develop's own behaviour in this runner, not a
  regression from the spike.
- **Not shown:** CI's blocking Chromium job runs only on PRs that change the
  Explorer, so it did not run here. Item 40, which does change the Explorer
  shell, must pass it.

## Clean-checkout build

A scratch worktree containing only tracked and unignored files builds once two
prerequisites exist: the generated query pages
(`scripts/generate_query_docs.py`) and `results-explorer/dist`. Item 20's CI
job runs both first; item 32 makes the generator an explicit step.

## Measurements

On a 4-core runner:

| Measure | Result |
| --- | --- |
| Sphinx full build, same machine | 11 min 49 s for 1,915 pages, about 0.37 s per page |
| Astro, 7 sample pages | 3.7–4.1 s, mostly fixed start-up cost |
| Astro, 1,256 pages (the generated query pages) | 39–41 s, about 28 ms per page |
| HTML, JS and CSS per docs page, gzip | 19.8–26.9 KB |
| Docs and blog requests to Explorer or DuckDB | 0 (every request listed in the harness output) |
| axe serious or critical, light and dark, 6 pages | 0; 2 moderate `landmark-unique` from code blocks |
| Sample routes in the inventory diff | All present at their exact URLs. Lost ids are theme ids only, except the partially authored API page and the hero-only landing page (above). |
| `npm audit --audit-level=high` | 5 findings, all from `http-cache-semantics` (see mitigation) |

**Build-time caveats.**

- **Sample:** the 1,256-page sample covers generated query pages only. The
  hand-written pages are larger.
- **RST conversion:** it ran one process per file. The 53 `.rst` files add
  about 12 s, and item 30 removes the cost by converting them.
- **Explorer data:** the Astro build also needs the Explorer build (about
  2 min 17 s of data publishing plus the Vite build), which the Sphinx docs
  step does not.
- **Sphinx timing:** Sphinx ran beside other work, but its user time (11 min
  31 s) is close to its real time, so the comparison holds.

Even with these costs the margin is large: 28 ms against 370 ms per page.

**Inventory caveats.**

- **Theme ids:** the sample pages lose only theme ids, by these patterns:
  `svg-*`, `toctree-checkbox-*`, `__navigation`, `__toc`, `searchbox`,
  `furo-main-content`, `benchbox-site-header-nav` and `post-meta-data`. The
  parity harness (item 50) must allow them by pattern, as the ADR's site
  inventory section requires.
- **Titles:** page titles change from "… - BenchBox 0.4.1 documentation" to
  "… | BenchBox". This is an intended change.
- **Headings:** Starlight adds an "On this page" heading, and ablog's sidebar
  headings are gone. Both are intended changes for item 50 to list.
- **Broken links:** every broken link points to a page outside the spike's
  sample.

## Go criteria

| Criterion | Met | Evidence |
| --- | --- | --- |
| Exact URL preservation achievable | Yes | `.html` URLs match for every sample route, including the API page at `additional-utilities.html`. |
| Zero axe serious or critical | Yes | 0 in 12 themed runs (6 pages, light and dark) and in every reflow run at 320, 375 and 1280 px |
| Build time no worse than the Sphinx docs build | Yes | About 28 ms against 370 ms per page |
| Explorer needs only shell extraction and config edits | Yes, by inspection | The Explorer ran unchanged at `/results/`, deep links included. The global header is in `results-explorer/src/components/Layout.tsx`, which wraps the router; pages and data code do not render it. The shell swap is reasoned from the code, not yet performed (see below). |

## Starlight overrides (D6)

- **Overridden:** `Header` (shared shell header), `PageTitle`, `Footer`
  (shared shell footer), `ThemeProvider` (the `benchbox:theme` script) and
  `ThemeSelect` (empty; the header owns the toggle). Starlight's built-in
  Pagefind and 404 route are off.
- **Unchanged:** the sidebar, table of contents, mobile menu and page frame.
- **Friction:**
  - Starlight styles sit in CSS layers, so shell rules are scoped with
    `:where(.shell)`.
  - Nested `<header>` elements caused landmark errors, fixed in the override.
  - Two token pairs failed contrast until remapped.

None of this needs a custom docs layout.

## Findings for later items

- **D10:** Astro 7 requires Node 22.12 or later. Item 20 moves `website/` and the
  site CI job to Node 22. The required-check jobs stay as they are unless they
  build `website/`.
- **G-h deviation, accepted:** `http-cache-semantics` up to 4.2.0
  (GHSA-ch52-4w7c-c8xp) is a direct dependency of `astro`, and no fixed release
  exists.
  - **Reachability:** `astro` uses it only in `dist/assets/build/remote.js`,
    the build-time cache for remote images. The site uses no remote images, and
    the package never reaches the served output.
  - **Why the Explorer precedent does not fully carry over:** `astro` is a
    production dependency, so `--omit=dev` does not clear it as it did for the
    Explorer's `braces` entry.
  - **Plan:** item 20 applies the Explorer's self-expiring allowlist gate
    (`results-explorer/scripts/audit-high.mjs`) to `website/`. The entry carries
    this reasoning, a review date and the advisory link, and it fails once a
    fixed release exists.
  - **Acceptance:** the approver accepts this as a recorded G-h deviation.
- **Converter handlers for items 30 and 31:**
  - `toctree` with `maxdepth`, `caption`, `hidden`, globs and `self`;
  - `tags`;
  - the roles `:doc:`, `:ref:` and the `:py:` roles;
  - `list-table`, `code-block`, admonitions and sphinx-design cards and tabs;
  - docutils-compatible heading ids, including numbered duplicates.
- **Markdown processing:** Astro 7's default processor does not run remark
  plugins, so the loader uses `@astrojs/markdown-remark` directly. That relies
  on the content-layer `rendered` API.
- **Extra output:** Starlight emits a sitemap because `site` is set; item 36
  decides it.
- **Explorer header coupling, for item 40:**
  - Beyond `Layout.tsx`, the header depends on `components/headerContract.ts`, `lib/theme.ts` and the footer theme radio group.
  - It is pinned by `Layout.test.tsx` and by the e2e specs `header.spec.ts`, `print.spec.ts` and `safe-area.spec.ts`.
  - The spike header drops the Explorer's Home, GitHub and call-to-action links, which `header.spec.ts` enforces. Item 40 decides header-link parity and updates those tests and the contract in the same change.
  - All of this is shell code; no query, metric or admission code is involved.

## Approval

- Approver: coordinating session
  <https://claude.ai/code/session_01GZSaWtTiCz9etgrhYRuVzu>, 2026-10-03.
- Independent review: a reviewer subagent that did not build the spike, 2026-10-03.
  Round 1 failed with 2 High findings (an ignored source file, narrow-screen
  header) and Medium and Low findings; all were fixed. Round 2: PASS, no Critical
  or High findings; its two text corrections are applied.
- Accepted deviations:
  - G-h: the `http-cache-semantics` advisory (see Findings).
  - Explorer suites: typecheck and unit tests are green, but one local Chromium
    end-to-end test fails on this runner's older browser build. The Explorer
    source is unchanged, so this does not block GO. Item 40 must pass CI's
    required Chromium job.
