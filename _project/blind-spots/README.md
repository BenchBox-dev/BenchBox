# Blind-Spot Findings

Centralized capture for **blind-spot audit (L2)** findings produced during
reviews — observations that *may* warrant action but haven't been triaged yet.

This directory exists because audit findings printed only in chat get lost.
Persisting each finding as its own file makes the backlog sweepable later
without creating PR merge collisions.

---

## What goes here

A finding belongs in this directory when it surfaces:

- A **gap in a review framework** that was used (axis missing, dimension
  the rubric can't capture).
- A **bug class** behind a reported instance (the symptom was fixed, but
  the underlying pattern probably exists elsewhere).
- A **scope-creep flag** — work that wasn't requested but might be load-bearing.
- An **assumption worth testing later** — something that was true at audit
  time but might decay.
- Anything else that came out of a Blind-Spot Audit (L2) section in a review.

### What does NOT go here

- Concrete actionable bugs with a clear owner → make a TODO.
- Architectural decisions → `_project/decisions/` (ADRs).
- Full reviews / audits → `_project/audits/`.
- Random ideas / brainstorming → `_project/notes/`.

If unsure, write the finding here. The sweep step is where dismissals happen,
not the write step.

---

## File naming

```
YYYY-MM-DD-HHMMSS-<short-slug>.md
```

- The timestamp prefix gives total ordering and uniqueness — two parallel
  reviews on two branches can never produce the same filename. **This is
  what makes the directory merge-collision-safe.**
- The slug is grep bait, kept short (3–6 words).

Use the local clock; precision to the second is plenty.

---

## Frontmatter schema (required)

Every finding file must start with YAML frontmatter matching this shape:

```yaml
---
id: 2026-04-29-143205-react-key-collision-class   # = filename stem
date: 2026-04-29                                  # ISO date
status: open                                      # open | actioned | dismissed | merged-to-todo
finding_kind: bug-class                           # framework-gap | bug-class | missed-axis | scope-creep | assumption | other
review_context: "ultrareview B4 / chore/dashboard-keys"
related_paths:
  - benchbox/dashboard/charts/TimeSeries.tsx
  - benchbox/dashboard/charts/PercentileLadder.tsx
suggested_sweep: "grep for sibling key-collision instances before declaring class fixed"
todo_id: null                                     # populated when promoted via sweep
---
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Must equal filename without `.md` |
| `date` | yes | ISO `YYYY-MM-DD` |
| `status` | yes | One of: `open`, `actioned`, `dismissed`, `merged-to-todo` |
| `finding_kind` | yes | One of: `framework-gap`, `bug-class`, `missed-axis`, `scope-creep`, `assumption`, `other` |
| `review_context` | yes | Free-form: which review / branch / PR / agent surfaced this |
| `related_paths` | optional | Repo-relative paths the finding touches |
| `suggested_sweep` | optional | One-line hint for the sweep step |
| `todo_id` | optional | Slug of the promoted TODO, populated by `sweep_blind_spots.py triage promote` |

Anything else is rejected by `validate_blind_spot.py`. Keep frontmatter
minimal — long context belongs in the body.

---

## Body shape

Keep it short. These are seeds, not specs.

```markdown
# <Title — one line, no jargon>

## Finding
<verbatim audit text from the review — copy/paste, don't paraphrase>

## Why this matters
<one short paragraph on the lesson, not the instance>

## Suggested next steps
- [ ] <concrete action 1>
- [ ] <concrete action 2>
```

---

## How findings get written

Project `CLAUDE.md` binds Claude Code's L2 audits to this directory:
when an L2 audit is generated during any review, the audit is **written to
disk first**, then quoted in the chat response. The chat output becomes a
view of the persisted file, not a separate ephemeral artifact.

Humans (and other agents) can also invoke the `/blind-spot` slash command
to record one explicitly.

---

## How findings get triaged

Sweep on demand:

```bash
make blind-spots-list                # all open findings (one row each)
make blind-spots-report              # counts by status + kind, oldest open first
make blind-spots-sweep               # alias for blind-spots-report
```

Direct script invocations:

```bash
uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list --status open
uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py show <id>
uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py triage <id> --action dismiss  --reason "..."
uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py triage <id> --action actioned [--reason "..."]
uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py triage <id> --action promote  --todo-id <todo-slug>
```

Triage outcomes (each stamps frontmatter and appends a one-line entry under
`## Triage log` in the body):

- **`dismiss`** — sets `status: dismissed`. Use when the finding doesn't
  warrant action.
- **`actioned`** — sets `status: actioned`. Use when a fix landed without
  needing a separate TODO (e.g., handled inline during the same review).
- **`promote`** — sets `status: merged-to-todo` and fills `todo_id`.
  Authoring the TODO file itself is **your** job — use
  `_project/TODO_ENTRY_TEMPLATE.yaml` and place it under
  `_project/TODO/<worktree>/planning/<slug>.yaml`. The sweep script only
  records the link; it does not generate TODO YAML.

Findings stay in the directory after triage — they're a historical record of
what was noticed, not a working queue. Use `status` filters to scope sweeps.

---

## Why this won't cause PR merge collisions

There are exactly two ways markdown-in-git directories generate merge
conflicts, and both are designed out:

1. **Two branches editing the same file at the same offset** — avoided by
   one-file-per-finding with timestamped names. Two parallel reviews produce
   two filenames, not two diffs of one file.
2. **Two branches editing a shared index** — avoided by *not checking in any
   hand-maintained index*. The sweep produces transient reports, and TODO
   promotion goes through the existing `todo_cli.py` infrastructure (which
   already handles its own indexes via `generate_indexes.py`).

The only file that gets edited in place after creation is the finding's own
frontmatter `status:` line during triage. Triage happens serially on a single
branch, so two people aren't dismissing the same finding from two PRs. If
they ever did, the conflict is a 3-line YAML diff, trivial to resolve.
