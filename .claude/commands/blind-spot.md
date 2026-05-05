---
allowed-tools: Bash(date:*), Bash(git:*), Bash(ls:*), Bash(grep:*), Bash(wc:*), Bash(tr:*), Bash(test:*), Bash(uv:*), Bash(make:*), Write, Edit, Read
description: Record a blind-spot audit finding to _project/blind-spots/ (file-first capture)
---

## Context

- Branch: !`git branch --show-current`
- Date/time: !`date +%Y-%m-%d-%H%M%S`
- Open findings: !`ls _project/blind-spots/*.md 2>/dev/null | grep -v README | wc -l | tr -d ' '`

## Your task

Follow the synced `SHARED/review-protocol` skill exactly. Apply §2
(defect gate) **before** anything else. If the gate triggers, refuse
to file and offer the user the TODO / inline-fix / escalation menu
described in SHARED §2. If the gate passes:

1. **Pick the slug.** Derive a 3–6 word kebab-case slug capturing the
   *class*, not the *instance*. Example: "react keys collide on
   platform name" → `react-key-collision-class`. If the user gave
   nothing, ask one short clarifying question and stop.

2. **Compose the filename** `_project/blind-spots/YYYY-MM-DD-HHMMSS-<slug>.md`
   using the timestamp from the Context block above. Filename stem must
   equal the `id` field in the frontmatter. If the path collides, append
   `-2`, `-3`, … before `.md`.

3. **Write the file** using the schema and body shape in
   `_project/blind-spots/README.md` (storage spec).

4. **Validate**:
   ```
   uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py _project/blind-spots/<filename>
   ```
   If validation fails, fix the frontmatter and re-run.

5. **Report** with `Recorded: _project/blind-spots/<filename>.md` and
   a quote of the body. **Stop there** — do not commit, do not push,
   do not run `make pr-open`. Per SHARED §4, the disk-write is local-only.

## Notes

Behavior is governed by `SHARED/review-protocol`.
Storage is governed by `_project/blind-spots/README.md`. Don't restate
either here.
