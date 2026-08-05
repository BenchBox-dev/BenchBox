# CI / local lint parity

`make ci-lint` (and `make pr-preflight`, which runs it) exists so that
every lint guard CI enforces on a develop PR also runs locally, before you
push. A guard that only exists in `.github/workflows/pr.yml` fires for the
first time on a pushed PR -- that costs a full remote CI round trip for a
failure you could have caught in seconds locally.

## The invariant

Every guard the `lint` job (job id `code-lint`) in `pr.yml` runs, after its
dependency-install step, must also run in the Makefile's `ci-lint` recipe --
at the **command** level, not just under a similarly-named local target.
`tests/system/test_ci_lint_parity.py` parses `pr.yml` (the source of truth)
and pins this: it fails if a `lint`-job guard command is missing from
`ci-lint`, and it fails if an exclusion entry references a step that was
renamed or removed (so the exclusion can't quietly rot into cover for a
guard nobody runs anywhere).

Command-level, not name-level, matters here: a local target can share a
step's name while running different logic. `skill-sync-check` in `ci-lint`
(`node skill-sync doctor`) is not the same command as CI's pinned
full-SHA skill-sync checkout plus `npm ci` and `verify` step -- treating the
name match as parity would hide that the local run isn't actually checking
what CI checks.

## Adding a new lint guard

When you add a new guard step to the `lint` job in `pr.yml`:

1. Give the step an `id: guard-<slug>` (see "Report-all: one CI cycle,
   every guard's result" below for why) and `continue-on-error: true`.
2. Add the equivalent command to the `ci-lint:` recipe in the `Makefile`
   (a `$(MAKE) <target>` line if the guard already has a `make` target, or
   the same `uv run ...` / script invocation the CI step uses), followed
   by its own `[ $$? -eq 0 ] || failed="$$failed <slug>"` bookkeeping line
   -- copy the pattern of an existing guard pair in the recipe.
3. If the guard has meaningful inline logic (more than a couple of lines)
   and would otherwise live only inside the workflow YAML, extract it to a
   script under `scripts/` first and have both `pr.yml` and `ci-lint` call
   that script. Duplicating logic into the Makefile as a second
   implementation is exactly the drift this invariant exists to prevent.
4. Run `uv run -- python -m pytest tests/system/test_ci_lint_parity.py -q`.
   If it fails: either step 2 was missed, the command text doesn't match
   verbatim, or step 1's `id`/`continue-on-error` are missing or malformed
   (`test_guard_steps_follow_naming_convention` enforces the convention;
   `test_lint_job_guards_run_in_ci_lint` enforces command parity).

## Report-all: one CI cycle, every guard's result

The `lint` job runs around fifteen independent guards. Historically the
job stopped at the first failing step, so a PR that tripped two unrelated
guards paid one full CI round trip per guard, discovered one at a time.
Every guard step now sets `continue-on-error: true` so a failure doesn't
stop the job -- every guard still runs, and each one's own pass/fail is
still visible as its own step in the Actions UI with its own log and
timing. What changes is that the *job's* overall result no longer
silently skips the guards after the first failure.

**Naming convention (this is what the aggregation is keyed on, not a
hand-maintained list):** every independent guard step's `id:` starts with
the prefix `guard-` (e.g. `guard-ruff`, `guard-audit-deps`). Setup steps
(checkout, `setup-python`, `setup-uv`, install dependencies) are not
guards -- they get no `id: guard-*` and no `continue-on-error`, because a
setup failure should stop the job immediately (there's nothing meaningful
to report about guards that never ran because `uv sync` failed).

The job's last step, `lint-guard-summary`, aggregates: it reads the
Actions `steps` context (`${{ toJSON(steps) }}`, passed in via an env var
rather than interpolated directly into the script), finds every step id
that starts with `guard-`, and checks that step's `outcome` (the raw
per-step result *before* `continue-on-error` is applied -- `conclusion`
would show `success` for every failed-but-continued guard and defeat the
whole point). It writes a pass/fail table to `$GITHUB_STEP_SUMMARY` and
exits nonzero if any guard's `outcome` was `failure`. Because
`lint-guard-summary` itself has no `continue-on-error`, that nonzero exit
makes the `code-lint` job's own result `failure` -- so `ci-required-result`
(which gates on `needs.code-lint.result`) still blocks the merge exactly
as before. Nothing here softens the gate; it only changes *when* you find
out a second guard also failed.

Deriving the guard set from the `guard-` id prefix (rather than hand-listing
step ids in the aggregator) is deliberate: a new guard added without the
prefix would otherwise run, fail, and be silently invisible to the
summary and its own `continue-on-error: true` would swallow the job-level
failure entirely. `tests/system/test_ci_lint_parity.py::test_guard_steps_follow_naming_convention`
pins the convention (every guard has the prefix + `continue-on-error`,
every non-guard step has neither), and
`test_lint_guard_summary_step_exists` pins that the aggregator step exists,
is named exactly `lint-guard-summary`, runs with `if: always()` (so it
still executes -- and reports -- after an earlier guard fails), and is the
job's last step.

`make ci-lint` mirrors the same report-all shape locally: the whole
recipe runs as one shell invocation (via `\` line continuations) with
`set +e`, running every guard command in turn and collecting failures
into a `$$failed` list instead of `make` aborting at the first nonzero
exit, then printing a consolidated `❌ FAILED guards:` list and exiting
nonzero if the list is non-empty. Guard output still streams live as each
guard runs -- nothing is buffered or captured, only the exit code is
checked after each command -- so `make ci-lint`'s console output looks the
same as before, just with the run continuing past a failure instead of
stopping. Because the `ci-lint` recipe body is now one logical shell line,
the parity test's line-matching normalizes away each guard command's
trailing `; \` continuation marker before comparing it against the `pr.yml`
command text -- see `_normalize_recipe_lines` in
`tests/system/test_ci_lint_parity.py`.

If a guard genuinely cannot run locally (see the network exception below
for the only current example), add it to the `EXCLUDED_STEPS` dict in the
parity test with a concrete reason -- do not silently omit it, and do not
weaken the CI guard itself so a lossier local equivalent can "pass."

## Documented exceptions

### Pinned skill-sync checkout verify

The `lint` job's "skill-sync tracked snapshot verify (cloud/CI integrity
gate)" uses `actions/checkout` at a full skill-sync commit SHA, runs
`npm ci` in that isolated tool checkout, then runs its built verifier against
the BenchBox root. This needs network access to fetch the pinned commit and
its npm dependencies. The explicit checkout avoids npm's unreliable
GitFetcher packaging path while retaining immutable source provenance.

This was tested directly in a local/sandboxed dev shell: the equivalent flow
hangs with no route (no DNS/proxy path configured for GitHub or the npm
registry). Two options were
considered:

- **Guard it with a network probe and print a notice.** Rejected:
  on a machine where Git/npm tooling and network are available, this
  swallows a real local verify failure and prints a "skipped" notice
  instead -- silently weakening the guard, which is the exact anti-pattern
  this parity invariant exists to prevent elsewhere.
- **Exclude it explicitly, with a reason, in the parity test.** This is
  what the repo does. CI's runner has network, so the gate stays fully
  enforced there; it is simply not a viable *blocking* local gate.

`make ci-lint` therefore does not run this step. `make skill-sync-check`
(`node skill-sync doctor`) is a different, unrelated local convenience and
does not substitute for it -- see the command-level-parity note above.

### Fast lane delta guard vs. develop

The `lint` job's "Fast lane ceiling delta vs develop" step
(`guard-fast-lane-delta`) restores a GitHub Actions cache entry (the
develop fast-lane baseline count, populated by `develop-post-merge.yml`
after every push to develop) and diffs this PR's own fast-lane collect
count against it. There is no local equivalent for an Actions cache
restore, so this has no `ci-lint` counterpart. It does not weaken local
enforcement: `guard-timing-policy` (the `--strict` step immediately above
it) already runs the absolute `max_fast_tests` ceiling check both in CI and
in `make ci-lint` -- the delta guard is additive to that check, not a
replacement, and is fail-open (`DELTA_CHECK_SKIPPED`, exit 0) whenever no
baseline is available, which is always true locally. See
docs/operations/fast-lane-budget.md for the full model.

## Guards `ci-lint` skips when it runs on a CI runner itself

Everything above is about the direction "a `pr.yml` guard must also run
locally." There is a second, separate direction this doc did not previously
cover: `develop-post-merge.yml`'s `lint` job runs `make ci-lint` directly on
a real, ephemeral GitHub-hosted runner (not as a local-parity convenience --
as a blocking gate wired into `auto-revert-on-failure`). Most `ci-lint`
guards are equally meaningful there, because they inspect the checked-out
tree, the installed venv, or a registry the repo ships -- none of which
differ between a laptop and a runner. A couple of guards instead read state
that only exists on a developer machine, and behave one of two bad ways on a
runner that lacks it:

- **Fail for a reason that has nothing to do with the code under test.**
  `agent-identity-check` did exactly this before #1558/#1509: it resolves
  `git config user.*`, an ephemeral runner has none, and the check treated
  "no identity" as a hard failure -- reddening every post-merge run for an
  environment fact, not a defect.
- **Silently no-op and report success while checking nothing.** This is the
  more dangerous failure mode: a guard that cannot fail reads as coverage in
  the Actions log and is never investigated. `skill-sync-check` does this
  today if left unguarded -- it shells out to `$(SKILL_SYNC)`, a local
  absolute developer path that plainly does not exist on a runner, hits its
  own "not installed; skipping" branch, and exits 0.

`_project/scripts/ci_lint_environment_gate.py` is the single place that
draws this boundary: a small, declarative `RUNNER_INAPPLICABLE_GUARDS` table
mapping a guard slug to why it cannot produce a meaningful result on
`GITHUB_ACTIONS=true`. The `ci-lint` recipe calls it immediately before each
listed guard (`if uv run -- python _project/scripts/ci_lint_environment_gate.py <slug>; then ...; fi`)
instead of the guard's own ad hoc `if [ "$$GITHUB_ACTIONS" = "true" ]`
special-case -- exactly the pattern the old `agent-identity-check` synthetic-identity
injection was, and the reason a *general* mechanism replaced it rather than
gaining a second one for `skill-sync-check`. A guard not listed in the table
always runs, on a runner exactly as it does locally -- the table is a narrow,
reasoned allowlist of exceptions, not a generic on/off switch, and adding an
entry removes real CI coverage inside `make ci-lint`'s own CI invocation
unless that guard is *also* covered for real somewhere else in CI:

- `agent-identity-check` has no CI-runner equivalent anywhere, by design --
  see `pr.yml`'s `code-lint` job, which has no counterpart step for the same
  reason. `agent-commit-range-check` is the real merge-time control (it
  reads the commits a branch actually carries, not resolved config) and is
  never in the gate's table; it keeps running unconditionally, in `ci-lint`
  and in `pr.yml`.
- `skill-sync-check`'s real CI-side coverage is `pr.yml`'s
  `guard-skill-sync-verify` step (the pinned-SHA network checkout described
  above), which runs against every PR before it can reach develop. Skipping
  the local-path-based `skill-sync-check` inside `ci-lint`'s own CI
  invocation does not remove coverage that existed there -- it removes a
  guard that was already structurally unable to check anything on a runner.

`GITHUB_ACTIONS` is never hand-toggled here: it is the platform-set variable
every GitHub Actions job already has, so local runs (including
`pr-preflight`) are unaffected -- both listed guards keep running locally
exactly as before this table existed.

## `pr-preflight` and the content guard

`make pr-preflight-fast-tests` (called by `make pr-preflight`) always runs
`pr-content-guard` (YAML/markdown/docs hygiene + artifact hygiene) now,
regardless of whether the branch's `needs-code-ci` path-filter decision is
true. Previously it only ran on the no-code-changes branch, so a PR that
touched both code and docs/markdown could skip those hygiene checks
locally and hit them for the first time in CI's `content-guard` job. The
`needs-code-ci` decision still gates only the fast-test pytest run.
