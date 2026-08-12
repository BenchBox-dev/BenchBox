<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Contributing to BenchBox

Code contributions that improve the quality and reliability of BenchBox are always welcomed.

This document provides guidelines and instructions for contributing.

## Development Environment Setup

### Prerequisites

- Python 3.10+
- Git
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)
- [GitHub CLI](https://cli.github.com/) (`gh`) — required for the one-shot PR flow below

### Setting Up Your Environment

1. Clone the repository:
   ```bash
   git clone https://github.com/joeharris76/BenchBox.git
   cd BenchBox
   ```

2. Install the package in development mode:
   ```bash
   make develop          # equivalent to: uv sync --group dev
   ```

3. Install the pre-commit + pre-push hooks:
   ```bash
   pre-commit install
   ```

   This installs two hooks (configured in `.pre-commit-config.yaml`):
   - **pre-commit**: ruff format/check, codespell, YAML / markdown lint, timing-policy check.
   - **pre-push**: `pr-preflight-fast-tests` — when `BENCHBOX_PREPUSH=1`, runs the path-aware fast-test lane so code PR pushes don't discover failures via the CI roundtrip.
   Existing clones that installed hooks before the pre-push stage was added should re-run `pre-commit install` once.

   If `pre-commit install` errors with `Cowardly refusing to install hooks with core.hooksPath set` and points at the default `.git/hooks` location, run `git config --unset-all core.hooksPath` and try again — that's a redundant override left over from earlier tooling.

## Branches & PR gate

`develop` is the long-lived development branch and the repository's default branch; **all changes land via PR**. `release` is release-only (handled by the version-branch flow — see `docs/operations/release-guide.md`). PRs target `develop` and squash-merge with linear history.

Required CI on `develop` reports through `ci-required-result`. The umbrella uses `.github/path-filters.yml` to classify each PR: content-only PRs run content validation and skip Python fast tests, while code, infra, workflow, tooling, and unknown paths run the post-Step-3 lint/type + Ubuntu 3.12 fast-test gate. Reviews are not required for solo-dev work; once a finished branch is armed, auto-merge lands it when required checks are green.

## Development Workflow

The canonical loop is **branch → edit → preflight → `make pr-open` → (when final) arm**. `make pr-open` **withholds** auto-merge by default so follow-up commits cannot race a half-pushed stack. When the branch is finished, arm with `make pr-ready` (or open already-final work with `make pr-open READY=1`); then walk away — don't poll.

1. **Create a feature worktree off `develop`.** Agents must keep the main clone read-only:

   ```bash
   WORKTREE_PATH=../BenchBox.wt-feat-your-thing
   make worktree-create BRANCH=feat/your-thing WORKTREE_PATH="$WORKTREE_PATH"
   cd "$WORKTREE_PATH"
   make agent-write-preflight
   uv sync --group dev
   ```

2. **Make your changes.** Iterate with the fast lane:

   ```bash
   make test              # fast lane (~1 min)
   make format            # ruff format .
   make lint              # ruff check .
   make typecheck         # ty check
   ```

   The pre-commit hook re-runs format/lint/etc. at commit time, so if you forget, the commit will fix or block as appropriate.

3. **Commit using [Conventional Commits](https://www.conventionalcommits.org/)** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`, `refactor:`):

   ```bash
   git add path/to/file.py path/to/test.py    # explicit paths, never -A
   git commit -m "fix: resolve race in foo loader"
   ```

4. **Run the local preflight, then open the PR (auto-merge withheld):**

   ```bash
   make pr-preflight      # local lint + path-aware content guard / fast tests
   make pr-open           # push + gh pr create --base develop (does NOT arm auto-merge)
   ```

   `make pr-open` refuses to run from `develop` or `release`. The PR stays open without auto-merge so you can push follow-ups safely.

5. **When the branch is final, arm auto-merge** (hands-free finish path):

   ```bash
   make pr-ready          # arm squash auto-merge on the open PR
   # Or open and arm in one step when you already know the branch is done:
   # make pr-open READY=1
   ```

   `make pr-ready` (or `READY=1`) is the only arm path: `auto-merge-on-open.yml` is revoke-only and never arms — not on `opened` / `reopened` / `synchronize`, and not on draft → ready (`ready_for_review` is not even a trigger; the historical workflow arm point never fired once and was deleted). Once armed, the PR squash-merges when required checks turn green — don't poll. Soundness-critical paths and the `no-auto-merge` hold label stay withheld pending review (see `docs/operations/repo-admin-settings.md`).

6. **After merge**, remove the clean linked worktree. The remote branch normally auto-deletes through the repository setting; clean local branches separately:

   ```bash
   make worktree-remove WORKTREE_PATH="$WORKTREE_PATH"
   ```

   Inspect open PRs at any time with `make pr-status`.

## Pre-Push Validation

There are two layers, and you only need the first:

**Required gate (mirrors what CI enforces):**

```bash
make pr-preflight
```

This runs the local lint/type gate, then uses `.github/path-filters.yml` to decide the fast-test lane. Content-only branches run the cheap content guard and skip Python fast tests; code, infra, workflow, tooling, and unknown paths run the fast tests. This mirrors the `ci-required-result` umbrella, so a green preflight almost always means a green CI. The opt-in pre-push git hook runs the same path-aware test portion when `BENCHBOX_PREPUSH=1`.

**Optional thoroughness check** — only useful when you've changed cross-cutting things (CI workflows, packaging, docs build, integration paths):

```bash
make ci-local
```

This runs the broader CI mirror:

| Step | Target |
|---|---|
| Lint + format + type checking | `make ci-lint` |
| Fast tests with coverage | `make ci-test` |
| Integration smoke tests | `make test-integration-smoke` |
| Documentation build | `make ci-docs` |
| Package build + install test | `make test-package` |

Or run any of those individually. Additional one-offs: `make security-audit`, `make spellcheck`, `make docstring-coverage`.

Skip `make ci-local` for everyday changes — `make pr-preflight` is the right gate. Once the PR is armed, auto-merge still blocks on any non-required check failure that *is* surfaced (e.g. doc build), so the cost of being wrong is just a re-push (and re-arm with `make pr-ready` if needed).

## Testing

We use pytest for testing. Common testing commands:

```bash
make test              # Fast local run (no coverage)
make test-unit         # Run unit tests only
make test-integration  # Run integration tests only
make test-fast         # Run fast tests (< 1 sec)
make test-ci           # CI profile with coverage + reports
```

The default `pytest.ini` is optimized for quick local feedback. Use the CI profile when you need coverage, HTML reports,
or JUnit XML output.

```bash
uv run -- python -m pytest                     # Fast local run
uv run -- python -m pytest -c pytest-ci.ini    # CI-equivalent instrumentation
uv run -- python -m pytest -m fast             # Fast tests only
```

The collection hook applies simple defaults: tests in `tests/unit` automatically receive the `unit` and `fast` markers, `tests/integration` receive `integration` with a default `medium` speed, and files in `tests/performance` are marked `performance` and `slow`. Add explicit markers to override those defaults for individual tests.

### Running the PySpark suite

PySpark 4.x only supports Java 17 and 21, so we provide `scripts/with_supported_java.sh` to automatically pick a compatible JDK (it prefers macOS’ `/usr/libexec/java_home -v 21`, then 17, and falls back to whatever `JAVA_HOME` you already exported). No shims are added for older runtimes.

To run every PySpark unit test:

```bash
make test-pyspark
```

The target shells out to the helper script, which validates the Java version and executes `tests/unit/platforms/dataframe/test_pyspark_df.py`. You can also wrap any BenchBox command that touches PySpark - benchmarks, smoke runs, etc.-like this:

```bash
scripts/with_supported_java.sh benchbox run --platform pyspark-df --benchmark tpch --scale 0.01 --non-interactive
```

CI jobs install Temurin 21 and invoke the same helpers so PySpark stays active everywhere automatically.

## Adding a New Benchmark

To add a new benchmark, create a new file in the `benchbox` directory and implement the `BaseBenchmark` interface. See existing benchmarks for examples.

## Adding DataFrame Platform Support

BenchBox uses a family-based architecture for DataFrame platforms. To add a new platform:

1. **Determine the family**: Expression (Polars, PySpark) or Pandas (Pandas, Modin, cuDF)
2. **Implement DataFrameContext**: Provides table access and family-specific helpers
3. **Implement platform adapter**: Handles data loading and query execution
4. **Register the platform**: Add to `DATAFRAME_ADAPTERS` registry
5. **Add tests**: Unit tests and integration tests

See [Adding a DataFrame Platform](docs/development/adding-dataframe-platform.md) for detailed instructions.

### DataFrame Query Guidelines

When implementing new DataFrame queries:

- Each query needs both `expression_impl` and `pandas_impl` functions
- Use the `DataFrameContext` protocol for table access
- Use `ctx.col` and `ctx.lit` for expression family implementations
- Use string-based column access for pandas family implementations
- Test both families independently

## Code Style

We use ruff for fast Python linting and formatting with a 120-character line length. Type hints are required and enforced with ty. Our pre-commit hooks will help enforce these standards.

- **Line length**: 120 characters
- **Formatter**: ruff (replaces black and isort)
- **Linter**: ruff (replaces flake8)
- **Type checker**: ty

## Documentation

Please update documentation when adding or modifying features. We use Sphinx for generating documentation.

## Releasing

External contributions land via PR against `develop` (squash-merge). Releases
are cut by maintainers via the version-branch flow documented in
[`docs/operations/release-guide.md`](docs/operations/release-guide.md):

1. `make bump VERSION=X.Y.Z` and `make changelog-draft VERSION=X.Y.Z` on `develop`.
2. `make release-prepare VERSION=X.Y.Z` cuts `vX.Y.Z` from `develop` with a
   release-curated tree and opens a PR against `release`.
3. Squash-merge the PR; tag `release`; `release.yml` publishes to PyPI.
4. `make release-rebase-develop VERSION=X.Y.Z` rebases `develop` onto the
   release-shaped `release` branch.

We follow semantic versioning.

## License

By contributing to BenchBox, you agree that your contributions will be licensed under the project's MIT license.
