# Implement a TODO

Drive a claimed tracker item from start to completion using MCP tools.

## The implementation sequence

### 1. Claim the work

1. Call `next` to inspect the ready queue or resume an active claim.
2. Call `take(id=...)` to claim the item. Store the returned `claim_token`.
3. Call `context(id=...)` to retrieve the full work breakdown, scope rules,
   preserves, and verifications.

### 2. Execute work units

Work through the units defined in `context`:

1. Call `start_unit(id=..., wid=...)` if you want the unit marked in progress
   before making edits (optional).
2. Edit code only within the paths listed under `only_modify`.
3. Test changes locally to generate verifiable evidence.
4. Record progress on the unit:
   ```json
   {
     "id": "ITEM-1",
     "wid": "w1",
     "evidence": "uv run pytest tests/test_feature.py (all passed)",
     "claim_token": "<token>"
   }
   ```
   Calling `progress` updates the unit and refreshes your claim lease.

### 3. Handle side work and deferrals

If you find necessary changes outside the item's scope:
- Do not edit outside approved scope.
- Call `defer(id=..., summary=..., reason=...)` to record the discovered work.
- Continue with the claimed item's approved scope.

### 4. Check scope before closing

Call `check_scope(id=...)`. When `files` is omitted, it automatically checks all
modified files against the item's git baseline.
- If an unapproved file was touched, revert the change or move it to a deferral.
- If the scope was legitimately too narrow, call `update_item` with `add_scope`
  and provide an audited reason:
  ```json
  {
    "id": "ITEM-1",
    "add_scope": [["only_modify", "src/new_path.py"]],
    "reason": "Include helper module required for implementation"
  }
  ```

### 5. Verification gate and finish

1. Call `lint(id=...)` to confirm planning consistency.
2. Call `finish(id=..., claim_token=...)`.
3. If `finish` returns `E_VERIFY_GATE`:
   - Agents cannot run verification commands directly.
   - Copy the exact `todo-db verify-run` command from the `recovery` envelope.
   - Ask the human to execute it:
     ```sh
     todo-db verify-run <id> --claim-token <token> --actor <principal>
     ```
   - Once the human runs the command and attests the workspace, call `finish`
     again to complete the item.
4. If you must abandon work, call `release(id=..., claim_token=...)` to return
   the claim to the ready queue.
