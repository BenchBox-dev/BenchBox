# Handoff Reference

Create a continuation prompt or session summary that lets another agent resume without rereading everything.

## Include

- Goal and current status.
- Files changed/read and why they matter.
- Decisions made and alternatives rejected.
- Commands run and results.
- Known failures, blockers, risks, and assumptions.
- Exact next steps with paths/commands.

## Modes

- `--compact`: under 300 words, highest-signal only.
- `--task`: produce a task prompt with objective, context, constraints, verification, and expected output.

## Rules

Do not claim work is committed, tested, pushed, or complete unless verified in the current session. Separate facts from recommendations.
