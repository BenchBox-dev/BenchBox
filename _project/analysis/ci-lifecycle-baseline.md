# CI lifecycle baseline (representative 28-day remeasurement)

> SUPERSEDED COHORT WARNING: this file currently covers 65 PRs enumerated
> from a single pulls-list page. Date-bounded search verifies 349 merged
> develop PRs in the window; the remaining 284 are being collected and this
> file will be rebuilt with a correction commit. Do not cite totals from
> this file as whole-cohort numbers until the warning is removed.

Frozen cohort: merged develop PRs 2026-08-11 through 2026-09-08 (registration commit d2fa960e4).
Method: every synchronize head enumerated via pulls/commits; runs+jobs+checks per head;
heads with zero observable runs recorded as missing-artifact, never dropped.
Refresh classification: two-parent head whose files(P1...M) are a subset of files(B...P2).
Report numbers and validation come from ci-lifecycle-baseline.json via --validate-lifecycle-baseline.

| PR | heads | observed | missing | attempts | completed min | cancelled min | ancestry-only refresh |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #1991 | 15 | 1 | 14 | 10 | 84.6 | 0.0 | 0 |
| #2001 | 1 | 1 | 0 | 9 | 17.0 | 0.0 | 0 |
| #2002 | 2 | 2 | 0 | 18 | 186.3 | 0.0 | 0 |
| #2003 | 1 | 1 | 0 | 9 | 81.3 | 0.0 | 0 |
| #2005 | 1 | 1 | 0 | 8 | 66.3 | 0.0 | 0 |
| #2006 | 3 | 1 | 2 | 10 | 98.7 | 0.0 | 0 |
| #2007 | 2 | 2 | 0 | 18 | 161.3 | 15.3 | 0 |
| #2009 | 1 | 1 | 0 | 9 | 71.0 | 0.0 | 0 |
| #2010 | 2 | 2 | 0 | 18 | 107.4 | 14.3 | 0 |
| #2011 | 3 | 1 | 2 | 11 | 81.7 | 0.0 | 0 |
| #2012 | 2 | 2 | 0 | 20 | 105.9 | 42.0 | 0 |
| #2015 | 1 | 1 | 0 | 10 | 76.9 | 0.0 | 0 |
| #2016 | 3 | 1 | 2 | 10 | 76.6 | 0.0 | 0 |
| #2017 | 2 | 1 | 1 | 11 | 82.9 | 0.0 | 0 |
| #2018 | 3 | 1 | 2 | 13 | 93.4 | 0.0 | 0 |
| #2019 | 1 | 1 | 0 | 8 | 69.8 | 0.0 | 0 |
| #2022 | 3 | 3 | 0 | 37 | 233.1 | 0.0 | 0 |
| #2023 | 1 | 1 | 0 | 9 | 3.9 | 0.0 | 0 |
| #2024 | 1 | 1 | 0 | 9 | 61.1 | 0.0 | 0 |
| #2025 | 1 | 1 | 0 | 9 | 65.0 | 0.0 | 0 |
| #2027 | 1 | 1 | 0 | 10 | 81.1 | 0.0 | 0 |
| #2028 | 1 | 1 | 0 | 12 | 72.7 | 0.0 | 0 |
| #2030 | 3 | 3 | 0 | 36 | 241.0 | 61.2 | 0 |
| #2031 | 1 | 1 | 0 | 12 | 105.6 | 0.0 | 0 |
| #2032 | 14 | 5 | 9 | 62 | 399.6 | 86.2 | 2 |
| #2033 | 5 | 5 | 0 | 47 | 317.4 | 46.5 | 0 |
| #2034 | 1 | 1 | 0 | 11 | 109.2 | 0.0 | 0 |
| #2035 | 1 | 1 | 0 | 9 | 78.9 | 0.0 | 0 |
| #2038 | 1 | 1 | 0 | 11 | 98.7 | 0.0 | 0 |
| #2039 | 2 | 2 | 0 | 18 | 130.5 | 22.8 | 1 |
| #2040 | 1 | 1 | 0 | 11 | 94.2 | 0.0 | 0 |
| #2041 | 1 | 1 | 0 | 11 | 84.4 | 0.0 | 0 |
| #2042 | 5 | 4 | 1 | 46 | 321.7 | 26.9 | 1 |
| #2043 | 3 | 3 | 0 | 34 | 285.4 | 0.0 | 1 |
| #2044 | 12 | 3 | 9 | 37 | 375.1 | 0.3 | 1 |
| #2046 | 27 | 12 | 15 | 144 | 486.3 | 284.7 | 0 |
| #2047 | 14 | 4 | 10 | 28 | 202.7 | 0.0 | 0 |
| #2049 | 7 | 1 | 6 | 12 | 126.7 | 0.0 | 0 |
| #2050 | 3 | 3 | 0 | 37 | 293.3 | 40.9 | 0 |
| #2051 | 17 | 14 | 3 | 137 | 689.4 | 273.7 | 3 |
| #2052 | 12 | 8 | 4 | 61 | 335.7 | 9.7 | 1 |
| #2053 | 5 | 5 | 0 | 55 | 314.5 | 111.9 | 1 |
| #2054 | 4 | 3 | 1 | 34 | 175.3 | 68.0 | 0 |
| #2055 | 8 | 8 | 0 | 95 | 630.1 | 96.0 | 2 |
| #2056 | 10 | 8 | 2 | 88 | 541.1 | 102.3 | 2 |
| #2057 | 3 | 3 | 0 | 36 | 269.8 | 0.0 | 0 |
| #2058 | 26 | 15 | 11 | 173 | 1087.2 | 205.8 | 8 |
| #2059 | 18 | 14 | 4 | 164 | 970.3 | 231.3 | 5 |
| #2060 | 42 | 22 | 20 | 260 | 1678.9 | 279.0 | 16 |
| #2061 | 2 | 1 | 1 | 11 | 112.1 | 0.0 | 1 |
| #2062 | 2 | 2 | 0 | 23 | 137.8 | 36.8 | 0 |
| #2063 | 1 | 1 | 0 | 9 | 68.1 | 0.0 | 0 |
| #2064 | 1 | 1 | 0 | 10 | 8.3 | 0.0 | 0 |
| #2065 | 8 | 4 | 4 | 47 | 306.9 | 50.2 | 5 |
| #2067 | 2 | 2 | 0 | 23 | 244.6 | 0.0 | 0 |
| #2069 | 5 | 2 | 3 | 20 | 15.9 | 0.0 | 3 |
| #2070 | 6 | 3 | 3 | 34 | 245.5 | 36.8 | 3 |
| #2071 | 3 | 3 | 0 | 30 | 258.5 | 0.0 | 2 |
| #2072 | 9 | 8 | 1 | 89 | 709.1 | 26.3 | 4 |
| #2075 | 4 | 2 | 2 | 24 | 180.5 | 0.0 | 1 |
| #2076 | 1 | 1 | 0 | 9 | 3.9 | 0.0 | 0 |
| #2077 | 4 | 4 | 0 | 31 | 11.9 | 0.0 | 1 |
| #2078 | 1 | 1 | 0 | 11 | 108.3 | 0.0 | 0 |
| #2079 | 1 | 1 | 0 | 9 | 84.6 | 0.0 | 0 |
| #2080 | 2 | 2 | 0 | 19 | 136.4 | 0.0 | 1 |

Total: 65 PRs, 349 heads (217 observed, 132 missing-artifact), 2346 attempts,
15053.3 completed and 2169.0 cancelled runner-minutes, 65 ancestry-only refreshes.

## Missing evidence

132 of 349 synchronize heads (38%) have zero observable workflow runs or check runs.
Spot-checked head d60b9998f597 (PR #2058): the runs API returns total_count 0 two days after merge,
so these are heads for which GitHub never scheduled runs (rapid-push supersession), not expired retention.
Cancelled/total cost below is therefore a lower bound; missing heads are quantified, not excluded.

## Avoidable-action baseline (refresh component)

65 ancestry-only refresh pushes in 28 days: exact two-parent merges carrying no feature-side edits.
One refresh carried feature edits (conflict resolution) and 3 externally-based merges are unclassified;
both stay outside the avoidable count (conservative). Rename-heavy merges could misclassify the same way.
The duplicate-local-validation component has no historical record and starts prospective measurement only;
it is not folded into this number.

## Downstream consumers

- develop-pr-concurrency w3 corrects its audit from this file (whole-lifecycle cancellation cost).
- exact-refresh-eligibility reads reason-code observations against this cohort window and denominator.
- pr-process-low-drama-acceptance compares prospective avoidable actions against the 65-refresh baseline.
