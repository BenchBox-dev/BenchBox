# Quality gate policy

Status: active

Owner: quality governance

Measured: 2026-08-08; quality baseline `d649c027f0`, duplicate correction recheck `4e25e77b1a`

## Decision

BenchBox uses several deliberately different quality controls. Their scopes,
threshold semantics, and CI consumers must remain explicit; a green result from
one is not evidence that another ran.

| Gate | Mode and scope | Hard policy | Advisory visibility | Ignored or excepted | Reproducible baseline | Required consumer |
| --- | --- | --- | --- | --- | --- | --- |
| Configured Ruff lint | `uv run ruff check .`; tracked Python discovered from the repository root | Enabled rules fail. C901 fails only when `CC > 18`. | None: a selected Ruff diagnostic is hard. | 34 global rule ignores, 5 per-file entries, and 8 discovery exclusions. `_project` is **not** excluded. | 0 diagnostics | Develop PR `guard-ruff`, release lint/test, nightly, and `make ci-lint` (also develop post-merge) |
| Ruff format | `uv run ruff format --check .`; configured discovery scope | Any formatting diff fails. | None | Same discovery rules as configured Ruff | 0 files | Same workflow surfaces as configured Ruff |
| Custom complexity policy | `make complexity-check`; scans `benchbox` with isolated Ruff C901 measurement at threshold 1 | Unexcepted `CC > 20` fails. Invalid, stale, unowned, drifted, overlong, or expired exception metadata always fails. Missing policy/target and empty or unparseable measurements also fail. | Every `12 <= CC <= 20` score is printed, including targets of any future hard exception. | 0 current hard exceptions | 6,442 functions with `CC > 1`; 180 advisory; 0 hard | Develop PR `guard-complexity-policy` and `make ci-lint` |
| Repository ty pass | `uv run ty check`; configured `benchbox` and `tests` scope | Configured error rules fail. | Warnings are printed without failing. | 7 globally ignored rule families | 641 warnings, 0 errors | Develop PR, release lint/test, nightly, and `make ci-lint` |
| Quality-governance strict type island | `make quality-governance-typecheck`; only `_project/scripts/check_complexity.py` | `ty check --error all`; every rule is hard except two line-local Python 3.10/3.11 TOML import compatibility suppressions | None | No architecture or production modules; those remain owned by their existing TODOs | 0 diagnostics | Develop PR `guard-quality-governance-typecheck` and `make ci-lint` |
| Duplicate delta | `make duplicate-check-delta`; AST Type-2 clones in `benchbox` versus the PR merge-base | Any positive duplicated-line delta fails. | Full changed-group report appears on failure. | 2 excluded path patterns, 6 global function names, 38 path-scoped rules | Merge-base 6,198/282 groups; branch 6,187/281; **-11, passing** | Develop PR `guard-duplicate-delta` and `make ci-lint` |
| Duplicate absolute | `make duplicate-check`; same AST scanner | More than 8,073 duplicated lines fails when invoked. | Report is always printed. | Same duplicate scanner configuration | 6,187 of 8,073 | Local/campaign only; not required CI |

“Required” above means the gate contributes to a required workflow result, not
merely that a command exists. The develop PR lint job uses `guard-*` step IDs,
`continue-on-error`, and the fail-closed `lint-guard-summary`; `make ci-lint`
mirrors each command. The parity test rejects a CI-only command that is absent
from the local aggregate.

## Implementations and consumers examined

This policy was derived from the behavior of more than four independent
implementations/consumers rather than from comments alone:

1. `[tool.ruff]`, `[tool.ruff.lint]`, and the exact `ruff==0.11.13` development
   dependency in `pyproject.toml` define configured discovery and rule behavior.
2. `Makefile` targets `lint`, `ci-lint`, `complexity-check`,
   `quality-governance-typecheck`, `duplicate-check`, and
   `duplicate-check-delta` define local operation and report-all behavior.
3. `.github/workflows/pr.yml` defines the required develop-PR aggregation and
   the base SHA supplied to duplicate delta.
4. `.github/workflows/lint.yml`, `test.yml`, and `nightly.yml` consume the
   configured Ruff/ty policy on release and compatibility surfaces; they do not
   imply that the `_project` complexity checker exists on curated release
   branches.
5. `_project/scripts/check_complexity.py` owns isolated custom score measurement,
   validates Ruff's concise-output count, and owns the temporary hard-exception
   lifecycle.
6. `scripts/check_duplicate_code.py` owns absolute and merge-base delta clone
   semantics; the two modes intentionally use the same scanner configuration.
7. `tests/system/test_ci_lint_parity.py` consumes workflow and Makefile commands
   as a drift guard, while `tests/unit/scripts/test_check_complexity.py` pins the
   quality-specific configuration and required CI wiring.

## Authority and legacy artifacts

Only `make complexity-check`, `make complexity-report`, and their shared
implementation `_project/scripts/check_complexity.py` are authoritative for
the current complexity policy. The former `scripts/check_complexity.py`
duplicate was removed because it parsed retired configuration and created a
second policy authority. `quality/complexity/classification-matrix.yaml`
remains a historical, non-gating artifact; do not update it as though its
entries were active exceptions.

The complexity targets and every other retained Make recipe whose executable
path depends on `_project/` are development-tree-only. A curated release keeps
their names for Make contract stability, but fails them with one explicit
development-tree message. Relocating the checkers into the release was rejected:
they validate development governance and would enlarge the shipped tooling
surface without adding a package-runtime capability.

## Ruff scope: configured discovery versus explicit paths

Before this policy, `_project` was excluded from configured repository
discovery, so `uv run ruff check .` passed without linting that tree. Ruff's
`force-exclude` setting is false, however: explicitly passing
`_project/scripts` still linted it and exposed exactly two lint diagnostics.
The independent formatter baseline found five files. The two lint findings and
five mechanical formatting diffs were fixed, then the `_project` discovery
exclusion was removed.

The resulting configured check is green. The repository has 62 tracked Python
files under `_project`; its local `_project/scripts/.venv` is ignored by Git,
and Ruff's `respect_gitignore = true` keeps that environment and its vendored
packages out of discovery. This change does not add a generated/vendor ignore,
a rule ignore, or a per-file suppression.

Ruff remains exactly pinned because `preview = true` can activate new behavior
on upgrade. The existing required `uv-lock-revision-check` makes a
`pyproject.toml` dependency change without its corresponding `uv.lock` update
fail. To upgrade Ruff, change the exact development requirement with `uv add`,
review all newly activated diagnostics, and commit the manifest, lock, and any
necessary fixes together. Roll back all of those parts together; never leave a
new pin with an old lock or suppress the newly discovered rules just to get a
green run.

## Complexity measurement and exceptions

The former list contained 152 function exclusions. Every entry was remeasured
against current Ruff C901 output before removal:

| Classification | Count | Decision |
| --- | ---: | --- |
| Exceeds custom hard ceiling (`CC > 20`) | 0 | No exception is justified. |
| Advisory (`12 <= CC <= 20`) | 84 | Remove the exclusion; keep the score visible. |
| Below advisory (`2 <= CC < 12`) | 44 | Remove stale metadata. |
| Target absent or no longer reported at threshold 1 (`CC <= 1`) | 24 | Remove stale metadata. |
| **Total measured** | **152** | **No current exception retained.** |

Configured Ruff and the custom checker must not be conflated. Configured Ruff
uses `max-complexity = 18` and fails on `CC > 18` within configured discovery.
The custom checker uses `max_complexity = 20`, fails on `CC > 20` in
`benchbox`, and additionally governs exception metadata. Its Ruff subprocess
uses `--isolated`: it inherits the installed pinned Ruff binary and only the
explicit CLI selection (`C901`, threshold 1, concise output), not
`pyproject.toml` Ruff selects, ignores, per-file ignores, excludes, or preview
settings. A project-level C901 ignore therefore cannot hide a custom hard score.
A custom exception does not suppress configured Ruff C901.

The custom policy table itself is still read from `pyproject.toml` by the
checker. The file, `[tool.benchbox.complexity]` table, thresholds,
`max_exception_days`, and `exclusions` key are required even when a threshold
is overridden on the command line. Ruff return-1 output must contain only
parseable C901 diagnostics plus exactly one matching `Found N errors.` summary.
Unexpected output, relevant stderr, a missing scan root, or zero measurements
under the authoritative source root fails closed.

If a future function genuinely requires a temporary custom hard exception, add
an array-table entry (not a string allowlist):

```toml
[[tool.benchbox.complexity.exclusions]]
target = "benchbox/path/module.py:function_name"
line = 123
score = 21
owner = "owning-workstream"
rationale = "Why the branching is currently irreducible and what removes it."
expires = "2026-09-01"
```

The pinned target, line, and score must resolve to exactly one current Ruff
measurement above 20. `max_exception_days = 90` bounds every review window: an
expiry must be after today and no more than 90 calendar days away. A missing
owner/rationale, an expiry on or before today, an overlong expiry, a moved
target, a changed score, or a score no longer above 20 fails
`make complexity-check`. `--no-fail` suppresses unexcepted score failures for
reporting only; it never suppresses metadata failures. An expired entry is
removed or renewed only after remeasurement and owner review—never by raising
the ceiling or selecting a distant expiry.

Rollback for a checker defect is atomic: revert the checker, its Make targets,
both required PR steps, its tests, and this policy together. Do not make CI
green by deleting only the required step, switching it back to report-only, or
raising `max_complexity`.

## Duplicate gate decision

The delta gate remains the required PR policy. It answers the reviewable
question “did this branch increase duplicated lines?” against the merge-base
without accepting the existing repository total as permanent. The absolute
8,073 ceiling remains a local/campaign safety check, but making it the only
required gate would permit 1,886 additional duplicated lines from the measured
6,187 before failing.

The initial quality-policy measurement correctly failed at `6,198 -> 6,199`
(`+1`). This governance change did not rebaseline, lower a check to report-only,
or add an ignore. It attributed the regression to a new +12 clone group between
`DataFrameQueryRuntime.load_table` and the dataframe benchmark mixin, offset by
an independently removed -11 `_attach_applied_tuning_ledger` group. The owning
adapter correction `4e25e77b1a` narrowed the protocol method and eliminated the
new +12 group.

Fresh measurement after that correction is `6,198/282 -> 6,187/281` (`-11`),
so both delta and absolute gates pass. The historical failure remains useful
evidence that the delta gate caught a real regression and governance did not
weaken or absorb it.

## Rejected alternatives and deferrals

| Alternative | Why rejected |
| --- | --- |
| Keep all 152 complexity exclusions and add metadata | None currently exempts a hard failure; metadata would be ceremonial and would continue hiding 84 advisory scores. |
| Convert every complexity advisory into a hard gate | The current baseline is 180 functions. That is architecture work, not honest governance-only enforcement. |
| Lower the custom ceiling from 20 to 18 | Configured Ruff already enforces `CC > 18`; duplicating it would obscure the distinct metadata/scanning contract without adding coverage. |
| Make all 641 repository ty warnings hard | It would capture production and architecture islands owned by prior TODOs, violating this task's governance-only boundary. |
| Add `_project` per-file Ruff ignores | The explicit baseline had only two fixable diagnostics; fixing them gave a green configured scope without weakening rules. |
| Replace required duplicate delta with the absolute ceiling | The current absolute headroom is too large to prevent a PR regression; it would have hidden the initially measured +1. |
| Rebaseline duplicate absolute to the current 6,187 | The delta gate already passes at -11; lowering the campaign ceiling without a fresh clone-classification campaign would be an arbitrary snapshot pin. |

Architecture complexity reductions, production strict-type islands, and
duplicate consolidation remain with their owning TODOs. This policy neither
changes production behavior nor claims those deferrals complete.
