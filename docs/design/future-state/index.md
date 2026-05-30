<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Future State Proposals

```{tags} contributor, architecture
```

These documents describe the intended end state for high-impact cleanup and
refactoring TODOs. Each proposal is tied to a planning item under
`_project/TODO/main/planning/` and makes the destination architecture explicit:
what gets pruned, excluded from the wheel, or reorganized within BenchBox.

## Sequencing and Priority

Not all proposals should be pursued simultaneously. Adversarial review
established the following priority tiers based on coupling analysis, effort, and
evidence of need:

**Tier 1: Act now (small effort, clear value):**
- **artifactlinks**: Dead code with zero consumers. Prune.
- **benchbox-maintainer**: Near-zero coupling. Remove entry point and exclude from wheel.
- **benchbox-experimental**: Namespace hygiene for 5 misplaced subsystems.

**Tier 2: Act when prerequisites are met:**
- **Benchmark family plugin seam**: Classify benchmark APIs and pilot a small
  family interface before splitting core benchmark packages.
- **MCP APIs**: Already an optional extra. Formalize 3 internal API refs as public exports. Defer distribution split until post-v1.0.
- **Monitoring**: Light coupling but no second consumer. Gate behind `benchbox[monitoring]` optional extra first.

Two proposals were discarded during adversarial review:
- **sqlplankit** (query-plan extraction): 37-file blast radius, shared-type
  boundary problem (`QueryPlanDAG` embedded in core result model), no external
  demand. Internal boundary improvements can be done without a package split.
- **todo-dag**: `_project/` does not ship to users, no second consumer exists.
  Extracting a package for single-repo contributor tooling is package sprawl.

## Proposals

- [Architecture contract decision index](contract-index.md) - active planning
  index for public-contract and future-state decisions
- [Benchmark family plugin seam](benchmark-family-plugin-seam/README.md) -
  **Medium** priority, gated by API classification and one pilot family
- [Prune publishing](prune-publishing-subsystem/README.md) - **High** priority (dead code removal)
- [Remove release tooling from wheel](remove-release-tooling-from-wheel/README.md) - **High** priority
- [Isolate experimental subsystems](isolate-experimental-core-subsystems/README.md) - **High** priority
- [Gate monitoring behind optional extra](gate-monitoring-behind-optional-extra/README.md) - **Medium** priority
- [Formalize MCP internal APIs](formalize-mcp-internal-apis/README.md) - **Medium** priority

```{toctree}
:maxdepth: 1
:hidden:

contract-index
benchmark-family-plugin-seam/README
prune-publishing-subsystem/README
remove-release-tooling-from-wheel/README
isolate-experimental-core-subsystems/README
gate-monitoring-behind-optional-extra/README
formalize-mcp-internal-apis/README
```
