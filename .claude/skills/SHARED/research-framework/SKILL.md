---
name: research-framework
description: Pre-edit investigation workflow for understanding code and behavior before changes.
---

# Research Framework

Mandatory before fixes, chained review remediation, performance changes, and standalone `/code research`.

## Steps

1. Scope affected path from request/error.
2. Read target file(s) plus at least one caller or test.
3. Trace data/control flow.
4. State current behavior in 2-3 sentences.
5. Form a `file:line` hypothesis.
6. Validate hypothesis before editing.

## Rules

- No file edits during research.
- Say when tests are absent.
- If scope spans more than 3 files, list them before deep reading.
- Output behavior, dependencies, coverage, risks.
