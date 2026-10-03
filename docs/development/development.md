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
make test
uv run -- python -m pytest -m fast

make test-all
uv run -- python -m pytest

make test-unit
uv run -- python -m pytest -m unit

make test-integration
uv run -- python -m pytest -m "integration and not live_integration"

make coverage-fast
make coverage-all
make coverage-opt-in-all
uv run -- python -m pytest --cov=benchbox --cov-report=term-missing
```

Linting and formatting run through Ruff:

```bash
make format
uv run ruff format .

make lint
uv run ruff check .
```

Type checking is available via:

```bash
make typecheck
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

## Pull Request Lifecycle & Merge Queue Integration

BenchBox enforces single-commit squash integration into `develop` with strict current-base verification:

- **`make pr-open`**: Pushes the current branch, verifies it is current with `origin/develop`, and creates or reuses the pull request. Arm it with `make pr-arm` (see `CONTRIBUTING.md`) and monitor until it merges.
- **`make pr-open READY=1`**: Opens or reuses the PR and arms it with `make pr-arm` in one step.
- **`make pr-ready PR=<n> HEAD=<sha>`**: Arms an open PR for an exact head through `make pr-arm`. With `EVIDENCE` or `BATCH` it instead runs the exact readiness transaction from caller-supplied evidence, used for a prepared batch, and arms auto-merge only after local/remote head, review, required-check, hold, and (for batch mode) final-tree checks pass. When a merge queue is active on `develop`, arming automatically enqueues the PR for speculative combined-tree testing.
- **Soundness Gate**: PRs modifying soundness-critical paths (`benchbox/core/equivalence/`, `benchbox/core/expected_results/`, etc.) carry a PR-body review attestation that `soundness-flag` checks, and `auto-merge-on-open.yml` disarms them on every push, so arm them with `make pr-arm` after the last push.
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


## Documentation templates

`docs/conf.py` selects Furo and loads the first-party templates under
`docs/_templates`. The custom `page.html` bridges ABlog into Furo's page structure:
ABlog's default page uses a layout that Furo does not provide. Sphinx's
`!page.html` lookup selects the installed theme's page rather than recursively
loading the custom override. The local ABlog archive and redirect templates
extend the custom page, keeping the shared navigation and footer controls.

The body block adds the site navigation before Furo's inherited body. The footer
adds the shared system/light/dark theme control. The extra-head block applies
stored theme choice before the page paints and adds the Atom feed link when ABlog
provides its feed context. The content block preserves Sphinx's rendered body,
adds date/author/tag metadata, moves that metadata after the first page heading,
and adds previous/next post links when enabled. Keep these responsibilities when
changing the template structure.

Template ownership follows its inputs. The installed Furo templates are external
package content; the local overrides, blog metadata and rendered documentation
remain first-party. `super()` selects inherited block output and `body` contains
Sphinx's rendered document; neither proves that all emitted content is external
or plain text. ABlog titles, collection names and feed settings also contribute
to output. Sphinx's template environment does not enable automatic HTML escaping.

The comment checker can analyze complete script/style regions that lie within a
single literal Jinja data segment with the existing JavaScript/CSS adapters. It
keeps unresolved rendered output visible as a coverage error. A literal source
scan does not certify all possible rendered pages: emitted tags, expressions and
control statements can alter executable regions; even Jinja comments can join
script fragments after removal. Do not silence that uncertainty
by treating framework context values as an ownership exemption.
