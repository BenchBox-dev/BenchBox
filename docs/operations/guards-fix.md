# `make guards-fix`: drift-guard remediation, one command

A small class of CI checks are "drift guards": they compare a checked-in
artifact (a doc, a fixture, a generated table) against a fresh regeneration
from the live source of truth, and fail when the two disagree. Each one is
fixed by a known, mechanical regen command — but the command differed per
guard and lived only in hand-carried agent prompts, so the same fix kept
getting rediscovered every time one of these failed in CI (a "steady
trickle" of otherwise-routine failures). `make guards-fix` runs every regen
that exists, in one place, then prints `git status --porcelain` so you can
review the diff before committing.

```bash
make guards-fix
```

## What it regenerates

| Guard | CHECK target | Regen it runs |
|---|---|---|
| Dependency inventory | `make audit-raw-check` | `make audit-raw` (`_project/scripts/dependency_audit/parse_deps.py`) |
| Benchmark correctness-oracle coverage map | `make oracle-coverage-map-check` | `make oracle-coverage-map` (`_project/scripts/generate_oracle_coverage_map.py`) |
| Visualization parity fixtures | `make parity-check` | `make parity-fixtures` (`tests/parity/generate_visualization_fixtures.py`) |
| sql_compat capability matrix / skip-reference docs | `make compat-docs-check` | `make compat-docs` (`scripts/generate_compat_docs.py`) |
| skill-sync tracked snapshot | `make skill-sync-check` | `make skill-sync` (no-op with a notice if the skill-sync CLI isn't installed locally — see the Makefile comments) |

**Not in this table: the UAT production-LOC ceiling gate.**
`uv run --project _project/scripts -- python _project/scripts/uat_loc_table.py --check`
used to be a regen guard and was listed here until 2026-08-06. It is now a
budget gate: it fails when `tests/uat/` exceeds a ceiling committed in
`_project/specs/uat-loc-budget.json`, and `make guards-fix` no longer runs it
and cannot fix it. Remediation is to remove code or to raise the ceiling
deliberately in its own PR. Running the script with no arguments prints the
current per-bucket numbers and headroom; it writes nothing.

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
suppression). Three guards in this class have no regen mode at all; their
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
- **Release curation list** (`scripts/check_release_curation.py`) — an
  unaccounted-for top-level path is classified by hand as either
  `main`-only (`_project/decisions/single-repo-migration.md`) or
  release-cut curated (the `release-cut:` target in `Makefile`).

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

See also: `make -n guards-fix` to preview what it will run without
executing anything, and the `guards-fix-regen-target-2` TODO for the
class-level rationale.
