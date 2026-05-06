---
id: 2026-05-05-154306-uat-noisy-neighbor-invocation-divergence
date: 2026-05-05
status: merged-to-todo
finding_kind: framework-gap
review_context: "principal-engineer review of UAT framework PR #205 (post-merge simplification audit)"
related_paths:
  - tests/uat/_cli.py
  - tests/uat/orchestrator.py
  - tests/uat/phases/preflight.py
suggested_sweep: "Centralize preflight-config-from-cfg conversion in one helper. Audit other phases for similar invocation-path-dependent behaviour (e.g. cleanup_enabled vs cleanup.* YAML)."
todo_id: uat-framework-review-followups
---

# Preflight `noisy_neighbor_warn_load` is honoured on `make uat-sweep`/`uat-stress` but skipped on `make uat-execute`

## Finding
The preflight phase reads `noisy_neighbor_warn_load` at
`tests/uat/phases/preflight.py:65`. The orchestrator path
(`tests/uat/orchestrator.py:71`) passes the YAML field to `run_preflight`.
The standalone `_cli.execute_main` path (`tests/uat/_cli.py:302-306`)
constructs the preflight call inline and does NOT pass
`noisy_neighbor_warn_load` — the preflight default is used regardless of
what the YAML config declares.

Net: `make uat-sweep` / `make uat-stress` honour the field; `make uat-execute`
silently ignores it. Same config file, two effective behaviours depending on
which Makefile target the operator chose.

## Why this matters
Operators who configured `noisy_neighbor_warn_load: 0.5` in their config
and switch from `uat-sweep` to `uat-execute` for a smaller test will lose
the noisy-neighbour warning without any indication. This is silent
behaviour divergence — the kind that erodes trust in framework guarantees.

## Suggested next steps
- [ ] Extract the preflight-config-from-`UATConfig` conversion into one helper
      in `tests/uat/phases/preflight.py` (or a small `_to_preflight_kwargs`
      function). Both invocation paths call the helper.
- [ ] Add a regression test: same config file, both invocation paths, assert
      identical preflight kwargs.
- [ ] Audit other phases for the same pattern. Candidate: `cleanup_enabled`
      (Python kwarg from `_cli.py:321`) vs the unread `cleanup.prune_databases`
      YAML field (see sibling blind-spot `uat-orphan-yaml-fields`).

## Triage log

- 2026-05-05: actionable (sweep). Confirmed: `tests/uat/_cli.py` still does not pass
  `noisy_neighbor_warn_load`; only `tests/uat/orchestrator.py:77` honours
  the field. Tracked under `uat-framework-review-followups`. Carry forward
  all three next-steps.
- 2026-05-05: promoted to TODO `uat-framework-review-followups`
