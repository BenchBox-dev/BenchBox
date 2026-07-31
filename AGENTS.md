# BenchBox Agent Guide

This file is the project authority for agent work. Keep it compact: detailed
operations belong in the linked docs, and generated skill mirrors belong to
`/Users/joe/.skill-sync/skills`.

## Authority and provenance

Apply instructions in this order:

1. platform/system safety and tool constraints;
2. the user's current request and explicit approvals;
3. this repository guide and the active project protocol;
4. loaded skills and mechanical tool output;
5. recommendations, examples, and historical notes.

`[AUTH-PROVENANCE-001]` Classify a requirement before acting: task authority,
repository policy, mechanical constraint, or recommendation. State the source
when it changes scope, identity, publication, or destructive behavior. Never
turn a recommendation or earlier task instruction into a standing requirement.

`[COMMIT-IDENTITY-001]` Resolve Git identity and inspect its config origin
before committing. Repository-local values override the user's global identity
but are not automatically intentional. Reject known agent/service identities
unless the user explicitly requests that exact identity for the current task.
Do not add an agent/service `Co-Authored-By` trailer or equivalent attribution
unless the current task explicitly requests that exact trailer; a stale request,
tool convention, or claim of agent contribution is not authorization.

## Authorization boundary

`[REVIEW-AUTH-001]` Reviews, audits, research, explanations, and diagnoses are
read-only except for explicitly authorized local capture. Do not remediate,
commit, push, open a PR, or write hosted tracker state without authorization.
A bundled request to review and fix remains review-only; remediation requires
explicit authorization in a later user turn. Its immediate action is findings
only, with zero tracked worktree-content changes; do not review and then edit
locally in the same turn. Implementation requests authorize the narrow
implementation workflow, not unrelated cleanup or external actions.

`[REVIEW-DEFECT-001]` Keep concrete correctness, security, or performance
defects in the review/action path; do not relabel them as blind spots.
`[REVIEW-L2-001]` L2 captures missed review dimensions, not defects already
found. `[REVIEW-CAPTURE-001]` In-review findings capture is local-only under
`~/.benchbox/finding-drafts/`; hosted sync needs separate authorization.

The active BenchBox binding and examples are in
`docs/development/agent-review-protocol.md`. It supersedes the legacy
`docs/development/review-protocol.md` document.

## Worktree and change safety

The primary clone `/Users/joe/Developer/BenchBox` is read-only for agents.
Before any edit, branch change, commit, push, or PR action:

```bash
make worktree-claim BRANCH=fix/descriptive-slug
cd <WORKTREE_PATH>
make agent-write-preflight
```

Stop if `git rev-parse --show-toplevel` is the primary clone. Emergency writes
there require explicit user authorization and
`BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1`. Preserve unrelated dirty work. Never use
destructive Git/filesystem commands without explicit approval. Use `rg`, and
stage only authorized paths; never `git add -A`.

A disposable clone — a remote agent session, a CI runner — has no canonical
clone to protect and no worktree pool to claim from, so it declares itself with
`BENCHBOX_EPHEMERAL_CLONE=1` instead of reaching for the emergency override.
The declaration is ignored wherever a pool is present, so it cannot weaken the
guard on a machine that uses one.

## Tooling and implementation

- Prefer repository `make` targets and existing helpers.
- Python tooling is `uv` only: `uv run -- ...`, `uv add`, `uv sync`, `uv lock`.
- Research the affected path, make the narrowest coherent change, and preserve
  compatibility and critical-path performance.
- Use Python 3.10+, four spaces, 120 columns, Ruff, and public API type hints.
- No credentials in Git; redact logs and use environment variables.
- Live cloud tests and broad/destructive cleanup require explicit approval.

For long output, write `/tmp/<slug>.log` and report status plus a short tail.
UAT/stress runs instead use `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`;
announce command, maximum runtime, log path, and stop condition. Do not commit
raw logs, screenshots, browser reports, or generated binary evidence unless it
has an identified durable consumer.

## Verification and close-out

Read a claimed TODO's `verification` ladder and run the narrowest proof first.
Useful local checks:

```bash
uv run -- python -m pytest -m fast -q
uv run -- ruff check .
uv run -- ruff format --check .
uv run -- ty check
```

Before publication, self-review with the `code` skill's review action and fix
all issues, considerations, and nits unless the user explicitly opts out. Run
`make pr-preflight` once, then `make pr-open`. Delegate boilerplate gates to a
low-effort subagent when available; the main agent chooses the command and
interprets failures. Do not poll CI: pending is a valid terminal state.

Dev PRs target `develop`, use squash merge, and never direct-push protected
branches. Force-push only feature/pool branches with `--force-with-lease`.
Soundness paths listed by `_project/scripts/auto_merge_soundness_paths.py`
require maintainer review and remain excluded from auto-merge. A drift/pinning
guard and its required-CI wiring must land in the same PR.

## TODO tracker

The shared database is the only TODO record. `_project/scripts/todo` is the
only write path; global `--db`/`--actor` flags precede the subcommand. Tracker
writes follow the same worktree policy. `todo claim <id>` prints the binding
work order; follow its scope, preserve rules, anti-patterns, dependencies, and
verification. Exit 2 means fix the cause, never bypass it. `todo ready` and
`todo stats` print an untriaged-findings banner on stderr when open findings or
unsynced drafts exist; triage via `todo finding candidates` (`finding
list`/`show`/`candidates` are read-only; findings are review blind spots, never
claimable items).

## BenchBox invariants

- Timing durations use `benchbox.utils.clock.mono_time()` and
  `elapsed_seconds()`; wall clocks are only for event/audit timestamps.
- Adapter SDK imports stay lazy. New SQL platforms subclass `PlatformAdapter`
  and register with `@register_platform`.
- CREATE TABLE rewrites are registered under `Phase.DDL_OPTIMIZE`; run
  `make compat-docs-check` and the DDL drift inventory check.
- Dependency upper bounds are exceptional. Current high-risk caps are
  `sqlglot<31`, `click<9`, `pydantic<3`, `pyarrow<24`, and `duckdb<2`.
- CLI dry runs must propagate explicit phases; deterministic runs use a seed.
- Green focused/fast tests are not UAT or production certification.

Apple/macOS notes: `make test-correctness-gate` uses Linux-generated digests;
use `make ci-linux` for parity. Mocker is local-only and unsuitable for the
known multi-service stacks; follow `docs/operations/uat-framework.md` for
container lifecycle and cleanup. Never globally prune without approval.

## Skills and generated mirrors

Stable wrappers are `code`, `test`, `todo`, `todo-db`, `blog`,
`benchbox-workflow`, `skill-sync`, and `tidy-perms`. `todo` authors ideas/specs;
`todo-db` owns tracker actions. Skill source is
`/Users/joe/.skill-sync/skills`; `.claude/skills`, `.codex/skills`,
`.gemini/skills`, and `.antigravity/skills` are generated mirrors. Run
`make skill-sync`, never hand-edit a mirror.

## Operational references

- PR/admin policy: `docs/operations/repo-admin-settings.md`
- UAT: `docs/operations/uat-framework.md`
- Release: `docs/operations/release-guide.md`
- Run lifecycle: `docs/development/run-lifecycle-map.md`
- Validation: `docs/development/result-integrity-validation.md`
- Adapter authoring: `docs/development/adding-new-platforms.md`
- SQL compatibility: `benchbox/sql_compat/README.md`
- Test taxonomy/lock: `tests/README.md`
- Instruction evaluation: `docs/operations/agent-instruction-evaluation.md`
