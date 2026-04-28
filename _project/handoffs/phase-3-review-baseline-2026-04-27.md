# Phase 3 Promotion Metrics — 2026-04-27 (baseline)

> This is the **baseline** review captured when the metrics system was
> set up. The `published-results` branch did not yet exist on origin at
> this point, so all six metrics correctly report zero. This file
> records the starting trajectory; subsequent quarterly reviews land
> alongside as `phase-3-review-YYYY-MM-DD.md` and the diff between them
> is the trend.

## Auto-generated report

- Repo: `joeharris76/BenchBox`
- Base branch: `published-results`
- Generated: 2026-04-27T21:02:51+00:00
- Source: `scripts/phase2_metrics.py`

## Summary

- No thresholds breached.

Promotion rule (see `_project/analysis/phase-3-promotion-metrics.md`): promote Phase 3 design TODOs only when **two or more quantitative thresholds** are breached for **two consecutive quarters**, OR **two qualitative thresholds** are breached in a single review.

## Metrics

| # | Metric | Value | Threshold | Status | Note |
|---|--------|-------|-----------|--------|------|
| 1 | Merged PRs / month (last 90d, by 30d bucket) | 0 / 0 / 0 (most recent 30d first) | >= 50/mo sustained for 3 mo | ok |  |
| 2 | Median PR review latency, hours (last 30d merged) | 0 PRs in window | > 72h | ok | no data |
| 3 | Open PRs > 7d old (snapshot) | 0 (of 0 open) | >= 5 sustained for 30d | ok | snapshot only; sustained-for-30d check requires comparing across reviews |
| 4 | Distinct requesters in 'Private/Unlisted' section | 0 | >= 3 | ok |  |
| 5 | Distinct requesters in 'Blocked-Maintainer' section | 0 | >= 5 | ok |  |
| 6 | Distinct requesters in 'Org-Spaces' section | 0 | >= 3 | ok |  |
