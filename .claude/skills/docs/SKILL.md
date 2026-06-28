---
name: docs
description: Use when the user asks to "create documentation", "build docs", "review docs", "compare documents", "compress docs", "adversarial review docs", or "commit docs".
version: 0.2.0
tools: Bash, Read, Write, Edit, Task
---

# Docs Workflow

Documentation creation, validation, review, comparison, and compression.

## Config

Read `.claude/skills/skill-sync.config.yaml` `docs` section for builder, source dir, build/serve/linkcheck/validate commands, markup, doc-type locations, and personas. Fallback to repo docs config and Makefile.

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `create` | "create docs", "add documentation" | Add doc page in configured location and build |
| `build` | "build docs", "validate docs" | Run configured docs command |
| `review` | "review docs", "check docs" | Check accuracy, completeness, clarity, examples |
| `compare` | "compare documents" | Use SHARED/compare-framework/SKILL.md on claims and relationships |
| `shrink` | "compress docs", "shrink doc" | Use SHARED/shrink-framework/SKILL.md; preserve executable constraints |
| `adversarial` | "adversarial review", "user perspective" | Test from persona/journey perspective |
| `commit` | "commit docs", "commit documentation" | Commit modified docs |
| `help` | "help", "list actions" | Show actions |

## Hard Rules

- `review`, `adversarial`, and `compare` are read-only under SHARED/review-protocol/SKILL.md.
- Write actions verify with configured build/validate command before commit.
- Shrink must preserve frontmatter, commands, paths, thresholds, relationships, decisions, and public contracts.
- Do not compress READMEs, changelogs, decisions, generated docs, or study artifacts unless explicitly requested.

## Action Notes

- **Create:** infer type (`guide`, `reference`, `tutorial`, `concept`), create with local heading/markup style, add navigation/toctree if needed, build.
- **Build:** empty -> build; named input -> configured `clean`, `serve`, `linkcheck`, or `validate`.
- **Review:** verify commands/paths where practical; report broken examples, missing prerequisites, outdated CLI flags, organization issues.
- **Compare:** extract claims independently from both docs, compare meaning and relationship graph; >=0.95 equivalent, 0.85-0.94 review, <0.50 critical.
- **Adversarial:** use configured persona or default `new-user`, `developer`, `ops`, `contributor`; follow the journey literally and report friction.
- **Commit:** file scope from docs source dir; prefix `docs`; verify with docs build.
