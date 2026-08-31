# Makefile architecture

BenchBox uses a small set of mandatory GNU Make includes while retaining a
substantial root `Makefile`. The retained root is deliberate: several repository
guards treat its source text as a compatibility API, while command-line and CI
consumers use GNU Make's evaluated target graph.

## Supported behavior

- GNU Make 3.81 or newer is supported. The root freezes
  `BENCHBOX_MAKEFILE_ROOT` before any include changes `MAKEFILE_LIST`, using
  the 3.81-supported `realpath`, `lastword`, and `dir` functions. Its
  `override` directive reserves the value against both a command-line
  assignment and an environment assignment under `make -e`.
- Includes are mandatory `include` directives, never `-include`. A missing
  module therefore stops parsing instead of silently dropping targets.
- Include paths are rooted at the real root-Makefile location. This preserves
  `make -f /path/to/Makefile`, invocation from another working directory, and
  the symlinked-Makefile worktree tests.
- `test` remains the default goal. Module includes occur only after the root
  has defined it.

## Ownership

| File | Responsibility | Extension rule |
|---|---|---|
| `Makefile` | Bootstrap, default goal, literal-text compatibility targets, quality/CI orchestration, release, PR, worktree, and UAT contracts | Keep a target here when an existing consumer intentionally parses the root text, or when it coordinates several domains |
| `make/platform-tests.mk` | Credentialed live-platform and local compose/container test lifecycle | Add platform-specific test entry points and their directly coupled engine variables/macros here |
| `make/documentation.mk` | Docs build/validation, generated compatibility docs, platform manifest, parity fixtures, and native TPC binary compilation | Add documentation or generated-contract targets here; do not place general lint targets here |
| `make/worktrees.mk` | Disposable worktree creation, exact-path removal, and listing | Keep the native Git lifecycle wrappers here; do not add slot allocation or automatic branch cleanup |
| `make/worktree-maintenance.mk` | Finding and soundness reporting utilities | Keep unrelated reporting targets here; worktree reaping remains exact-path and operator-driven — the only branch reaper (`branch-prune-merged` in the root `Makefile`) is an explicit exception for worktree-less branches at their merged `headRefOid` |
| `make/help.mk` | Exact ordered `make help` recipe | Preserve existing category and command order; add a help line in the same change as a new user-facing target |
| `make/inventory.json` | Current evaluated target, alias, prerequisite, recipe, variable, macro, statement-order, default-goal, and include-order contract | Regenerate only for an intentional permitted contract change and review the manifest diff |
| `make/monolith-baseline.json` | Durable inventory of the committed pre-split monolith: 198 targets, 195 public targets, and default goal `test` | Do not regenerate during ordinary Make changes; changing this migration proof requires a separate architectural decision |
| `make/migration-proof.json` | Compact hashes, counts, include order, and reviewed delta for the initial split | The normal inventory writer never changes this file; preserve it with the monolith baseline as historical evidence |
| `make/check_makefile_inventory.py` | Inventory reader, writer, and historical verifier | Keep it with the release-retained Make runtime so the public guard remains executable after curation |

Cross-module prerequisites stay explicit in target headers. A module must not
invoke another module by reaching into its file; it invokes the public target.
Variables live with the recipes they configure unless they are root bootstrap
or cross-domain orchestration inputs.

## Consumer evidence and root-owned boundaries

The split was designed against repository consumers, not only target size.

| Implementation or consumer | Observed contract | Design consequence |
|---|---|---|
| `.github/workflows/pr.yml`, `develop-post-merge.yml`, `nightly.yml`, and `lint.yml` | Invoke public targets through GNU Make | Included targets are transparent; the inventory pins their names, prerequisites, recipes, and ordering within recipes |
| `tests/system/test_ci_lint_parity.py` and `tests/unit/scripts/test_ci_lint_environment_boundary.py` | Parse the literal root `ci-lint:` recipe | `ci-lint` remains root-owned with byte-identical command order |
| `tests/unit/test_standardized_test_commands.py` and `tests/unit/test_linting_consolidation.py` | Search or parse root test, coverage, correctness, marker, lint, and format definitions | Those definitions remain root-owned; moving them requires first migrating the consumers in a separately scoped change |
| `tests/unit/test_release_infrastructure.py`, `tests/unit/workflows/test_auto_merge_enablement_point.py`, and `tests/unit/test_auto_merge_soundness_paths.py` | Parse release, PR, auto-merge, worktree lifecycle, package, and UAT gate source text | Those operational safety recipes remain root-owned |
| `tests/unit/test_agent_write_preflight.py` | Slices the root `skill-sync` recipe | `skill-sync` and its adjacent check remain root-owned |
| `tests/uat/test_cli_dispatch.py` | Slices the root `uat-sweep` recipe | `uat-sweep` stays root-owned |
| `tests/integration/worktree/test_worktree_*` | Run the real Makefile with `-f` or through a symlink from another repository | `BENCHBOX_MAKEFILE_ROOT` resolves the real root before mandatory includes load |
| `scripts/check_release_curation.py` | Parses the release curation recipe from the root path | Release curation remains root-owned until the parser supports include expansion |

No repository consumer referenced `MAKEFILE_LIST` before the split. The new
bootstrap variable nevertheless freezes the root path before includes append to
that built-in list, preventing future ordering-dependent path drift. It is a
repository-reserved variable and is not a supported user customization point.

The pre-split root had 2,752 lines. The modular root has 1,726 lines and the six
included modules have 1,043 lines. The extra lines are the guarded bootstrap,
six include directives, inventory target, and its intentional help entry; the
expanded semantic statement stream otherwise matches the baseline exactly.

## Release curation

The top-level `make/` directory is release runtime, not `_project` tooling. It
is retained on curated release branches alongside `Makefile`; release-cut still
removes `_project` in full. Keeping the modules, inventories, proof, and checker
together prevents a curated `Makefile` from becoming unparsable and keeps
`make makefile-inventory-check` usable on the released tree.

Tests that load curated-out `_project` scripts must be curated or degrade
explicitly. The release recipe removes the complexity-checker test. The Make
inventory test now loads its retained checker, while the two platform-registry
cases that need the development-only platform-manifest generator skip when that
generator is absent; the rest of that behavioral file remains release coverage.
The release curation tests materialize the retained Make runtime, execute its
help and inventory targets, fail when a required module is omitted, verify the
remaining `_project`-dependent test is removed, and collect both retained test
files against the curated shape.

## Drift guard

Run:

```bash
make makefile-inventory-check
```

The guard expands only the repository's narrow, mandatory include syntax and
does not execute Make recipes. It compares the checked-in manifest against:

- the default goal and ordered include list;
- all explicit and pattern targets plus the phony target set;
- exact target headers and prerequisites;
- exact recipe bytes and command ordering;
- variable assignments and `define` macro bodies;
- the global ordered stream of assignments, macros, phony declarations, and
  rules after include expansion.

Moving an unchanged target between root and a module leaves its rule contract
unchanged only when its expanded parse position is also unchanged. Removing or
renaming a public target, changing a prerequisite or recipe, or reordering
assignments fails closed.

The separate migration proof records the six ordered includes, the
non-overridable `BENCHBOX_MAKEFILE_ROOT` bootstrap, the public phony
`makefile-inventory-check` target and help line, and the release-curation entry
required by the complexity test that still depends on `_project`. Its normalized
semantic hash equals the monolith's hash; the reviewed target delta changes the
baseline counts from 198/195 to 199/196.

That evidence does not freeze the Make interface. For an intentional future
contract change, regenerate only the current inventory and review its diff:

```bash
uv run -- python make/check_makefile_inventory.py --write
git diff -- Makefile make/
make makefile-inventory-check
```

The writer validates but never rewrites `monolith-baseline.json` or
`migration-proof.json`. Before such a future regeneration, the ordinary check
fails closed; after regeneration it accepts the reviewed current contract. Do
not add the writer to `guards-fix`: target-interface changes require a reviewed
decision rather than automatic regeneration.

At the introducing split commit, or a checkout reconstructed from it, reproduce
the historical comparison explicitly:

```bash
uv run -- python make/check_makefile_inventory.py --verify-migration
```

Later intentional Make changes are expected to diverge from that historical
comparison; the immutable proof metadata remains valid and auditable without a
third full inventory copy.

## Change and rollback cases

| Change | Required action | Rollback |
|---|---|---|
| Add a target inside an existing domain | Add it to the owning module, add help if public, regenerate and review inventory | Revert the target, help entry, and manifest together |
| Move a target from root to a module | First prove no root-literal consumer remains; move comments, variables, rule, and recipe as one block; inventory should show only include/ownership changes | Move the exact block back to its original parse position and remove an empty module |
| Add a module | Add one mandatory rooted include at the intended parse position and update this ownership table; regenerate inventory | Move its blocks back, remove the include, then remove the module |
| Emergency rollback of this split | Restore the six module bodies at their include positions, delete the include lines and `BENCHBOX_MAKEFILE_ROOT`, then remove the guard target/help line | The resulting Makefile should reproduce `monolith-baseline.json` exactly |

## Alternatives rejected

- **Split by line count.** Rejected because it cuts coupled variables/macros
  away from recipes and ignores literal-root consumers.
- **Move every target and update all parsers at once.** Rejected because the
  authorized scope excludes most literal-parser tests and would combine a
  compatibility migration with the structural refactor.
- **Optional or wildcard includes.** Rejected because missing or misspelled
  modules can silently remove public targets.
- **A generated monolithic root mirror.** Rejected because it creates two
  apparent sources of truth and makes edits land in generated compatibility
  text rather than the owning module.
- **Inventory only target names.** Rejected because names alone cannot detect
  changed prerequisites, aliases, environment-variable wiring, shell flags,
  exit behavior, or command ordering.
