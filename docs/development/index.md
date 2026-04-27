<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Developer Documentation

```{tags} contributor
```

Documentation for contributors and developers working on BenchBox.

## Roadmap

- [Development Roadmap](roadmap.md) - Planned platform and benchmark additions

## Getting Started with Development

- [Development Guide](development.md) - Setting up development environment and workflow
- [Testing](testing.md) - Testing strategies, running tests, and test organization
- [Pytest xdist Safety](pytest-xdist-safety.md) - Why macOS worker counts are capped and how to validate changes

## Contributing

- [Adding New Platforms](adding-new-platforms.md) - How to add support for new database platforms
- [Import Patterns](import-patterns.md) - Lazy loading and dependency management patterns
- [TPC Compilation Guide](tpc-compilation-guide.md) - Compiling TPC benchmark tools

## Architecture & Design

- [Architecture Overview](../design/architecture.md) - High-level system architecture
- [Code Structure](../design/structure.md) - Codebase organization
- [DB API 2.0](db-api-2.md) - Python DB API 2.0 specification and platform integration
- [Runtime Modules](runtime-modules.md) - Runtime module organization and responsibilities
- [Run Lifecycle Map](run-lifecycle-map.md) - Current `benchbox run` execution/export branches
- [Data Sharing](data-sharing.md) - Data sharing between benchmark phases
- [Dependency Compatibility](dependency-compatibility.md) - Managing optional dependencies

## Testing

- [Testing Guide](testing.md) - Testing strategies and test organization
- [Pytest xdist Safety](pytest-xdist-safety.md) - Root cause, reproducer, and validation checklist for xdist lock-ups
- [Testing Index](../testing/index.md) - Test documentation overview
- [Live Integration Tests](../testing/live-integration-tests.md) - Running tests against live databases

## Results & Validation

- [Result Integrity Validation](result-integrity-validation.md) - Three-tier validator: structural, completeness, and believability checks for result JSON files

## Reference

- [Read Primitives Catalog](read-primitives-catalog.md) - Catalog of primitive read operations
- [Read Primitives: Platform Skip Reference](read-primitives-skips-reference.md) - Why each query is skipped per platform and how to re-enable

## Related Documentation

- [Concepts](../concepts/index.md) - Core concepts and glossary

```{toctree}
:maxdepth: 1

roadmap
getting-started
development
platform-development
adding-new-platforms
adding-dataframe-platform
architecture-design
data-dependencies
import-patterns
tpc-compilation-guide
testing
pytest-xdist-safety
read-primitives-catalog
read-primitives-skips-reference
runtime-modules
run-lifecycle-map
data-sharing
dependency-compatibility
db-api-2
test-quality-guidelines
result-integrity-validation
../platform-config-audit
```
