# Auto-merge-on-open stranding — forensic reconstruction

Source: `harden-auto-merge-on-open-stranding` (w0). Reconstructs, from git
history plus the GitHub API, why three fixes were committed but never reached
merged `develop` and had to be re-landed (§2.7 → #986, §2.16 → #996, §2.22 →
#997).

All SHAs below are still present in the repository (fetchable via
`git log --all` / `git show`, or `mcp__github__get_commit`), so every claim in
this document is directly re-verifiable.

## The confirmed mechanism (all three cases)

**This is not "auto-merge merged a stale SHA out from under an open PR."** In
all three cases, no PR ever existed for the stranded commit at all. The
pattern is:

1. A feature branch `B` has a commit `X`. A PR is opened for `B` and
   `auto-merge-on-open.yml` squash-merges it into `develop` at time `T1`. The
   PR is now **closed (merged)**.
2. The **same local branch/worktree `B`** stays checked out (not reset to the
   fresh `develop` tip, not replaced by a new branch) and, later, receives a
   **new commit `Y`** implementing unrelated or follow-on work.
3. `Y` is pushed to `origin/B` — but because `B`'s only PR already merged and
   closed, GitHub does not reopen it or create a new one. `pull_request:
   opened`/`synchronize` events only fire for a PR that is currently open, so
   `auto-merge-on-open.yml` (which is purely `pull_request`-event-triggered)
   never runs against `Y`.
4. `Y` sits on the still-existing remote branch `origin/B`, uncovered by any
   PR, until a later manual/forensic re-review discovers it and re-implements
   the fix under a fresh PR.

This does not match hypothesis (a) (a PR merging a stale head while a newer
push was in flight), because there was no open PR racing a push in any of the
three cases — the originating PR had already fully merged, in some cases
hours, before the stranded commit was even authored. It's closest to
hypothesis (b) ("PR closed... commits abandoned"), except the PR was closed
*by merging*, not left open-then-closed, and the abandoned commits were
authored **after** that merge, on the same branch name, rather than being
part of the merged PR's own history.

## Case §2.7 — re-landed via #986

- **Original PR:** #966 ("fix(publishing): reject invalid trust labels; fail
  on incomplete submission manifest (§2.3/§2.4)"), branch
  `remediate-submission-trust-label-enforcement`.
- **Merged SHA (squash, on develop):** `99b513fcd1fbe79fc922498b257c0c3534fcce18`
  — merged **2026-07-05T13:33:13Z**. PR head at merge time (per GitHub API):
  `aec4c1eb24face31b7554ca6486ec134bc9a1bd0`.
- **Stranded commit:** `43c4f689bf8e739ed633c997153321accfc284fc`
  ("ci(submission): reject validator/workflow changes in a corpus submission
  PR (§2.7)"), authored **2026-07-05T18:06:23Z** — **4h33m after #966
  merged** — directly on top of `aec4c1eb` (`git log
  aec4c1eb..origin/remediate-submission-trust-label-enforcement` shows exactly
  this one commit). `origin/remediate-submission-trust-label-enforcement`
  still exists on the remote and its tip is still `43c4f689`.
- **Verdict:** no PR was ever opened against
  `remediate-submission-trust-label-enforcement` a second time
  (`search_pull_requests head:remediate-submission-trust-label-enforcement`
  returns only #966). The §2.7 guard commit was authored and pushed to an
  already-merged-and-closed branch and was never covered by any PR event.
  **Mechanism: post-merge commit on a dead branch (closest to hypothesis (b),
  not (a)).**

## Case §2.16 — re-landed via #996

- **Original PR:** #964 ("docs(explorer-qa): fix S7.6 security mechanism,
  stale sample IDs, URL-sync + trigger claims"), branch
  `remediate-qa-and-browser-test-doc-accuracy`.
- **Merged SHA:** `c3155c16a32da2ae79e9881683db688256127632` — merged
  **2026-07-05T00:35:41Z**. PR head at merge: `5dff1a88cce478d3c2755a58b48be3b5b8f085b1`.
- **Stranded commit:** `cf394466a1422db63ea93546ef1d870d6d90c28a`
  ("docs(explorer-qa): make the QA plan reusable across passes (§2.16)"),
  authored **2026-07-05T12:35:40Z** — **12h** after #964 merged — directly on
  top of `5dff1a88` (the pre-squash head of the already-merged #964).
  `origin/remediate-qa-and-browser-test-doc-accuracy` still exists on the
  remote and its tip is still `cf394466`.
- **Compounding factor:** the *next* PR touching the same doc
  (#968, merged 2026-07-05T12:41:20Z, six minutes after `cf394466` was
  authored but on a different branch) explicitly asserted in its own body:
  "§2.16 (QA-plan reusability) landed with the QA-doc-accuracy change (#964)
  — same file" — a mistaken belief that §2.16 had already been handled,
  which is why nobody went back to open a fresh PR for the branch carrying
  `cf394466`.
- **Verdict:** same post-merge-commit-on-a-dead-branch mechanism as §2.7, plus
  a mistaken "already landed" assumption that suppressed any incentive to
  re-open a PR for it. `search_pull_requests
  head:remediate-qa-and-browser-test-doc-accuracy` returns only #964.

## Case §2.22 — re-landed via #997

- **Original PR:** #968 ("docs: fix governance/architecture doc drift (ADR
  index, stale evidence, CI descriptions)"), branch
  `remediate-governance-and-doc-drift`.
- **Merged SHA:** `a50ca2bf53fb425bb30d430fd9dd357e75edf101` — merged
  **2026-07-05T12:41:20Z**. PR head at merge: `2e51e894456c13b49f35dcf3ef6ce93f0ea490ca`.
  This PR's own body explicitly **deferred** §2.22 as a "low-risk cosmetic
  follow-up," i.e. at merge time the author's stated intent was *not* to land
  it yet.
- **Stranded commits:** `4865a2f24e5aed743d6209956da7b53a3d4d1de1` ("test:
  relocate explorer tests to mirror migrated source (§2.22)", authored
  **2026-07-05T13:04:45Z**, 23m after #968 merged) and
  `3368763728794ed7d9bc54e8f6a6029e6c8d6526` ("test: fix relocated-test
  imports and ADR paths (fixup for §2.22)", authored
  **2026-07-05T13:06:49Z**), both stacked directly on `2e51e894`.
  `origin/remediate-governance-and-doc-drift` still exists on the remote and
  its tip is still `33687637`.
- **Verdict:** the deferral was reversed minutes later on the same
  already-merged-and-closed branch, but — same as the other two cases — no
  new PR was opened to carry the reversal, so `auto-merge-on-open.yml` never
  ran against it. `search_pull_requests
  head:remediate-governance-and-doc-drift` returns only #968.

## Cross-case pattern

| Case | Original PR | Merged SHA | PR-head SHA | Merged at | Stranded commit(s) | Authored at | Gap |
|---|---|---|---|---|---|---|---|
| §2.7  | #966 | `99b513fc` | `aec4c1eb` | 2026-07-05T13:33:13Z | `43c4f689` | 2026-07-05T18:06:23Z | 4h33m |
| §2.16 | #964 | `c3155c16` | `5dff1a88` | 2026-07-05T00:35:41Z | `cf394466` | 2026-07-05T12:35:40Z | 12h00m |
| §2.22 | #968 | `a50ca2bf` | `2e51e894` | 2026-07-05T12:41:20Z | `4865a2f2`, `33687637` | 2026-07-05T13:04:45Z / 13:06:49Z | 23m–25m |

All three stranded commits are **direct children of the PR-head SHA that had
already been squash-merged**, on a **branch name that already had a merged,
closed PR**, authored **after** that merge. None of them was ever the head of
a *new* PR before the forensic re-review recovered them. The three still-live
remote branches (`remediate-submission-trust-label-enforcement`,
`remediate-qa-and-browser-test-doc-accuracy`, `remediate-governance-and-doc-drift`)
each still point at the stranded tip today.

## Implication for w1 (guard design)

`auto-merge-on-open.yml` is not itself defective — it correctly acts on every
PR event it receives. The actual gap is that **a commit pushed to a branch
whose PR already merged generates no PR event at all**, so there is no hook
point in the current CI graph that ever sees these commits. A guard has to
work from the *push* side (branch push, not PR event) or from a scheduled
sweep that diffs each remaining/stale remote branch against `develop`,
rather than hardening `auto-merge-on-open.yml`'s own merge-time logic (which
was never the point of failure). See the parent TODO's w1 unit for the
candidate designs; this document intentionally does not pick one, per the
TODO's own instruction to let w0's verdict — recorded here — decide it.
