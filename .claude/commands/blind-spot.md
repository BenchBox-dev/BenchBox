---
allowed-tools: Bash(date:*), Bash(git:*), Bash(ls:*), Bash(grep:*), Bash(wc:*), Bash(tr:*), Bash(test:*), Bash(mkdir:*), Bash(uv:*), Bash(make:*), Write, Edit, Read
description: Capture a blind-spot audit finding as a draft in ~/.benchbox/finding-drafts/ (out-of-tree, zero-credential)
---

## Context

- Branch: !`git branch --show-current`
- Date/time: !`date +%Y-%m-%d-%H%M%S`
- Unsynced drafts: !`ls ~/.benchbox/finding-drafts/*.md 2>/dev/null | wc -l | tr -d ' '`

## Your task

Follow `docs/agent/review-protocol.md` exactly. Apply the
defect gate `[REVIEW-DEFECT-001]` **before** anything else: a finding that
materially affects correctness, performance, or security is a defect, not a
blind spot. If the gate triggers, refuse to file and offer the user the
TODO / inline-fix / escalation menu instead. If the gate passes:

1. **Pick the slug.** Derive a 3–6 word kebab-case slug capturing the
   *class*, not the *instance*. Example: "react keys collide on
   platform name" → `react-key-collision-class`. If the user gave
   nothing, ask one short clarifying question and stop.

2. **Compose the path** `~/.benchbox/finding-drafts/YYYY-MM-DD-HHMMSS-<slug>.md`
   using the timestamp from the Context block above (run
   `mkdir -p ~/.benchbox/finding-drafts` first). Drafts live outside every
   worktree — capture needs no credentials and no network, and per
   `[REVIEW-CAPTURE-001]` the draft file is the *sole* in-review write for a
   finding.
   Filename stem must equal the `id` field in the frontmatter. If the path
   collides, append `-2`, `-3`, … before `.md`.

3. **Write the file** using the frontmatter schema and body shape in
   `_project/blind-spots/README.md` (storage spec). Required fields are
   `id, date, status, finding_kind, review_context`. Optional capture fields:
   `observed_sha` and `evidence` (a list of `{path, pattern, note}`) for
   provenance; leave the triage fields (`urgency`, `breadth`, `confidence`)
   unset — they are assigned later at triage, never required at capture.

4. **Validate**:
   ```
   uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py ~/.benchbox/finding-drafts/<filename>
   ```
   If validation fails, fix the frontmatter and re-run.

5. **Report** with `Recorded: ~/.benchbox/finding-drafts/<filename>.md` and
   a quote of the body. **Stop there** — do not commit, do not push, do not
   run `make pr-open`, and do not write the finding into the tracker database.
   Per `[REVIEW-CAPTURE-001]` the draft file is local-only; syncing it into
   the tracker (`todo finding sync`) is a separate, user-authorized landing
   step.

## Notes

Behavior is governed by `docs/agent/review-protocol.md`.
Storage is governed by `_project/blind-spots/README.md`. Don't restate
either here.
