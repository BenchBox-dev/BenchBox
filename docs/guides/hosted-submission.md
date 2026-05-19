# Hosted Result Submission

```{tags} guide, results
```

Use this flow when you want a local BenchBox run to appear on the hosted
BenchBox results platform.

## 1. Run A Benchmark

```bash
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01 --non-interactive
```

BenchBox writes the result JSON under `benchmark_runs/results/`. If query plans
or tuning were captured, companion files sit beside the primary result.

## 2. Check The Result

```bash
uv run -- benchbox results
uv run -- benchbox submit --last --service --dry-run
```

The dry run validates the local bundle, computes the hash, lists companion
files, and prints the hosted upload target. It does not read credentials and
does not contact the service.

## 3. Authenticate

```bash
uv run -- benchbox auth login
uv run -- benchbox auth status
```

`benchbox auth login` stores the hosted token in the operating system keyring.
For CI, set `BENCHBOX_SUBMIT_TOKEN` instead. `BENCHBOX_SERVICE_TOKEN` is still
accepted as a lower-precedence fallback for older automation.

## 4. Submit

```bash
uv run -- benchbox submit --last --service
```

BenchBox uploads the canonical result JSON, the generated manifest, and any
companion files. With the default `--wait`, it polls until the service publishes
or rejects the submission.

Use `--no-wait` when you only need the submission id:

```bash
uv run -- benchbox submit --last --service --no-wait
```

## 5. Track The Hosted URL

```bash
uv run -- benchbox results --submitted
```

Successful hosted submissions create local sidecars next to the source result:

```text
benchmark_runs/results/<result>.<idempotency-key>.submission.json
```

The sidecar stores status, submission id, public result id, public URL,
service URL, and idempotency key. It never stores the auth token.

## PR-Based Alternative

Hosted upload is not required for community contribution. To create a local
package for a pull request:

```bash
uv run -- benchbox submit --last --output ./submission
```

Follow the generated `CONTRIBUTING.md` and open the PR against the
`published-results` branch.
