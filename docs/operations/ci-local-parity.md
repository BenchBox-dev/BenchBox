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
`npx -y github:joeharris76/skill-sync#<sha> verify` step -- treating the
name match as parity would hide that the local run isn't actually checking
what CI checks.

## Adding a new lint guard

When you add a new guard step to the `lint` job in `pr.yml`:

1. Add the equivalent command to the `ci-lint:` recipe in the `Makefile`
   (a `$(MAKE) <target>` line if the guard already has a `make` target, or
   the same `uv run ...` / script invocation the CI step uses).
2. If the guard has meaningful inline logic (more than a couple of lines)
   and would otherwise live only inside the workflow YAML, extract it to a
   script under `scripts/` first and have both `pr.yml` and `ci-lint` call
   that script. Duplicating logic into the Makefile as a second
   implementation is exactly the drift this invariant exists to prevent.
3. Run `uv run -- python -m pytest tests/system/test_ci_lint_parity.py -q`.
   If it fails, either step 1 was missed or the command text doesn't match
   verbatim.

If a guard genuinely cannot run locally (see the network exception below
for the only current example), add it to the `EXCLUDED_STEPS` dict in the
parity test with a concrete reason -- do not silently omit it, and do not
weaken the CI guard itself so a lossier local equivalent can "pass."

## The one documented exception: skill-sync `npx` verify

The `lint` job's "skill-sync tracked snapshot verify (cloud/CI integrity
gate)" step runs a pinned `npx -y github:joeharris76/skill-sync#<sha>
verify --project .`. This needs network access to fetch the pinned commit
from GitHub over the npm/git-over-https path `npx` uses for a `github:`
spec.

This was tested directly in a local/sandboxed dev shell with `npx`
installed: the command hangs with no route (no DNS/proxy path configured
for the npm registry or a git-over-https fetch). Two options were
considered:

- **Guard it with `command -v npx && npx ... || echo notice`.** Rejected:
  on a machine where `npx` *is* installed and network *is* reachable, this
  swallows a real local verify failure and prints a "skipped" notice
  instead -- silently weakening the guard, which is the exact anti-pattern
  this parity invariant exists to prevent elsewhere.
- **Exclude it explicitly, with a reason, in the parity test.** This is
  what the repo does. CI's runner has network, so the gate stays fully
  enforced there; it is simply not a viable *blocking* local gate.

`make ci-lint` therefore does not run this step. `make skill-sync-check`
(`node skill-sync doctor`) is a different, unrelated local convenience and
does not substitute for it -- see the command-level-parity note above.

## `pr-preflight` and the content guard

`make pr-preflight-fast-tests` (called by `make pr-preflight`) always runs
`pr-content-guard` (YAML/markdown/docs hygiene + artifact hygiene) now,
regardless of whether the branch's `needs-code-ci` path-filter decision is
true. Previously it only ran on the no-code-changes branch, so a PR that
touched both code and docs/markdown could skip those hygiene checks
locally and hit them for the first time in CI's `content-guard` job. The
`needs-code-ci` decision still gates only the fast-test pytest run.
