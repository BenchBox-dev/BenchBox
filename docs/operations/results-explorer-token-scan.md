# Results Explorer — Token-Scan Gate

The Results Explorer retheme moves public surfaces onto CSS-variable tokens
defined in the single shared token file `landing/shared/site-tokens.css`
(consumed by `website/`, the Results Explorer and the landing page) and the
legacy static theme at `landing/shared/site-theme.css`. This gate keeps the contract durable: a PR
that reintroduces a raw Tailwind palette literal (`text-gray-700`,
`bg-blue-500`, `border-red-300`, …), arbitrary color literal, SVG hex color,
or raw `rgb()` / `rgba()` value breaks CI rather than ships silently.

## Why the gate exists

PR #268 introduced new literal-styled "Result summary", `ResultMetricCard`,
and Compare guardrails sections during the same window PR #269 was
finalizing its release-readiness report. The squash merge of #269 silently
kept those literals because both the per-PR token scan and the
release-final capture were generated against the PR branch, not the
post-merge develop tree. PR #271 closed the regression manually and raised
the L2 framework-gap blind-spot
`_project/blind-spots/2026-05-07-211858-release-readiness-against-pre-merge-tree.md`.
This gate is the durable answer to that gap: it runs on every PR touching
`results-explorer/src/` and on the post-merge develop tip, so concurrent-PR
regressions break CI before they ship.

## Running locally

```bash
make lint-explorer-tokens
make lint-site-theme-tokens
```

The scan is stdlib-only Python; no `uv sync` is required before it runs.

## What the gate flags

A regex match for any combination of:

- **utility prefixes** — `text`, `bg`, `border`, `divide`, `ring`,
  `placeholder`, `fill`, `stroke`, `outline`, `shadow`
- **palettes** — `slate`, `gray`, `zinc`, `neutral`, `stone`, `red`,
  `orange`, `amber`, `yellow`, `lime`, `green`, `emerald`, `teal`, `cyan`,
  `sky`, `blue`, `indigo`, `violet`, `purple`, `fuchsia`, `pink`, `rose`
- **stops** — `50`, `100`, `200`, `300`, `400`, `500`, `600`, `700`,
  `800`, `900`, `950`
- **arbitrary color classes** — `text-[#374151]`,
  `bg-[rgb(55,65,81)]`, `stroke-[rgba(...)]`
- **raw color functions / SVG literals** — `#374151`, `#374151cc`,
  `rgb(...)`, `rgba(...)`

Files scanned: `*.tsx`, `*.ts`, `*.jsx`, `*.js`, `*.css`, `*.html` under
`results-explorer/src/` for `make lint-explorer-tokens`. The
`make lint-site-theme-tokens` target runs the same scan over the static
theme/header pages and docs adapter CSS:

- `landing/shared/`
- `landing/index.html`
- `landing/style.css`
- `landing/prompts/index.html`
- `landing/prompts/prompts.css`
- `docs/_templates/page.html`
- `docs/_static/custom.css`
- `results-explorer/index.html`
- `results-explorer/src/components/Layout.tsx`

### Known coverage gaps

The scan now covers the previously documented arbitrary-value and raw SVG
literal gaps. The following still do **not** trip the gate today:

- **Concatenated classnames** — `"text-gray-" + n` or
  `` `text-${color}-700` `` are not matched (the regex needs a literal
  contiguous token).

## Allowlisting an intentional literal

Append an inline marker on the same line as the literal:

```tsx
// JS / TS / TSX / JSX
<div class="text-gray-700" /> // allow-explorer-token-literal: third-party widget skin
```

```css
/* CSS */
.legacy-badge { color: theme('colors.gray.700'); } /* allow-explorer-token-literal: legacy alias retained for badge migration */
```

The marker requires a non-empty reason. Lines without a reason still trip
the gate.

Prefer adding a CSS variable token (`var(--bb-...)`) over allowlisting.
The allowlist is for legitimate exemptions only — third-party widget
skins, deliberate palette exports for design tooling, and similar.

## CI wiring

`.github/workflows/ci.yml` job `explorer-tokens` runs on a pull request where
the `ci-paths` classifier sets
`explorer-paths-needed`, which is the `explorer-tokens` group in
`.github/path-filters.yml` (a change under `results-explorer/src/`). It runs
`make lint-explorer-tokens`. The shared site theme has its own
`site-theme-tokens` job in the `landing` unit. The job is
part of the `explorer` unit in `.github/ci-units.yml`, so `explorer` fails when
the scan fails and, because a skipped required job also fails its unit, when
the scan is skipped while its paths changed. The scan validates the pull request
head; with the queue retired, it is not repeated on the composed tree. The
post-merge trunk suite does not run this token scan, so a squash race that
reintroduces literals is not covered by a second scan.

### When the gate is wrong (false positive)

If the regex flags a legitimate literal at an inopportune moment (e.g.,
3am hotfix, a docs/comment string that happens to spell a Tailwind
token), the on-call workflow is:

1. **Allowlist the line** with `// allow-explorer-token-literal: <reason>`
   (or the `/* … */` form for CSS), where `<reason>` is concrete enough
   that a reviewer six months from now can decide whether to remove the
   marker. The marker regex (`ALLOW_MARKER_RE`) only requires a
   non-empty reason; for hotfix allowlists, the team convention is
   `hotfix-YYYY-MM-DD followup-needed-issue-NNN` so a sweep can find
   them later — but the format is not enforced by the gate.
2. **File a regex-fix TODO** under `_project/TODO/main/planning/`
   (`category: Bug`) describing the false-positive shape, so the
   allowlist can be removed once the regex is tightened. Use
   `_project/scripts/scan_explorer_tokens.py` as the single source of
   truth — adjust `UTILITIES`, `PALETTES`, `STOPS`, or `LITERAL_RE`
   itself.

The gate is intentionally conservative: matching a literal in a comment
or string is the documented contract (see
`tests/unit/scripts/test_scan_explorer_tokens.py::test_literal_re_matches_inside_comments_and_strings_by_design`).
The allowlist is the operational answer.

## Extending or removing the gate

The scan lives at `_project/scripts/scan_explorer_tokens.py`. Edit
`UTILITIES`, `PALETTES`, `STOPS`, `ARBITRARY_COLOR_RE`, `HEX_RE`, or
`RGB_RE` to widen or narrow coverage. The Makefile targets are
`lint-explorer-tokens` and `lint-site-theme-tokens`. If a future
ESLint/stylelint graduation lands (see TODO
`results-explorer-token-scan-ci-gate`), retire this script in the same PR
that wires the new rule into `npm run lint`.
