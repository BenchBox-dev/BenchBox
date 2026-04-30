# Dev-loop path filter smoke test - 2026-04-30

## Scope

This record validates the Step 3a path classifier, local content guard, hosted
workflow PR, and post-merge ruleset update.

`act` was not available in this worktree (`command -v act` returned no path), and
the new `.github/workflows/pr.yml` workflow cannot produce GitHub workflow run
URLs until it exists on the PR branch. The PR run from this branch is therefore
the first GitHub-hosted workflow run URL; the initial section captures the local
smoke evidence used before opening that PR.

## Results

| Case | Simulated changed path | Decision | Guard | Timing |
| --- | --- | --- | --- | --- |
| TODO-only | `_project/TODO/main/active/dev-loop-step-3a-path-based-ci-skip.yaml` | `safe_content_only=true`, `needs_code_ci=false` | content guard ran YAML and TODO graph checks | 2 seconds, under 60 seconds |
| docs/ | `docs/development/run-lifecycle-map.md` | `safe_content_only=true`, `needs_code_ci=false` | content guard ran markdown and docs validation | under 1 second, under 60 seconds |
| code | `benchbox/cli/execution.py` | `safe_content_only=false`, `needs_code_ci=true` | full PR tier selected through `code-lint` and `code-test` gates | under 1 second |
| unknown full | `quality/example.txt` | `safe_content_only=false`, `needs_code_ci=true`, `unknown_paths=["quality/example.txt"]` | full PR tier selected through `code-lint` and `code-test` gates | under 1 second |
| gitignore | `.gitignore` | `safe_content_only=false`, `needs_code_ci=true` | full PR tier selected through `code-lint` and `code-test` gates | under 1 second |

## Commands

Classifier and guard smoke source:

```bash
uv run -- python scripts/path_filter_decision.py --changed-file <paths> --json-out <json> --lists-dir <lists>
make -s pr-content-guard PATH_LISTS=<lists>
```

The smoke run wrote per-case JSON and guard logs under `/tmp/step3a-smoke`.

## GitHub workflow evidence

Workflow PR: <https://github.com/joeharris76/BenchBox/pull/79>

Hosted workflow run:
<https://github.com/joeharris76/BenchBox/actions/runs/25187343062>

PR #79 merged to `develop` at `2026-04-30T20:29:55Z` as squash commit
`9c82b61f5be83cf018af216a7cf99866b7a4da04`.

The hosted run showed:

- `ci-paths` passed in 11 seconds.
- `content-guard` passed in 1 minute 5 seconds.
- `lint` passed in 3 minutes 14 seconds.
- `test (ubuntu-latest, 3.12)` passed in 8 minutes 59 seconds.
- `ci-required-result` passed in 2 seconds after aggregating the selected jobs.

## Branch Ruleset Update

Ruleset: `develop-squash-only` (`15611785`), targeting `refs/heads/develop`.

Before W7:

```json
{
  "strict_required_status_checks_policy": false,
  "do_not_enforce_on_create": false,
  "required_status_checks": [
    {
      "context": "lint"
    },
    {
      "context": "test (ubuntu-latest, 3.12)"
    }
  ]
}
```

After W7:

```json
{
  "strict_required_status_checks_policy": false,
  "do_not_enforce_on_create": false,
  "required_status_checks": [
    {
      "context": "ci-required-result"
    }
  ]
}
```

Only the required status check contexts changed. The ruleset kept
`strict_required_status_checks_policy=false`, no bypass actors, the existing
squash-only pull-request rule, required linear history, non-fast-forward
protection, and deletion protection.
