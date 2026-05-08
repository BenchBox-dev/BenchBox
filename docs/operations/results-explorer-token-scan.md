# Results Explorer — Token-Scan Gate

The Results Explorer retheme moves every public surface onto CSS-variable
tokens defined in `results-explorer/src/index.css`. This gate keeps the
contract durable: a PR that reintroduces a raw Tailwind palette literal
(`text-gray-700`, `bg-blue-500`, `border-red-300`, …) under
`results-explorer/src/` breaks CI rather than ships silently.

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

Files scanned: `*.tsx`, `*.ts`, `*.jsx`, `*.js`, `*.css`, `*.html` under
`results-explorer/src/`.

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

- **PR-time** — `.github/workflows/pr.yml` job `explorer-tokens` runs when
  `results-explorer/src/` is in the PR diff. It is a required
  `ci-required-result` input.
- **Post-merge** — `.github/workflows/develop-post-merge.yml` job
  `explorer-tokens` re-runs the gate against the merged develop tree so
  that a squash race that reintroduces literals trips the auto-revert
  path even when each PR-time scan passed against its own pre-merge tree.

## Extending or removing the gate

The scan lives at `_project/scripts/scan_explorer_tokens.py`. Edit the
`UTILITIES`, `PALETTES`, and `STOPS` tuples to widen or narrow coverage.
The Makefile target is `lint-explorer-tokens`. If a future ESLint/stylelint
graduation lands (see TODO `results-explorer-token-scan-ci-gate`), retire
this script in the same PR that wires the new rule into `npm run lint`.
