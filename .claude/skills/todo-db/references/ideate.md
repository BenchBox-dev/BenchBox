# Ideate

Refine a raw concept into a clear problem statement and design direction before
creating tracker items.

## Workflow

1. **State the core problem**:
   Describe the user or system need simply. Distinguish the underlying problem
   from proposed solutions.
2. **Ask decisive questions**:
   Ask questions only when the answer changes the architecture, scope, or
   feasibility. Avoid questions that can be answered by reading the codebase.
3. **Compare viable options**:
   List two or three concrete approaches. State direct trade-offs for each:
   simplicity, maintenance burden, reversibility, and performance.
4. **Test assumptions**:
   Challenge assumptions about platform constraints, dependency contracts, and
   data safety.
5. **Shape candidate tracker fields**:
   Identify the primary components to prepare for `create_item`:
   - Candidate IDs and titles (kebab-case, imperative).
   - Dependencies between the candidate items.
   - Acceptance criteria for each item.
6. **Define boundaries**:
   - **In scope**: The minimal set of changes that solves the core problem.
   - **Out of scope**: Explicit non-goals and deferred enhancements.
   - **Open questions**: Unknowns requiring spikes or user decisions.

## Next step

`create_item` one task per independent piece of work, linked with `needs`.
