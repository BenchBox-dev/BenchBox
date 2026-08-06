# Implement TODOs

## Steps

1. Pick the next item: `todo ready` shows the top ready item. `todo claim <id>` prints the full work order — scope, must-preserve notes, anti-patterns, verification steps, ready units, and deferrals. Treat it as the complete briefing. If `ready` prints a warning on stderr about untriaged findings, run `todo finding candidates` and `todo finding triage <id> ...` to clear them before you pick new work. Findings are review blind spots, not claimable items.
2. For each work unit: run `todo start <id> <wid>` (optional), implement the unit, then `todo done <id> <wid> --evidence "<command or commit or PR>"`.
3. Defer out-of-scope work at once: `todo defer <id> --summary "..." --reason "..."`.
4. Before you commit: run `todo check-scope <id>` and `todo verify <id> --run [seq]`.
5. Complete: `todo complete <id> --pr <n>` — but first resolve every deferral with `todo promote <deferral-id> --to-item <slug>` or `todo dismiss <deferral-id> --reason "..."`. The command refuses if deferrals remain.

## Findings

Triage through `todo finding candidates`, `todo finding triage`, `todo finding sync`, and `todo finding promote`. See the finding commands in the tracker help. Findings never enter the ready queue.
