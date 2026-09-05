# Batch handoff

Create a self-contained prompt that enables a new agent session to continue
or close a batch without access to previous conversation history.

## Handoff structure

Include these sections in order:

1. **Objective and item set**:
   - Batch name and list of all TODO IDs.
   - State whether the next phase is implementation (`batch`) or close-out (`closeout`).
2. **Tracker preflight**:
   - Instructions to call `get_instructions` and `doctor` before writing.
   - State the target database location and project identity.
3. **Current verified state**:
   - Live branch names, commit SHAs, and open PR numbers.
   - Location of the local ledger file (for example, `.todo-batch/<slug>.txt`).
   - Active claims or claim tokens held by the session.
4. **Execution order**:
   - Ordered list of remaining items and reasons for dependencies.
5. **Scope boundaries**:
   - Paths allowed to be modified.
   - Known preserves and anti-patterns.
6. **Known blockers and recovery**:
   - Unresolved issues, waiting CI gates, or flaky tests with remediation steps.
7. **Verification checklist**:
   - Exact test commands required before completion.
   - Human verification status (`todo-db verify-run`).
8. **Next concrete step**:
   - The exact MCP tool call or command the incoming agent should execute first.

## Writing rules

- Verify facts before writing. Do not mark work completed, merged, or verified
  unless proven during handoff generation.
- Keep the handoff concise. Omit raw diffs, verbose test output, and conversational history.
