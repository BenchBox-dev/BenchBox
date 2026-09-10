# Review TODO quality

Evaluate the quality and readiness of a tracker item before or during
implementation.

## Review checklist

Audit the item using `show_item(id=...)`:

### 1. Description
- Does the description state the problem and the expected outcome?
- Are non-obvious constraints written down, not assumed?

### 2. Acceptance
- Are the acceptance criteria observable and specific?
- Do they verify substantive behavior rather than cosmetic flags?

### 3. Dependencies
- Are all prerequisite items recorded in `needs`?
- Is the item free of circular dependency chains (creation rejects them)?

### 4. Readiness
- Is the item `open` and unclaimed, with all `needs` done?
- If `blocked`, is the reason recorded in the description or context?

Report gaps concretely; fix them with `update_item` when authorized.
