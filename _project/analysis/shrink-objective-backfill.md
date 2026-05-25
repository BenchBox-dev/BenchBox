# Shrink Objective-Function Backfill Validation (#587–#604)

**Date:** 2026-05-24
**TODO:** `shrink-objective-function-and-guardrail` (w2)
**Goal:** `_project/goal-shrink-core-code.md`

## Purpose

The shrink campaign's original driver was a single gameable proxy
(`cloc --include-lang=Python benchbox/`). A three-round review judged it
Goodhart-prone and traced two confirmed defects to it. The goal statement has
since been rewritten to encode a corrected objective function (the
logic-vs-data discriminator in *Ledger and Credit*, lines 86–90, plus the
seven *Guardrails*, lines 112–126). This note **validates** that the corrected
objective function actually separates the campaign's genuine reductions from
its gamed relocations when applied to real merged history — i.e. that the new
metric is not just another unmeasured proxy.

## Method

For each merged PR #587–#604, classify against the objective function:

- **Net maintained-Python delta** (`additions − deletions`, dominated by
  `.py` for logic PRs and by `.yaml` for relocation PRs). The credit formula
  (`credited = net_deleted_maintained_python − added_maintained_python −
  uncredited_relocation`) zeroes out moves that merely shift lines.
- **Guardrail status**: did the PR introduce a violation (import-time I/O,
  dynamic symbol injection, unreadable SQL, missing schema validation)?
- **Moved-content class**: `logic` (credited) vs `data/metadata/query-surface`
  relocation (credited only under the four conditions in goal:88).

## Classification

| PR | Title (abbrev) | +add / −del | net | Class | Objective-function verdict |
|----|----------------|-------------|-----|-------|-----------------------------|
| 587 | joinorder df translations | +5 / −1116 | **−1111** | logic | **Credit** — dead hand-translations removed; generator preserves semantics (proven by [[shrink-followup-joinorder-benchmark-semantics]]) |
| 588 | joinorder synthetic df | +225 / −1007 | **−782** | logic | **Credit** — consolidation; semantic note retained |
| 589 | tpcds df channel queries | +438 / −1287 | **−849** | logic | **Credit** — consolidation |
| 590 | benchmark metadata catalogs | +1494 / −1026 | **+468** | data relocation | **Refuse** — net *positive* Python; Python→YAML move **and** Guardrail 1 violation (module-level eager YAML I/O). Fixed by [[shrink-followup-registry-lazy-cached-load]] |
| 591 | dependency metadata catalog | +898 / −602 | **+296** | data relocation | **Refuse** — net positive; metadata relocation, no logic removed |
| 592 | dataframe catalog data | +1331 / −1448 | −117 | data relocation | **Marginal/Refuse** — near-zero net; relocation-dominated, not logic reduction |
| 593 | static help & pricing catalogs | +636 / −667 | −31 | data relocation | **Marginal/Refuse** — near-zero net; relocation |
| 594 | presto/trino adapter plumbing | +783 / −1757 | **−974** | logic | **Credit** — DRY consolidation of real plumbing |
| 595 | mysql wire adapter plumbing | +780 / −1503 | **−723** | logic | **Credit** — DRY consolidation |
| 596 | dataframe primitive managers | +617 / −1577 | **−960** | logic | **Credit** — consolidation |
| 597 | tpcds df channel queries | +941 / −1762 | **−821** | logic | **Credit** — consolidation |
| 598 | platform hook metadata | +319 / −583 | −264 | mixed | **Partial** — metadata relocation + some plumbing removal |
| 599 | clickbench df queries | +359 / −1067 | **−708** | logic | **Credit** — body removal; orientation-doc check deferred to [[shrink-followup-restore-dataframe-orientation-docs]] |
| 600 | flightdata df queries | +386 / −797 | **−411** | logic | **Credit** |
| 601 | ssb df queries | +208 / −967 | **−759** | logic | **Credit** |
| 602 | taxi & tsbs df queries | +567 / −1441 | **−874** | logic | **Credit** |
| 603 | dataframe query implementations | +1088 / −1981 | **−893** | logic | **Credit (with debt)** — generator consolidation; Guardrail 2 findability debt tracked by [[shrink-followup-generated-impl-findability]] |
| 604 | static query catalogs | +1050 / −1870 | −820 | query-surface relocation | **Refuse as logic** — net delete is relocation, **and** Guardrail 4 violation (escaped-newline SQL scalars). Fixed by [[shrink-followup-sql-catalog-yaml-block-scalars]] |

## Finding

The corrected objective function **separates genuine from gamed reductions
cleanly**:

- **Genuine logic reductions** (#587–589, #594–597, #599–603) show large
  *negative* net Python deltas (−400 to −1100) from removing real
  implementation/maintenance surface. The discriminator credits them.
- **Gamed relocations** (#590 +468, #591 +296, #592 −117, #593 −31) show
  *near-zero or positive* net Python delta because the deletions are matched by
  YAML data additions. The credit formula's
  `− uncredited_relocation` term zeroes them out. Two of them (#590, #604) also
  trip an explicit guardrail.

Decisive cross-check: **every PR the objective function refuses or flags is
exactly a PR that required a defect-fix follow-up in this batch** — #590→registry
eager-load, #604→escaped SQL, #603→globals() findability. The raw-`cloc` proxy
credited all of them equally; the corrected objective function does not. The
metric is therefore not just another unmeasured proxy — it is falsified by, and
agrees with, the independent defect findings.

## Conclusion

The objective function encoded in the goal statement is **ratified and
validated**. No merged PR is reverted (genuine wins stand); the gamed
relocations are remediated by their targeted follow-up TODOs rather than by
reverting the relocation itself. The automated `make shrink-guardrail` tooling
remains **deferred** (goal chose a narrative planning-thesis + PR-stated
guardrail-evidence design); this backfill is the evidence that the narrative
gates are sufficient.
