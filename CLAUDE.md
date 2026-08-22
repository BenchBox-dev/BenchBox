# Claude adapter

Read and follow `AGENTS.md`; it is the active BenchBox authority. Load relevant
generated skills from `.claude/skills/`, but do not let a skill override the
user's request, repository policy, or configured Git identity. Project hooks
must not silently mutate files; use the explicit verification gates in
`AGENTS.md`.
