# `make guards-fix`: drift-guard remediation, one command

A small class of CI checks are "drift guards": they compare a checked-in
artifact (a doc, a fixture, a generated table) against a fresh regeneration
from the live source of truth, and fail when the two disagree. Each one is
fixed by a known, mechanical regen command, but the command differs per
guard. `make guards-fix` runs every regen that exists, in one place, then
prints `git status --porcelain` so you can review the diff before committing.

```bash
make guards-fix
```

## What it regenerates

| Guard | CHECK target | Regen it runs |
|---|---|---|
| Dependency inventory | `make audit-raw-check` | `make audit-raw` (dependency-audit parser script) |
| Benchmark correctness-oracle coverage map | `make oracle-coverage-map-check` | `make oracle-coverage-map` (oracle coverage-map generator script) |
| Visualization parity fixtures | `make parity-check` | `make parity-fixtures` (`tests/parity/generate_visualization_fixtures.py`) |
| sql_compat capability matrix / skip-reference docs | `make compat-docs-check` | `make compat-docs` (`scripts/generate_compat_docs.py`) |
| skill-sync tracked snapshot | `make skill-sync-check` | `make skill-sync` (fail-closed when the vendored wrapper is missing — see the Makefile comments) |

**Not in this table: the UAT production-LOC ceiling gate.** It is a budget
gate, not a regen guard: it fails when `tests/uat/` exceeds a committed line
ceiling, and `make guards-fix` cannot fix it. Remediation is to remove code or
to raise the ceiling deliberately in its own change.

Each regen is idempotent: run it against an already-current artifact and
nothing changes. `make guards-fix` on a clean `develop` checkout should be a
complete no-op — an empty `git status --porcelain` at the end. If it isn't,
that's real drift that predates your change; investigate before assuming
it's something you introduced.

Two of the regenerated artifacts carry a provenance timestamp that is
intentionally excluded from the CHECK comparison (e.g. the oracle coverage
map's `generated:` header) — `guards-fix` refreshing that date alone, with
the `content-revision` hash unchanged, is not drift and won't fail CI.

## What it deliberately does not touch

`guards-fix` only regenerates artifacts. It never edits an allowlist,
ceiling, or curation list — those stay a human-reviewed decision, and each
guard still fails CI on drift afterward (regen is remediation, not
suppression). Two guards in this class have no regen mode at all; their
failure output names the exact hand edit instead:

- **Module-size guard** (`tests/system/test_module_size_thresholds.py`) —
  when a tracked module exceeds its budget, the failure prints a
  ready-to-paste `ALLOWLIST` entry carrying the module's *current* line
  count. Paste it in with a real justification; `ALLOWLIST_HEADROOM` is
  added on top automatically.
- **DDL governance drift** (`benchbox/sql_compat/inventory.py
  --check-ddl-drift`, run as part of `make compat-docs-check`) — an
  unregistered or uninspectable DDL-optimize transform is fixed by
  registering it under `benchbox/sql_compat/rules/ddl_optimize/`, adding a
  `_DDL_GOVERNANCE_TRANSFORMER_ALIASES` entry (if it's registered under a
  different function name), or an explicit `_DDL_DRIFT_EXEMPTIONS` entry
  with rationale.

## When to run it

Run it locally whenever one of the CHECK targets above fails, or
proactively before opening a PR that touched a file one of these guards
watches (dependencies, benchmark registry/oracles, visualization math,
`sql_compat` rules, `tests/uat/*`). Review the resulting diff like any other
change before committing — `guards-fix` is an operator command, not
something CI runs on your behalf. It is intentionally **not** wired into any
CI workflow to self-heal: a guard failing in CI should fail, and be fixed by
a human running this command and reviewing the diff, not silently patched by
the pipeline itself.

Use `make -n guards-fix` to preview what it will run without executing
anything.
