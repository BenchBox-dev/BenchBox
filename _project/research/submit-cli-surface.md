# `benchbox submit` Phase 3 CLI Surface Design

This is the design sketch for extending `benchbox submit` from its
current Phase 2 PR-packaging behavior to a Phase 3 hosted-API backend.

**The current Phase 2 command stays.** This design adds the `--service`
flag (and supporting infrastructure) without breaking the existing
`benchbox submit --output PATH` workflow that ships in v0.2.x.

Output of [Phase 3 design TODO][design] w1 +
[CLI integration TODO][cli] w1.

[design]: ./../analysis/ingest-architecture-design.md
[cli]: ./../DONE/main/planning/integrate-benchbox-cli-submit-and-service-auth.yaml

## Distinction from `benchbox publish`

`benchbox publish` and `benchbox submit` look superficially similar
("send a result somewhere"); they are not interchangeable. Surface
this in `--help` and the docs so users always know which one they
mean.

| Question                            | `benchbox publish`                        | `benchbox submit`                          |
|-------------------------------------|-------------------------------------------|--------------------------------------------|
| Who is the audience?                | The submitter, optionally a private team  | The public BenchBox results platform       |
| Where do bytes land?                | A storage destination *the submitter owns* (local path, S3 bucket, GCS bucket, etc.) | The BenchBox hosted ingest service or a maintainer-curated PR |
| Is the result browsable on benchbox.dev? | No                                   | Yes (after acceptance)                     |
| Is auth required?                   | Only the destination's auth (e.g., AWS creds) | A BenchBox token tied to your account     |
| Phase                               | Independent of Phase 1/2/3                | Phase 2 (PR mode) and Phase 3 (API mode)   |

The mental model: `publish` is "save this somewhere I control";
`submit` is "share this with the world."

## CLI surface — full `--help` text after Phase 3 extension

```
Usage: benchbox submit [OPTIONS] [RESULT_FILE]

  Submit a benchmark result bundle to the BenchBox results platform.

  Two modes, selected automatically by --output / --service:

    --output PATH (Phase 2, default)
      Package the canonical bundle + submission manifest into PATH ready
      for opening a PR against the BenchBox repository's results-data/
      directory. No network. No credentials. Existing v0.2.x behavior.

    --service [URL] (Phase 3)
      Upload the canonical bundle to a hosted ingest API. Polls for
      acceptance status, prints the public permalink on success, and
      records the submission in benchbox results --submitted history.
      Requires authentication via 'benchbox auth login'.

  RESULT_FILE: Path to result JSON file (optional; with --last, picked
  from history).

  Examples:
    # Package most recent result for PR contribution (Phase 2; default)
    benchbox submit --last

    # Submit most recent result to the hosted platform (Phase 3)
    benchbox submit --last --service

    # Submit a specific bundle to a non-default service URL (e.g., staging)
    benchbox submit results/tpch_sf01_duckdb.json --service https://staging.benchbox.dev/v1

    # Preview what would be uploaded without sending bytes
    benchbox submit --last --service --dry-run

  Note: benchbox submit shares results publicly. To copy a result to
  storage you control (local path, S3, etc.), use 'benchbox publish'.

Options:
  --last                   Use most recent result file
  --benchmark TEXT         Filter by benchmark name (with --last)
  --platform TEXT          Filter by platform name (with --last)
  --output PATH            Phase 2 mode: write submission package to PATH
                           [default: submission]
  --service [URL]          Phase 3 mode: submit to the hosted ingest API.
                           Without a URL, uses config 'service.url'
                           (default: https://api.benchbox.dev/v1).
  --visibility CHOICE      Phase 3 only. One of: public, unlisted, private.
                           [default: public]
  --idempotency-key UUID   Phase 3 only. Override the auto-generated key.
                           Useful for resumable retries.
  --wait / --no-wait       Phase 3 only. Wait for the service to finish
                           validation and print the public URL. [default: wait]
  --dry-run                Preview what would be packaged or uploaded
                           without writing files / sending bytes.
  --help                   Show this message and exit.
```

## Config keys

Two new config sections under `~/.benchbox/config.yaml`. Both are
optional; defaults reflect the public hosted service.

```yaml
service:
  # Phase 3 hosted ingest API. The CLI reads this when --service is
  # passed without an explicit URL.
  url: https://api.benchbox.dev/v1

  # If true, every benchbox submit defaults to --service mode. Off by
  # default so the v0.2.x experience is unchanged for anyone who didn't
  # ask to opt in.
  default_mode: pr  # one of: pr | service

submission:
  # Default visibility for hosted submissions. Reads only by the
  # service-mode path. Never affects PR-mode packaging.
  default_visibility: public

  # Default true — wait for ingest to finish before returning.
  wait_for_completion: true
```

**Existing placeholder reconciliation:**

`benchbox/cli/config.py` currently has:

```yaml
submit_to_service: false
service_url: "https://api.benchbox.dev/v1"
```

These are kept for compatibility but become **deprecated aliases**:

- `submit_to_service` → `service.default_mode` ('service' if true, else 'pr')
- `service_url` → `service.url`

The CLI prints a one-time deprecation note on first read of an old key
and migrates the file in place on next save. Removed in 0.4.

## Authentication surface

A separate command tree, `benchbox auth`, manages tokens. This keeps
the auth flow out of the submit command's hot path and avoids
overloading `submit` with every credential operation.

```
Usage: benchbox auth COMMAND [ARGS]...

Commands:
  login    Authenticate with the BenchBox results platform.
  logout   Remove the locally-stored token.
  status   Show the current token status (account, expiry).
  whoami   Print the actor identity bound to the current token.
```

Token storage:

- macOS: Keychain via `keyring` Python package
- Linux: Secret Service (gnome-keyring, KWallet) via `keyring`; falls
  back to encrypted `~/.benchbox/credentials.yaml` (encrypted with a
  user-provided passphrase) when no service is available
- Windows: Credential Manager via `keyring`

Tokens are never written to plaintext config. `service.url` is the
only network-related plaintext config key.

## Status reporting

When `--service --wait` is in effect, the CLI prints status updates
as the submission moves through its lifecycle:

```
$ benchbox submit --last --service
Uploading bundle (4.2 MB) to https://api.benchbox.dev/v1 ...
  ✓ Received       (submission_id: 7a2b8c3d-...)
  ✓ Validating
  ✓ Accepted       (result_id: tpch-duckdb-sf001-2026q2-7a2b)
Public URL: https://benchbox.dev/results/r/tpch-duckdb-sf001-2026q2-7a2b
Saved to submission history.
```

On `--no-wait` the CLI prints `submission_id` and exits. Future
status checks via `benchbox auth status` and `benchbox results
--submitted` (existing surface; gains a "hosted URL" column).

## Local validation in `--dry-run`

`--dry-run` works with or without `--service`:

| Mode                | What `--dry-run` does                                         |
|---------------------|---------------------------------------------------------------|
| `--output --dry-run` | Computes the bundle hash and prints the file list that would be packaged. Existing v0.2.x behavior. |
| `--service --dry-run` | Validates the bundle against the schema-v2 spec, prints what would be uploaded (size, hash, manifest envelope), and verifies token presence. **Does not** send any bytes to the service. |

This is the entry point for "is my submission valid?" before paying
the network round-trip.

## What this design explicitly does NOT include

- **`benchbox submit --watch`** for continuous re-uploads on file
  change. Out of scope for Phase 3 launch.
- **A `submit` web UI**. The hosted explorer reads results; it does
  not accept uploads. All writes go through the CLI.
- **OAuth flow with browser redirect**. Personal API keys are sufficient
  for launch. OAuth is a follow-up if org-space demand crosses Phase 3
  promotion metric M6.

## Implementation order (when Phase 3 is greenlit)

The work units of [`integrate-benchbox-cli-submit-and-service-auth`][cli]
remain pending. Implementation order is fixed by their existing
`needs:` edges (w1→w2→w3→{w4→w5→w6→w7}→w8). w1 is this document; w2
is the reuse map at [`./submit-reuse-points.md`](./submit-reuse-points.md).
w3-w8 require the hosted ingest API to exist before they can be
written or tested.
