# BenchBox Light/Dark Theme Contract

Date: 2026-05-14
Scope: landing, prompts, docs/blog, and Results Explorer public surfaces.

This supersedes the previous Results Explorer mixed-theme-only contract. The
product contract is now a shared three-choice preference (`system`, `light`,
`dark`) whose effective light or dark theme applies across every public
surface.

## Inventory

| Surface | Prior theme assumptions | New owner |
|---|---|---|
| `landing/index.html` and `landing/prompts/index.html` | Dark-first variables in page CSS, hard-coded header colors, gradient glows, cards, badges, inline code, and copy buttons. | `landing/shared/site-theme.css` plus page-level semantic aliases. |
| `docs/` and `blog/` | Furo owned a separate light/dark contract while the custom BenchBox nav stayed dark; `docs/_static/custom.css` kept raw Cobalt2 code, table, admonition, and blog colors. | Shared BenchBox theme preference mapped to Furo `data-theme`; docs CSS consumes shared semantic variables. |
| Results Explorer | `results-explorer/src/index.css` mixed dark shell and light analytical panels by design; charts and SVG labels used fixed light hex colors; tests pinned the mixed contract. | `results-explorer/src/lib/theme.ts`, `results-explorer/src/index.css`, and `results-explorer/src/lib/chartTheme.ts`. |
| Shared header | Three implementations could drift across static pages, docs/blog, and Results. | One visible header contract with `data-benchbox-theme-toggle` and `--bb-site-header-*` variables. |

## Theme Choice

| Concern | Contract |
|---|---|
| Values | `system`, `light`, `dark`. |
| Persistence | Explicit `light` or `dark` choices are stored in `localStorage` under `benchbox:theme`; `system` removes that key. |
| Effective theme | `system` resolves through `prefers-color-scheme`; explicit choices override system preference. |
| First paint | Static pages, docs/blog templates, and Results Explorer index apply `data-bb-theme-choice`, `data-bb-theme`, and `data-theme` in the document head before loading app code. |
| Runtime sync | `landing/shared/site-theme.js` and `results-explorer/src/lib/theme.ts` update the same attributes and dispatch the same persisted choice. |
| Furo | BenchBox maps the preference onto Furo's `data-theme` contract and hides Furo's independent toggle so docs/blog do not expose two unsynchronized controls. |

## Token Families

| Token family | Static site/docs source | Results source |
|---|---|---|
| App/page background | `--bg-primary`, `--bg-secondary`, `--bg-tertiary` | `--bb-surface-app`, `--bb-surface-data`, `--bb-surface-data-muted` |
| Text | `--text-primary`, `--text-secondary`, `--text-muted` | `--bb-data-fg-primary`, `--bb-data-fg-muted`, `--bb-data-fg-subtle` |
| Header/shell | `--bb-site-header-*` | same names in `results-explorer/src/index.css` |
| Borders/elevation | `--border-primary`, `--border-secondary`, `--card-shadow` | `--bb-data-border`, `--bb-data-border-strong`, `--bb-surface-elevated` |
| Status | `--info-color`, `--success-color`, `--warning-color`, `--danger-color`, `--neutral-color` | `--bb-tone-*`, `--bb-status-*` |
| Code/docs | `--code-bg`, `--code-fg`, `--code-border`, `--code-accent`, `--code-line-number` | `--bb-code-bg`, `--bb-code-fg` |
| Tables/sticky surfaces | `--table-header-bg`, `--table-row-alt-bg` | `--bb-surface-sticky`, `--bb-data-border-*` |
| Charts | none on static pages | `--bb-chart-axis`, `--bb-chart-grid`, `--bb-chart-label`, `--bb-chart-tooltip-bg`, categorical/sequential/diverging chart variables |

Dark mode is first-class for Results analytical surfaces: data panels, sticky
tables, heatmaps, chart axes, chart labels, chart tooltips, empty states,
warning states, and loading skeletons use dark tokens instead of light islands.

## Regression Gates

- `make lint-explorer-tokens` scans `results-explorer/src/` for raw Tailwind
  palette classes, arbitrary color classes, SVG hex literals, and `rgb()` /
  `rgba()` literals outside token definitions.
- `make lint-site-theme-tokens` scans the static header/theme surfaces,
  landing pages, docs template, docs custom CSS, and the Results header shell.
- `tests/unit/test_site_header_parity.py` verifies the shared header links,
  theme assets, and theme toggle are present across landing, prompts,
  docs/blog, and Results.
- Results Vitest and Playwright checks verify the persisted theme choice,
  route survival, and light/dark visible colors.

## Decisions

- Use one visible BenchBox theme control in the shared global header.
- Keep `system` as the first-visit default and as an explicit reset state.
- Let Furo continue rendering docs/blog layout, search, sidebars, code blocks,
  tables, admonitions, tags, and archives, but drive its theme through the
  shared BenchBox attributes.
- Keep chart categorical colors stable across tabs while moving axis, grid,
  text, tooltip, faster/slower, and status fills behind CSS variables.
