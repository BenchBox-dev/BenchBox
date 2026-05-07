# Results Explorer Theme Inventory (2026-05-07)

Inventory and surface-model decision for
`results-explorer-retheme-theme-system-foundation` (w1 + w2). Captures the
state of `results-explorer/src` at branch
`feat/results-explorer-theme-system-foundation` so downstream retheme TODOs
have a stable reference.

## w1 — Style Inventory

### Direct surface classes (`bg-white`, `bg-gray-50/100/900`)

```text
$ rg -nc 'bg-white|bg-gray-50|bg-gray-100|bg-gray-900' src/pages src/components
```

| File | Hits |
|---|---:|
| `pages/Query.tsx` | 19 |
| `pages/BenchmarkIndex.tsx` | 18 |
| `pages/Home.tsx` | 16 |
| `components/QueryHeatmap.tsx` | 14 |
| `components/MetaLeaderboard.tsx` | 12 |
| `components/LoadingSpinner.tsx` | 11 |
| `pages/PlatformIndex.tsx` | 9 |
| `pages/ResultDetail.tsx` | 7 |
| `components/FacetRail.tsx` | 7 |
| `components/ChartPanel.tsx` | 7 |
| `components/RankTable.tsx` | 5 |
| `components/Layout.tsx` | 4 |
| `components/QueryDiffTable.tsx` | 3 |
| `pages/Compare.tsx` | 2 |
| `components/CompareSummary.tsx` | 2 |
| `components/ComparabilityReceipt.tsx` | 2 |
| `components/SparklineTable.tsx` | 1 |
| `components/RunReceipt.tsx` | 1 |
| `components/CostScatter.tsx` | 1 |
| **Total** | **141** |

### Rounded / shadow / badge primitives

```text
$ rg -nc 'rounded-lg|rounded-md|shadow-sm|badge-' src/pages src/components
```

The hottest sites: `pages/Home.tsx` (15), `pages/BenchmarkIndex.tsx` (11),
`components/TrustBadge.tsx` (11 — token site, expected),
`pages/Query.tsx` (8), `components/QueryHeatmap.tsx` (6),
`components/LoadingSpinner.tsx` (6), `components/FacetRail.tsx` (6),
`components/ComparabilityReceipt.tsx` (6).

Legacy `badge-{blue,green,yellow,red,gray}` literals: 45 occurrences across
pages and components. These collapse role distinctions (trust vs. validation
vs. computed) into raw color tiers and are the main source of badge collision
flagged by the audit.

### Native form elements

```text
$ rg -nc '<select|<input[^>]*type=.checkbox.' src/pages src/components
```

| File | Hits |
|---|---:|
| `pages/BenchmarkIndex.tsx` | 3 |
| `pages/Home.tsx` | 2 |
| `pages/Compare.tsx` | 1 |
| `pages/PlatformIndex.tsx` | 1 |
| `components/ChartPanel.tsx` | 1 |

### Borders / inline brand state

`border-gray-200` and `border-gray-300` together appear ~93 times, mostly as
ad-hoc card borders. Direct `brand-500/600/700` references on inline active
states cluster in `BenchmarkIndex.tsx` (9), `Home.tsx` (6),
`MetaLeaderboard.tsx` (5), `FacetRail.tsx` (3), `ChartPanel.tsx` (3),
`PlatformIndex.tsx` (3), `QueryHeatmap.tsx` (3) — these are the surfaces
where active/selected ambiguity was reported in the audit.

### Highest-churn files (theme work)

Pages: `Home.tsx`, `BenchmarkIndex.tsx`, `Query.tsx`, `PlatformIndex.tsx`,
`ResultDetail.tsx`, `Compare.tsx`.

Components: `Layout.tsx`, `MetaLeaderboard.tsx`, `FacetRail.tsx`,
`ChartPanel.tsx`, `LoadingSpinner.tsx`, `ErrorMessage.tsx`,
`TrustBadge.tsx`, `TuningBadge.tsx`, `RankTable.tsx`, `QueryHeatmap.tsx`,
`QueryDiffTable.tsx`, `ComparabilityReceipt.tsx`, `RunReceipt.tsx`,
`SparklineTable.tsx`, `CompareSummary.tsx`.

### Primitives downstream pages should consume

| Concern | Today | Target primitive |
|---|---|---|
| App background | `body` ⇒ `bg-gray-50` | `--bb-bg-app` token in `:root` |
| Surface card | ad-hoc `bg-white rounded-lg shadow-sm` | `<DataCard>` / `.panel` |
| Hero/filter summary | mixed `bg-white` and dark hero on Home | `.surface-hero` with dark token |
| Tabs | per-page anchor + `border-b-2` literals | `<Tabs>` |
| Segmented control | per-page `<button>` arrays | `<SegmentedControl>` |
| Buttons | `.btn-primary` / `.btn-secondary` only | `<Button variant>` |
| Native select | `<select>` | `<Select>` |
| Native checkbox | `<input type=checkbox>` | `<Checkbox>` |
| Trust/validation badge | `badge-*` literal classes | `<StatusBadge tone>` |
| Facet chip | per-page `<button>` arrays | `<FacetChip>` |
| Loading state | per-component skeletons | `<LoadingSpinner>` shell on token |
| Error state | `bg-red-50` literals | `<ErrorState>` |
| Empty state | inline copy and gray boxes | `<EmptyState>` |
| Chart control group | per-chart toolbars | `<ChartControlGroup>` shell |

## w2 — Surface Model Decision

### Decision

**Adopt the dark BenchBox shell + light analytical data panels model.**

- Global chrome (header, secondary nav, footer) and high-level brand surfaces
  (Home hero, leaderboard hero, filter summary band) use the dark BenchBox
  palette already pinned in `--bb-bg-primary` / `--bb-fg-primary` /
  `--bb-accent`.
- Dense data surfaces (tables, charts, receipts, comparison output, query
  diff, sparklines, heatmaps) sit on **restrained light analytical panels**
  using a fresh set of light tokens. This preserves information density and
  contrast for chart paint while keeping the BenchBox identity at the edges.
- "Elevated" panels (drawers, popovers, ChartPanel toolbars when active) get
  a slightly warmer light surface so they read above the base data panel
  without inventing new shadow/border noise.

### Why not the alternatives

- **Fully dark Explorer.** Rejected for the public results surface: dark
  axes/tables hurt scan speed for novice readers, and the project already
  publishes maintainer-curated comparison tables that benefit from print-like
  panels. Keeping dark only at the chrome and hero retains the brand cue
  without forcing dark-mode chart palettes everywhere.
- **Fully light Explorer.** Rejected for brand consistency with
  `benchbox.dev/docs/`, `/blog/`, and the leading marketing surfaces, which
  use the same dark chrome.

### Acceptable use of dark surfaces

- App-wide header and Explorer secondary nav.
- Footer.
- Page heroes and filter summary bands above data panels.
- Status bars or callouts inside otherwise-dark contexts.

Dark surfaces **must not** be used for dense tables, query result viewers,
chart plot areas, or compare/diff output. Those remain on light data panels
because their readability and color encoding budget rely on a near-white
canvas.

### Acceptable use of accent + status color

- Accent (`--bb-accent`): primary buttons, primary nav active state, key
  links inside dark surfaces, focus-visible ring on dark surfaces. Not for
  chart categorical encoding (charts get their own categorical scale token).
- Status (`success / warning / danger`): trust + validation tone via the
  shared `StatusBadge` only. Pages must not express the same role with
  `text-green-600`/`text-red-600` literals.

### Borders and shadows

- One border token at the data-panel level (`--bb-border-default`).
- One subtle border token for inline dividers, sticky table edges
  (`--bb-border-subtle`).
- Avoid `shadow-md`/`shadow-lg` ornament; elevation is conveyed by surface
  token, not drop shadow. `shadow-sm` is permitted only on `.panel-elevated`.

### Density expectation

Tables, sparkline rows, query timing rows, and rank tables retain their
current row height envelope. The retheme **must not** replace dense rows
with marketing-style cards on desktop sizes. Mobile breakpoints get a
separate decision in `results-explorer-retheme-responsive-accessibility`.

### Out of scope for this TODO

- Page-level rewrites. The follow-up retheme TODOs migrate routes to these
  primitives.
- New runtime design-system dependency (Radix, shadcn, etc.). The
  primitives below are thin Preact wrappers around Tailwind utility strings
  driven by the new tokens; no extra dependency is added.
