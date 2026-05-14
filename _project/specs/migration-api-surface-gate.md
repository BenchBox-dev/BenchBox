# Migration API Surface Gate

Status: active for remaining single-repo migration phases.

## Purpose

Bulk migration PRs can accidentally add user-facing commands, importable modules,
or filesystem conventions without a discrete design review. Before any remaining
single-repo migration phase is marked Done, its PR description must include an
API surface diff section that makes those changes explicit.

## Required PR Section

Each migration-phase PR must include:

```markdown
## API surface diff

- New CLI commands: <none | list with audience tags>
- New console_script entry points: <none | list>
- New public Python imports: <none | list>
- New filesystem conventions: <none | list config dirs, env vars, generated paths>
- Approval: <maintainer-approved in this PR | covered by ADR/TODO link | none>
```

Use `none` explicitly. An omitted row is not equivalent to no change.

## Classification

| Class | Meaning | Required action |
| --- | --- | --- |
| Approved public surface | Intended for users or external automation | PR body names the maintainer approval or links the ADR/spec. |
| Internal implementation surface | Importable only because it supports an approved command or test | PR body names the owning command/module and why no public docs are added. |
| Accidental surface | Arrived through migration mechanics without a decision | Remove it in the PR, hide it, or file/link a remediation TODO before Done. |
| Retired surface | Deleted or made unreachable by the phase | List it under removals when relevant; no approval needed unless compatibility changes. |

## Review Checklist

Run targeted probes before writing the PR body:

```bash
git diff --name-only origin/develop...HEAD -- 'benchbox/cli/**' 'benchbox/**/__init__.py' 'pyproject.toml' 'Makefile' '.github/workflows/**'
git diff origin/develop...HEAD -- 'benchbox/cli/**' | rg '@click\.(command|group)|console_scripts|entry_points'
git diff origin/develop...HEAD -- 'benchbox/**/__init__.py'
git diff origin/develop...HEAD -- . | rg 'BENCHBOX_[A-Z0-9_]+|~/.benchbox|benchmark_runs|results-data|results-explorer/public/data'
```

The probe list is intentionally lightweight. It is a review gate, not a new CI
tool. If a phase touches a different surface family, add a targeted grep for
that family in the PR body.

## Completion Rule

A migration TODO cannot move to DONE unless the PR body contains the API surface
diff section or the TODO explains why no PR was opened. Any accidental surface
found by the gate must be removed, approved, or routed to a follow-up TODO before
completion.
