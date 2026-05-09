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

### Known coverage gaps

The regex matches *named-palette* utilities only. The following do **not**
trip the gate today:

- **Arbitrary-value classes** — `text-[#374151]` (the literal hex
  equivalent of `text-gray-700`), `bg-[rgb(55,65,81)]`, etc. A
  contributor reaching for the hex equivalent of a token bypasses the
  scan. The blind-spot scenario was named-palette literals (PR #271
  retokenized `text-gray-700`-style classes), so this is acceptable for
  the current contract; widen the regex to a `text-\[` shape if a
  future incident shows arbitrary-value bypass in the wild.
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

- **PR-time** — `.github/workflows/pr.yml` job `explorer-tokens` is gated
  in two tiers. The **outer job** runs on any PR where
  `needs.ci-paths.outputs.needs-code-ci == 'true'` (i.e., any PR in the
  code-CI tier — Python, infra, explorer, etc.). The **inner scan step**
  then `git diff`s against the base ref and only invokes
  `make lint-explorer-tokens` when at least one path under
  `results-explorer/src/` changed. The aggregator at
  `pr.yml`'s `ci-required-result` job treats `success` and `skipped` for
  this check as passing; `failure` blocks the PR. The two-tier shape
  exists because `ci-paths` does not yet emit an `explorer-paths-needed`
  output, so the cheapest available correctness gate is to spin the
  outer job on every code-CI PR and have its inner step diff-check the
  paths. The `explorer-tokens-path-classifier-output` TODO collapses
  this to a single tier by promoting `explorer-paths-needed` into the
  `ci-paths` classifier output, after which the outer job can be gated
  directly on the path predicate and skip cleanly when no
  `results-explorer/src/` files changed.
- **Post-merge** — `.github/workflows/develop-post-merge.yml` job
  `explorer-tokens` runs unconditionally on every push to develop and
  re-runs the gate against the merged develop tree so that a squash
  race that reintroduces literals trips the auto-revert path even when
  each PR-time scan passed against its own pre-merge tree.

## What happens when the post-merge gate trips

The post-merge `explorer-tokens` job feeds three downstream consumers in
`.github/workflows/develop-post-merge.yml`:

1. **`auto-revert-on-failure`** — `if:` includes
   `needs.explorer-tokens.result == 'failure'`. When red, it opens an
   auto-revert PR on the offending squash commit, applies the
   `incident:develop-red` label, and adds the original PR's author as a
   reviewer. Conflicts on the revert open a tracking issue with
   `incident:develop-red-revert-conflict`. **The auto-revert is a PR,
   not a direct push** — landing the revert still requires explicit
   merge.
2. **`metrics`** — the `post_merge_red` shell flag flips true; the
   `develop_red_detected_at` jq filter selects the earliest
   `completed_at` across `lint`, `fast-test`, and `explorer-tokens` as
   the red-detection timestamp.
3. The dev-loop metrics row is emitted to the `metrics` artifact under
   `dev-loop-metrics/<sha>.json`.

### When the gate is wrong (false positive)

If the regex flags a legitimate literal at an inopportune moment (e.g.,
3am hotfix, a docs/comment string that happens to spell a Tailwind
token), the on-call workflow is:

1. **Close the auto-revert PR** if one was opened — the `incident:develop-red`
   label makes it discoverable via `gh pr list --label incident:develop-red`.
2. **Allowlist the line** with `// allow-explorer-token-literal: <reason>`
   (or the `/* … */` form for CSS), where `<reason>` is concrete enough
   that a reviewer six months from now can decide whether to remove the
   marker. The marker regex (`ALLOW_MARKER_RE`) only requires a
   non-empty reason; for hotfix allowlists, the team convention is
   `hotfix-YYYY-MM-DD followup-needed-issue-NNN` so a sweep can find
   them later — but the format is not enforced by the gate.
3. **File a regex-fix TODO** under `_project/TODO/main/planning/`
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

The scan lives at `_project/scripts/scan_explorer_tokens.py`. Edit the
`UTILITIES`, `PALETTES`, and `STOPS` tuples to widen or narrow coverage.
The Makefile target is `lint-explorer-tokens`. If a future ESLint/stylelint
graduation lands (see TODO `results-explorer-token-scan-ci-gate`), retire
this script in the same PR that wires the new rule into `npm run lint`.
