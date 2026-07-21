# Implement TODOs

1. `todo ready` picks the top ready item; `todo claim <id>` prints the work
   order: scope, must-preserves, anti-patterns, verification ladder, ready
   units, and deferrals. Treat it as the whole briefing.
2. Per unit, optionally `todo start <id> <wid>`, implement, then
   `todo done <id> <wid> --evidence "<command run / commit / PR>"`.
3. Defer skipped work immediately with `todo defer <id> --summary "..."
   --reason "..."`.
4. Before commit, run `todo check-scope <id>` and
   `todo verify <id> --run [seq]`. Complete with `todo complete <id> --pr <n>` only after units and
   deferrals resolve via `todo promote <deferral-id> --to-item <slug>` or
   `todo dismiss <deferral-id> --reason "..."`.
