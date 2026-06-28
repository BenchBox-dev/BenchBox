---
name: todo
description: Use when the user asks to "create a TODO", "manage TODOs", "show TODO items", "prioritize TODOs", "implement a TODO", "implement a batch of TODOs", "batch implement TODOs", "review TODOs", "complete a TODO", "cleanup TODOs", "create TODOs from spec", "initialize TODO system", "ideate on an idea", "refine an idea", "write a spec", or "create a specification".
version: 0.6.0
tools: Bash, Read, Edit, Write, Task
---

# TODO Workflow

YAML TODO management with dependency graphs, indexes, and implementation guardrails.

## Paths And Commands

Resolve paths from `todo.config.yaml`, else `_project/TODO` and `_project/DONE` at git root. Indexes live under `_indexes/` and are generated, never hand-edited.

```bash
TODO_CLI="uv run --project ~/.claude/tools/todo todo-cli"
TODO_VALIDATE="uv run --project ~/.claude/tools/todo todo-validate"
TODO_INDEX="uv run --project ~/.claude/tools/todo todo-index"
```

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `init` | "initialize TODOs", "setup TODO system" | Bootstrap config, dirs, schema/template, indexes |
| `list` | "show TODOs", "list items" | Query items, stats, ready queue |
| `create` | "create TODO", "add item" | Create validated item(s) with work units and guardrails |
| `prioritize` | "prioritize", "rebalance" | Rebalance priorities using impact/deps/effort/time |
| `implement` | "implement TODO", "work on" | Execute ready work units with guardrails, tests, commits |
| `batch` | "implement these TODOs", "batch implement", "work through this group of TODOs" | Drive a deduped TODO group through implement -> verify -> complete -> `code` review -> fix -> PR; one PR per TODO; local scratch ledger; polls not-ready deps; stops only when every item is terminal |
| `review` | "review TODO quality" | Score clarity, completeness, actionability, freshness, guardrails, work breakdown |
| `complete` | "mark complete", "finish TODO" | Move completed item to DONE and reindex |
| `cleanup` | "cleanup TODOs", "commit TODO changes" | Validate graph/schema, cleanup, commit |
| `from-spec` | "TODOs from spec", "parse requirements" | Convert spec into TODO YAML |
| `ideate` | "ideate", "refine idea", "brainstorm" | Diverge/converge on ideas, surface assumptions |
| `spec` | "write spec", "create specification" | Produce decision-ready spec before code |
| `help` | "help", "list actions" | Show actions |

## Hard Rules

- Write actions auto-cleanup after verification and commit/push through SHARED/commit-framework/SKILL.md.
- `batch` is a write action: use one local scratch state file, one PR per TODO, and no mid-batch stop for ordinary wait states — record pending CI as `waiting`; use bounded, announced monitoring only for batch-owned dependency gates that must resolve before another TODO can proceed. Deterministic gate runs (per-item suite, PR-open equivalent, CI status) are delegatable to a low-effort subagent for run-and-report only — see SHARED/verify-framework/SKILL.md. See `references/batch.md`.
- Plain `review` is read-only under SHARED/review-protocol/SKILL.md; after findings apply its L2 audit.
- Implementation must read the TODO guardrails, research target code, respect `scope_limit`, test each work unit, mark work done, and commit incrementally.
- Use flat `work[]` with `needs` edges; inter-item dependencies go in `deps.needs`.
- See `references/structure.md` for schema, statuses, commands, and layout.

## Action Notes

- **Init:** create default config/dirs, copy schema/template, generate empty indexes.
- **List:** `$TODO_CLI list|stats|ready`; support priority/status/worktree filters.
- **Create:** parse title(s) or conversation; slug id; choose worktree/phase/priority/category; add `work[]`, `deferred[]`, optional `deps.needs`; for code work add specific `verification`, `must_preserve`, `approach`, and risk-only `anti_patterns`/`scope_limit`. When the TODO adds a new module, env var, or file-system convention, also add `prior_art` listing existing patterns considered (`<path>:<concept> — reuse / extend / supersede`).
- **Prioritize:** ideal active distribution is Critical 0-2, High 3-5, Medium-High 5-10; update and reindex.
- **Implement:** confirm ready, get `$TODO_CLI next <slug>`, move planning -> active, implement ready units using SHARED/research/slicing/verify, run verification, `$TODO_CLI done`, commit changed files only.
- **Batch:** dedupe inputs; read all TODOs; sort in-batch `deps.needs`; keep an uncommitted scratch ledger at an already-ignored local path; process the next ready TODO; for each item run `implement` -> verification -> `complete` -> `code review` (or equivalent five-axis review) -> fix Critical/Required findings (apply Nit/Consider only within `scope_limit`; log skipped Nit/Consider in the PR body) -> re-verify/re-review as needed -> commit via SHARED/commit-framework then the project PR-open equivalent; record pending CI as `waiting`, use bounded announced monitoring only for batch-owned dependency gates, retry once; mark `blocked` only for hard blockers. An in-batch `deps.needs` edge means the upstream PR must merge before the dependent TODO becomes ready (unless a stacked-branch exception is recorded). One `batch` invocation over a named TODO set is a single authorization for the per-item implement/commit/PR/auto-merge cycle. See `references/batch.md`.
- **Review:** grade 0-3 across clarity, completeness, actionability, freshness, guardrails, work breakdown; Required findings for vague verification, broad scope, missing dependencies, legacy nested format, or missing `prior_art` when the TODO adds a new module/env-var/file-system convention (cite at least one existing pattern with file path; score 0 if absent, 3 if present with reuse decisions). Freshness has an evidence-durability sub-axis: when `description` cites upstream evidence (specific dependency version, harness PASS, observed external behavior), require either a `w0:` re-validation work unit with a committed compact summary of command, checked SHA/version, PASS/FAIL, and key lines/counts, or an explicit pin of the evidence. Raw stdout belongs in ignored local paths, CI artifacts, or `BENCHBOX_OUTPUT_DIR`, not committed `_project/verification-logs/*.log` transcripts. Score 0 for cited-but-unbound evidence, 3 for re-runnable+summarized.
- **Complete:** require all work done/no blockers, set `Completed` + date, `git mv` to DONE, reindex.
- **Cleanup:** `$TODO_CLI check-graph`, `$TODO_CLI cleanup`, `$TODO_VALIDATE --all`, `$TODO_INDEX`, commit TODO/DONE files.
- **From-Spec:** parse markdown/yaml/text into items and work units; support `--dry-run`; write planning items, validate, index. If the spec was authored outside the spec/ideate flow, apply plan-deepening L3 to separate requirements from upstream constraints.
- **Ideate:** restate as problem, ask only material questions, generate options, stress-test assumptions, recommend MVP/not-doing/open questions; before recommending, apply plan-deepening L3 and the L2 missed-dimension question inline, note any reframe; save only after confirmation.
- **Spec:** state assumptions, define objective, commands, structure, style, tests, boundaries, success criteria, and review gate; before finalizing apply plan-deepening L3, include a reframe only if it changes the spec; save only after confirmation.

- Read `scope_limit`/`must_preserve`/`anti_patterns`/`verification` before broad code. Read TODO `verification:` first; run the narrowest listed/targeted check before broad gates. For TODO-backed PRs, diff `--name-only` against `scope_limit.only_modify` before content.
