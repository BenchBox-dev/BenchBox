# Dev-loop path filter smoke test - 2026-04-30

## Scope

This record validates the Step 3a path classifier and local content guard before
the workflow PR lands on `develop`.

`act` was not available in this worktree (`command -v act` returned no path), and
the new `.github/workflows/pr.yml` workflow cannot produce GitHub workflow run
URLs until it exists on the PR branch. The PR run from this branch is therefore
the first GitHub-hosted workflow run URL; this record captures the local smoke
evidence used before opening that PR.

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

Workflow run URL: not available before the workflow PR is opened. The branch PR
must show:

- TODO-only and docs/ style changes report `ci-required-result` green after the
  content guard without running Python fast tests.
- Code, unknown full, and gitignore changes select the full PR tier by running
  `code-lint` and `code-test`.
- The required result check aggregates the selected jobs and fails closed.
