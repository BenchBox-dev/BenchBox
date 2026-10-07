# Utility Commands

```{tags} reference, cli
```

This page covers smaller utility commands for dependency checking, system profiling, benchmark discovery, and configuration validation.

(cli-check-deps)=
## `check-deps` - Check Dependencies

Check dependency status and provide installation guidance for different platforms.

### Options

- `--platform TEXT`: Check dependencies for specific platform
- `--verbose`, `-v`: Show detailed dependency information
- `--matrix`: Show installation matrix and exit

### Usage Examples

```bash
# Overview of all platform dependencies
benchbox check-deps

# Check specific platform
benchbox check-deps --platform databricks

# Show detailed installation matrix
benchbox check-deps --matrix

# Verbose output with recommendations
benchbox check-deps --verbose
```

(cli-profile)=
## `profile` - System Profiling

Profile the current system to understand hardware capabilities and provide recommendations.

### Usage

```bash
benchbox profile
```

This command analyzes:
- CPU cores and architecture
- Memory capacity and availability
- Disk space
- Operating system details
- Python environment

Provides recommendations for:
- Appropriate scale factors
- Concurrency settings
- Platform selection

(cli-benchmarks)=
## `benchmarks` - Manage Benchmark Suites

Manage and browse available benchmark suites.

### Subcommands

#### `benchmarks list`

Display all available benchmark suites with descriptions.

```bash
benchbox benchmarks list
```

Shows information about:
- TPC-H, TPC-DS, TPC-DI (official TPC benchmarks)
- ClickBench, H2ODB (industry benchmarks)
- SSB, AMPLab (academic benchmarks)
- ReadPrimitives, WritePrimitives, TPC-Havoc (testing benchmarks)

(cli-validate)=
## `validate` - Validate Configuration

Validate BenchBox configuration files for syntax and completeness.

### Options

- `--config TEXT`: Configuration file path (optional)

### Usage Examples

```bash
# Validate default configuration
benchbox validate

# Validate specific configuration file
benchbox validate --config ./custom-config.yaml
```

(cli-validate-results)=
## Result Integrity Validation

Result integrity validation checks benchmark result JSON files for structural
integrity, completeness, and statistical believability. It runs 20 checks
across three tiers against hardcoded benchmark specifications.

There is no `benchbox` subcommand for it; `benchbox validate` checks
configuration files, not result bundles. With the installed package, use the
`validate_results` tool of the [MCP server](../mcp.md), which accepts one
result file or a directory of result files. Contributors working from a source
checkout can also run the standalone `validate_results.py` script, which wraps
the same validator.

See the [Result Integrity Validation](../../development/result-integrity-validation.md)
developer guide for the full check list.

**Notes:**
- Automatically excludes `.plans.json` and `.tuning.json` companion files
- Specs cover 21 of 22 benchmarks with 8 legacy alias mappings (e.g., `star_schema` → `ssb`); `ai_primitives` is not yet covered

## Related

- [Result Integrity Validation](../../development/result-integrity-validation.md) - Architecture and check details
- [Configuration](configuration.md) - Configuration file format and options
- [Platforms](platforms.md) - Platform management commands
