# Brand Ownership Decision: Results Explorer

**Decision**: BenchBox placement at `benchbox.dev/results/`
**Date**: 2026-04-03
**Status**: Resolved

## Context

The results explorer needed a brand placement decision before launch: should it live at
`benchbox.dev/results/` under the BenchBox brand, or under a separate Oxbow Research
brand? The strategy memo carried a "working default" of BenchBox placement pending this
resolution.

## Research Findings

Git history and codebase search show that Oxbow Research was an earlier brand concept
that has been actively cleaned out of the BenchBox repository:

- `refactor: move Oxbow Research content to dedicated repository` - Oxbow Research
  content was moved to a separate repo, deliberately decoupled from BenchBox.
- `docs(blog): remove Oxbow references; add BenchBox-only PUBLICATION_SCHEDULE` - All
  Oxbow references were removed from the blog and replaced with BenchBox-only content.
- `chore(todo): remove 8 Oxbow blog TODO items` - Eight Oxbow-focused blog TODOs were
  deleted, not reassigned.
- `fix(blog): correct GitHub org in links (Oxbow-Research -> joeharris76)` - GitHub
  org links were corrected away from an Oxbow Research org to the owner's personal
  account.

Oxbow Research has no independent web presence, no domain registration, no product
positioning, and no active identity within this codebase. It was a parallel brand
concept that has been superseded by BenchBox as the primary public identity.

## Tradeoffs Evaluated

### BenchBox placement (`benchbox.dev/results/`)
- Pro: Integrated with the tool's brand - results are produced by BenchBox, so housing
  them under `benchbox.dev` is coherent and self-reinforcing.
- Pro: Single domain, simpler deployment - no second hosting property to configure,
  maintain, or keep in sync with the CI/CD pipeline.
- Pro: Traffic driven by the explorer reinforces the BenchBox brand and drives
  tool adoption.
- Pro: Consistent with Phase 1 strategy (static GitHub Pages, zero backend services) -
  the Vite app outputs to `site/results/` without additional infrastructure.
- Pro: Aligns with how ClickBench, js-framework-benchmark, and CloudSpecs all work:
  the tool and the public results live under one identity.
- Con: Explorer is tied to BenchBox's scope - if Oxbow Research ever becomes a distinct
  analytical research brand with its own domain, migrating URLs would require redirects.

### Oxbow Research placement
- Pro: Broader potential positioning - could encompass results from tools other than
  BenchBox, or research that is not benchmark-specific.
- Con: Oxbow Research has no current domain, web presence, or product identity. Building
  under this brand requires creating that identity from scratch before launch.
- Con: Split brand awareness - two separate properties to promote, two audiences to
  build, no natural cross-traffic between tool users and results readers.
- Con: Additional infrastructure - a second GitHub Pages site or separate hosting
  property, separate CI/CD, separate navigation.
- Con: The explorer's primary value is reproducibility: visitors can re-run any result
  with `benchbox run`. That value proposition is incoherent under a brand that is not
  BenchBox.
- Con: Git history shows Oxbow Research has been actively separated from BenchBox - any
  placement there would reverse a deliberate architectural decision.

## Decision Rationale

The working default of BenchBox placement is confirmed. Oxbow Research does not have
the web presence, product identity, or active development investment to serve as a
launch destination. More importantly, placing the results explorer under BenchBox is
the coherent choice: the explorer's core value proposition (reproducible results,
`benchbox run` re-execution) is inseparable from the BenchBox brand. Splitting them
would weaken both.

The risk of future URL migration is acceptable. If Oxbow Research ever develops into
a distinct brand with its own domain and audience, redirects from `benchbox.dev/results/`
are straightforward. Starting under a non-existent brand to avoid future redirects
would be premature optimization.

## Downstream Impact

- **Domain/URL**: `benchbox.dev/results/` - confirmed, no changes needed to existing
  scaffolding or implementation TODOs.
- **CI/deployment**: No changes needed. The existing GitHub Pages workflow that copies
  `results-explorer/dist/` to `site/results/` remains the target architecture.
- **Navigation**: Add "Results" link to the shared `benchbox.dev` site header/nav, as
  already planned in the strategy memo.
- **Visual identity**: BenchBox design system (header, nav, styling) - consistent with
  the strategy memo's existing direction.
- **Phase 2+ submission model**: Contributions go to the BenchBox repository via PR;
  trust labels read "maintainer" and "community", both under the BenchBox umbrella.
