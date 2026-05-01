(cli-submit)=
# `submit` - Submit Results

```{tags} reference, cli, results
```

Package or upload a benchmark result bundle for the BenchBox results platform.

`benchbox submit` has two destinations:

- `--output` packages a local PR-ready bundle for the `published-results`
  contribution flow. This mode does not use the network or credentials.
- `--service` uploads the same canonical bundle to a hosted ingest API. This
  mode requires `benchbox auth login` or `BENCHBOX_SUBMIT_TOKEN`.

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
| `--service [URL]` | str | - | Upload to hosted ingest API; without a URL uses `https://api.benchbox.dev/v1` |
| `--visibility public\|unlisted\|private` | choice | `public` | Hosted submission visibility |
| `--idempotency-key TEXT` | str | auto | Hosted retry/resubmit key |
| `--wait / --no-wait` | flag | `--wait` | Poll for hosted publication before returning |
| `--dry-run` | flag | - | Preview packaging or upload without writing files or sending bytes |
| `--submitted-by TEXT` | str | git user | Override local PR manifest submitter name |

## What Gets Created

Running `benchbox submit --output ./submission` creates this layout:

```
submission/
├── bundle/
│   ├── <result>.json           # verbatim copy of the canonical result file
│   ├── <result>.plans.json     # companion file - only if present
│   └── <result>.tuning.json    # companion file - only if present
├── <result>.manifest.json      # metadata and hashes for validation
└── CONTRIBUTING.md             # step-by-step instructions for opening the PR
```

### `<result>.manifest.json` fields

| Field | Description |
|-------|-------------|
| `submission_tool_version` | `benchbox/<version>` string |
| `submitted_at` | ISO-8601 UTC timestamp |
| `bundle_file` | Filename of the result JSON |
| `bundle_hash` | SHA-256 hex digest of the result file |
| `companion_hashes` | Per-file SHA-256 hashes for `.plans.json` and `.tuning.json` companions |
| `benchmark` | Benchmark name (e.g. `tpch`) |
| `platform` | Platform name (e.g. `duckdb`) |
| `scale_factor` | Scale factor used |
| `phase` | Submission phase (`2` = PR-based) |
| `submission_path` | `"PR-based"` or `"hosted-service"` |
| `submitted_by` | Explicit flag, `git config user.name`, or empty with warning |

## Phase 2 vs Phase 3

`benchbox submit --output` is the Phase 2 community PR path.
`benchbox submit --service` is the Phase 3 hosted API path.

| Phase | Workflow | Auth required |
|-------|----------|---------------|
| 2 (current) | Package locally → open PR manually | No |
| 3 (hosted) | `--service` uploads to the hosted API | Yes (`benchbox auth login` or env token) |

Both modes use the same canonical schema-v2 result JSON and companion files.
There is no second hosted-only wire format.

## Hosted API Mode

Authenticate once:

```bash
benchbox auth login
```

Then submit a result:

```bash
benchbox submit --last --service
```

Hosted mode sends a multipart request containing:

- `bundle`: the primary result JSON bytes
- `manifest`: the submission manifest JSON bytes
- `companions[]`: `.plans.json` and `.tuning.json` files when present
- `visibility`: `public`, `unlisted`, or `private`

BenchBox sends a stable idempotency key derived from the service URL and bundle
hash unless you pass `--idempotency-key`. Retrying the same bundle against the
same service reuses that key.

When `--wait` is enabled, BenchBox polls hosted status until the result is
published or rejected. When `--no-wait` is used, BenchBox records the
submission id locally and exits after the service accepts the upload.

Hosted submissions are tracked with sidecar files next to the source result:

```
benchmark_runs/results/<result>.<idempotency-key>.submission.json
```

List them with:

```bash
benchbox results --submitted
```

## `submit` vs `publish`

These commands serve different purposes:

| | `benchbox publish` | `benchbox submit` |
|-|-------------------|------------------|
| Purpose | Copy artifacts to local dir or cloud storage | Share results with BenchBox results platform |
| Network | Configured destinations (may be remote) | None in `--output`; hosted API in `--service` |
| Auth | Per-destination | Hosted token only for `--service` |
| Workflow | Internal sharing / archival | Community contribution via PR or hosted API |

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

# Log in for hosted submission
benchbox auth login

# Upload to hosted API and wait for publication
benchbox submit --last --service

# Upload to staging without waiting for publication
benchbox submit --last --service https://staging.benchbox.dev/v1 --no-wait

# Show hosted submission history
benchbox results --submitted
```

## Related

- [auth](auth.md) - Manage hosted submission credentials
- [results](results.md) - View benchmark result files
- [export](results.md#export) - Export results to CSV, HTML, or JSON formats
- [report](report.md) - Historical analysis and trend detection
