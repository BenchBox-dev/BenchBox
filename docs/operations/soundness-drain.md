<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Soundness-PR drain digest

```{tags} contributor, operations, ci
```

## The signal, and what it is not

Soundness-path PRs (see `_project/scripts/auto_merge_soundness_paths.py`'s
`SOUNDNESS_PREFIXES`, mirrored in `.github/CODEOWNERS`) correctly **never
auto-merge**. `.github/workflows/auto-merge-on-open.yml` withholds or revokes
squash auto-merge the moment a PR's diff touches the comparator/parser
surface, the oracle-adjacent reference data, the `sql_compat` rule-dispatch
core, or the gate machinery itself. That withholding is intentional — CI
cannot catch a change that redefines the oracle it validates against, so
those PRs must be reviewed and merged by hand.

What the gate does not do on its own is tell anyone a PR is *waiting*. Two
PRs (#1116, #1142) sat parked for days, accumulating merge conflicts,
before anyone noticed. **This digest is purely observational** — it adds a
daily "someone should look at this" signal on top of the unchanged gate. It
never merges, approves, or otherwise changes a PR's mergeability. The only
mutations it performs are:

1. adding/removing the `awaiting-owner` label to match the current queue, and
2. creating/updating a single pinned tracking issue with the digest text —
   and only when the queue is non-empty.

## How a PR qualifies for the queue

`_project/scripts/soundness_drain_report.py` lists every OPEN PR targeting
`develop` and includes a PR in the digest when **all** of the following
hold:

- **(a) required-lane green** — the `ci-required-result` check run (the
  aggregate required-check job defined in `.github/workflows/pr.yml`) on the
  PR's head SHA completed with `conclusion: success`.
- **(b) awaiting the owner** — auto-merge is currently OFF, **and** either
  the diff touches a soundness-critical path (reused via
  `any_soundness_path` imported from `auto_merge_soundness_paths.py` —
  never re-derived or edited), or the owner (`joeharris76`, per
  `.github/CODEOWNERS`) is a requested reviewer.
- **(c) parked > 24h** — more than 24 hours of park time (see below).
  The gate deliberately does NOT use `updated_at`: the script's own label
  writes and ordinary human comments bump `updated_at`, so an idle-based
  gate would flap a genuinely parked PR out of the queue every time the
  signal fires.

Draft PRs are always excluded regardless of the above.

### Park time

Each qualifying PR also reports **park time**: hours since the PR became
ready-and-green, anchored on the `ci-required-result` check run's
`completed_at` (falling back to `updated_at` if that timestamp is
unavailable). This is emitted per PR in both the text digest and `--json`
output, and is the intended input for park-time re-measurement work (the
WS9 re-measure references this field rather than recomputing it).

## Running locally

```bash
uv run -- python _project/scripts/soundness_drain_report.py            # human digest, read-only
uv run -- python _project/scripts/soundness_drain_report.py --json      # machine-readable, read-only
uv run -- python _project/scripts/soundness_drain_report.py --apply     # also syncs the label + pinned issue
uv run -- python _project/scripts/soundness_drain_report.py --self-test # fixture-only, no network
```

Auth is a short token-source chain, never a long-lived PAT: `GITHUB_TOKEN`
or `GH_TOKEN` from the environment first; if neither is set and the `gh`
CLI is on `PATH`, its own token (`gh auth token`) is used. Without `--apply`
the script only reads — no labels or issues are touched.

## The `awaiting-owner` label

The label is fully owned by this script under `--apply`: it is added to
every currently-qualifying PR and removed from any evaluated PR that no
longer qualifies (check went red, auto-merge got re-enabled, idle dropped
back under 24h on a fresh push, etc.). Do not hand-manage it — the next
scheduled run will reconcile it back to the computed set.

## The daily digest issue

`.github/workflows/soundness-drain.yml` runs the report on a daily schedule
(`workflow_dispatch` is also available for an on-demand run) and calls
`--apply`. The digest is posted to a single pinned issue titled
**"Soundness-PR drain queue"** — found by exact title plus a body marker
(`<!-- soundness-drain-digest -->`, so a human issue reusing the title is
never adopted or clobbered) and updated in place (or created if it doesn't
exist yet), never as per-PR or per-event comments. When the queue drains,
an existing digest is patched to the empty state exactly once; after that
an empty queue produces no create, no update, no notification. This keeps
the signal to at most one digest a day, silent on a clean queue, and never
leaves a stale "parked" list showing after the queue empties.

The workflow uses the default `GITHUB_TOKEN` with a minimal permissions
block (`contents: read`, `pull-requests: write`, `issues: write`) and never
`pull_request_target`.
