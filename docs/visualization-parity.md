# Visualization Parity - CLI↔Explorer Contract

BenchBox has two visualization layers that must produce identical numbers:

| Layer | Location | Language |
|-------|----------|----------|
| CLI charts | `benchbox/core/visualization/ascii/` | Python |
| Explorer charts | `results-explorer/src/components/` | TypeScript/Preact |

The parity infrastructure ensures these never drift apart.

## Contract files

Fixtures live in `tests/parity/fixtures/` and are **checked into git**.
Each file is a JSON contract for one chart math helper:

| Fixture | TS helper | Python reference |
|---------|-----------|-----------------|
| `heatmap_color.json` | `colorForCell` | `benchbox/core/visualization/ascii/heatmap.py` |
| `lightness_for_cell.json` | `lightnessForCell` | same |
| `speedup_ratio.json` | `speedupRatio` | `benchbox/core/visualization/ascii/normalized_speedup.py` |
| `delta_pct.json` | `deltaPct` | `benchbox/core/visualization/ascii/diverging_bar.py` |
| `sort_by_magnitude_desc.json` | `sortByMagnitudeDesc` | same |
| `per_query_speedup.json` | `perQuerySpeedup` | N/A - no Python CLI chart; originated in `Compare.tsx`, unified via `chartMath.ts` |
| `geomean_ms.json` | `geomeanMs` | `_project/scripts/explorer_pipeline/transformer.py` `_display_geomean_ms` |
| `box_stats.json` | `computeBoxStats` | `_project/scripts/explorer_pipeline/transformer.py` `_compute_box_stats` |
| `cdf_ecdf.json` | `computeECDFPoints` | `_project/scripts/explorer_pipeline/transformer.py` `_compute_ecdf` |
| `rank_table.json` | `computeRankTable` | `_project/scripts/explorer_pipeline/transformer.py` `_compute_ranks` |
| `percentile_ladder.json` | `computePercentile` | `_project/scripts/explorer_pipeline/transformer.py` `_compute_percentile` |

## Policy

**New chart types are added to `chart_types.py` first; the explorer follows.**

When you add a new chart type:
1. Register it in `benchbox/core/visualization/chart_types.py`.
2. Add the corresponding Python math helper to `generate_visualization_fixtures.py`.
3. Run `make parity-fixtures` to regenerate fixtures.
4. Implement the TS helper in `results-explorer/src/lib/chartMath.ts`.
5. Add cases to the Vitest parity suite (`chartMath.parity.test.ts`).
6. CI runs `make parity-check` + Vitest on every PR to catch drift.

## Workflow for changing a computation

If you change how a number is calculated (either Python or TS side):

```bash
# 1. Modify the Python implementation
# 2. Regenerate fixtures - this changes the contract:
make parity-fixtures

# 3. Run parity-check to confirm fixtures now match
make parity-check

# 4. Run Vitest - new fixture values must pass the TS side too
cd results-explorer && npm test -- chartMath.parity

# 5. Commit the fixture diff - reviewers must approve the numeric change
git add tests/parity/fixtures/
```

**Never regenerate fixtures silently.** The diff is part of the review.

## Verifying parity without regenerating

```bash
make parity-check      # Python side: regenerate into tmpdir, diff, fail if different
cd results-explorer && npm test -- chartMath.parity   # TS side: all fixture cases pass
```

## Float tolerance

The Vitest suite uses `Math.abs(result - expected) < 1e-9`.
Python and JavaScript IEEE-754 agree at this precision for the formulas used
here (log10, exp, division). If you add a formula where the tolerance is
insufficient, document it in the fixture case and increase the tolerance
in `assertParity()` for that specific case only.

## Null handling

Python `None` maps to JSON `null`, which TypeScript receives as `null`.
Every helper has at least one null-input case in its fixture. The parity
suite asserts `result === null` (not `NaN` or `undefined`).

## Failure modes

When `make parity-check` fails in CI, use this decision tree:

**1. Which side changed?**

Check `git diff` to see if the Python function or the TS helper was modified.

**2. Python changed intentionally** (you updated the math in `generate_visualization_fixtures.py` or the referenced Python module):
```bash
make parity-fixtures      # regenerate fixtures from new Python source
make parity-check         # confirm no remaining drift
cd results-explorer && npm test -- chartMath.parity   # TS must still pass
```

**3. TypeScript changed intentionally** (you updated a helper in `chartMath.ts`):
- The fixture is the Python source of truth - do NOT regenerate fixtures.
- Fix the TS helper until `npm test -- chartMath.parity` passes.
- If the TS change was intentional AND correct, update the Python reference to match, then regenerate.

**4. Neither changed (CI flake)**:
- Re-run the job.
- If persistent: check for float platform differences (rare; tolerance is 1e-9).

**Running a single failing fixture case locally:**
```bash
cd results-explorer && npm test -- chartMath.parity --reporter=verbose 2>&1 | grep "FAIL\|chart="
```
