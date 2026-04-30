---
allowed-tools: Bash(date:*), Bash(git:*), Bash(ls:*), Bash(grep:*), Bash(wc:*), Bash(tr:*), Bash(test:*), Bash(uv:*), Bash(make:*), Write, Edit, Read
description: Record a blind-spot audit finding to _project/blind-spots/ (file-first capture)
---

## Context

- Branch: !`git branch --show-current`
- Date/time: !`date +%Y-%m-%d-%H%M%S`
- Open findings: !`ls _project/blind-spots/*.md 2>/dev/null | grep -v README | wc -l | tr -d ' '`

## Your task

The user wants to record a blind-spot audit finding. Follow the protocol in
`_project/blind-spots/README.md` exactly. Do **not** invent a different shape.

1. **Pick the slug.** From the user's description (the part after `/blind-spot`),
   derive a 3–6 word kebab-case slug capturing the *class*, not the *instance*.
   Example: "react keys collide on platform name" → `react-key-collision-class`.
   If the user gave nothing, ask one short clarifying question and stop.

2. **Compose the filename.** Use the timestamp from the Context block above:
   `_project/blind-spots/YYYY-MM-DD-HHMMSS-<slug>.md`. Filename stem must equal
   the `id` field in the frontmatter. If that exact path already exists, append
   a short numeric suffix before `.md` (`...-<slug>-2.md`, then `-3`, etc.).

3. **Write the file** using this exact frontmatter schema. Required fields are
   `id`, `date`, `status` (always `open` at write time), `finding_kind`, and
   `review_context`. Optional: `related_paths`, `suggested_sweep`, `todo_id`.

   ```yaml
   ---
   id: <filename stem>
   date: <YYYY-MM-DD>
   status: open
   finding_kind: <framework-gap | bug-class | missed-axis | scope-creep | assumption | other>
   review_context: "<one line: which review / branch / agent surfaced this>"
   related_paths:
     - <repo-relative path>
   suggested_sweep: "<one-line hint for the sweep step>"
   todo_id: null
   ---
   ```

   Body shape:

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

4. **Validate** the new file:

   ```
   uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py _project/blind-spots/<filename>
   ```

   If validation fails, fix the frontmatter and re-run. Do not commit a
   malformed finding.

5. **Report** to the user with one line and a quote of the body:

   ```
   Recorded: _project/blind-spots/<filename>.md

   <body content>
   ```

   Do not commit unless the user asks. The file lives on the current branch;
   it'll ride along with whatever PR is in flight.

## Notes

- Findings are **observations**, not actionable TODOs. Promotion-to-TODO is a
  sweep-step decision (`make blind-spots-sweep`), not a write-step decision.
- Keep the body short. Long context belongs in a TODO or audit doc.
- Never hand-edit `_project/blind-spots/_indexes/` — there is no checked-in
  index by design (avoids merge collisions). Reports are regenerated on demand.
