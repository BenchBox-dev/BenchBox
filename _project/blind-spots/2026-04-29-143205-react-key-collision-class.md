---
id: 2026-04-29-143205-react-key-collision-class
date: 2026-04-29
status: open
finding_kind: bug-class
review_context: "ultrareview B4 / dashboard chart key collisions"
related_paths:
  - benchbox/dashboard/charts/TimeSeries.tsx
  - benchbox/dashboard/charts/PercentileLadder.tsx
suggested_sweep: "grep for React keys derived from non-unique fields across all chart components before declaring the class fixed"
todo_id: null
---

# Symptom-vs-Class Axis Missing from 5-Axis Review Framework

## Finding

The five-axis framework misses one issue specific to symptom-vs-class fixes:
whether the fix addresses the bug class or just the reported instance. B4 was
reported on TimeSeries, but the underlying class is "React key uses a
non-unique field that the dataset's batch nature can collide." That class
shows up at least once more in PercentileLadder. Fixing only TimeSeries
leaves the same defect ready to fire on the next dataset where two DuckDB
rows share a platform name. C1 captures this; the framework's "Architecture"
axis would have given a 9 if I hadn't widened the lens. Worth recording as a
habit: when a key-collision bug surfaces, always sweep the file tree for
sibling instances before declaring the class fixed.

## Why this matters

Reviews driven by a fixed-axis rubric will systematically under-weight
defects whose blast radius is "this class of bug, anywhere it shows up"
rather than "this file's behavior." A high score on the existing axes can
co-exist with an entire class of bugs left intact in sibling files. This is
not specific to React keys — it applies anywhere a fix targets a single
call-site of a generalizable defect.

## Suggested next steps

- [ ] Add a "bug-class blast radius" check to the review framework, used
      when the finding is structural rather than behavioral.
- [ ] Sweep all chart components under `results-explorer/src/components/`
      for React keys derived from non-uniqueness-guaranteed fields
      (platform name, query id, etc.) and convert to composite or stable
      IDs. Live candidates: `DivergingBarChart` (`<g key={queryId}>`),
      `RankTable` (`<tr key={qid}>`), `QueryHeatmap` (`<… key={qid}>` /
      `<… key={row.result_id}>`), `StackedPhase`, `CostScatter`. Use
      `git grep "key={" results-explorer/src/components/` as the seed.
- [ ] When a sweep is done, link the resulting TODO/PR back here and
      flip `status:` to `merged-to-todo`.

## Triage log

- 2026-05-02: verified actionable. The reviewed components moved from
  `benchbox/dashboard/charts/` to `results-explorer/src/components/`
  (the `benchbox/dashboard/` tree no longer exists). The two cited
  files now carry explicit comments warning against
  `key={date}` (TimeSeries.tsx:36-37) and `key={platform}`
  (PercentileLadder.tsx:23) collisions, so the *original* instances
  are mitigated. The broader bug-class sweep across all chart
  components has NOT been performed — `git grep "key={"
  results-explorer/src/components/` returns ~30 hits including
  `key={queryId}` / `key={qid}` patterns whose uniqueness is not
  obvious without per-call analysis.
