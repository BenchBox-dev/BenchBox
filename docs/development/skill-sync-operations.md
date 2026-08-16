# skill-sync operations

Operational behavior of `make skill-sync` and `make skill-sync-check` that is
not obvious from their output. Policy — mirrors are generated, never hand-edited,
and integrity comes from PR review of the mirror diff plus the untracked-mirror
drift guard — lives in `AGENTS.md` under **Skills and generated mirrors**.

Skill source is `/Users/joe/.skill-sync/skills`. `.claude/skills` is tracked;
`.codex/skills`, `.gemini/skills`, and `.antigravity/skills` are generated
mirrors that are not.

## `make skill-sync` always dirties two files it did not change

**`skill-sync.lock`** is rewritten on every run with timestamp-only churn: the
`lockedAt` and `fetchedAt` fields move, while digests and pins stay identical.
The lockfile diff is therefore noise by default. `git checkout skill-sync.lock`
after syncing keeps the PR diff to the real change; `make skill-sync-check`
still passes without the rewritten timestamps.

**`.gitattributes`** is rewritten too: the CLI moves its managed block

```
# >>> skill-sync managed (do not edit) >>>
/.claude/skills/** -text
# <<< skill-sync managed <<<
```

to end-of-file. That conflicts with any `develop`-side `.gitattributes` change,
so sequence the two rather than landing them in parallel.

## The pin must be reachable from canonical `main`

The skill-sync CLI clones `--depth 1` of the default branch. A `skill-sync.yaml`
pin that exists only on a feature branch will not sync, and the failure is a
missing ref rather than an obviously wrong pin. Land the skill-source change on
`main` first, then advance the pin here.

## `skill-sync-check` reports false drift in a fresh worktree

In a newly created `git worktree`, `make skill-sync-check` reports `drift` and
`materialization` failures for the codex, gemini, and antigravity mirrors —
roughly 11 missing skills each. Those mirrors are local-only and unmaterialized
in a fresh checkout; only `claude` is tracked. The same command is clean in the
primary clone.

Judge a worktree run on the `claude` rows alone, or re-run in the primary clone
before treating drift as real.

## Project review checks need `config.code.review_checklist`

The shared five-axis review rubric carries no BenchBox-specific items. It applies
them only when `config.code.review_checklist` exists in `skill-sync.yaml`, which
`make skill-sync` then renders into the generated `code` skill.

The failure mode is silent: a project-specific check dropped from the shared
rubric, and not landed under that key, disappears from review with no error from
either the rubric or the sync. When removing a check from the shared rubric,
confirm it exists here first.
