---
id: 2026-05-05-080138-uat-bash-parity-structural-only
date: 2026-05-05
status: merged-to-todo
finding_kind: assumption
review_context: "/code review of PR #205 (UAT framework W2-W11)"
related_paths:
  - tests/uat/test_matrix.py
  - tests/uat/timeouts.py
  - tests/uat/matrix.py
  - scripts/local_stress_test.sh
suggested_sweep: "in any future bash→Python port, treat structural parity (same dict keys/values) and behavioral parity (same outcome under boundary inputs) as separate test contracts."
todo_id: uat-framework-review-followups
---

# "Bash parity" tested at dictionary level, not behavioral level

## Finding
The bash-parity tests assert that PLATFORM_PORTS, PLATFORM_EXTRA_OPTS,
PLATFORM_CLI_FLAGS, and PLATFORM_UV_EXTRA in `matrix.py` have the same
keys and values as the corresponding bash case statements. This catches
key-set drift but does NOT assert behavioral parity. Examples where the
two could diverge silently:

- `tcp_probe` in bash uses `nc -z` (or /dev/tcp fallback) and returns
  exit 1 on TIMEOUT, REFUSED, or NXDOMAIN uniformly; the Python port
  catches `(OSError, ValueError)` and returns False. NXDOMAIN raises
  socket.gaierror (an OSError subclass) — caught. But timing
  characteristics differ: bash nc has its own timeout heuristic; Python's
  `create_connection(timeout=2.0)` is rigorously 2s. On a cold sweep
  hitting unreachable platforms, divergent timeout behavior could
  produce different "skip vs hang" outcomes between the two paths.
- `run_with_timeout` reaps SIGKILL after 200ms; the perl wrapper does
  the same in principle, but the perl wrapper waited on `setpgrp`
  semantics that are not bit-identical to `os.setsid + os.killpg`
  on macOS vs Linux.

## Why this matters
Bash-to-Python ports of operationally-load-bearing scripts almost
always introduce subtle Unix-y semantics gaps. Asserting "the dict has
the same entries" is necessary but not sufficient. The user-facing
question is: under the same boundary inputs (timeout firing,
unreachable platform, SIGKILL'd child), do the two paths produce the
same observable outcome (exit code, log content, timing)?

## Suggested next steps
- [ ] Add a behavioral-parity smoke test that runs `tcp_probe` against
      a known-closed port from both the bash function (via `bash -c`)
      and the Python function, asserting same return value and similar
      timing.
- [ ] For `run_with_timeout`, add a slow test that runs the perl
      wrapper and the Python wrapper against a `sleep 30` child with a
      1s cap and asserts both return exit code 124 within 1.5s.
- [ ] When porting future bash scripts, write structural and behavioral
      parity tests as separate suites; do not let the structural one
      satisfy the audit.

## Triage log

- 2026-05-05: actionable (sweep). Tracked under `uat-framework-review-followups`
  (planning, Not Started). No behavioral-parity smoke for
  `tcp_probe`/`run_with_timeout` yet. Carry forward all three next-steps.
- 2026-05-05: promoted to TODO `uat-framework-review-followups`
