# Implement TODOs

## Steps

1. Run `todo ready`, then `todo claim <id>` for the full work order: scope,
   must-preserve notes, anti-patterns, verification, ready units, and deferrals.
   If `ready` warns about findings, run `todo finding candidates` and
   `todo finding triage <id> ...` before choosing new work. Findings are not
   claimable items.
2. For each work unit: run `todo start <id> <wid>` (optional), apply
   `shared-change-framework/SKILL.md` Section 1 before source-code edits,
   implement the unit, then run `todo done <id> <wid> --evidence "<command or commit or PR>"`.
3. Defer out-of-scope work immediately with
   `todo defer <id> --summary "..." --reason "..."`.
4. Before committing, run `todo check-scope <id>` and
   `todo verify <id> --run [seq]`.
5. Resolve every deferral with `todo promote <deferral-id> --to-item <slug>` or
   `todo dismiss <deferral-id> --reason "..."`. Then run
   `todo complete <id> --pr <n>`; it refuses unresolved deferrals.

## Findings

Use `todo finding candidates`, `todo finding triage`, `todo finding sync`, and
`todo finding promote` as documented in tracker help. Findings never enter the
ready queue.
