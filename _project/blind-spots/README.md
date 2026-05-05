# Blind-Spot Findings

Storage for **blind-spot audit (L2)** findings: framework gaps, post-fix
pattern notes, and dormant assumptions. One file per finding, sweepable
later without PR merge collisions.

## Behavior is governed elsewhere

The rules for **when** to write a finding here, **what** counts as a
blind spot vs a defect, and **what** capture authorizes (and does not
authorize) live in `~/.claude/skills/SHARED/review-protocol.md`. This
README documents only **storage**: frontmatter schema, file naming,
validation, and sweep workflow. Defects (anything that materially
affects correctness, performance, or security) go to TODOs, not here —
see SHARED §2.

---

## File naming

```
YYYY-MM-DD-HHMMSS-<short-slug>.md
```

- The timestamp prefix gives total ordering and practical uniqueness. If the
  exact target path already exists (same second + same slug), append a short
  numeric suffix such as `-2` before `.md`. **This is what makes the directory
  merge-collision-safe.**
- The slug is grep bait, kept short (3–6 words), lowercase kebab-case with no
  empty segments or trailing hyphen.

Use the local clock; precision to the second is plenty when paired with the
exists-before-write suffix rule.

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
| `related_paths` | optional | Repo-relative paths the finding touches; list of strings or `null` |
| `suggested_sweep` | optional | One-line hint for the sweep step; string or `null` |
| `todo_id` | optional | Non-empty slug of the promoted TODO, populated by `sweep_blind_spots.py triage promote`; `null` while open |

Anything else is rejected by `validate_blind_spot.py`. Keep frontmatter
minimal — long context belongs in the body.

---

## Body shape

Keep it short. These are seeds, not specs. `validate_blind_spot.py` enforces
the top-level title plus the three required `##` sections below.

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

Behavior governed by `~/.claude/skills/SHARED/review-protocol.md` §4.
When that protocol authorizes a capture, the file is written here on
the local branch and surfaced in chat with a `Recorded: <path>` line.
The capture is local-only — it does not authorize a commit beyond the
file, a push, or a PR. Use the `/blind-spot` slash command for explicit
recording.

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

Triage outcomes (each updates only `status` / `todo_id` in frontmatter and
appends a one-line entry under `## Triage log` in the body):

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
   one-file-per-finding with timestamped names plus the exists-before-write
   suffix rule. Two parallel reviews produce two filenames, not two diffs of
   one file.
2. **Two branches editing a shared index** — avoided by *not checking in any
   hand-maintained index*. The sweep produces transient reports, and TODO
   promotion goes through the existing `todo_cli.py` infrastructure (which
   already handles its own indexes via `generate_indexes.py`).

The only file that gets edited in place after creation is the finding's own
frontmatter `status:` / `todo_id:` line during triage plus its own
`## Triage log` section. Triage happens serially on a single branch, so two
people aren't dismissing the same finding from two PRs. If they ever did, the
conflict is a small finding-local diff, not a shared-index conflict.
