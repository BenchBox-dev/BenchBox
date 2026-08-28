---
title: "How the Results Explorer qualifies comparisons"
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, comparability, validation, duckdb-wasm]
status: DRAFTED
---

# Outline: How the Results Explorer qualifies comparisons

## Purpose

Explain the engineering behind the Results Explorer preview launched with v0.4.0. Show how the
site separates display, comparison, and ranking decisions without claiming that it certifies the
underlying results.

## Audience

- Data engineers reading public benchmark comparisons.
- Maintainers designing transparent results sites.
- BenchBox users who want to audit the published snapshot.

## Thesis

A benchmark site should not turn every timing into a winner claim. BenchBox separates results that
can be displayed, compared, and ranked; blocks winner claims when workload identity or timing
coverage fails; shows recorded differences as warnings; and leaves missing evidence visible.

## Evidence boundary

- UI and eligibility behavior: `refs/tags/v0.4.0` source.
- Corpus corrections: tagged `results-data/CORPUS_NOTES.md`.
- Current figures: deployed snapshot read on August 28, 2026.
- Architecture: released static build and public DuckDB snapshot.
- Avoid calling warnings hard comparability gates. Benchmark, scale, phase, and timing coverage
  suppress winner claims; version, environment, validation, tuning, and cost differences are
  visible warnings.

## Structure and word budget

Target: 1,800-2,200 words.

### 1. Two numbers are not yet a comparison, 180 words

- Open with two plausible timings and the questions they omit.
- Introduce the Explorer as a v0.4.0 curated preview.
- State the thesis and non-certification boundary.

### 2. The launch snapshot, 220 words

- 138 results: 134 displayable, 105 comparable, 55 rankable.
- Validation: 56 passed, 30 partial, 52 not run.
- Evidence gaps: 11 complete environment records, no recorded driver versions, 8 tuning modes.
- All rows are maintainer-run with unspecified funding.
- Uneven platform coverage. These figures are a dated snapshot, not permanent product claims.

### 3. Four decisions, 320 words

Explain admission, display, comparison, and ranking as distinct layers. Include named exclusion
reasons and one concrete example for each.

### 4. Hard gates and visible warnings, 360 words

| Check | Effect |
| --- | --- |
| Canonical benchmark, scale factor, phase | A mismatch suppresses winner and ranking claims |
| Shared valid timings and minimum coverage | Insufficient overlap suppresses the comparison claim |
| Platform or driver version | Difference is shown in the Comparability Receipt |
| Validation, environment, execution mode, tuning, cost | Recorded differences are warnings, not automatic blockers |
| Missing values | Shown as not recorded; missing-only fields do not add a warning count |

State explicitly that warnings may coexist with winner claims. The receipt helps readers judge a
comparison; it is not certification.

### 5. A static read path, 260 words

- One 8,400,896-byte DuckDB snapshot is queried by DuckDB-WASM in the browser.
- The site also publishes 138 downloadable JSON result bundles, one per launch-snapshot row, so do
  not call the whole corpus one file.
- No application API, authentication service, or database server sits in the Explorer read path.
- Static hosting, CDN, build, and publication controls still matter.
- Browser SQL is the main payoff; an attach failure appears as an error rather than an empty table.
- Describe CI performance budgets as test thresholds, not production latency measurements.

### 6. Corrections to the corpus, 360 words

- August 24: withdraw 60 zero-query DataFrame non-measurements.
- Withdraw 17 additional truthful SQL bundles to preserve the raw three-platform cohort floor;
  do not call those 17 invalid.
- August 25: normalize 52 retained bundles whose summary claimed passed or partial while the
  validation phase was not run. Preserve timings and failure records; mark validation `not_run`.
- Admission now rejects the same contradictory validation shape.
- General lesson: passing validation must require evidence that work ran.

### 7. Audit it yourself, 200 words

- Start at the Explorer root and open Query from navigation.
- Run a SQL count by `validation_status` and `is_ranking_eligible`.
- Open a result detail, inspect methodology and provenance, then download its bundle.
- Explain that rerunning provides independent corroboration, not guaranteed timing reproduction.
- Keep the CTA browse-only; invite corrections and discussion through GitHub issues.

### 8. What the preview does not establish, 140 words

- It does not cover all platforms, environments, benchmarks, or funding sources.
- It does not make hardware-different results equivalent.
- It does not certify every comparison shown.
- Close on the principle: visible gaps are more useful than false precision.

## Editorial risks

- Do not use "reliable" as an unqualified property of the results.
- Do not say the Explorer predates v0.4.0; this post treats v0.4.0 as its public preview launch.
- Do not turn receipt warnings into eligibility gates.
- Do not call 34 inventory benchmark-scale groups ranking cohorts.
- Do not describe the static architecture as a security guarantee.
- Do not claim the 17 cohort-floor withdrawals were invalid.
- Do not infer an exact implementation root cause for the zero-query validation issue.
- Do not invite submissions until public instructions are open and consistent.
