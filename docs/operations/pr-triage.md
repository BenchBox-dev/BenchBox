# PR triage runbook

Durable judgment rules for triaging open PRs against `develop` — the parts
of PR triage that are stable enough to write down once, rather than
rediscovered per-session. These are rules, not a walkthrough: they assume
familiarity with the dev-loop (`AGENTS.md`) and the auto-merge machinery
(`.github/workflows/auto-merge-on-open.yml`,
`_project/scripts/auto_merge_soundness_paths.py`).

## Always confirm against the current head SHA

Webhook payloads and CI event data can reference a SHA that is no longer
the PR's head — a later push superseded it before (or while) the event was
being processed. Before acting on any webhook-delivered check-run or
comment payload, re-fetch the PR and confirm its head SHA still matches
what the event described. Acting on a stale SHA risks approving, merging,
or "fixing" a state the PR has already moved past.

## Platform outage vs. a real failure

A whole-run failure where every job dies at the `setup-python` or
`setup-uv` step, with GitHub's "Unicorn" HTML error page appearing in the
job logs instead of normal output, is a GitHub Actions infrastructure
outage — not a defect in the PR. Wait and re-run once the outage clears;
do not start debugging the PR's own code for a failure signature like this.

## Cross-branch comparison uses a worktree, never `checkout -- .`

To compare the current branch against another ref (develop, a sibling
branch, a tag), use `git worktree add <path> <ref>` and diff/read from
there. Never run `git checkout <ref> -- .` against the current working
tree to "borrow" another ref's files — that mutates the current branch's
tracked files in place, can stage unrelated changes, and can silently
discard uncommitted work with no undo path as clean as a worktree's.

## TODO-tracker modify/delete merge conflicts

When a merge conflict is a modify/delete on a TODO-tracker record (one
side archived or completed the item; the other side still has edits
against the live copy), check which side already archived/completed the
item and keep that side's resolution. Do not resurrect an archived item by
re-adding the modified-but-stale copy — that reintroduces work the other
side had already closed out.

## Browser-lane triage

- Chromium's full e2e suite **does** gate develop merges. The required
  status check is `Results Explorer browser gate` (ruleset
  `develop-squash-only`), not a subordinate of `ci-required-result` —
  browser and PR workflows are separate. The gate is path-aware via
  `explorer-changes`: a red Chromium run on explorer-relevant paths makes
  the PR unmergeable; unrelated PRs get a green gate without running the
  suite. Before attributing a red Chromium (or gate) result to the PR under
  review, check whether develop's own tip is already red for the same
  reason; a pre-existing develop-side failure is not the PR's fault.
  Full wiring and lane status:
  [`docs/operations/browser-ci.md`](browser-ci.md) (merge-gate decision).
  Historical tracker id `chromium-blocking-suite-not-in-required-checks`
  described the pre-ruleset state and is no longer accurate.
- Firefox `@smoke` has been green in recent history — a red Firefox run is
  worth investigating as a real signal, not waved off as routine flake.
- WebKit failures are **not** dismissible as flake. See
  `docs/operations/browser-ci.md` for current lane status and the
  triage rule in force there.

## `mergeable_state` semantics

- `dirty` — a real merge conflict against the base branch; the PR needs a
  rebase/merge before anything else is worth checking.
- `blocked` — a required check or gate hasn't passed (or hasn't run) yet.
  Not a conflict; look at the check runs, not the tree.
- `unknown` — GitHub hasn't finished computing the field yet. Refetch
  after a short wait; never conclude anything (mergeable or not) from
  `unknown` itself.

## The two standing sweeps

Two automated, read-only sweeps cover complementary parts of the "PR is
green but stuck" problem; neither one enables auto-merge, merges, or edits
a PR's mergeability — both only alert.

- **Soundness-drain daily digest**
  (`_project/scripts/soundness_drain_report.py`, scheduled via a daily
  workflow) — for PRs that correctly never get auto-merge because they
  touch a soundness-critical path (or have the owner as a requested
  reviewer): flags ones parked more than 24h since their required lane
  went green, so they don't sit forgotten accumulating conflicts while
  waiting on the owner's manual review and merge.
- **Green-unmerged nightly sweep**
  (`_project/scripts/green_unmerged_sweep.py`,
  `.github/workflows/nightly.yml`) — alerts only on **true stranding**:
  non-draft, non-soundness, non-hold-label PRs whose required lane is green,
  auto-merge is still off more than 2 hours after the head commit, **and**
  the PR timeline shows prior arm intent that was lost. `--apply` only
  upserts the digest issue; it **never** enables auto-merge and must not
  re-arm a hold it did not set.

  After the auto-merge hold, **an intentional non-armed green PR is normal**,
  not a stuck state, and the sweep **excludes** it. Auto-merge is **not**
  armed by `opened`, `reopened`, or `synchronize` (a re-push will not flip it
  on). The only intentional arm signals are:

  - `make pr-ready` (or `make pr-arm-auto-merge`) on a finished branch
  - `make pr-open READY=1` to open and arm in one step
  - draft → ready (`ready_for_review` in `auto-merge-on-open.yml`), and only
    when the PR does **not** carry the `no-auto-merge` label

  **Classifier (arm intent):** a PR is stranded only when auto-merge is off
  *and* the issue/PR timeline includes at least one of
  `ready_for_review`, `auto_squash_enabled` / `auto_merge_enabled`, or
  `auto_merge_disabled` (the last implies a prior enable that was dropped).
  Never-armed intentional holds never emit those events. Missing timeline
  data fail-closes to "no arm intent" (prefer a missed strand over
  false-positiveing holds). Durable holds (draft or `no-auto-merge`) are
  also excluded even if the timeline still shows older arm events.
  `--apply` only upserts the digest issue from the stranded set; it never
  enables auto-merge and therefore cannot re-arm holds.

  Do **not** remediate a green-unmerged alert by re-pushing "to re-trigger
  synchronize." That path no longer enables auto-merge. When the branch is
  final, arm via `make pr-ready` / `READY=1` / draft → ready; if work
  continues, leave auto-merge off (or apply a durable hold — see below).

  A green `enable`-job run is also not proof the PR's `auto_merge` field is
  set — the sweep re-reads the PR field (and the timeline) rather than
  trusting the workflow conclusion.

## Durable auto-merge holds

`gh pr merge --disable-auto` alone is **not** a durable product signal: a later
intentional arm path could still enable auto-merge. Both re-arming layers
honour these durable holds (and neither re-arms on push or nightly `--apply`):

| Hold | Who honours it | Effect |
| --- | --- | --- |
| **Draft** | `auto-merge-on-open.yml` (job skip), green-unmerged sweep | Not ready; no arm, not stranded |
| **Label `no-auto-merge`** | `auto-merge-on-open.yml` (enable blocked + disable on apply/`labeled`), green-unmerged sweep | Non-draft intentional hold; revoke any enabled auto-merge; not stranded |
| **Never armed** | green-unmerged sweep (timeline arm-intent classifier) | Green + auto-merge OFF with no prior arm events is normal after the post-#1592 policy; not stranded |

Use draft while the branch is incomplete. Use `no-auto-merge` when the PR
should stay non-draft (CI/review as ready) but must not auto-merge — for
example waiting on another PR, or after an explicit disable that must survive
a later `ready_for_review` / re-arm attempt. Remove the label before arming
with `make pr-ready` or draft → ready.

Both sweeps upsert a single marker-tagged tracking issue while their
respective queue is non-empty, and patch it to the empty state exactly
once when it drains — never a per-run flood of new issues.

## Develop post-merge SLA

The green-unmerged sweep also checks the most recent "Develop post-merge"
workflow run (`.github/workflows/develop-post-merge.yml`) on develop's
tip. If that run's conclusion is `failure`, treat it as **same-day
fix-forward priority**: every PR opened after a red develop tip inherits
that breakage, so the fix should land before the day ends rather than
queuing behind routine work. This SLA is about triage priority only —
it does not change how `develop-post-merge.yml` itself behaves.
