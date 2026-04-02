<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Development Guide

```{tags} contributor, guide
```

This guide provides information for developers who want to contribute to BenchBox or understand its internal architecture.

## Getting Started with Development

### Prerequisites

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) (recommended for environment management)
- `git`

### Setting up the Development Environment

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/joeharris76/benchbox.git
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
# or full suite
make coverage-all
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

## Release Preparation Workflow

BenchBox uses a fully automated release process that handles tree curation, package building,
smoke testing, and git operations with timestamp normalization. See
[release/RELEASE_AUTOMATION.md](../../release/RELEASE_AUTOMATION.md) for complete documentation.

### Quick Start

```bash
# Run the complete automated release workflow
./scripts/automate_release.py --version 0.2.0
```

This single command performs:

1. **Pre-flight checks**: Validates CHANGELOG, git status, and version format
2. **Tree curation**: Creates public snapshot in `../BenchBox-public/`
3. **Package building**: Builds wheel and sdist with `SOURCE_DATE_EPOCH`
4. **Smoke tests**: Installs and tests in isolated environment
5. **Git operations**: Creates commit and tag with normalized timestamps
6. **Archiving**: Saves artifacts to `release/archive/v0.2.0/`

All file timestamps are normalized to the most recent Saturday at midnight UTC,
ensuring no trace of actual creation/modification times.

### Manual Steps

The following remain manual for safety:

- **Before release**: Update CHANGELOG.md with release notes
- **After automation**: Push to remote (`git push origin main && git push origin v0.2.0`)
- **Publishing**: Upload to PyPI (`twine upload dist/benchbox-0.2.0*`)

### Component Scripts

The automation orchestrates these internal scripts (not typically called directly):

- `scripts/prepare_release.py` - Tree curation
- `scripts/build_release.py` - Package building with timestamp normalization
- `scripts/verify_release.py` - Smoke testing
- `scripts/finalize_release.py` - Git operations

For emergency manual operation or debugging, see the detailed documentation.

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
