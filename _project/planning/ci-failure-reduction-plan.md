# CI Failure & Merge-Blocker Reduction Plan

Date: 2026-07-23
Status: proposal (no code changes in this document's PR)
Scope: PRs targeting `develop` (release lane out of scope except where noted)

## 1. Evidence base

Because every dev PR lands via squash auto-merge once CI is green, the head
commit of a merged PR is always green — GitHub check-run history at PR heads
therefore *understates* failure cost. The real cost shows up as fix-forward
round trips (push → CI red → diagnose → push again), merge conflicts on
shared guard files, and post-merge breakage on `develop`. Evidence used here:

- **Guard-file churn** (`git log --since=2026-06-20 --name-only`):
  `_project/config/fast_test_lane_policy.json` is the 2nd most-touched file
  in the repo (10 PRs), behind only `todo_db.py`. Eight ceiling bumps landed
  in the single week 2026-07-16 → 2026-07-22.
- **`_ceiling_note` archaeology**: ~30 documented bumps since 2026-04-13,
  including two multi-PR "composed once so the queued branches carry
  byte-identical policy content instead of N conflicting bumps" episodes
  (2026-07-18: five branches; 2026-07-19: two branches). That choreography
  is manual merge-queue management by hand.
- **Recent-PR check-run sample** (last 23 non-draft PRs to `develop`,
  2026-07-23): zero blocking-check failures at heads; the only red check is
  `WebKit (@smoke, non-blocking)` — failed on **both** PRs that triggered the
  explorer browser matrix (#1270, #1264) while Firefox and Chromium passed
  both times. That is a deterministic WebKit breakage, not a flake.
- **Module-size guard**: retripped twice during the 2026-07 tuning batch on
  exact-fit allowlist entries before `ALLOWLIST_HEADROOM = 25` was added
  (see the comment in `tests/system/test_module_size_thresholds.py`).
- **Repo settings**: `strict_required_status_checks_policy: false`, squash
  auto-merge, no merge queue. `develop-post-merge.yml` exists explicitly as
  the safety net for stale-base composition breakage.
- **Recurring-pattern list from the PR-triage loop** (all previously
  verified): FAST_LANE_VIOLATION, module-size allowlist, DDL-drift alias
  registration, codespell, dependency-inventory DRIFT, CLI-surface drift,
  stale-branch conflicts.

## 2. Failure taxonomy

| # | Class | Mechanism | Frequency / cost |
|---|-------|-----------|------------------|
| A | Shared-counter contention | Global `max_fast_tests` + prose `_ceiling_note` in one JSON file; every test-adding PR must edit the same line | ~1 bump/PR during feature pushes; textual conflicts; manual multi-PR composition |
| B | Stale-base semantic composition | Non-strict required checks + auto-merge: two PRs green individually, over-ceiling (or otherwise broken) after both land | Post-merge `develop` breakage; drives the "composed byte-identical bump" ritual |
| C | Allowlist/drift guards | Module size, DDL governance aliases, CLI surface, dependency inventory, oracle map, curation list, UAT LOC table, skill-sync lock | Steady trickle; each miss = 1 full CI round trip |
| D | Local/CI parity gaps | Guards that run in CI but not in `make ci-lint`/preflight fire for the first time in CI | Every gap is a guaranteed remote-only failure |
| E | Serial fail-fast lint lane | `lint` job stops at first failing guard; multi-guard misses cost N round trips | Multiplies C and D |
| F | Perma-red non-blocking checks | WebKit @smoke fails deterministically; red is "expected" | Triage noise; normalizes ignoring red; 160 MB artifact per failure |
| G | Human-gate latency | Soundness-path PRs (CODEOWNERS mirror) correctly withhold auto-merge but then sit idle (#1116, #1142) | Days of queue latency; conflict risk grows while parked |
| H | Triage-loop friction | Webhook events reference stale SHAs; no CI-success webhooks; auto-merge enable not verified | Wasted triage wakes; risk of green-but-unmerged PRs |

Classes A+B are the same root problem seen from two sides and are the top
priority: they are the only class that *scales with PR throughput* (currently
~50 squash merges in 2 weeks) and they already force manual serialization of
the merge queue.

## 3. Workstreams

### WS1 — Fast-lane budget: remove per-PR contention (P0)

Root causes: (a) the ceiling is absolute and bumped with "minimal working
headroom" (+5…+33), guaranteeing the next test-adding PR retrips it; (b) the
justification log is a single JSON string, so any two bumps conflict
textually; (c) the check is not base-relative, so two independently-green PRs
compose over the ceiling (class B).

Changes, in order:

1. **Move the log out of the JSON.** Replace `_ceiling_note` with
   `_project/config/fast_lane_ceiling_log.md` (append-only, one dated entry
   per bump) and add `merge=union` for it in `.gitattributes`. The JSON
   retains only the number. Two PRs bumping to different values still
   conflict on one short line — trivially resolvable — instead of on a 5 KB
   prose blob. (Small; do first.)
2. **Coarse headroom quantum.** Policy: bumps go in increments of +500 with
   resulting headroom ≥ 250 (maintainer precedent exists: the 22572 → 25000
   directed bump). Encode in `timing_policy_check.py`: print a WARNING when
   headroom < 100 so the bump lands *before* the violation. Target cadence:
   about one ceiling PR per month instead of one per feature PR.
3. **Base-relative delta guard (replaces the ceiling as the per-PR gate).**
   `develop-post-merge` already runs `ci-lint` on the develop tip and prints
   `Fast lane tests collected: N`; persist N (Actions cache or repo
   variable). The PR lint job then enforces `pr_count - develop_count <=
   DELTA` (start at 150) and only *warns* on absolute headroom. The absolute
   ceiling stays as a backstop enforced post-merge + nightly, auto-ratcheted:
   when headroom < 100, a scheduled job opens a mechanical `chore/` PR
   bumping by +500 with a generated log entry. Net effect: feature PRs stop
   editing the policy file entirely.
4. **Longer term — measure the real thing.** The count is a proxy for lane
   wall-time. The PR `test` job already runs the entire fast lane; record its
   duration (and per-test top-20 from `--durations`) into
   `dev-loop-metrics`, and once 4 weeks of data exist, add a wall-clock
   budget assertion (e.g. fail > 15 min) and consider demoting the count
   check to advisory.

Acceptance: over a 2-week window, zero feature PRs touch
`fast_test_lane_policy.json`; zero post-merge FAST_LANE breaks on `develop`.

### WS2 — Merge integration: adopt the GitHub merge queue on `develop` (P0/P1, maintainer/admin action)

Today's setup (non-strict checks + auto-merge + post-merge safety net) means
composition errors are caught *after* they land. The ceiling-note choreography
is a hand-rolled merge queue. GitHub's native merge queue gives the same
guarantee automatically: each queued PR's required checks re-run on the
speculative merge ref, so class B disappears — including for guards this plan
doesn't touch (module size, drift checks, uv.lock).

- Add `merge_group` to `pr.yml` triggers (the required umbrella
  `ci-required-result` must report on merge-group refs).
- Enable the queue in the `develop-squash-only` ruleset; keep squash;
  auto-merge becomes "add to queue when green".
- Cost check: required lane is ~20 min; at 3–5 PRs/day the queue adds
  minutes of latency, not hours. Trial for 2 weeks; keep
  `develop-post-merge` as belt-and-braces during the trial.
- The auto-merge-on-open workflow and the soundness-path withholding logic
  in `_project/scripts/auto_merge_soundness_paths.py` need review for queue
  interaction (soundness PRs must stay out of the queue). **Soundness paths
  and `release.yml` are owner-gated — this workstream is a maintainer
  decision, not an agent PR.**
- If the queue is declined: fall back to making `develop-post-merge` failure
  loud (auto-file an issue + notification) and documenting a fix-forward SLA.

### WS3 — Local/CI parity: no guard fires first in CI (P0, cheap)

`make ci-lint` currently omits guards the CI lint job runs:
`lint-imports`, the public-contract drift check, `audit-raw-check`, the
release-curation-list drift check, and the untracked skill-mirror drift
guard. The content-guard suite (YAML/markdown/docs-refs hygiene) is skipped
by `pr-preflight` whenever code changes are present, and codespell runs only
in `docs.yml`/pre-commit. Every one of these is a remote-only surprise.

1. Sync `ci-lint` to the `pr.yml` lint job 1:1 (add the five missing guards;
   add `make spellcheck`, it is fast).
2. Make `pr-preflight` always run `pr-content-guard`, not only on
   docs-only diffs.
3. Pin the parity with the repo's own idiom: a fast test that parses
   `.github/workflows/pr.yml`, extracts the lint job's `make`/script
   invocations, and asserts each appears in the `ci-lint` recipe
   (mirror of `test_codeowners_covers_soundness_paths`). This prevents
   class D from regrowing as new guards are added.

### WS4 — One CI round trip reports all failures (P1)

The lint job is fail-fast across ~15 independent guards, so an agent fixes
ruff, pushes, then discovers the timing-policy failure, pushes, then
discovers compat-docs… Each discovery costs a full CI cycle plus a triage
wake. Restructure the lint job (and `ci-lint`) to run every independent
guard with `continue-on-error: true` (locally: accumulate exit codes), then
fail once at the end with a consolidated summary in `$GITHUB_STEP_SUMMARY`.
Guards stay individually visible; the round-trip count drops to 1.

### WS5 — Guard ergonomics: regenerate, don't hand-edit (P1)

1. **`make guards-fix`**: one target that runs every regenerable-artifact
   fixer — `dependency_audit/parse_deps.py` (inventory), oracle coverage
   map regen, parity fixtures, UAT LOC table, curation list, skill-sync —
   then prints `git status`. Wire a mention of it into each corresponding
   guard's failure message and into the `pr` skill.
2. **Remediation-command audit**: every drift guard's failure output must
   print the exact command or exact line to add (the DDL-governance check
   should name `_DDL_GOVERNANCE_TRANSFORMER_ALIASES`; the module-size guard
   should print the ready-to-paste allowlist entry with the current line
   count, per its own re-baseline convention). One pass over all guards; add
   the message to the guard's unit test so it can't rot.
3. **Codespell at commit time**: worktree-claim should ensure pre-commit
   hooks are installed in pool worktrees (agents commit via git directly;
   an uninstalled hook is why codespell reaches CI at all).

### WS6 — WebKit smoke: fix or demote — never perma-red (P1, small)

Non-blocking-but-always-red is the worst state: it trains everyone to ignore
red and ships a 160 MB report artifact per failure. Timebox one diagnosis
session on the WebKit @smoke failures (2/2 deterministic on 2026-07-22,
Firefox green — likely a real WebKit-specific regression in the explorer).
Then either fix it, or move the WebKit job to `nightly.yml` with an
auto-filed issue on failure, and delete the job from the PR lane until
supported. Also update the triage-loop prompt: Firefox @smoke was green in
the sample — only WebKit is broken, and it is *not* a flake, so "ignore"
guidance should become "known-broken, tracked in issue #X". Trim the
failure-artifact retention (traces on first retry only, retention-days: 3).

### WS7 — Drain the human gate predictably (P2)

Soundness-path PRs correctly wait for the owner, but they park silently and
grow conflicts while parked (#1116, #1142). Add a small scheduled job (or a
`dev-loop-metrics` section + morning-brief hook) that lists open PRs which
are green, auto-merge-withheld, and idle > 24 h, so the owner gets one daily
"ready for your review: N PRs" signal. Label them `awaiting-owner` for
at-a-glance triage. Target: median park time < 1 day, which also shrinks the
stale-branch/conflict class on exactly the PRs that can least afford
re-review.

### WS8 — Triage-loop hardening (P2)

1. **Verify auto-merge actually engages.** The API snapshot showed
   `auto_merge: null` on open PRs whose `enable` job succeeded (may be
   timing, may be a silent failure — e.g. token permissions after ruleset
   changes). Add a step to the enable workflow that re-reads the PR and
   fails loudly if auto-merge is still off, plus a nightly sweep for
   green-but-unmerged non-soundness PRs.
2. **Codify the judgment rules** currently living in the hand-carried triage
   prompt (stale-SHA verification, platform-outage signature, worktree-based
   cross-branch comparison) into `docs/operations/pr-triage.md` so any
   session/agent inherits them without prompt archaeology.

### WS9 — Measure it (P0 baseline, then continuous)

Extend `dev-loop-metrics` to compute, per merged PR: pushes-after-open
(fix-forward count), time-open-to-merge, whether `fast_test_lane_policy.json`
was touched, and first-pass required-lane green rate (via Actions run history
per head branch, not head-SHA check runs). Capture the baseline **before**
landing WS1–WS4, review after two weeks, and let the numbers arbitrate
whether WS2 (merge queue) stays.

## 4. Sequencing & ownership

| Order | Item | Size | Owner |
|-------|------|------|-------|
| 1 | WS9 baseline metrics | S | agent PR |
| 2 | WS1.1–1.2 (log split, quantum, warning) | S | agent PR |
| 3 | WS3 (ci-lint parity + pin test) | S | agent PR |
| 4 | WS4 (report-all lint lane) | M | agent PR |
| 5 | WS1.3 (delta guard + auto-ratchet) | M | agent PR |
| 6 | WS6 (WebKit fix-or-demote) | S–M | agent PR |
| 7 | WS2 (merge queue trial) | M | **maintainer** (ruleset + owner-gated workflows) |
| 8 | WS5, WS7, WS8 | S each | agent PRs |
| 9 | WS1.4 (wall-clock budget) | M | after 4 wks of WS9 data |

Explicit non-goals: weakening any soundness gate (CODEOWNERS mirror,
auto-merge withholding, release-lane checks) — those stay exactly as
designed; this plan only removes friction from the mechanical guard classes
around them.
