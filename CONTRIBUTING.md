<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Contributing to BenchBox

Code contributions that improve the quality and reliability of BenchBox are always welcomed.

This document provides guidelines and instructions for contributing.

## Development Environment Setup

### Prerequisites

- Python 3.8 or higher
- Git
- uv (fast Python package manager)

### Setting Up Your Environment

1. Clone the repository:
   ```bash
   git clone https://github.com/username/benchbox.git
   cd benchbox
   ```

2. Install the package in development mode:
   ```bash
   make develop
   ```

   Or manually with uv (modern approach):
   ```bash
   uv sync --group dev
   ```

3. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

## Development Workflow

1. Create a new branch for your feature or bugfix:
   ```bash
   git checkout -b feature-name
   ```

2. Make your changes and ensure all tests pass:
   ```bash
   make test
   ```

   Or run tests directly:
   ```bash
   uv run -- python -m pytest
   ```

3. Ensure your code follows our style guidelines:
   ```bash
   make format    # Format code with ruff
   make lint      # Check code style
   make typecheck # Type checking with ty
   ```

   Or run checks directly:
   ```bash
   uv run ruff format .
   uv run ruff check .
   uv run ty check
   ```
   (Note: pre-commit will run these checks automatically when you commit)

4. Commit your changes:
   ```bash
   git commit -m "Description of changes"
   ```

5. Push your branch and create a pull request:
   ```bash
   git push origin feature-name
   ```

## Pre-Push Validation

Before pushing code, run the CI checks locally to catch issues early:

```bash
# Run ALL CI checks (recommended before pushing)
make ci-local
```

This runs the same checks as GitHub Actions:
1. Lint + format + type checking (`make ci-lint`)
2. Fast tests with coverage (`make ci-test`)
3. Integration smoke tests (`make test-integration-smoke`)
4. Documentation build (`make ci-docs`)
5. Package build and install test (`make test-package`)

You can also run individual checks:

```bash
make ci-lint              # Lint, format check, and type checking
make ci-test              # Fast tests with 75% coverage threshold
make ci-docs              # Build documentation
make test-integration-smoke  # Quick integration tests
make test-package         # Build and test package installation
make security-audit       # Run pip-audit security scan
make spellcheck           # Check spelling with codespell
make docstring-coverage   # Check docstring coverage
```

Running `make ci-local` before every push ensures CI will pass and saves time waiting for GitHub Actions feedback.

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
   release-curated tree and opens a PR against `main`.
3. Squash-merge the PR; tag `main`; `release.yml` publishes to PyPI.
4. `make release-rebase-develop VERSION=X.Y.Z` rebases `develop` onto the
   release-shaped `main`.

We follow semantic versioning.

## License

By contributing to BenchBox, you agree that your contributions will be licensed under the project's MIT license.
