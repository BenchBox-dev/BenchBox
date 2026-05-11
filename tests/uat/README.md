# tests/uat — Developer Guide

This is the framework developer's guide. The operator guide is
`docs/operations/uat-framework.md`; the design contract is
`_project/specs/uat-framework.md`.

## Layout

```
tests/uat/
├── __init__.py
├── _cli.py                        # argparse entry points for every make uat-* target
├── matrix.py                      # platform/benchmark dicts + reachability + registry import
├── runner.py                      # single-cell execution
├── config.py                      # YAML schema validation
├── timeouts.py                    # signal-based subprocess timeout
├── ladder.py                      # scale-ladder + early-stop
├── cleanup.py                     # reuse-aware database pruning
├── docker_assets.py               # UAT-owned Docker compose mapping/lifecycle helpers
├── orchestrator.py                # sweep orchestration (make uat-sweep entry point)
├── phases/
│   ├── preflight.py
│   ├── enumerate.py
│   ├── execute.py
│   ├── validate.py
│   ├── package.py
│   ├── explorer_smoke.py
│   └── report.py
├── configs/
│   ├── stress-default.yaml        # TEMPLATE preset for `make uat-stress`
│   ├── uat-2026-05-02.yaml        # FROZEN replay of the historical sweep
│   └── .frozen-hashes.json        # SHA-256 enforcement for FROZEN files
├── fixtures/
│   └── uat-2026-05-02-matrix-summary-header.tsv
├── test_*.py                      # fast-test coverage (mark.fast)
└── test_replay_2026_05_02.py      # slow-marked structural-parity assertion
```

## Adding a phase

1. Create `tests/uat/phases/<name>.py` with a top-level `run_<name>`
   function that takes a `UATConfig` (or just the inputs it needs) and
   returns a dataclass with an `exit_code()` method.
2. Add `<name>` to `tests/uat/config.py::VALID_PHASES`.
3. Wire the phase into `tests/uat/orchestrator.py::run_sweep`.
4. Add a `<name>_main` argparse entry in `tests/uat/_cli.py`.
5. Add a `make uat-<name>` target to the Makefile.
6. Add fast tests to `tests/uat/test_<name>.py`.

## Running tests

```bash
# Fast tests only (default for `make test-fast`).
uv run -- python -m pytest tests/uat -q -m fast

# All tests including the slow-marked replay assertion.
uv run -- python -m pytest tests/uat -q -m "fast or slow"
```

## Bash-parity test

`tests/uat/test_matrix.py::test_bash_parity_*` parses
`scripts/local_stress_test.sh` and asserts every key/value in the
bash case statements matches `matrix.py`. If the bash script changes,
this test fails and the Python port must be updated in the same PR.
This is the drift-prevention contract.

## Sequential platform execution

`config.execute.parallel_platforms` exists as a reserved field that
must be `False`. Setting it `True` raises at config load time; the
execute phase additionally asserts `False` at runtime as a second
line of defence. Do not delete either guard. Origin of the rule:
UAT W3 line 222 in
`_project/handoffs/results-explorer-uat-retrospective-20260502.md`.

## Runtime output root

UAT sweeps default to the shared `~/Developer/benchmark_runs` root,
not the current worktree. `output.benchmark_runs_dir_template` is
resolved once per sweep and passed to every `benchbox run` subprocess
as `BENCHBOX_OUTPUT_DIR`; preflight and reuse-aware database cleanup
derive their default roots from the same value. Keep these paths
aligned whenever adding a phase that reads or writes run artefacts.

## Docker lifecycle boundary

Docker lifecycle belongs in `phases/execute.py`, not in platform
adapters and not in `benchbox run`. The execute phase is the only layer
that knows when all cells for one platform have finished and the next
platform is about to start, so it can preserve same-platform reuse while
releasing UAT-owned Docker volumes before the next platform.

`docker_assets.py` owns the platform → compose-file mapping, project-name
sanitizer, and command builders. Automated commands must always include
`docker compose -p <uat-owned-project> -f <compose-file>` and must never
use global prune commands. The current managed-start contract is:

- `cleanup.docker_manage_platforms: false` (default): keep existing
  external-stack behavior; reachability probes decide whether Docker
  platforms run or skip, and Docker cleanup is reported as disabled.
- `cleanup.docker_manage_platforms: true`: start a deterministic
  `benchbox-uat-...` compose project before probing a Docker platform and
  tear down only that project in a `finally` block at platform completion.
- `cleanup.docker_platform_switch: volumes`: the storage-saving mode;
  generates `down -v --remove-orphans` for the UAT-owned project only.

Compose files with fixed `container_name` values are not project-scoped;
managed startup rejects those platforms until the compose file is changed
or a safe override is added. Today that affects `pg-duckdb`,
`pg-mooncake`, and `timescaledb`. Keep fast tests for this mapping in
sync with `matrix.PLATFORM_GROUPS["docker"]`.

Interrupted-run recovery is explicit:

```bash
make uat-docker-cleanup        # dry-run inventory + commands
make uat-docker-cleanup APPLY=1
```

The recovery command removes only compose-labelled projects whose name
starts with the UAT prefix (`benchbox-uat` by default). It also reports
non-UAT Docker resources with creation time and a manual cleanup command,
but it never deletes them automatically.

## Frozen-config hashes

When you add a new FROZEN config:

```bash
python3 -c "import hashlib; from pathlib import Path; \
  print(hashlib.sha256(Path('tests/uat/configs/<name>.yaml').read_bytes()).hexdigest())"
```

Add the entry to `tests/uat/configs/.frozen-hashes.json` and commit
both files together. `tests/uat/test_frozen_configs.py` enforces
hash equality at PR time.

## Dependencies

The framework imports `benchbox.core.benchmark_registry` directly (no
eval, no shell-out). It invokes `scripts/uat_validator_rollup.py` and
`scripts/validate_submission.py` as subprocesses without modifying
their public CLIs. It does not import or modify any code under
`benchbox/`, `results-explorer/`, or `results-data/`.
