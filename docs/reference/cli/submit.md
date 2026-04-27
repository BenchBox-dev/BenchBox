(cli-submit)=
# `submit` - Submit Results

```{tags} reference, cli, results
```

Package a benchmark result bundle for contribution to the hosted results platform.
Creates a local output directory containing the canonical bundle, a submission
manifest, and contribution instructions - ready for opening a PR against
`results-data/`.

## Basic Syntax

```bash
benchbox submit [RESULT_FILE] [OPTIONS]
```

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `RESULT_FILE` | path | - | Path to result JSON file (optional) |
| `--last` | flag | - | Use most recent result file |
| `--benchmark TEXT` | str | - | Filter by benchmark name (with `--last`) |
| `--platform TEXT` | str | - | Filter by platform name (with `--last`) |
| `--output DIRECTORY` | path | `./submission` | Output directory for submission package |
| `--dry-run` | flag | - | Preview what would be packaged without writing files |

## What Gets Created

Running `benchbox submit` creates the following layout inside `--output`:

```
submission/
├── bundle/
│   ├── <result>.json           # verbatim copy of the canonical result file
│   ├── <result>.plans.json     # companion file - only if present
│   └── <result>.tuning.json    # companion file - only if present
├── submission-manifest.json    # metadata for the PR reviewer
└── CONTRIBUTING.md             # step-by-step instructions for opening the PR
```

### `submission-manifest.json` fields

| Field | Description |
|-------|-------------|
| `submission_tool_version` | `benchbox/<version>` string |
| `submitted_at` | ISO-8601 UTC timestamp |
| `bundle_file` | Filename of the result JSON |
| `bundle_hash` | SHA-256 hex digest of the result file |
| `benchmark` | Benchmark name (e.g. `tpch`) |
| `platform` | Platform name (e.g. `duckdb`) |
| `scale_factor` | Scale factor used |
| `phase` | Submission phase (`2` = PR-based) |
| `submission_path` | `"PR-based"` |

## Phase 2 vs Phase 3

`benchbox submit` is a **Phase 2** command.

| Phase | Workflow | Auth required |
|-------|----------|---------------|
| 2 (current) | Package locally → open PR manually | No |
| 3 (planned) | `--upload` sends directly to hosted API | Yes (`service.token`) |

The local bundle produced in Phase 2 is designed to be compatible with Phase 3's
upload payload, so the output directory is not throwaway.

## `submit` vs `publish`

These commands serve different purposes:

| | `benchbox publish` | `benchbox submit` |
|-|-------------------|------------------|
| Purpose | Copy artifacts to local dir or cloud storage | Package for community PR contribution |
| Network | Configured destinations (may be remote) | None (Phase 2) |
| Auth | Per-destination | None (Phase 2) |
| Workflow | Internal sharing / archival | Community contribution via PR |

## Examples

```bash
# Package a specific result file
benchbox submit results/tpch_sf1_duckdb.json

# Package the most recent result
benchbox submit --last

# Package the most recent TPC-H result
benchbox submit --last --benchmark tpch

# Preview what would be packaged (no files written)
benchbox submit --last --dry-run

# Use a custom output directory
benchbox submit --last --output ./my-submission
```

## Related

- [results](results.md) - View benchmark result files
- [export](results.md#export) - Export results to CSV, HTML, or JSON formats
- [report](report.md) - Historical analysis and trend detection
