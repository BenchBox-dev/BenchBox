---
name: docs
description: Use when the user asks to "create documentation", "build docs", "review docs", "compare documents", "compress docs", "adversarial review docs", or "commit docs".
version: 0.3.0
tools: Bash, Read, Write, Edit, Task
---

# Docs Workflow

Route the request below and read the selected action file. Preserve local
markup, navigation, and build conventions.

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
| `compare` | compare documents | `shared-investigation-framework/SKILL.md` (Compare section) |
| `shrink` | compress/shrink docs | `shared-investigation-framework/SKILL.md` (Shrink section) |
| `adversarial` | adversarial/user-perspective review | `references/adversarial.md` |
| `commit` | commit documentation | `references/commit.md` |
| `help` | help/list actions | this table |

## Global rules

- `review`, `adversarial`, and `compare` are read-only under
  `shared-review-protocol/SKILL.md`.
- Repository write actions use the shared change framework's named branch,
  verification, commit, and approved-plan PR workflow. The `commit` action
  handles existing documentation changes; it is not required for other writes.
- Shrink follows the shared framework and preserves frontmatter, commands,
  paths, thresholds, relationships, decisions, and public contracts. Compress
  READMEs, changelogs, decisions, generated docs, or study artifacts only when
  explicitly requested.
