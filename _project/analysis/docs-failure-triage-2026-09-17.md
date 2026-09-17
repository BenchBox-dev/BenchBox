# Documentation workflow PR failure triage, 2026-08-23..2026-09-16

Method: every `docs.yml` run in the window was listed via the Actions API;
for each of the 164 failed runs (144 `pull_request`, 20 `push`) the jobs
payload was fetched, and the failed steps were resolved from the jobs
payloads. Failed-step logs were sampled per class (10 visual-compare job
logs, 4 linkcheck runs fully censused across all 41 linkcheck-failed runs,
all 5 example-validation/build failures). 3 runs returned no jobs
(expired retention) and carry no classification.

## Per-job table

| Failed job | Runs | Share of 164 |
|---|---:|---:|
| Public-site visual regression | 122 | 74% |
| linkcheck | 41 | 25% |
| example-validation | 4 | 2% |
| build | 1 | 1% |

Per-run combos: visual-only 115 (112 single, 3 matrix-duplicate),
linkcheck-only 38, visual+linkcheck 3, visual+example-validation 1,
example-validation-only 3, build-only 1, no job data 3.

## Per-cause table

| Cause | Failed step | Runs | Verdict |
|---|---|---:|---|
| Real visual mismatches on pages the PR changed, merged without recorded approval | Capture and compare public site | ~100 | Gate working as designed; see recommendation |
| No baseline bound to the exact base SHA | Determine baseline mode | 20 | Strictness by design; early-window cluster is retention effect |
| Compare links to result IDs that exist in no corpus | Check documentation links | 29 runs involved | Fixed during the window by the post-16 link repair (#2147); docs 11/11 green since |
| Bot-gated hosts (AMPLab 403/timeout, Geekbench 403, old-owner redirect 429) | Check documentation links | ~16 runs involved | Fixed during the window by the same repair (allowlist with comment) |
| Transient 5xx/429/timeouts on third-party hosts | Check documentation links | ~12 runs involved | Inherent; linkcheck already retries twice |
| Missing draft images, one unsafe-path finding, one prompts-catalog staleness | example-validation steps | 4 | Gate working; each was a real finding on its PR |
| Placeholder credentials (`AKIA…EXAMPLE`, `password=secret`) matched by pattern | Scan assembled site for privacy leaks | 1 | Single false positive on 09-03, none since; scanner left untouched |

Run IDs by class (all `docs.yml`):

- Visual compare: pinned from the jobs census; samples inspected in full:
  32607230782, 33173426172, 33449832585, 33979596978, 34296989469,
  32639629718, 32878090115, 32908874383, 33282624353, 33407102328,
  33510872791, 33579874229, 33981606756, 33996038204, 34311390476,
  34698706588, 34776620196 (plus the remainder of the 100 in the census
  file set; every sampled mismatch named pages its PR plausibly changed,
  and every sampled PR merged with no approval recorded).
- Baseline mode: 32610797552, 32611876780, 32637797757, 32787551811,
  32860694781, 32860715856, 32870012225, 32870026917, 32870040262,
  32880905746, 32883283200, 32889238889, 32893674592, 33281140790,
  33406153959, 33577995194, 33578002716, 33639401320, 34698584072,
  34762707080.
- linkcheck: 32905216871, 33079421433, 33090728652, 33198626699,
  33407102328, 33407603511, 33411936998, 33416753315, 33418755832,
  33421308072, 33423066368, 33425022302, 33425427400, 33428967025,
  33432342507, 33436535080, 33436831310, 33440875922, 33442990639,
  33444437230, 33444874500, 33446057517, 33464892059, 33550707904,
  33675723014, 33938278489, 34053953307, 34130913351, 34858342632,
  35025651076, 35029974358, 35033078794, 35034038159, 35034225574,
  35034354755, 35034549756, 35035095543, 35036826306, 35039549878,
  35040266655, 35040553574.
- example-validation: 34989356423, 33789777256, 33314678357, 33395527794.
- build: 33700106381.
- No job data: 34058859651, 34044445244, 33686775504.

## What this triage changes

Nothing in the workflow. The census shows the actionable in-window
causes (dead comparison links, bot-gated hosts) were already repaired
during the window, and the remaining dominant class — visual comparison
failing on related, unapproved page changes — is the gate functioning as
designed on a non-required check. Narrowing the visual lane (for example
skipping comparison when the baseline is missing, or scoping it to
site-rendered paths) would re-scope a reviewed gate and is not done here.

## Recommendation (maintainer decision)

If the visual red rate stays near 100 failures per 25 days with approvals
still bypassed, decide one of: keep the friction as the price of the
approval flow; scope comparison to runs touching site-rendered paths; or
make visual a required check so its failures must be approved or fixed.
That decision needs its own review; this note is its evidence.

## Watch

Baseline PR failure rate: 22% (144 of 662). Repair date: 2026-09-16.
Report the docs PR failure rate over the 7 days after the repair against
that baseline, with the same per-job split.
