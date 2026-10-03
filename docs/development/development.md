<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Development Guide

```{tags} contributor, guide
```

This guide provides information for developers who want to contribute to BenchBox or understand its internal architecture.

## Getting Started with Development

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) **0.8 or newer** (recommended for environment
  management). The committed `uv.lock` uses lockfile `revision = 3`; an older uv
  silently rewrites it to revision 2 as a side effect of any `uv add`/`uv lock`
  run. A pre-commit guard (`_project/scripts/check_uv_lock_revision.py`, also
  runnable via `make uv-lock-revision-check`) rejects such a downgrade — if it
  fires, upgrade uv (`uv self update`) and regenerate the lock.
- `git`

### Setting up the Development Environment

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/BenchBox-dev/benchbox.git
    cd BenchBox
    ```

2.  **Create a virtual environment:**

    ```bash
    uv venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**

    ```bash
    uv pip install -e .[dev,docs]
    ```

    The `[dev]` extra installs testing, linting, and typing tools. Combine it with `[docs]` when you plan to build the Sphinx documentation locally.

### Running Tests

BenchBox uses `pytest` for testing. Run tests using either `make` commands or direct `pytest`:

```bash
# Fast tests for quick feedback
make test
# or
uv run -- python -m pytest -m fast

# Full test suite
make test-all
# or
uv run -- python -m pytest

# Unit tests only
make test-unit
# or
uv run -- python -m pytest -m unit

# Integration tests
make test-integration
# or
uv run -- python -m pytest -m "integration and not live_integration"

# With coverage (fast tests only - quick feedback)
make coverage-fast
# or routine coverage (excludes stress/resource-heavy/live tests)
make coverage-all
# or full tree including opt-in stress/resource-heavy/live tests (needs services + credentials)
make coverage-opt-in-all
# or
uv run -- python -m pytest --cov=benchbox --cov-report=term-missing
```

Linting and formatting run through Ruff:

```bash
make format
# or
uv run ruff format .

make lint
# or
uv run ruff check .
```

Type checking is available via:

```bash
make typecheck
# or
uv run ty check
```

## Contributing

We welcome contributions! Please see the `CONTRIBUTING.md` file in the root of the project for details on our development process, coding standards, and how to submit a pull request.

## Maintainer Dev Loop

Maintainers and AI agents use one disposable linked worktree per task. Create
it for the branch, work there until the PR merges, then remove that exact
clean registration. See [the disposable worktree guide](../operations/dev-loop-worktrees.md)
for common commands and recovery scenarios. External contributors working
from a fork can use the same lifecycle.

## Pull Request Lifecycle

BenchBox enforces single-commit squash integration into `develop`. A pull request merges by auto-merge once its required checks pass on its own head; there is no merge queue and no strict up-to-date rule. `.github/workflows/trunk.yml` tests `develop` after each merge, and a red trunk is reverted first (`make trunk-revert PR=<n>`; see `docs/operations/merge-queue-governance.md`):

- **`make pr-open`**: Pushes the current branch, verifies it does not conflict with `origin/develop`, and creates or reuses the pull request. It refuses any pull request that is not a revert while trunk has been red for more than 30 minutes. Arm it with `make pr-arm` (see `CONTRIBUTING.md`) and monitor until it merges.
- **`make pr-open READY=1`**: Opens or reuses the PR and arms it with `make pr-arm` in one step.
- **`make pr-ready PR=<n> HEAD=<sha>`**: Arms an open PR for an exact head through `make pr-arm`. With `EVIDENCE` or `BATCH` it instead runs the exact readiness transaction from caller-supplied evidence, used for a prepared batch, and arms auto-merge only after local/remote head, review, required-check, hold, and (for batch mode) final-tree checks pass. GitHub then merges the PR as soon as the required checks are green on that head.
- **Soundness Gate**: PRs modifying soundness-critical paths (`benchbox/core/equivalence/`, `benchbox/core/expected_results/`, etc.) need the required `oracle-review` check, which passes only when the Codex connector app has reviewed the current head (required thread resolution binds its findings), and `auto-merge-on-open.yml` disarms them on every push, so arm them with `make pr-arm` after the last push.
- **`make pr-refresh`**: Refreshes a stale PR branch onto `origin/develop` when resolving merge conflicts locally. Run one branch at a time.

## Release Preparation Workflow

See [the release guide](../operations/release-guide.md) for the full
maintainer workflow (version-branch flow on a single repo with
`develop` and `main`).

## Validation APIs

BenchBox exposes a CLI-independent validation workflow through
`benchbox.core.validation.ValidationService`. The service orchestrates preflight,
manifest, database, and platform capability checks and returns structured
`ValidationResult` objects that mirror the data surfaced by the CLI.
Programmatic consumers can run comprehensive validation with:

```python
from benchbox.core.validation import ValidationService

service = ValidationService()
results = service.run_comprehensive(
    benchmark_type="tpcds",
    scale_factor=1.0,
    output_dir=output_path,
    manifest_path=manifest_path,
    connection=db_connection,
    platform_adapter=adapter,
)
summary = service.summarize(results)
```

This enables benchmarks, adapters, and external automation to reuse the same
validation logic without importing CLI modules.

The CLI mirrors these capabilities via the `benchbox run` command. Use
`--enable-preflight-validation`, `--enable-postgen-manifest-validation`, and
`--enable-postload-validation` to toggle each stage while the core lifecycle
runner captures the resulting validation metadata.

## Import Patterns

Benchmarks use a lightweight lazy-loading system so the core package can start
quickly and only load optional dependencies when needed. See
`docs/development/import-patterns.md` for guidance on adding new benchmarks to
the registry, writing tests for lazy imports, and troubleshooting missing
dependency errors.
