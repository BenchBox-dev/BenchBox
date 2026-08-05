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

- Chromium's full e2e suite is "blocking" in name only — it is **not** in
  the required-check set (tracker:
  `chromium-blocking-suite-not-in-required-checks`). Before attributing a
  red Chromium run to the PR under review, check whether it is already red
  on develop's own tip; a pre-existing develop-side failure is not the
  PR's fault.
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
  `.github/workflows/nightly.yml`) — alerts on non-draft, non-soundness
  PRs whose required lane is green but auto-merge is still off for more
  than 2 hours after the head commit.

  After the auto-merge hold, **an intentional non-armed green PR is normal**,
  not a stuck state. Auto-merge is **not** armed by `opened`, `reopened`, or
  `synchronize` (a re-push will not flip it on). The only intentional arm
  signals are:

  - `make pr-ready` (or `make pr-arm-auto-merge`) on a finished branch
  - `make pr-open READY=1` to open and arm in one step
  - draft → ready (`ready_for_review` in `auto-merge-on-open.yml`)

  Do **not** remediate a green-unmerged alert by re-pushing "to re-trigger
  synchronize." That path no longer enables auto-merge. If the branch is
  final, arm it; if work continues, leave auto-merge off.

  Known follow-up: `green_unmerged_sweep.py` still classifies many of these
  intentional holds as stranded (false positives). Fixing the classifier is
  out of the enablement-hold change set (`_project/scripts/`); until then,
  treat sweep hits as triage signals, not proof of a broken arm path. A green
  `enable`-job run is also not proof the PR's `auto_merge` field is set —
  the sweep re-reads the PR field rather than trusting the workflow conclusion.

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
