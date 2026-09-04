# Implement TODOs

## Steps

1. **Find and claim work:**
   - Call MCP `next` to inspect the queue.
   - Follow `next_action` to call `take(id="<id>")`. This returns the claim and active `claim_token`.
2. **Retrieve context:**
   - Call `context(id="<id>")` for the bounded work order: work units, scope rules, must-preserve notes, anti-patterns, verification commands, and deferrals.
3. **Execute work units:**
   - Apply `shared-change-framework/SKILL.md` Section 1 before editing source code.
   - For each work unit, make workspace edits, run project tests via `Bash`, then call:
     ```json
     progress(id="<id>", wid="<wid>", evidence="<command, commit, or PR>", claim_token="<claim_token>")
     ```
4. **Deferrals:**
   - Defer out-of-scope discoveries immediately with:
     ```json
     defer(id="<id>", summary="...", reason="...")
     ```
   - Resolve open deferrals before completion with `dismiss_deferral(deferral_id=..., reason="...")` or `promote_deferral(deferral_id=...)`.
5. **Pre-close inspection:**
   - Check modified files against declared scope: `check_scope(id="<id>", files=[...])`.
   - Review quality and rules: `lint(id="<id>")`.
6. **Finish and Verification Gate (`E_VERIFY_GATE`):**
   - Call `finish(id="<id>", claim_token="<claim_token>")`.
   - If `finish` returns `E_VERIFY_GATE`:
     1. Stored verification commands require human attestation.
     2. Extract the exact command from the error `recovery[0]` field:
        ```sh
        todo-db --actor <principal> verify-run <id> --claim-token <claim_token>
        ```
     3. **Do NOT run `verify-run` via `Bash`.** Present the command to the human operator and halt until they confirm execution.
     4. Once attested, call `finish` again.

## Findings

Under `--profile full`, use `finding_create`, `finding_triage`, and `finding_promote`. Findings are synced to the database through the credentialed floor command `todo-db finding sync`.
