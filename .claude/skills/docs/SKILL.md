---
name: docs
description: Use when the user asks to "create documentation", "build docs", "review docs", "compare documents", "compress docs", "adversarial review docs", or "commit docs".
version: 0.2.0
tools: Bash, Read, Write, Edit, Task
---

# Docs Workflow

Route the request to one action below. Before acting, read the file in the
Read column for the selected action. Preserve local markup, navigation, and
build conventions.

## Resolve

Read `.claude/skills/skill-sync.config.yaml` `docs` first for builder, source
directory, build/serve/linkcheck/validate commands, markup, doc locations, and
personas. Fall back to repo docs config and the Makefile.

## Actions

| Action | Trigger | Read |
|---|---|---|
| `create` | create/add documentation | `references/create.md` |
| `build` | build/validate docs | `references/build.md` |
| `review` | review/check docs | `references/review.md` |
| `compare` | compare documents | `SHARED/investigation-framework/SKILL.md` (Compare section) |
| `shrink` | compress/shrink docs | `SHARED/investigation-framework/SKILL.md` (Shrink section) |
| `adversarial` | adversarial/user-perspective review | `references/adversarial.md` |
| `commit` | commit documentation | `references/commit.md` |
| `help` | help/list actions | this table |

## Global rules

- `review`, `adversarial`, and `compare` are read-only under
  `SHARED/review-protocol/SKILL.md`.
- Write actions verify with configured build/validate commands before commit.
- Shrink preserves frontmatter, commands, paths, thresholds, relationships,
  decisions, and public contracts.
- Do not compress READMEs, changelogs, decisions, generated docs, or study
  artifacts unless explicitly requested.
