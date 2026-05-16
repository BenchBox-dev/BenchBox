# Prompts Landing Phase 3 Platform Footgun Evidence

Checked on 2026-05-16 at repo SHA `67c0b1bf3062d3462d30ae12b526c21e31369df9`.

Scope:
- Searched `~/.claude/projects/-Users-joe-Developer-BenchBox` with `rg -g '*.jsonl'`.
- Counted 361 top-level session logs; subagent logs were included in pattern matches.
- Raw broad-match capture is local only at `/tmp/prompts-phase3-evidence-rg.log` and is not committed.
- Adapter-default review is local only at `/tmp/prompts-phase3-adapter-defaults.log`.

Observed matches by matching JSONL files:

| Pattern | Files |
|---|---:|
| `5285c89f` | 3 |
| `e47108b5` | 6 |
| `2fd35b2d` | 4 |
| `eed8fe29` | 9 |
| `b43e249e` | 6 |
| `9978f3bd` | 10 |
| `a970ce74` | 5 |
| `fceaed01` | 9 |
| `--platform-option` | 359 |
| `http_port` | 134 |
| `endpoint=sc` | 27 |
| `dsdgen` | 273 |
| `tpcds` | 1068 |

Adapter-default findings:
- SingleStore uses `port=3306` by default in `benchbox/platforms/singlestore.py`; this differs from the TODO's older `13306` note, so the catalog hint uses `3306`.
- QuestDB uses `pg_port=8812`, `http_port=9000`, and `ilp_port=9009`; the catalog hint calls out `http_port=9000`.
- Doris uses `port=9030`, `http_port=8030`, and `be_http_port=8040`; the catalog hints include the SQL and FE HTTP ports.
- StarRocks uses `port=9030` and `http_port=8040`; this differs from the TODO's older `8030` note, so the catalog hint uses `8040`.
- Velox remote mode uses `deployment=remote` and default Spark Connect endpoint `sc://localhost:50051`; the catalog hints include both.

Bundled TPC-DS binary evidence:
- `_binaries/tpc-ds/linux-arm64/dsdgen`
- `_binaries/tpc-ds/linux-x86_64/dsdgen`
- `_binaries/tpc-ds/darwin-arm64/dsdgen`
- `_binaries/tpc-ds/darwin-x86_64/dsdgen`

Interpretation:
- The sampled session IDs remain auditable, and the adapter review confirms the prompt should surface platform-option hints.
- Two TODO seed values had drifted (`singlestore` port and `starrocks` HTTP port); the implementation follows current adapter defaults.
