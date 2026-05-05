# Weekly Codex PR-Review Sweep — Template

A reusable checklist for the recurring "Codex PR-review follow-ups for week
ending YYYY-MM-DD" TODOs. Built from the
`codex-pr-review-followups-week-2026-05-01` execution and extended with the
two axes the original sweep template missed (captured in blind-spot
`_project/blind-spots/2026-05-01-130000-codex-followups-todo-misses-coverage-downgrades.md`).

## When to use this template

Run a sweep weekly (or whenever a backlog of `chatgpt-codex-connector[bot]`
inline review threads has accumulated on merged PRs). Each sweep produces:

1. A new TODO at
   `_project/TODO/main/planning/codex-pr-review-followups-week-YYYY-MM-DD.yaml`
2. A rescan audit at
   `_project/audits/codex-thread-rescan-week-YYYY-MM-DD.md` listing
   resolved-by-this-TODO, already-fixed-by-earlier-merges, and
   still-actionable threads
3. Optional cross-links from in-window blind-spots filed under
   `_project/blind-spots/YYYY-MM-DD-*` to the TODO

For routine single-pass cleanup, prefer the automated Make routine before
creating another manual inventory:

```bash
# Preview the candidate queue.
make codex-pr-review-followups-list CODEX_REVIEW_SINCE=YYYY-MM-DD CODEX_REVIEW_UNTIL=YYYY-MM-DD

# In a feature worktree, action each queued comment, reply with the
# BenchBox action marker, run preflight, and open the batched PR.
make codex-pr-review-followups CODEX_REVIEW_SINCE=YYYY-MM-DD CODEX_REVIEW_UNTIL=YYYY-MM-DD
```

The routine uses the same judgment rules below: it verifies current behavior
before editing, treats stale-but-fixed threads as no-current-action, preserves
historical DONE verification commands when they are still executable
documentation, and skips future reprocessing only after it has posted a reply
containing the `benchbox-codex-review-followup-actioned` marker.

If the routine crashes mid-sweep (transient `gh api` failures and pre-commit
hook auto-fixes will normally retry; anything else exits with a non-zero
status), re-drive it on the same worktree with `CODEX_REVIEW_RESUME=1`:

```bash
make codex-pr-review-followups CODEX_REVIEW_RESUME=1 CODEX_REVIEW_SINCE=YYYY-MM-DD
```

`--resume` (or its env-var form) implies `--allow-dirty` so the prior
per-comment commits on the branch are accepted, and parses
`git log origin/<base>..HEAD` for the per-comment commit subject to skip
comments whose fix already landed locally. The GitHub-marker check still
catches threads where both the commit and the reply already succeeded, so
`--resume` only needs to short-circuit the codex re-run for half-completed
work. Use it after any unplanned exit; do not use it on a fresh branch.

## Trust model — review the resulting PR before merge

The routine runs `codex exec --sandbox workspace-write -c approval_policy=never`
against the contents of comments authored by `chatgpt-codex-connector[bot]`.
That gives codex unattended write access to the repo for the duration of the
sweep. The trust boundary is the **author filter** (`--author` /
`CODEX_REVIEW_AUTHOR`). Anyone with repo write can change that flag to action
comments from any author. Treat the routine accordingly:

- The codex sandbox (`workspace-write`) permits codex to read the whole repo
  and write any file under the worktree. It does not get network access by
  default, but it can run any local command (including `git`, `uv`, `make`).
- `approval_policy=never` means codex never prompts before running a local
  command — including ones that mutate state. The routine is intentionally
  unattended, so this is required.
- Per-comment commits land **before** the GitHub marker reply is posted, and
  each commit message includes the source PR# + comment id (see
  `commit_message_for_result`). This means a crash mid-sweep leaves a
  reviewable diff on the branch and no phantom-actioned thread on GitHub.
- The reviewer of the resulting PR should: (a) skim each per-comment commit
  to confirm the change matches the source comment's intent, (b) reject any
  commit that pulled in unrelated edits, (c) verify that a "fixed"
  disposition actually corresponds to a change on disk (a stale Codex run
  could in principle fabricate an evidence block while leaving the tree
  unchanged — the per-commit diff is the ground truth).
- Prompt-injection content inside a Codex comment body is treated as input,
  not instruction; the prompt template
  (`_project/scripts/prompts/codex_pr_review_followup.md`) tells codex to
  verify against the current tree and to make the smallest coherent fix.
  Reviewers should still be alert to PRs that touch suspiciously broad
  surface area for a single Codex finding.

## Required scope axes

The frame "unresolved Codex review threads from PRs #N–#M" is good at
catching what Codex flagged-and-was-never-resolved, but blind to several
adjacent failure modes. **All five axes below are mandatory** — skip any
one of them only with an explicit `out-of-scope:` line citing why.

### Axis 1 — Codex inline threads (the canonical scan)

```bash
# Discover merged PRs in the review window.
START_DATE=YYYY-MM-DD  # the Monday before the sweep window
END_DATE=YYYY-MM-DD    # the Sunday closing the window

git log --since="$START_DATE 00:00:00 -0400" --until="$END_DATE 23:59:59 -0400" \
  --merges --grep '#[0-9]\+' --pretty='%H %s' origin/develop

# For each merged PR, list its inline review comments.
gh api repos/joeharris76/BenchBox/pulls/<PR>/comments \
  --jq '.[] | select(.user.login == "chatgpt-codex-connector[bot]")'
```

Bucket each comment as **Fixed (link the commit)**, **Already fixed by
earlier merge (link that merge)**, or **Still actionable (becomes a w-unit
in the TODO)**.

### Axis 2 — In-window blind-spot findings

`_project/blind-spots/YYYY-MM-DD-*.md` may have been filed during the same
review window by `/code review`, `/blind-spot`, or other paths. Codex
threads will not surface these — they came from local agents.

```bash
# Findings filed during the review window. Use explicit start/end dates so
# the listing is bounded to the actual sweep range; ${START_DATE:0:7} only
# scopes to a calendar month, which can pull pre-window findings or omit
# late-week ones.
ls _project/blind-spots/ \
  | awk -v s="$START_DATE" -v e="$END_DATE" '
      /^[0-9]{4}-[0-9]{2}-[0-9]{2}-/ {
        prefix = substr($0, 1, 10)
        if (prefix >= s && prefix <= e) print
      }
    '

# Note: `make blind-spots-list` (sweep_blind_spots.py list) filters by
# status/kind only and has no --since/--until. Do NOT use it to scope this
# axis: it pulls historical open findings outside the window and can omit
# in-window non-open findings, making the sweep scope inconsistent. If a
# date-window flag is added to sweep_blind_spots.py, replace the awk filter
# above with that command.
```

For each in-window finding:

- Cross-link it from the TODO's `description:` or relevant `w-unit notes:`.
- If the finding maps to a w-unit (e.g. a test was loosened in a PR Codex
  also commented on), add a `must_not_do:` line connecting them so a
  future agent picking up the w-unit cannot land the fix without
  addressing the blind-spot.
- If the finding is out-of-window or unrelated, mention it explicitly
  ("blind-spot 2026-MM-DD-foo is out-of-scope: process change tracked
  separately").

The 2026-05-01 sweep added the `do not fix Home.tsx without restoring
strict cold-load row counts` rule to its `must_not_do` list precisely
because cross-linking the blind-spot caught the regression-coverage
downgrade Codex itself never flagged.

### Axis 3 — Tests weakened in the window

Codex flags individual lines, not coverage downgrades. A PR can land a fix
that simultaneously loosens an assertion that was guarding the same
failure mode. The bug class is "assertion-loosening alongside fix lands
without a guard"; the original scan template had no axis for it.

```bash
# Source: the same merge range as Axis 1. Match Axis 1's inclusive end-of-day
# bound — bare `--until=$END_DATE` resolves to midnight at the *start* of
# END_DATE, which excludes test changes merged later on the closing day
# (precisely the changes this axis exists to catch).
git log --since="$START_DATE 00:00:00 -0400" --until="$END_DATE 23:59:59 -0400" -p \
  --diff-filter=M --pretty='format:%H %s' origin/develop \
  -- '*.spec.ts' '*.spec.tsx' '*test*.py' 'tests/' \
  | rg -B 5 -A 5 'toHaveCount\(.*\) ->|\.length\) ?=>|count.*>\s*0|expect\(.*\)\.toBeGreaterThan\(0\)|assert.*> 0'
```

Patterns to flag (non-exhaustive — extend as new patterns surface):

- Replacing `expect(X).toHaveCount(N)` / `assertEqual(len(...), N)` with
  `count > 0` / `length > 0` / `assertGreater(..., 0)`.
- Removing strict-equal mocks/fixtures and replacing them with
  fixture-DB polling (loses the byte-for-byte regression guarantee).
- Deleting a regression test entirely with no replacement (search for
  `removed test` / `unused test` / `flake` justification on the PR).
- Loosening `expect(..., {timeout: T1})` to `expect(..., {timeout: T2 > T1})`
  by an order of magnitude (often masks intermittent regressions).

For each match: if Codex did not flag it, file a w-unit OR a blind-spot
finding pointing at the diff. Do not silently accept "the team
simplified" without confirming the regression mode the original test
guarded is still covered.

### Axis 4 — Codex threads that were "marked resolved" without a fix

Codex's resolved-state in GitHub is unreliable: a contributor can resolve
a thread by replying or by clicking the resolve button, even if the code
was never changed. A thread that GitHub reports as resolved but for which
no commit in the window matches the fix description is a candidate for a
w-unit. The 2026-05-01 sweep used a manual cross-check; the next sweep
should script it:

```bash
gh api repos/joeharris76/BenchBox/pulls/<PR>/comments \
  --jq '.[] | select(.user.login == "chatgpt-codex-connector[bot]") | {id, body, path, original_position, original_commit_id}'

# Then: for each thread, search the merged-PR diff for content that
# matches the comment's path/anchor; if nothing changed in the comment's
# vicinity AND the thread is reported resolved, it's a phantom-resolution.
```

### Axis 5 — DONE-item verification commands that drifted

If the review window includes commits that touched a path or tool an
older DONE-item used in its `verification:` block (e.g. a script that
got renamed or an API that changed shape), the verification command may
silently no-op or fail. The 2026-05-01 policy decision below is
inherited:

> Historical DONE-item verification commands are kept executable. If a
> Codex finding identifies a portability or correctness defect in a
> DONE-item verification block, fix it in place. Rationale: those
> commands serve as runnable documentation of how the policy was
> confirmed, so anyone re-verifying the historical decision (forks,
> recreated rulesets, future audits) needs them to work.

## TODO file shape

Use `_project/TODO_ENTRY_TEMPLATE.yaml` as the base. The conventional
fields for a Codex sweep TODO:

- `id: codex-pr-review-followups-week-YYYY-MM-DD`
- `title: "Address unresolved Codex PR review follow-ups from the week ending YYYY-MM-DD"`
- `worktree: main`
- `priority: High`
- `category: Testing and Quality Assurance`
- `description:` — number of merged PRs scanned, number of Codex comments
  found, the policy decision quoted from Axis 5, AND a paragraph noting
  which in-window blind-spots were folded in vs out-of-scope (Axis 2).
- `work:` — one w-unit per still-actionable thread; one
  `summary: "Re-run the Codex thread scan and produce the rescan audit"`
  unit at the end whose `notes:` block lists the required audit sections.
- `must_not_do:` — must include cross-links from any folded-in
  blind-spots so the rule travels with the work.
- `verification:` — must include checks for each w-unit AND a check that
  the rescan audit file exists with the three required sections.

## Rescan audit shape

`_project/audits/codex-thread-rescan-week-YYYY-MM-DD.md` is the
per-sweep public record. Required sections:

1. `## Resolved By w1-wN` — one row per fixed thread, link to the
   commit that fixed it.
2. `## Already-Fixed By Earlier Merges` — one row per stale-but-OK
   thread, link to the merge that already fixed it.
3. `## Still Actionable` — one row per thread that needs a w-unit
   (should be empty after the sweep TODO completes).

## Closing the loop

When the TODO completes:

- Triage the cross-linked blind-spots — typically `--action actioned`
  with a one-line reason citing the TODO id.
- Mention the rescan audit file in the TODO's `final_notes:` block.
- If new patterns surfaced for Axis 3 (test-weakening) that this
  template did not list, add them here so the next sweep starts wider.
