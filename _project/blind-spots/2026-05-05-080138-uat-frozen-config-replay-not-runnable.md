---
id: 2026-05-05-080138-uat-frozen-config-replay-not-runnable
date: 2026-05-05
status: open
finding_kind: assumption
review_context: "/code review of PR #205 (UAT framework W2-W11)"
related_paths:
  - tests/uat/configs/uat-2026-05-02.yaml
  - tests/uat/test_replay_2026_05_02.py
  - tests/uat/test_frozen_configs.py
suggested_sweep: "any 'frozen historical record' pattern in the repo — audit whether the freeze guarantees runnability at thaw time, or only readability."
todo_id: null
---

# Frozen-config policy proves the file hasn't changed; not that it can still drive a sweep

## Finding
The frozen-config mechanism (`tests/uat/configs/uat-2026-05-02.yaml`
+ `.frozen-hashes.json` + `test_frozen_configs.py`) catches edits to
the file. The slow-marked replay test runs the orchestrator with
`dry_run=True`, which short-circuits every phase. Together these
guarantee the YAML bytes haven't changed and that the file parses.
They do NOT guarantee the file would actually drive a real sweep
months from now, because:

- The platform list (e.g. `cedardb`, `velox`) could be retired from
  `PLATFORM_GROUPS` in `matrix.py`.
- The benchmark group `dataframe` could change shape if the registry
  retires/adds platforms.
- The `submit_terminal_state` vocabulary could narrow.

The dry-run replay test silently passes through all of these; a real
re-run with `dry_run=False` would fail at execute or package time.
The first user to actually replay this file in 2027 eats the failure
without warning.

## Why this matters
"Frozen historical record" is a recurring pattern (release manifests,
golden snapshot tests, frozen test fixtures). The freeze typically
guards content but not runnability. Two different invariants —
"this file hasn't been edited" vs. "this file still works against
the current code" — get conflated under the same "frozen" label.

## Suggested next steps
- [ ] Add a fast test that loads each FROZEN config via
      `load_config()` AND runs `enumerate_cells(config.raw)` against
      the current registry, asserting the cell list is non-empty and
      every (platform, benchmark) is still resolvable. This catches
      registry retirement at PR time, not at replay time.
- [ ] Document the policy explicitly: the freeze is content-stable,
      not behavior-stable. If a registry change retires a platform
      cited in a frozen config, file an issue rather than silently
      regenerating the hash.
