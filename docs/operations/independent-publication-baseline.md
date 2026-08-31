# Independent publication baseline operations

The A0 snapshot is `publication-baseline-2026-08-31.json`. It records separate
repository, build, deployment, and live-observation evidence before publication
control changes.

## Capture

Prerequisites are authenticated read access through `gh`, fetched
`origin/develop`, `origin/release`, and `origin/published-results` refs, and HTTPS
access to `benchbox.dev`.

```bash
uv run python scripts/publication/capture_baseline.py
uv run python scripts/publication/capture_baseline.py --check
```

Capture reads only Git, GitHub APIs, and the live public database. It does not
modify either corpus tree or the deployment workflow. `--check` validates the
committed snapshot without refreshing it.

## Interpretation

- `accepted_path_union` is the preservation contract. Counts and bytes are
  diagnostics only.
- `published_only_paths` are expected accepted archive history and must not be
  discarded because they are absent from `develop`.
- Artifact `size_in_bytes` is stored compressed artifact size. It is not Pages
  bandwidth or the uncompressed site size.
- Pages bandwidth is marked unavailable because the GitHub APIs expose no
  transfer-total metric. Do not invent a transfer estimate.
- The live database SHA-256 and HTTP metadata prove what was observed at capture
  time. They are not a substitute for a route-complete dual-publication probe.

## Freeze and incident response

The controlling decision is
`_project/decisions/independent-publication-a0-freeze-2026-08-31.md`. While the
freeze is active, preserve the current release deploy and mirror path. If the
site regresses, re-run Documentation for the recorded release SHA or revert the
release branch through its protected PR flow, then verify `/`, `/results/`, and
`/results/data/results.duckdb`.

Do not release a freeze surface until its named decision gate has fresh evidence.
BenchBox maintainers own incident response until a later gate names and tests a
replacement operator.
