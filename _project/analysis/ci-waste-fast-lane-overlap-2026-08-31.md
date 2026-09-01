# Fast-lane selection overlap inventory (2026-08-31)

## Scope and provenance

This is a bounded overlap inventory, not a proposal to skip, split, demote, or
otherwise change a CI lane. It inventories the fast-marker selection used by
`pull_request`, `merge_group`, post-merge, and nightly workflows.

Source inspection was pinned at `origin/develop` / worktree `HEAD`
`bd888c28a6d3753a065b868cbec9d386002cd131` on 2026-08-31. Input SHA-256
hashes at that revision are:

| Input | SHA-256 |
| --- | --- |
| `Makefile` | `b2c36a91eb92971d3e9230a6506e76346781cf104bfb1ecef564578ff01ecf1a` |
| `.github/workflows/pr.yml` | `7dcfcbda44ccdbd3b643f027ef9b9842d5d4ad50a250b8561f30d7e0eb1151fa` |
| `.github/workflows/develop-post-merge.yml` | `379eaab24b9baed15c350d8d893ea686beb7d98ef80c11e5b4f628829a0b7813` |
| `.github/workflows/nightly.yml` | `ff150c448ca4e1702f2285204235cda0bc3f2281e6a9df047dc87c69e4837e82` |
| `_project/config/fast_test_lane_policy.json` | `33e9f2cf18709c8f9a1aaf0c06a0b6a66c3e46dfbd6bb12950fb81d6ac4a7f68` |
| `_project/scripts/timing_policy_check.py` | `29583476770fa20c81643ee3d9c4e297642bc955dc8358d33db620bfc26bf4a7` |
| committed remeasure manifest | `e8f2970a1e5ddb9dcdd59a71b20fa8ed6bb55cec55e50da1354d8deb6b9f3eb1` |

The normalized selector in all cells is:

```text
tests; -m "fast and not (slow or stress or resource_heavy or live_integration)";
--tb=short; -p pytest_cov; --cov=benchbox; coverage XML and term reports;
--cov-fail-under=70
```

Historical source evidence needed to interpret the observed runs is preserved
in `ci-waste-fast-lane-overlap-2026-08-31-sources.json` (SHA-256
`cafe063fb8aea28ef17f2ac200b73852ccdba947e6ba0e6951099ecd2796ef49`).
It records the exact relevant workflow and Makefile excerpts, their source
commit/path/line provenance, the original full-file hashes, and a SHA-256 for
each reconstructed excerpt. Every manifest cell names its applicable excerpts.
The replay verifies the snapshot and excerpt hashes, checks that each excerpt
is bound to the cell's source SHA, and matches its command/configuration anchors
against the retained job log. It does not need the historical Git objects.

`Makefile:784-787` owns the canonical `make ci-test` form. `pr.yml:736-739`
and `nightly.yml:61-64` inline the equivalent pytest invocation.

## Identity rule and evidence levels

An **exact identity** requires the same commit SHA, OS, Python version, and a
hash of sorted collected node IDs. Selector or configuration equality alone is
only a configuration similarity. Historical Actions metadata and retained logs
expose final outcome summaries and timing, not the collected node-ID list.
Selection identity is therefore unknown for every cell; no count is treated as
a collected-selection fingerprint.

Evidence is layered as follows:

1. **w0, selector:** source configuration at the pinned revision.
2. **w1, outcome observation:** observed Actions run SHA, workflow/job, OS,
   Python, final fast-step outcome summary, and null node-ID hash.
3. **w2, weight:** unknown for every fast step. The committed remeasure
   manifest has event-level completed runner minutes, not fast-step allocation.

The ceiling and delta safeguards remain distinct from this inventory. The
current policy ceiling is 29,050 selected fast tests. `pr.yml:454-481` keeps
the absolute `guard-timing-policy` and its additive `guard-fast-lane-delta`;
`develop-post-merge.yml:72-96` persists the develop baseline. This inventory
does not alter or reinterpret either guard.

## Evidence cells

Outcome total is the final pytest summary's passed + skipped + failed tests;
it is not a collected-node count or selection fingerprint. Step durations are
the Actions jobs API timestamps for **only** `Run fast tests` or `Run CI
fast-test mirror`, rounded to two decimals.

| Event / workflow / job | Observed SHA | OS / Python | Outcome total | Sorted node-ID hash | Fast-step runner-minutes | Duration | Evidence kind |
| --- | --- | --- | ---: | --- | ---: | --- |
| `pull_request` / Develop PR / `test (ubuntu-latest, 3.12)` | `c2de6c302688247d5d79f31b8386cceb4a429749` | Ubuntu / 3.12 | 28,611 | null | null | 9.00 min | run `33407603525`, job `99539237870`; API step timestamps and log summary |
| `merge_group` / Develop PR / `test (ubuntu-latest, 3.12)` | `0f9f6682754a824cc18567fbc71295dfed503eec` | Ubuntu / 3.12 | 28,630 | null | null | 9.45 min | run `33409803494`, job `99546309441`; API step timestamps and log summary |
| `push` / Develop post-merge / `fast-test` | `4585863f90b18ac40a54ee7ea544ab8973190f17` | Ubuntu / 3.12 | 28,608 | null | null | 11.47 min | run `33395527790`, job `99499014396`; API step timestamps and log summary |
| `schedule` / Develop post-merge / `fast-test` | `4585863f90b18ac40a54ee7ea544ab8973190f17` | Ubuntu / 3.12 | 28,608 | null | null | 11.93 min | run `33398409495`, job `99508451767`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (ubuntu-latest, 3.10)` | `3ff3ebd23df6da8c5176168f7a09ad92ddd0128d` | Ubuntu / 3.10 | 28,605 | null | null | 13.58 min | run `33389517555`, job `99479672475`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (ubuntu-latest, 3.12)` | same | Ubuntu / 3.12 | 28,605 | null | null | 11.70 min | run `33389517555`, job `99479672372`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (ubuntu-latest, 3.13)` | same | Ubuntu / 3.13 | 28,605 | null | null | 11.38 min | run `33389517555`, job `99479672545`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (macos-latest, 3.12)` | same | macOS / 3.12 | 28,605 | null | null | 11.35 min | run `33389517555`, job `99479672348`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (windows-latest, 3.10)` | same | Windows / 3.10 | 28,580 | null | null | 19.48 min, failed | run `33389517555`, job `99479672294`; API step timestamps and log summary |
| `schedule` / Nightly Validation / `test (windows-latest, 3.12)` | same | Windows / 3.12 | 28,580 | null | null | 17.05 min, failed | run `33389517555`, job `99479672429`; API step timestamps and log summary |

The nightly run itself is run `33389517555`, event `schedule`, workflow
`Nightly Validation`, SHA `3ff3ebd23df6da8c5176168f7a09ad92ddd0128d`, and
conclusion `failure`. The two Windows fast-test summaries each contain three
failures. This is observed unique platform execution, not duplicate proof.

## Classification

| Relationship | Classification | Basis |
| --- | --- | --- |
| Any cells with the same selector text | Configuration similarity only | The historical evidence has no node-ID set, so it cannot establish selection overlap. |
| Post-merge push and schedule | Exact identity unknown | SHA, OS, Python, and outcome total match, but outcome totals do not identify a node set. |
| Six nightly matrix cells | Coverage/outcome observations only | The matrix differs by OS/Python; the two Windows outcome summaries contain failures. This does not establish that other cells are duplicate or unique work. |
| Every pair | No exact identity established | The required SHA + OS + Python + sorted-node-ID-hash key cannot be completed from the observable data. |

## Runner-minute weighting and limits

The committed remeasure manifest contains completed runner-minute totals for
whole event-fan-out cohorts. It does not record individual fast-step runner
minutes or a partition that could derive them. Accordingly, every w2 fast-step
runner-minute field is null. The document may cite the committed manifest for
event-level context, but it does not use its PR or merge-group medians as a
weight for any cell.

Limits: final pytest summaries do not preserve sorted node IDs; a matching
outcome total is not a node-set hash. The listed runs were live-read on
2026-08-31, while the static input hashes are pinned at `bd888c28a`. Runtime
SHAs differ from that source pin, so this report separates historical observed
execution from current configuration. The remeasure sample is bounded and
observational; its runner-minute totals are not a causal estimate.

## Reproduction commands

```text
git rev-parse HEAD
shasum -a 256 Makefile .github/workflows/pr.yml .github/workflows/develop-post-merge.yml .github/workflows/nightly.yml _project/config/fast_test_lane_policy.json _project/scripts/timing_policy_check.py _project/analysis/ci-waste-remeasure-2026-08-31-manifest.json
shasum -a 256 _project/analysis/ci-waste-fast-lane-overlap-2026-08-31-sources.json
gh api repos/BenchBox-dev/BenchBox/actions/runs/<run-id>
gh api repos/BenchBox-dev/BenchBox/actions/runs/<run-id>/jobs?per_page=100
NO_COLOR=1 GH_PAGER=cat gh run view <run-id> --job <job-id> --log
uv run -- python _project/analysis/replay_ci_waste_remeasure.py
uv run -- python _project/analysis/replay_ci_waste_fast_lane_overlap.py --self-check
uv run -- python _project/analysis/replay_ci_waste_fast_lane_overlap.py
empty_object_dir="$(mktemp -d)"
GIT_OBJECT_DIRECTORY="$empty_object_dir" git cat-file -e 'c2de6c302688247d5d79f31b8386cceb4a429749^{commit}'  # expected to fail
GIT_OBJECT_DIRECTORY="$empty_object_dir" uv run -- python _project/analysis/replay_ci_waste_fast_lane_overlap.py
```

The API calls provide run metadata and the named-step timestamps; `gh run view`
provides the final pytest summary used for the outcome total. Neither exposed a
sorted node-ID artifact or fast-step runner-minute allocation for these runs.
