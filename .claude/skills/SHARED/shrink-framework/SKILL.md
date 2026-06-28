---
name: shrink-framework
description: Validation-driven compression workflow that requires semantic comparison before approval.
---

# Shrink Framework

Compress without changing behavior, public interfaces, or safety rules.

## Allowed

Application source, agent-facing docs, config files. Do not shrink tests, generated files, vendored code, migrations, changelogs, or READMEs unless explicitly requested.

## Workflow

1. Validate file type and preserve constraints.
2. Save baseline.
3. Compress dead/repeated/verbose text only.
4. Compare baseline vs compressed with SHARED/compare-framework/SKILL.md.
5. Approve if score meets threshold and relevant checks pass; otherwise iterate up to 3 times.

## Preserve

Public API/interface, type contracts, side effects, error handling, dependencies, commands, paths, thresholds, safety rules, TODO/FIXME/why-comments, frontmatter required by skills or slash commands.

## Safe Cuts

Repeated examples, duplicate boilerplate, verbose report templates, comments that restate code, impossible defensive branches, and reference prose already covered by shared protocols.

## Decision

| Result | Action |
|---|---|
| Score >= threshold and checks pass | Replace original |
| Score >= threshold and checks fail | Fix or revert |
| Score < threshold and attempts remain | Restore missing semantics and retry |
| Score remains low | Report best version and ask |

## Report

State original size, new size, reduction, score, removed/simplified areas, checks run, and residual risk.
