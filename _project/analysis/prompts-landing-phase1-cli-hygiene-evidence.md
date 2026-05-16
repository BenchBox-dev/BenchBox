# Prompts Landing Phase 1 CLI Hygiene Evidence

Checked on 2026-05-16 at repo SHA `3a1037dd29bd1da656ec8e5f129bee2dce7ae828`.

Scope:
- Searched `~/.claude/projects/-Users-joe-Developer-BenchBox` with `rg -g '*.jsonl'`.
- Counted 361 top-level session logs; subagent logs were included in pattern matches.
- Raw broad-match capture is local only at `/tmp/prompts-phase1-evidence-rg.log` and is not committed.

Observed matches by matching JSONL files:

| Pattern | Files |
|---|---:|
| `--non-interactive` | 192 |
| `tail -20` | 252 |
| `force datagen` | 103 |
| `--force datagen` | 102 |
| `Summarise` | 3 |
| `summarize` | 288 |
| `tee` | 454 |
| `/tmp/.*\.log` | 94 |
| `benchbox results --paths` | 5 |
| `benchbox results show-cli` | 15 |
| `e47108b5-48e4-408d-a9d6-98d6ad875b69` | 6 |
| `2fd35b2d-f541-40f4-9abf-b44a40763116` | 4 |

Audit anchors:
- `e47108b5-48e4-408d-a9d6-98d6ad875b69.jsonl` and subagent logs are present.
- `2fd35b2d-f541-40f4-9abf-b44a40763116.jsonl` and subagent logs are present.
- The `2fd35b2d...` QuestDB remediation trace includes a live command using `--force datagen`.

Interpretation:
- The evidence supports keeping the TODO's local-session claims about recurring non-interactive, output-capture, summary, and force-datagen recovery needs.
- Counts are broad grep counts, not unique failure counts; they are used to justify prompt guardrails, not to quantify incident frequency.
