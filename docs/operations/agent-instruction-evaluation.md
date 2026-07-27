# Agent instruction evaluation

BenchBox treats agent instructions as executable governance. The deterministic
gate measures three dimensions:

| Dimension | Evidence |
|---|---|
| Effectiveness | Every adversarial scenario maps to a stable policy ID and expected authority class. |
| Efficiency | Active instruction bytes and adapter sizes stay below explicit budgets and improve on the recorded baseline. |
| Conformance | Forbidden identity, mutation, stale-pointer, and mirror patterns fail the audit. |

Run the loop after changing instructions, adapters, commands, hooks, or synced
skills:

```bash
make agent-instructions-check
make agent-identity-check
uv run -- python -m pytest tests/unit/scripts/test_agent_instruction_audit.py -q
make skill-sync-verify
```

The first command reads `_project/evals/agent-instructions/scenarios.json`,
prints candidate metrics, and exits nonzero on a violated policy. Tests include
negative mutations to prove the guard detects regressions. CI runs the same
audit when any governed path changes. Review candidate metrics against the
baseline embedded in the scenario corpus; raise a budget only with a documented
rationale and a new adversarial case.

`agent-identity-check` resolves both author and committer identities before a
commit. It blocks known agent/service names and vendor noreply addresses even
when a stale repository-local Git config overrides the user's global identity.
An explicitly authorized task-local exception requires
`BENCHBOX_ALLOW_AGENT_GIT_IDENTITY=1` on that commit command; never persist the
exception in Git config.

This loop tests deterministic instruction structure, not model compliance by
itself. Periodically run the scenario prompts through supported agents, record
pass/fail and latency outside the repository, and add any escaped behavior as a
new deterministic scenario or invariant before changing prose.
