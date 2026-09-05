# Review TODO planning quality

Evaluate the quality and readiness of a tracker item before or during
implementation.

## Verification checklist

Audit the item using `show_item(id=...)` and `lint(id=...)`:

### 1. Scope rules
- Are `only_modify` paths as narrow as possible?
- Does the scope exclude unrelated modules and generated files?
- If living documents (such as specifications or architectural policies) are
  modified, verify that the unit description reflects current file contents
  rather than stale citations.

### 2. Verification commands
- Call `verify_list(id=...)` to inspect stored commands.
- Are commands non-interactive and deterministic?
- Do commands verify substantive behavior rather than cosmetic flags?
- Do commands avoid network calls or external shared state unless explicitly designed for hosted testing?

### 3. Work units
- Is each unit small, clear, and independently evidenced?
- Are done units left untouched? (Completed units carry immutable evidence.)

### 4. Dependencies
- Are all prerequisite items recorded via `add_dependency`?
- Is the item free of circular dependency chains?

## Linting

Call `lint(id=...)` to execute automatic schema and policy checks:
- An item with lint findings will fail the `E_LINT_GATE` at `finish`.
- Resolve findings by calling `update_item` to adjust scope, work breakdown, or
  verification commands before proceeding with implementation.
