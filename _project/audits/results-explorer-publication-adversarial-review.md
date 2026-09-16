---
develop_sha: fddedf261b2446d62d6c51114c8b31c059c5a420
---

<!--
Base branch: this repo has both `main` and `develop`. `develop` (tip
fddedf261b2446d62d6c51114c8b31c059c5a420) is the live development branch and
the subject of this review; `main` (2d3295c7) is the release-only branch, 2419
commits behind develop. All "reality" claims below were re-derived against a
read-only worktree of origin/develop unless a finding explicitly names main or
the published-results branch. Review conducted per docs/development/review-protocol.md
(read-only + local capture; no commit/push/PR).
-->

# Results Explorer & Publication — Adversarial Review

## 1. Executive summary

I reviewed the two "publish"-shaped subsystems and every doc/ADR/workflow/test
that asserts something about them: (a) the **Results Publication** path
(`benchbox publish` → `benchbox/core/publishing/`, `benchbox submit`, the
`published-results` corpus branch and its `sync`/`validate-submission`
workflows), and (b) the **Results Explorer** (the Vite/Preact + DuckDB-WASM app
under `results-explorer/` and the static-snapshot pipeline under
`_project/scripts/explorer_pipeline/` + `explorer_publish.py`). Contrary to two
of the seeded leads, `results-explorer/` **does** exist (on `develop`, not
`main`), the `adr-explorer-cli-surface.md` migration **did** fully land, the
`explorer_pipeline` tests are **not** orphaned (260 collect and pass against the
migrated `_project` location), and the audit-SHA governance contract **is**
wired into `pr.yml`. What I could not verify from this checkout: live runtime
behavior of the deployed explorer and the live state of `benchbox.dev/results/`
(outbound HTTPS to that host is proxy-blocked). The headline risks are three:
(1) a **Critical** CI hole where `package-smoke`, `dependency-audit`, and
`parity-check` are permanently skipped yet counted as passing; (2) a
**Critical** published future-state doc that instructs maintainers to delete the
live `benchbox publish` subsystem as "dead code"; and (3) a **Required** trust
provenance gap where a community result missing its manifest sidecar is silently
badged `maintainer-run` and promoted into official rankings. A recurring theme
across the corpus is that the prose (ADRs, runbooks, QA plans, future-state
docs) is voluminous and has drifted from the code faster than it has been
maintained — several "Accepted"/"maintained" documents describe a prior world.

Findings by severity: **2 Critical, 11 Required, 11 Advisory.**

---

## 2. Findings

### Publication Path — Correctness & Security

#### 2.1 Community results without a manifest sidecar are silently promoted to `maintainer-run` and made ranking-eligible

- Evidence: The community-vs-maintainer trust label is derived **solely** from
  the presence of a `.manifest.json` sidecar, defaulting to the most-trusted
  tier when absent:
  - `_project/scripts/explorer_pipeline/pipeline.py:458-460` — `effective_trust = trust_label` (the build default) and only becomes `COMMUNITY_TRUST_LABEL` "if `_find_submission_manifest(bundle_path) is not None`".
  - `_project/scripts/explorer_publish.py:45-46` — `--trust-label` defaults to `"maintainer-run"`, and `.github/workflows/docs.yml:112` invokes the build with **no** `--trust-label`, so every unmanifested bundle inherits `maintainer-run`.
  - `scripts/generate_corpus_inventory.py:41-52` — the same "sidecar present → community, else `DEFAULT_TRUST_LABEL`" rule.
  - The gate is never enforced: `benchbox/validation/bundle.py:718-726` validates the manifest hash only `if manifest_path is not None`; a bundle with no sidecar produces no error and no warning. `validate-submission.yml` runs only `validate_submission.py` + `generate_corpus_inventory.py --check`, neither of which requires a sidecar.
  - Consequence for ranking: `_project/scripts/explorer_pipeline/models.py:82-89` — `RANKING_ELIGIBLE_TRUST_LABELS = {"maintainer-run", "ci-verified"}`; `is_ranking_eligible` (`models.py:343-349`) admits `maintainer-run`. `community-submission` is intentionally excluded — so mislabeling flips a result from "displayed, not ranked" to "officially ranked."
- Impact: A contributor who omits (or deliberately withholds) the sidecar has
  their result badged as maintainer-verified and placed in the official
  leaderboard. This defeats the provenance model the trust labels exist to
  enforce. The only backstop is human review, and the maintainer review
  checklist (`results-phase-2-runbook.md:49-55`) never tells the reviewer to
  confirm sidecar presence.
- Severity: Required (provenance integrity / maintainer trust; the escalation
  criteria in `results-phase-2-runbook.md:166` — "a trust-label or visibility
  bug would publish misleading provenance" — describe exactly this).
- Remediation: Make the sidecar mandatory for any bundle under
  `results-data/bundles/` in `validate_submission.py`/`validate-submission.yml`
  (hard error when a primary bundle has no paired `.manifest.json`), OR have the
  explorer/inventory trust derivation treat a missing sidecar on the
  community-submission path as `community-submission` (fail-closed) rather than
  inheriting the build default. Add the sidecar check to the runbook review
  checklist.

#### 2.2 The explorer build discards the publisher's trust label entirely, including the `unofficial-research` compliance guardrail

- Evidence: The publish CLI *requires* `--label unofficial-research` for
  non-compliant TPC results (`benchbox/cli/commands/publish.py:97-110`,
  `run.py` `--publish-label`). But the explorer pipeline never reads any
  publish-time label from the bundle or the `~/.benchbox/published.json` store —
  it stamps a single CLI/`--trust-label` value on every result
  (`pipeline.py:377` `trust_label: str = "maintainer-run"`), overridable only by
  sidecar presence (§2.1). A bundle published as `unofficial-research` is
  re-badged `maintainer-run` by the explorer build. (Confirmed: no trust
  extraction in `transformer.py`; the `.manifest.json` carries no label field.)
- Impact: The compliance guardrail that `unofficial-research` exists to satisfy
  is silently voided the moment the result enters the explorer corpus — an
  unofficial/subscale TPC-DS result can appear maintainer-verified and ranked.
- Severity: Required.
- Remediation: Carry per-bundle provenance from the bundle/manifest into the
  pipeline (read `compliance_class` / a label field and map to the correct trust
  tier), instead of stamping one build-wide label.

#### 2.3 `BundlePublisher` silently coerces an unknown trust label to `maintainer-run`

- Evidence: `benchbox/core/publishing/bundle_publisher.py:88` —
  `self.label = label if label in VALID_LABELS else "maintainer-run"`. The CLI
  path is guarded by `click.Choice` (`publish.py:74`), but programmatic callers
  (`publish_bundle`, `run --publish`, any API user) get their invalid label
  upgraded to the **most** trusted tier rather than an error.
- Impact: A typo'd or attacker-influenced label (`"communtiy-submission"`,
  `"unofficial"`) is stored and referenced as `maintainer-run` in the durable
  publication record — a truthful-looking but wrong provenance stamp.
- Severity: Required.
- Remediation: Raise `ValueError` on an out-of-vocabulary label instead of
  coercing; only fall back to a default when the caller passed `None`.

#### 2.4 A present-but-empty manifest grants the community label without ever verifying the bundle hash

- Evidence: When a manifest is present but missing `bundle_file`/`bundle_hash`,
  `_validate_manifest_hash` emits `vr.warn(...)` and returns
  (`benchbox/validation/bundle.py:594-602`). `ValidationResult.ok` is
  `len(self.errors) == 0` (`bundle.py:170-172`), so warnings do **not** fail the
  check. Meanwhile sidecar *presence* alone flips the trust label to
  `community-submission` (§2.1) and inventory (`generate_corpus_inventory.py:50`).
- Impact: A submission can ship a contentless `.manifest.json`, pass
  `Validate Submission` green, receive a `community-submission` badge, and have
  its bundle bytes never actually hash-checked — the integrity contract the
  manifest represents is unenforced in this path.
- Severity: Required.
- Remediation: Promote the "manifest present but missing `bundle_file`/
  `bundle_hash`" case from `warn` to `error` (a sidecar that exists must be
  complete and must verify).

#### 2.5 The publisher's URI/dedup/companion handling is sound (verified — no defect)

- Evidence: `build_reference` (`store.py:266-286`) uses `is_cloud_path`
  (`cloud_storage.py:344-361`, schemes `s3/gs/gcs/az/abfss/azure/dbfs`) and
  otherwise `Path(destination).resolve()/filename` → `as_uri()`; the appended
  filename is always a basename (`source.name`), so no traversal via label/path.
  `_copy_bundle` (`bundle_publisher.py:251-271`) copies by `file.name` basename.
  The attacker-facing validator path is well-hardened:
  `_is_safe_bundle_filename` (`bundle.py:551-564`) rejects `/`, `\`, NUL, `..`,
  absolute and multi-segment names, and `_validate_manifest_hash` rejects
  symlinks before `is_file()` (`bundle.py:615-617`). Dedup key is
  `(resolved source_path, destination)` (`store.py:246-253`).
- Impact: None — recorded so a reader knows the traversal/spoofing surface was
  checked and passed. (Minor nit, Advisory-adjacent: dedup compares
  `destination` as a raw string, so `/x` vs `/x/` yield duplicate records; and
  `existing.scale_factor = scale_factor or existing.scale_factor` drops a
  legitimate `0.0` republish. Neither is a security issue.)
- Severity: Advisory (nits only).
- Remediation: Optionally normalize `destination` before the dedup compare.

#### 2.6 The operative `validate-submission.yml` on `published-results` still lets manifest-only PRs bypass hash validation

- Evidence: Contributor PRs target `published-results`, so the workflow that
  runs is the **on-branch** copy. That copy lacks the `CHANGED_MANIFESTS` block
  present on develop: `git show origin/published-results:.github/workflows/validate-submission.yml | grep -c CHANGED_MANIFESTS` → `0`; develop's copy → `3`. The
  develop block's own comment states the risk it closes: "A manifest-only PR
  skips both validate_submission.py and the corpus inventory check … so a bad
  manifest edit can merge without verifying the hash." The `sync` workflow's
  path allowlist (`sync-results-data-to-published.yml:21-30`) does not include
  `.github/workflows/**`, and its `GITHUB_TOKEN` could not push workflow files
  anyway — so nothing detects or mirrors this drift.
- Impact: On the exact branch where external, untrusted PRs land, a PR that
  edits only a `.manifest.json` (e.g. swapping in an attacker-chosen hash for an
  already-merged bundle) runs neither the validator nor the inventory drift
  check and can merge unverified.
- Severity: Required.
- Remediation: Add `.github/workflows/validate-submission.yml` to the slim-branch
  allowlist and document (in the ADR/runbook) how the on-branch workflow is kept
  current; or trigger `validate-submission` with `pull_request_target` from a
  trusted branch so the up-to-date workflow always runs. (Note the copies must
  differ in the `--no-project` invocation per the ADR, so verbatim mirroring is
  not correct — the update mechanism needs to be explicit.)

#### 2.7 `validate-submission.yml` executes PR-controlled validator code (self-green risk)

- Evidence: The trigger path filter is `results-data/bundles/**` (any-of match).
  The validator scripts run from the PR merge commit, so a PR that touches a
  bundle **and** `scripts/validate_submission.py` or
  `benchbox/validation/bundle.py` runs its own doctored validator and can
  self-report PASS. (Token is `contents: read` and downgraded for forks, so this
  is not privilege escalation — but it is trivial check-spoofing.) Neither
  `contributing-results.md` nor the runbook calls this out; the only backstop is
  the runbook's instruction to redirect out-of-allowlist PRs
  (`results-phase-2-runbook.md:134-135`).
- Impact: A green "Submission Validation" check is not trustworthy if the PR
  altered the validator; a reviewer relying on the check can be misled.
- Severity: Advisory (mitigated by review, no elevated permissions).
- Remediation: Run validation from a trusted ref (`pull_request_target` +
  checkout of base's validator), or fail the job if the PR modifies validator
  files, or narrow the trigger so validator edits route to `develop` only.

#### 2.8 Fork-PR validation comment likely 403s under the default token

- Evidence: `validate-submission.yml:3-12` uses plain `pull_request` with
  `permissions: pull-requests: write`. For fork PRs GitHub caps `GITHUB_TOKEN`
  read-only regardless of the `permissions:` block, so the always()-gated
  "Post PR comment" github-script step (`:97-132`) should 403 — turning even a
  passing validation red for the external-contributor audience the flow is for.
- Impact: External contributors (the whole point of Phase 2) see a red/failed
  check even when their bundle is valid.
- Severity: Required — but verify against a real historical fork-PR run first
  (a repo setting granting fork PRs write tokens would change this; I could not
  observe a live run).
- Remediation: Move commenting to a `workflow_run`/`pull_request_target`
  companion workflow that runs with the base repo's token, or gracefully skip
  commenting when the token is read-only.

---

### CI / Pipeline Integrity

#### 2.9 Three PR gates (`package-smoke`, `dependency-audit`, `parity-check`) are permanently skipped yet counted as passing

- Evidence: The gating jobs read outputs that the `ci-paths` job never exports.
  `ci-paths` declares only 7 outputs (`.github/workflows/pr.yml:20-26`:
  `safe-content-only, needs-code-ci, content-guard-needed, changed-paths,
  code-paths, unknown-paths, estimated-runner-minutes-saved`). But:
  - `pr.yml:770` and `:812` gate on `needs.ci-paths.outputs.packaging-needed == 'true'`.
  - `pr.yml:858` gates on `needs.ci-paths.outputs.viz-needed == 'true'`.
  The classifier emits these as **step** outputs
  (`scripts/path_filter_decision.py:196-200`; `.github/path-filters.yml:93-98`),
  but in GitHub Actions `needs.<job>.outputs.X` exists only if re-declared in the
  job's `outputs:` map. Undeclared → empty string → `== 'true'` always false →
  jobs always skipped. `ci-required-result` explicitly treats `skipped` as pass
  (`pr.yml:963-973`), and its comment claims this "cannot silently green a
  packaging regression" — which is exactly what happens. Shipped in HEAD
  (`fddedf26`, PR #952); the outputs map was never extended.
- Impact: Packaging regressions (the class `pr.yml:803` says "let v0.3.0 ship a
  broken clean install"), `pip-audit` findings, and CLI↔explorer visualization
  parity breaks all pass PR CI silently; `parity-check` never earns the green run
  its promotion criterion needs.
- Severity: Critical.
- Remediation: Add `packaging-needed: ${{ steps.classify.outputs.packaging-needed }}`
  and `viz-needed: ${{ steps.classify.outputs.viz-needed }}` (plus any other
  `<group>-needed` gate consumed downstream) to the `ci-paths` `outputs:` map.
  Add a CI meta-test asserting every `needs.ci-paths.outputs.*` referenced in
  `pr.yml` is declared.

#### 2.10 The snapshot-invariants gate exists but nothing runs it — the deploy ships an unvalidated read model

- Evidence: `_project/scripts/results_explorer_snapshot_invariants.py` enforces
  12 eligibility invariants; its docstring says it exists "so release gates can
  run it." There is no such caller: `grep -rn "snapshot_invariants" Makefile
  .github/workflows/ tests/ results-explorer/ _project/scripts/*.py` returns only
  the script's own definition (and historical audit prose). `docs.yml:110-118`
  builds the snapshot and immediately runs `npm run build` with no validation
  step in between.
- Impact: A malformed snapshot (missing required columns, ranked rows with no
  primary metric, compare-eligible rows without enough timings) deploys to the
  public explorer with no gate catching it.
- Severity: Required.
- Remediation: Invoke `results_explorer_snapshot_invariants.py` against
  `results-explorer/public/data/` in `docs.yml` right after the build step (and
  expose it as a `make` target), failing the build on violation.

#### 2.11 `make validate-imports` references a script that does not exist

- Evidence: `Makefile` `validate-imports` runs
  `uv run -- python scripts/validate_imports.py`, but that file does not exist
  (the real gate is `make lint-imports` → `uv run -- lint-imports`, the
  import-linter console script, which is what `pr.yml` uses). This was the only
  missing script among ~44 script references checked across the Makefile.
- Impact: A maintainer running the advertised `make validate-imports` gets a
  file-not-found; CI is unaffected.
- Severity: Advisory.
- Remediation: Point `validate-imports` at `lint-imports` (or delete the stale
  target).

---

### Doc / Reality Drift

#### 2.12 The `prune-publishing-subsystem` future-state doc instructs deletion of the live `benchbox publish` subsystem

- Evidence: `docs/design/future-state/prune-publishing-subsystem/README.md:31-33`
  — "Coupling analysis found zero consumers of the publishing module: no CLI
  integration, no runtime imports, no result-export coupling. The expected
  outcome is pruning." Listed as active, **High priority (dead code removal)** in
  `docs/design/future-state/index.md:43` and in the Sphinx toctree (renders on the
  published docs site). Reality: `benchbox/cli/commands/__init__.py:33` registers
  `publish`; `benchbox/cli/commands/publish.py:23-24` imports
  `benchbox.core.publishing.bundle_publisher`/`store`; `run.py` `--publish` calls
  `publish_bundle`; `tests/unit/core/publishing/` (33 tests) and
  `tests/integration/test_publish_cli.py` cover it. Timeline: the doc was written
  2026-04-01 (`90a2fd08`, v0.2.0) about the *old* generic layer, which was
  **deleted** in `0182c955` (2026-04-27) — the same commit that added the current
  `bundle_publisher.py`/`store.py` at the same path. The doc's "Related TODO:
  `prune-publishing-subsystem`" no longer exists.
- Impact: A maintainer or agent working the future-state backlog reads
  "High priority, zero consumers, no CLI integration" and deletes
  `benchbox/core/publishing/`, breaking the shipped `benchbox publish` command
  and `benchbox run --publish`. This is the single concrete instance where the
  "publish" naming collision (§2.19) causes real damage.
- Severity: Critical (a published instruction to delete live, shipped code).
- Remediation: Archive the doc (move under `docs/design/future-state/_archive/`
  or mark `Status: Completed in v0.2.1`), remove it from the active index/toctree,
  and note that the path now hosts the live bundle-publish subsystem.

#### 2.13 The "explorer is built and published from `main`" story contradicts the release curation and the workflow wiring

- Evidence: `results-phase-2-runbook.md:41-47` states the explorer "is built
  from `main` via docs.yml … The explorer publishes from `main`'s view of
  `results-data/`," and `contributing-results.md:108` promises "the docs CI
  workflow automatically rebuilds the results explorer with the new data" after a
  merge. But:
  - `docs.yml` has no trigger on `published-results` (`:3-36`; push=main,
    PR=main/develop); the `deploy` job requires `github.event_name == 'push' &&
    github.ref == 'refs/heads/main'` (`:193`), so §6's `gh workflow run docs.yml`
    (`workflow_dispatch`) builds but never deploys.
  - `Makefile:1070-1072` (`release-cut`) runs
    `git rm -rf … results-data results-explorer …` and deletes the four results
    workflows from every release branch, so `results-data/`/`results-explorer/`
    can never reach `main` under current curation.
  - `docs.yml:79-84` itself documents that on `main` the explorer steps are a
    "deliberate no-op" because `hashFiles('results-explorer/package.json')` is
    empty; `git ls-tree origin/main` confirms none of `results-explorer/`,
    `results-data/`, `_project/scripts/explorer_publish.py` exist on main
    (`results-explorer/` has never existed on main).
- Impact: A merged community submission never appears in the public explorer via
  any automated path, and there is no automated flow back from `published-results`
  into develop/main. A maintainer following the runbook waits for a rebuild that
  cannot occur; a contributor reading `contributing-results.md` is promised an
  auto-rebuild that never runs.
- Severity: Required.
- Remediation: Reconcile the docs with the actual pipeline: either (a) document
  that the explorer is served from `develop`/a dedicated build and fix the deploy
  trigger accordingly, or (b) if `main` is genuinely the source, stop stripping
  `results-data`/`results-explorer` in `release-cut`. Update
  `contributing-results.md:108` and `results-phase-2-runbook.md §1.3/§6` to
  describe the real trigger and the fact that `workflow_dispatch` does not deploy.

#### 2.14 The default branch (`main`) ships QA/ADR/runbook docs and a Make target that reference paths absent on `main`

- Evidence (all via `git show origin/main:…` / `git ls-tree origin/main`): main
  **lacks** `results-explorer/`, `_project/scripts/`, `_project/audits/`, and any
  explorer publisher (neither `benchbox/cli/commands/explorer.py` nor
  `_project/scripts/explorer_publish.py`). main **has**
  `docs/operations/results-explorer-qa.md` (7 references to
  `results-explorer/`/`_project/`/`results-data/`; e.g. `cd results-explorer`,
  the `_project/audits/*.md` contract, `_project/scripts/audit_sha_backfill.py`),
  `adr-explorer-cli-surface.md` (mandates a script path absent on main), and a
  `Makefile` `audit-sha-check` target invoking `_project/scripts/audit_sha_check.py`
  which is absent on main (so the target fails). main's `README.md:66` links
  "Browse results online: benchbox.dev/results/". Mitigation that passes:
  `CONTRIBUTING.md:44` states "`develop` is the long-lived development branch; …
  `main` is release-only."
- Impact: Anyone landing on the default GitHub branch reads QA runbooks, an ADR,
  and a Make target that reference infrastructure existing only on develop, plus a
  README link to a results site the current main pipeline cannot have deployed.
- Severity: Required (default-branch reader experience).
- Remediation: Exclude these dev-only docs from the release curation (as
  `results-explorer/`/`_project/` already are), OR add a prominent "this page
  describes develop-only tooling" banner, OR keep only docs whose referenced
  paths survive `release-cut`.

#### 2.15 `adr-published-results-slim-corpus-branch.md` (Accepted) contradicts the branch it governs

- Evidence: ADR `:100-103` claims the validators are "stdlib-only … no
  `benchbox.*` imports," and the allowlist table `:84-86` **excludes** `benchbox/`.
  Reality: `scripts/validate_submission.py:23` imports
  `from benchbox.validation.bundle import …` (with an importlib fallback);
  `sync-results-data-to-published.yml` watches/mirrors
  `benchbox/validation/bundle.py` (`:29,:83,:127,:160`); and
  `git ls-tree -r origin/published-results | grep ^benchbox/` shows
  `benchbox/validation/bundle.py` present on the branch (landed via mirror PR
  #555, 2026-05-21). The ADR's own maintenance trigger ("a new validator …
  becomes load-bearing … and would need to be vendored") fired but the ADR
  (last touched 2026-05-03) was never updated. Minor: the ADR references a TODO
  path now under `_project/DONE/`.
- Impact: The allowlist is the governance contract for a public, force-pushed
  branch. An auditor comparing the branch to the ADR would flag
  `benchbox/validation/bundle.py` as contamination and could "clean" it, breaking
  submission CI; the stdlib-only claim misleads anyone re-deriving the
  `uv run --no-project` invocation contract.
- Severity: Required.
- Remediation: Update the ADR allowlist to include `benchbox/validation/bundle.py`
  and correct the "stdlib-only / no `benchbox.*`" statement to describe the
  shared-implementation + importlib-fallback reality; fix the DONE TODO path.

#### 2.16 The "maintained" Results Explorer QA plan points future testers at a sealed audit and a closed TODO

- Evidence: `results-explorer-qa.md:7-10` says the plan "should be reused for
  future … passes," yet `:95` and `:392` hardcode saving findings to
  `_project/audits/results-explorer-qa-pass2-findings.md` — a completed,
  `develop_sha`-stamped audit (pass 3 already happened;
  `results-explorer-qa-pass3-findings.md` exists). `:392` also says to "update the
  existing pass-1 TODO" and `:369` references the `results-explorer-qa-pass1-fixes`
  TODO — completed at `_project/DONE/main/active/results-explorer-qa-pass1-fixes.yaml`.
  `:114` directs screenshots to `_project/audits/screenshots/`, which does not
  exist. (Also noted per the seed: there is no `*pass1*findings*` file — pass-1
  evidence lives only in the QA doc's S11 list and the DONE TODO, so the audit
  trail is asymmetric.)
- Impact: A pass-4 tester following the doc appends to a sealed pass-2 audit,
  corrupting a record whose `develop_sha` stamp then misdescribes its contents,
  and tries to update a TODO that no longer exists.
- Severity: Required.
- Remediation: Parameterize the pass number (e.g. "save to
  `results-explorer-qa-pass<N>-findings.md`, next unused N"), drop the hardcoded
  pass-1 TODO reference, and either create `_project/audits/screenshots/` or
  update the retention instruction to match the "not retained in git" reality the
  pass-2 findings already record.

#### 2.17 QA doc §S7.6 security check asserts a mechanism that does not exist ("`bench.results` is a view")

- Evidence: `results-explorer-qa.md:331` — "confirm `bench.results` is a view,
  not the bare table — or that DDL … is rejected or a no-op." Reality: the
  builder creates `results` as a **table**
  (`_project/scripts/explorer_pipeline/duckdb_builder.py:371,:282`; the file's
  views are `result_detail_metrics` and `platform_index_rows`). The real
  protection is the read-only attach: `results-explorer/src/db.ts:278` —
  `ATTACH 'results.duckdb' AS bench (READ_ONLY)` (and `:275` registers the file
  HTTP-backed/unwritable). There is **no** SQL statement filtering in the editor
  path (`src/pages/Query.tsx:608-617` passes raw SQL to `queryRows`). So DDL/DML
  against `bench.*` is rejected (catalog is read-only), but `CREATE TABLE …`/`SET`
  against the in-memory catalog succeed (transient, tab-local) — "no-op" is the
  wrong word. An e2e test pins the rejection: `results-explorer/e2e/routes/query.spec.ts:153-168`.
- Impact: A QA tester who checks "is it a view?" files a false failure; a
  reviewer citing S7.6 claims a protection in a form that doesn't exist. The
  underlying security property (published data cannot be mutated) does hold.
- Severity: Advisory (doc-wording defect; the property itself is satisfied).
- Remediation: Reword S7.6 to "the `bench` database is attached `READ_ONLY`;
  writes to `bench.*` error; writes to the in-memory catalog succeed but are
  tab-local and transient and cannot alter the published snapshot."

#### 2.18 QA-doc fixture/route drift (sample IDs, corpus surfaces, URL-sync claims)

- Evidence: `results-explorer-qa.md:5` claims the fixture corpus spans
  `duckdb, sqlite, datafusion, polars` with 12 results, but there is **no sqlite
  fixture anywhere** (`find results-explorer -name "*sqlite*"` → empty), and 5 of
  6 sample result IDs in §S5 do not exist in the tree (only
  `tpch-duckdb-sf0.01-20260403-7fe93365` is real). `:S3.1` says view mode "is not
  currently URL-synced" — stale: `BenchmarkIndex.tsx:211` uses
  `useUrlState("view", …)`. `:S3.4` says the trust filter is "not URL-synced" —
  stale: it flows through `useFacetUrlState`. Browser-testing doc overstates the
  push trigger as "every push … that touches results-explorer/" — push is
  `branches: [main]` only (`results-explorer-browser.yml:5-6`).
- Impact: Testers waste time on non-existent sample IDs / a non-existent sqlite
  surface and file false findings against already-fixed URL-sync behavior.
- Severity: Advisory (the sample-ID section borders on Required — it is unusable
  as written).
- Remediation: Regenerate the sample-ID list and corpus-surface description from
  the actual `test-fixtures/`, and delete the stale "not URL-synced" notes.

#### 2.18b Assorted smaller doc drifts (grouped)

- Evidence:
  - Strategy doc cites deleted files as current evidence:
    `benchbox-results-platform-strategy.md:480` points at
    `benchbox/core/publishing/artifacts.py` / `permalink.py`, both deleted in
    `0182c955` (2026-04-27).
  - `adr-explorer-cli-surface.md:38-41` and `results-explorer-browser-testing.md:70-72`
    say docs.yml / browser workflow "trigger only on `main`" and run on "every
    push and pull request" — both now also run on PRs to develop, and the browser
    push trigger is main-only.
  - `results-explorer-token-scan.md:135-137` omits `medium-test` from the jq
    filter it describes (`develop-post-merge.yml:515` includes it).
  - `repo-admin-settings.md:58-59` says `ci-required-result` "aggregates 4 jobs";
    the real `needs` list has 10 (`pr.yml:916`).
  - `results-phase-2-runbook.md:29-30` says the sync watches "two vendored
    validators" (it watches three code files incl. `benchbox/validation/bundle.py`)
    and calls `seed-corpus.yml` a "quarterly refresh" (it is `workflow_dispatch`
    only, no `schedule`).
- Impact: Each misleads a maintainer re-deriving CI behavior or the release
  surface from the docs.
- Severity: Advisory.
- Remediation: Correct each cited line against the current YAML/tree.

---

### Architectural Boundary & Naming Collisions

#### 2.19 Five overlapping "publish" senses; the collision is mostly disambiguated but has one live hazard

- Evidence: The token "publish" spans (1) `benchbox publish` — copy a bundle to
  storage + track (`benchbox/cli/commands/publish.py`); (2) `benchbox submit` —
  community corpus PR; (3) `explorer_publish.py build` — build the static snapshot
  (`_project/scripts/explorer_publish.py`, click group `explorer_publish`); (4)
  the `published-results` corpus branch; (5) the stale "generic publishing /
  artifactlinks" concept in the prune doc. The strategy doc explicitly splits
  publish vs submit (`benchbox-results-platform-strategy.md:14-20`), the CLI ref
  disambiguates publish vs export (`CLI_REFERENCE.md:75-88`), `submit.md:123-133`
  has a "submit vs publish" table, and `db.ts:192` no longer names a command — so
  most surfaces are safe. The one place a reader acts on the wrong "publish" is
  §2.12 (the prune doc / future-state index treating the live `benchbox publish`
  backend as the dead generic layer).
- Impact: Bounded — the concrete damage is captured as §2.12; the rest is
  cognitive overhead.
- Severity: Advisory.
- Remediation: Fix §2.12; optionally add a one-line "publish disambiguation" note
  to `AGENTS.md`/CLI docs naming all five senses.

#### 2.20 Trust-label vocabulary diverges between the publisher and the explorer

- Evidence: `bundle_publisher.py:30` — `VALID_LABELS = ("maintainer-run",
  "community-submission", "ci", "local", "unofficial-research")`. The explorer's
  `TrustBadge` config keys are `ci-verified`, `ci-validated`, `local-run`
  (`results-explorer/src/components/TrustBadge.tsx:19-43`), and ranking eligibility
  is `{"maintainer-run", "ci-verified"}` (`models.py:82-89`). So a bundle labeled
  `ci` or `local` by the publisher renders under the explorer's "unrecognised —
  contact maintainers" fallback and (for `ci`) is **not** ranking-eligible despite
  the publisher treating `ci` as a first-class trusted label; `unofficial-research`
  has no explorer badge at all.
- Impact: Cross-subsystem inconsistency: the two halves of the platform disagree
  on the label vocabulary, so publisher-set labels can silently degrade to
  "unrecognised" / non-ranked in the UI.
- Severity: Advisory.
- Remediation: Define one canonical trust-label enum shared by
  `benchbox/core/publishing/` and `_project/scripts/explorer_pipeline/` +
  `TrustBadge`, and map `ci`↔`ci-verified` / `local`↔`local-run` explicitly.

#### 2.21 `TrustBadge` hides entirely on an empty label instead of showing "unknown"

- Evidence: `results-explorer/src/components/TrustBadge.tsx:64` —
  `if (!trustLabel) return null;`. (Moot in the current pipeline because
  `trust_label` is `NOT NULL` in the snapshot schema, `duckdb_builder.py:392`, but
  the component contract is hide-on-missing.)
- Impact: If a future schema/path yields an empty label, the trust dimension is
  silently hidden rather than flagged.
- Severity: Advisory.
- Remediation: Render the `DEFAULT_CONFIG`/"unknown" badge on empty rather than
  returning null.

#### 2.22 Explorer-related tests live under misleading directory paths

- Evidence: `tests/unit/core/explorer_pipeline/*` all import
  `_project.scripts.explorer_pipeline.*` (the module moved out of
  `benchbox.core` per `adr-explorer-cli-surface.md`), and
  `tests/unit/cli/test_explorer_build_contract.py` imports
  `_project.scripts.explorer_publish` while testing no `benchbox.cli` command.
  The tests pass (verified, see §3-preface), so this is a naming residue, not a
  breakage.
- Impact: A reader navigating by directory believes the explorer pipeline still
  lives under `benchbox/core` / that a CLI contract test covers a CLI command.
- Severity: Advisory.
- Remediation: Relocate to `tests/unit/scripts/explorer_pipeline/` and
  `tests/unit/scripts/` to mirror the migrated source layout.

---

### Explorer Runtime Surface (static-analysis only)

#### 2.23 No CSP on the explorer, combined with duckdb-wasm remote-fetch capability

- Evidence: `results-explorer/index.html` sets no CSP meta tag; duckdb-wasm
  (1.32.0 per `package-lock.json`) can `INSTALL httpfs`/`read_csv('https://…')`.
  The SQL editor's text is component state (`Query.tsx:115`), never seeded from
  URL params, so there is no injection vector — a user would have to paste hostile
  SQL themselves, and the queried data is public.
- Impact: A self-inflicted-only exfiltration channel; no third-party injection
  path found. No XSS sinks exist (`grep dangerouslySetInnerHTML|innerHTML|
  document.write|eval` over `src` → zero), and all app-generated SQL is
  parameterized with allowlisted columns (`queryFilters.ts:33-161`).
- Severity: Advisory.
- Remediation: Add a restrictive CSP (and consider disabling
  `autoload`/`httpfs` in the wasm config) if the threat model includes a user
  pasting attacker-supplied SQL.

---

## 3. L2 — what this review's method did not cover

These are gaps in the review approach itself, not defects (all defects above are
owned in §2). Preface: I confirmed the `explorer_pipeline`/publishing tests pass
(260 + 33 green) and the ADR migration/audit-SHA wiring landed, so the
"orphaned tests / unexecuted migration" class was checked and came back clean.

- **No runtime observation of the explorer or the deployed site.** The review is
  entirely static. I verified the read-only DuckDB attach and the absence of SQL
  filtering from source, but did not run the app, the Playwright suite, or a real
  snapshot build — so I cannot confirm the *actual* error text on rejected DDL,
  whether duckdb-wasm in the shipped bundle really can fetch `httpfs`, or that the
  built `.duckdb` matches the schema at runtime. Outbound HTTPS to
  `benchbox.dev/results/` is proxy-blocked, so the live deployment state
  (Finding 2.13/2.14) is inferred from workflow gating + branch content, never
  observed. A reviewer with Actions history / a live browser could confirm or
  refute whether the explorer has *ever* deployed.
- **No adversarial modeling of the hosted submission service.** `benchbox submit`
  has an entire hosted path (`submit_auth.py`, `submit_service.py`, token refresh,
  visibility choices) that ships to end users on `main`/PyPI. This review scoped to
  the PR-based Phase-2 flow; the hosted API's auth/token/replay surface was not
  examined.
- **No performance-budget evaluation.** The explorer has documented range-read /
  snapshot-size budgets (`e2e/capability/range-read-budget.spec.ts`) and the
  pipeline does per-bundle I/O; I did not assess whether the snapshot build or the
  browser read model meets any latency/size budget, or how it scales past the
  current ~525-result corpus.
- **Docs read opportunistically, not exhaustively.** The `docs/` +
  `_project/` prose corpus is very large (dozens of ADRs, handoffs, decisions,
  specs). I verified the documents named in the seeds and those they cross-link,
  but there are whole doc trees (`_project/decisions/`, `_project/planning/`,
  `_project/research/`, `_project/specs/`) whose claims about these subsystems I
  did not re-derive. The drift rate observed (§2.12–2.18b) suggests more of the
  same class exists unexamined.
- **Concurrency/ordering of the sync + release pipelines not modeled.** I read the
  `sync`/`release-cut`/`docs` workflows for content correctness but did not reason
  about interleavings (e.g. a mirror PR racing a release cut, or a
  `published-results` force-push landing between a contributor PR's checks and its
  merge) — a class of bug the static read cannot surface.

---

<!--
Per docs/development/review-protocol.md §1 & §4, this capture is local-only.
No commit, push, PR, or remediation was performed. Remediation of any finding
above requires explicit user authorization in a separate turn.
-->
