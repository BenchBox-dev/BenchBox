# External Dry-Run Retrospective — 2026-04-28

> Source: agent-proxy run via Claude Cowork (cold sandbox, no repo mounted,
> no GitHub auth, no maintainer tooling). The parent TODO
> `external-contributor-submission-dry-run` requires a *human* contributor
> dry-run; this run is a doc-hardening pre-pass that surfaces friction the
> human shouldn't have to discover. The TODO is **not closed** by this run.

## Timeline

- 13:20:53Z — Cloned `joeharris76/BenchBox` into `/tmp/BenchBox`. (First clone into the Cowork outputs mount failed on a `.git/config.lock` permission error; re-cloned into `/tmp` and proceeded. Sandbox quirk, not a doc issue.)
- 13:21:02Z — Read `docs/contributing-results.md` cold. Spotted broken Prerequisites link (`getting-started.rst`) before doing anything else.
- 13:21:30Z — `pip install benchbox` (sandbox is throwaway, `--break-system-packages`). Installed `benchbox 0.2.1`.
- 13:21:55Z — Ran `benchbox run --platform duckdb --benchmark tpch --scale 0.01` exactly as the doc says. Failed: "Platform 'duckdb' is not available (missing dependencies)". CLI told me to install `benchbox[duckdb]`. The doc did not.
- 13:22:00Z — `pip install "benchbox[duckdb]"`.
- 13:22:05Z — Re-ran benchmark. Passed. Result written to `benchmark_runs/results/tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json` — note the filename shape (extra `_sql_` segment, hash suffix) does not match the doc's example `tpch_sf001_duckdb_20260401_120000.json`.
- 13:22:18Z — `benchbox submit --last --dry-run`. Listed three files. Ran the real package: `benchbox submit --last --output ./submission`. Bundle, manifest, and a `CONTRIBUTING.md` were written.
- 13:22:30Z — Read packaged `submission/CONTRIBUTING.md`. It disagrees with `docs/contributing-results.md` in three places (no inventory regeneration, no `published-results` branch target, no local-validation block).
- 13:23:10Z — Inspected manifest: `submitted_by` is empty; the CLI never asked for a contributor and offers no flag to set one. The doc table promises a "contributor" field.
- 13:23:30Z — Tried `uv run -- python scripts/validate_submission.py …` exactly as the doc says. Timed out at 45s. Switched to plain `python3 scripts/validate_submission.py …`. Passed in <1s.
- 13:23:50Z — Pre-stage inventory check: `python3 scripts/generate_corpus_inventory.py --check` → OK (12 bundles).
- 13:24:00Z — Followed Step 3.2/3.3: copied bundle and `submission-manifest.json` into `results-data/bundles/` (in my throwaway clone — would-have-pushed in user's clone).
- 13:24:10Z — Re-ran `--check`. Failed exactly as the doc warns ("Missing from inventory: ..."). Ran `--write`. Inventory regenerated to 13 bundles, NOT 14 — the manifest file was silently filtered out. Behavior is undocumented.
- 13:24:25Z — `--check` again. OK. Stop point: would-have-pushed and would-have-opened-PR. Logged in Appendix B.
- 13:25:13Z — Compiled artifacts.

## Environment caveats

Cowork sandbox could not test:

- **GitHub auth** of any kind (no `gh`, no token, no SSH agent).
- **`git push`** to a fork or to the user's repo.
- **`gh pr create`** / opening a PR via API.
- **CI run of "Validate Submission"** — that workflow only fires on PR open. I ran the CI's underlying scripts (`validate_submission.py`, `generate_corpus_inventory.py`) directly, but the workflow file itself, the PR-comment posting path, and any GitHub-context glue went untested.
- **Maintainer review / merge / docs CI rebuild** of `results-explorer` (Step 5).
- **`pre-commit install`** — would write hooks into a clone that's about to be discarded.
- **Trust-label assignment** in the explorer ("Community Submission") — that's a downstream rendering step.
- **`uv run`** in this sandbox stalls past 45s on the validation script. May be sandbox CPU/network constraint, not a real-world contributor problem — flagging because the doc relies entirely on `uv run` for the local-validation block.

## Friction items

- **Step: Prerequisites #1 — broken relative link.** Expected: link to a Getting Started guide. Actual: `[Getting Started](getting-started.rst)` resolves to `docs/getting-started.rst`, which does not exist. There's `docs/usage/getting-started.md` and `docs/development/getting-started.rst`. Resolved by skipping (I already had pip available). Classification: **doc-fix**. *(Patched in the same PR as this retrospective.)*

- **Step: Step 1 — `benchbox run --platform duckdb …`.** Expected: works after `pip install benchbox`. Actual: errors with "Platform 'duckdb' is not available (missing dependencies). Run uv pip install \"benchbox[duckdb]\" to install dependencies." The CLI message is good; the doc is silent on extras. Resolved by following the CLI hint. Classification: **doc-fix**. *(Patched in the same PR as this retrospective.)*

- **Step: Step 1 — example filename in §1.** Expected: real result filenames look like `tpch_sf001_duckdb_20260401_120000.json` (the doc's example for the explicit `benchbox submit <path>` form). Actual: `tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json`. The `_sql_` mode suffix and the hash tail are not in the doc's example, so a contributor copy-pasting the second `benchbox submit` form has to translate. Resolved by using `--last`. Classification: **doc-fix**.

- **Step: Step 2 — bundle table.** Expected: per the table, my bundle directory should contain `<result>.json`, `<result>.plans.json`, `<result>.tuning.json`, plus the manifest and the README. Actual: only `<result>.json`. The doc footnotes "(if captured)" / "(if used)" but never explains how a contributor would *opt in* to capture plans or apply tuning before running. The "if" rules out of nowhere. Resolved by ignoring. Classification: **doc-fix**.

- **Step: Step 2 — packaged `CONTRIBUTING.md` disagrees with `docs/contributing-results.md`.** The file `benchbox submit` writes into the bundle is a 16-line stub. It does not mention: (a) regenerating `corpus-inventory.json` before commit, (b) targeting the `published-results` branch (it just says "open a pull request"), (c) the local validation block. A contributor who reads only the in-bundle file — which is what `submit` directs them to ("See CONTRIBUTING.md in the output directory for instructions") — will open a PR against `main` with a stale inventory. CI on the user side will then catch it; that's wasted round-trips. Classification: **tool-fix** (regenerate the in-bundle file from the canonical doc, or have `submit` print the canonical instructions).

- **Step: Step 2 — manifest filename collision.** Doc instruction 3.3: "Copy `submission/submission-manifest.json` alongside the bundle files." The filename is generic. `results-data/bundles/` currently contains zero manifests. Two community PRs landing in the same window would write to the same filename. The doc never names the convention. Classification: **process-gap** (also a tool-fix candidate — emit `<result>.manifest.json` instead).

- **Step: Step 2 — `submitted_by` is empty.** The doc table promises the manifest contains "contributor". My manifest's `submitted_by` field is an empty string. *Maintainer correction during review: the CLI does fall back to `git config user.name` via `_get_git_username()` at `submit.py:49-60`. The Cowork sandbox simply had no `user.name` set, so the fallback returned `""` silently with no warning.* Real failure mode: silent empty when the fallback misses, plus no override flag. Classification: **tool-fix** (warn loudly when the fallback returns empty, add `--submitted-by` override).

- **Step: Step 3.5 — branch target ambiguity.** Doc says PR against `published-results` branch, but the in-bundle CONTRIBUTING.md does not, and `git remote show origin` shows `main` as HEAD. A contributor following GitHub defaults will target `main`. Doc could call out the branch more loudly (bold + first time it's mentioned); CLI could open the PR URL with the base preselected. Classification: **doc-fix** + **tool-fix**.

- **Step: Step 4 — schema version key naming.** The doc calls bundles "schema-v2 result bundle". The JSON has no `schema_version` key. The actual key is `version: "2.1"`. The "Quality Expectations" section says "Schema v2 format - only the current schema version is accepted" without naming the key. Anyone trying to grep their JSON for compliance will look in the wrong place. Classification: **doc-fix**.

- **Step: "Running Validation Locally" — `uv run` stall.** Expected: `uv run -- python scripts/validate_submission.py …` returns in seconds. Actual: timed out at the sandbox's 45s ceiling. Plain `python3 scripts/validate_submission.py …` returned in ~1s and passed. May be a Cowork-specific environment problem (uv warming a venv), but the doc gives no fallback. Classification: **cowork-can't-test** primarily, with a **doc-fix** suggestion (offer the `python` invocation as an alt for environments without uv).

- **Step: Step 3.4 — manifest filtered silently from inventory.** After copying the bundle plus the manifest into `results-data/bundles/`, the inventory regenerator counted 13 (= 12 + 1), not 14. It silently dropped `submission-manifest.json`. That's probably the right behavior, but it's undocumented — a contributor seeing the count not match their file count will worry. Classification: **doc-fix**.

## What worked / what didn't / what I'd change

**What worked.** The CLI itself was the most polished surface. `benchbox run`'s missing-dependency error was clear and actionable. `benchbox submit --dry-run` showed exactly what would land. `validate_submission.py` and `generate_corpus_inventory.py --check`/`--write` did what the doc said they would. The benchmark itself ran clean on the smallest scale and produced a usable bundle.

**What didn't.** The doc is the weak surface. Three independent friction points are caused by the doc lagging the CLI: the missing extras, the broken Prerequisites link, and the bundle-table claim about plans/tuning files that are gated on flags the doc never names. The packaged `CONTRIBUTING.md` is the worst single artifact — it's authoritative-looking and the CLI points the contributor at it, but it omits two of the four steps the canonical doc requires for the PR to merge cleanly.

**What I'd change.** Make `benchbox submit` either (a) embed the canonical contributing-results.md verbatim into the bundle, or (b) print a one-screen checklist that includes `published-results` branch + inventory regeneration. Add a `--submitted-by` flag (default to `git config user.name`, warn on empty). Drop the "if captured / if used" rows from the bundle-table or move them to a footnote with a how-to. Fix the broken link.

## Agent-vs-human caveat

A human cold-running this would probably hit the missing-`[duckdb]`-extras error, give up for ten minutes assuming the install was broken, then either follow the CLI hint or post in Discussions. I pattern-matched on "missing dependencies" + the literal `uv pip install …` suggestion in the error and fixed it in seconds — agents are cheap on these. Conversely, a human reading the broken Prerequisites link would notice immediately ("404 — clearly a doc bug, file an issue, move on"); I almost ignored it because I had `pip` already and didn't *need* the page. Humans will also more readily read the in-bundle `CONTRIBUTING.md` and trust it as the latest source of truth, which is the worst place to put stale instructions. And a human is more likely to ask a maintainer "do I really PR against `published-results`? — that's unusual" before pushing, whereas an agent will just do whatever the doc says. Net: the friction items are real for both, but humans are more likely to file an issue and stop, agents more likely to grind through and never report.

## Follow-ups filed

Six follow-up TODOs landed alongside this retrospective in
`_project/TODO/main/planning/`:

- `dry-run-followup-package-canonical-contributing.yaml` (High)
- `dry-run-followup-submitted-by-flag.yaml` (Medium)
- `dry-run-followup-manifest-filename-convention.yaml` (Medium)
- `dry-run-followup-bundle-table-conditionals.yaml` (Low)
- `dry-run-followup-broken-getting-started-link.yaml` (Low — already
  patched in this PR; YAML kept as the tracked record)
- `dry-run-followup-uv-fallback-and-schema-key.yaml` (Low)

The parent TODO `external-contributor-submission-dry-run` is **not
closed**: the human contributor dry-run (w1–w5) is still required
because Cowork structurally cannot exercise auth, push, PR open, CI
validate, maintainer review, trust-label apply, or explorer redeploy.
This run is a doc-hardening pre-pass that reduces friction for the
human run.

---

## Appendix A — Bundle structural report

Directory tree of `submission/`:

```
submission/
├── CONTRIBUTING.md
├── bundle
│   └── tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json
└── submission-manifest.json
```

`submission-manifest.json` contents:

```json
{
  "submission_tool_version": "benchbox/0.2.1",
  "submitted_at": "2026-04-28T13:22:25.715970+00:00",
  "bundle_file": "tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json",
  "bundle_hash": "927236b656b60931c69f23fa2e4888bd98e47e080bee6ae8092efc0f042d02e8",
  "benchmark": "TPC-H",
  "platform": "DuckDB",
  "scale_factor": 0.01,
  "phase": 2,
  "submission_path": "PR-based",
  "submitted_by": ""
}
```

Bundle JSON top-level shape (`bundle/tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json`, 17,111 bytes):

- Top-level keys: `version`, `run`, `benchmark`, `platform`, `config`, `summary`, `phases`, `queries`, `tables`, `cost`, `execution`, `environment`, `export`
- `version: "2.1"` (note: not `schema_version`)
- `run.id`: `a0be0851` (matches the filename suffix; this is a separate
  run ID, not the manifest's `bundle_hash`)
- `benchmark`: `{id: tpch, name: TPC-H, scale_factor: 0.01, test_type: power}`
- `platform`: `{name: DuckDB, version: 1.5.2, …}`
- `summary.queries`: `{total: 66, passed: 66, failed: 0}` — that's 22 queries × 3 measurement runs.
- `summary.timing`: `{total_ms: 221, avg_ms: 3.3, min_ms: 1, max_ms: 5, p99_ms: 5}`
- `queries` array length: 88 records (22 × (1 warm-up + 3 measurement)).
- 22 distinct query IDs 1..22.

`validate_submission.py` ran against this bundle and reported 0 error(s),
0 warning(s). The doc never instructs contributors to record any hashes
or row counts by hand; everything is auto-populated by `benchbox submit`.

## Appendix B — "Would-have" command log

Every command stopped at because of the auth/file-write boundary:

```
# Step 3.1 — Fork the BenchBox repo
would have run: <browser action> open https://github.com/joeharris76/BenchBox → click Fork
expected: a fork at <my-username>/BenchBox

# Step 3.2 — Clone the fork and switch to a feature branch
would have run: git clone git@github.com:<my-username>/BenchBox.git && cd BenchBox && git checkout -b results/tpch-duckdb-sf001-20260428
expected: working tree on a new branch ready for the bundle copy

# Step 3.2 — Copy bundle into results-data/bundles/
would have run: cp /path/to/submission/bundle/tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json results-data/bundles/
expected: one new file under results-data/bundles/

# Step 3.3 — Copy submission-manifest.json
would have run: cp /path/to/submission/submission-manifest.json results-data/bundles/
expected: manifest sits next to the bundle file  [filename collision risk, see follow-up TODO]

# Step 3.4 — Regenerate inventory
would have run: uv run -- python scripts/generate_corpus_inventory.py --write
expected: results-data/corpus-inventory.json bumped from 12 to 13 bundles  [verified via python3 invocation in /tmp clone — succeeded]

# Step 3.5 — Commit
would have run: git add results-data/bundles/tpch_sf001_duckdb_sql_20260428_132205_a0be0851.json results-data/bundles/submission-manifest.json results-data/corpus-inventory.json && git commit -m "results: tpch DuckDB sf0.01"
expected: one commit with bundle + manifest + inventory delta

# Step 3.5 — Push
would have run: git push -u origin results/tpch-duckdb-sf001-20260428
expected: branch published on the fork

# Step 3.5 — Open PR
would have run: gh pr create --repo joeharris76/BenchBox --base published-results --head <my-username>:results/tpch-duckdb-sf001-20260428 --title "results: tpch DuckDB sf0.01" --body "<auto>"
expected: PR opened against the published-results branch (NOT main — see friction item)

# Step 4 — CI Validate Submission
would have run: <GitHub Actions> .github/workflows/validate-submission.yml triggered by PR open
expected: schema-valid bundle, hash matches manifest, inventory in sync, summary comment posted on PR

# Step 5 — Maintainer review and merge
would have run: <maintainer action> review + Squash and merge
expected: PR merged into published-results

# Step 5 — Post-merge docs CI
would have run: <GitHub Actions> docs CI rebuilds results-explorer with the new bundle
expected: bundle visible in the explorer with "Community Submission" trust label

# Optional — pre-commit hooks
would have run: pre-commit install
expected: future commits in this clone auto-check inventory drift  [skipped because the clone is throwaway; would run in user's clone]
```
