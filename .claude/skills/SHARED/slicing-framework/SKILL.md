---
name: slicing-framework
description: "Build multi-file changes in thin vertical slices: implement, test, verify, commit, repeat."
---

# Slicing Framework

Use for multi-file work, features, refactors, or any change likely to exceed about 100 lines before testing.

## Rules

- Start with the simplest thing that can work; avoid premature abstractions.
- Touch only task-required code; surface adjacent issues as "noticed but not touching."
- Prefer vertical slices; use contract-first for parallel components and risk-first for uncertainty.
- Each slice must implement, test, verify, and commit one logical behavior.
- Keep the project buildable and each increment independently revertible.
- New incomplete code stays disabled by default.
