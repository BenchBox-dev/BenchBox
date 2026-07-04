# Results Explorer & Results Publication — Adversarial Review Prompt

**Audience:** a fresh agent session with repo access and no prior context.
**Output:** a topic-grouped findings report, each finding paired with a
specific remediation, saved under `_project/audits/`.

Copy everything below the rule into a new agent session verbatim.

---

## Prompt

You are conducting a deep adversarial review of BenchBox's **Results
Explorer** and **Results Publication** subsystems — both the code and the
architecture/process docs that describe them. This is a review, not an
implementation task: follow `docs/development/review-protocol.md` in full.
Concretely that means:

- Read-only plus local capture. You may read code, run local
  analyses/tests/greps, and write your findings file. You MUST NOT commit,
  push, open a PR, or touch any write-shaped skill as a side effect of this
  review.
- Apply the defect gate from Section 2 of that protocol to every finding:
  if it materially affects correctness, security, or performance, it is a
  **defect** and goes in your severity table with a concrete remediation —
  it does not get filed away as a vague "blind spot."
- Run an L2 pass (Section 3): after your instance-level findings, ask what
  *class* of problem your review method didn't ask you to look for, and
  say so explicitly rather than silently generalizing an instance finding.

### What counts as in scope

Treat "Results Explorer" and "Results Publication" broadly — they overlap
and are frequently confused with each other in this codebase, which is
itself something to scrutinize:

1. **Results Explorer** — the browser-based read model and UI for
   published results (referenced as `results-explorer/` — a Vite/Preact +
   DuckDB-WASM app), and whatever pipeline builds/exports the static
   DuckDB snapshot it reads (search for `explorer_pipeline`,
   `explorer_publish`, `explorer build`, `explorer-build-contract`).
2. **Results Publication** — the schema-v2 result-bundle publish/tracking
   path (`benchbox publish`, `benchbox/core/publishing/`,
   `PublicationStore`, `BundlePublisher`), the `published-results` git
   branch and its sync workflow, and the Phase 2 external-contributor
   submission flow (validator workflow, `docs/contributing-results.md`,
   `docs/operations/results-phase-2-runbook.md`).
3. Every doc, ADR, CI workflow, Makefile target, and test that asserts
   something about either of the above.

### Method: verify, don't trust

The single most important instruction in this review: **do not take any
doc, ADR, comment, or docstring's claims at face value.** This codebase has
an unusually large body of architecture prose (ADRs, future-state design
docs, brand-ownership decisions, QA runbooks, audit-SHA contracts) sitting
alongside the actual code and git history, and prose and reality can and do
diverge here. For every non-trivial claim you rely on, re-derive it the way
`docs/development/adr/adr-explorer-cli-surface.md`'s "Provenance Facts"
section does: `git log`, `git show --stat`, `git blame`, `find`/`grep`
against the actual tree — then cite the command and its output as evidence
in your finding, not just a paraphrase.

Specifically, verify each of the following instead of assuming either
answer — these are leads, not conclusions:

- **Does `results-explorer/` actually exist anywhere reachable from this
  repo** (any branch, any remote, a documented separate repo), given how
  extensively `docs/operations/results-explorer-qa.md`,
  `docs/development/results-explorer-browser-testing.md`,
  `docs/operations/results-explorer-token-scan.md`, and multiple ADRs
  describe its source files, routes, and CI wiring? If it's genuinely
  absent, work out whether every doc/CI reference that assumes its
  presence is still accurate, stale, or actively misleading to a
  maintainer following the docs today.
- **Did the migration in `adr-explorer-cli-surface.md` actually land?**
  That ADR mandates moving `benchbox/cli/commands/explorer.py` and
  `benchbox/core/explorer_pipeline/` to
  `_project/scripts/explorer_publish.py` /
  `_project/scripts/explorer_pipeline/`. Check whether the old locations,
  the new locations, and `_project/scripts/` itself exist — and whether
  `tests/unit/core/explorer_pipeline/` (or any other test directory) still
  imports a module that no longer exists anywhere.
- **Is `docs/design/future-state/prune-publishing-subsystem/README.md`
  still accurate?** It asserts "zero consumers... no CLI integration" for
  the publishing module as grounds for deletion. Check whether
  `benchbox/cli/commands/publish.py` (registered in
  `benchbox/cli/commands/__init__.py`) and `benchbox/core/publishing/`
  (`BundlePublisher`, `PublicationStore`) contradict that, and if so,
  whether this is because a newer, real publishing system was built after
  the prune doc was written — in which case the future-state doc is stale
  and pointing maintainers at the wrong subsystem.
- **Are the naming collisions between the two "publish" concepts
  (bundle-publish/tracking vs. explorer-snapshot-publish) causing real
  confusion** in docs, error messages, contract files, or code — not just
  a stylistic nit, but a place where a reader/script could act on the
  wrong command.
- **Do `_project/audits/`, `_project/blind-spots/`, `_project/scripts/`,
  and `_project/TODO/` actually contain what the docs assume?** Several
  docs (the QA plan, the token-scan gate, the review protocol itself)
  reference specific files or an established, reused process in these
  directories. Confirm what's actually present versus referenced, and
  whether any Makefile target that depends on a referenced-but-missing
  script would fail if run right now.
- **`published-results` branch and sync architecture**
  (`adr-published-results-slim-corpus-branch.md`,
  `.github/workflows/sync-results-data-to-published.yml`,
  `validate-submission.yml`): confirm the branch, workflow files, and
  validator described actually exist and match the ADR's description of
  what they do; look specifically for drift between "Accepted" ADR status
  and what's actually wired into CI today.
- **DuckDB read-only surface claim**: `docs/operations/results-explorer-qa.md`
  §S7.6 asserts `bench.results` is a view (not the bare table) or that
  DDL/DML against the ad-hoc SQL editor is rejected/no-op — a real
  security property, not just a UX nicety. If the underlying code is
  reachable in this repo, verify the claim against the actual attach/view
  definition rather than the doc's assertion. If the code isn't in this
  repo, say so as a finding rather than silently skipping the check.
- **CI wiring reality**: for any workflow file referenced by these docs
  (`.github/workflows/docs.yml`, `develop-post-merge.yml`, `pr.yml`,
  `sync-results-data-to-published.yml`, `validate-submission.yml`), confirm
  the job names, commands, and conditionals the docs describe still match
  what's in the YAML today.

Beyond these seeded threads, actively look for more of the same *class* of
problem — don't stop once you've confirmed or refuted the items above.

### Additional adversarial angles

- **Correctness/security in the publication path**: bundle deduplication,
  reference-URI construction (`file://`, `s3://`, `gs://`, `abfss://`) in
  `BundlePublisher`/`build_reference` — can a crafted result-bundle path or
  label cause path traversal, an incorrect dedup match, or a truthful-looking
  but wrong reference URI? Check `VALID_LABELS` enforcement and companion
  file (`.plans.json`, `.tuning.json`) handling for confusion/spoofing risk.
- **Trust/provenance labeling**: results carry `trust_label`s
  (`maintainer-run`, `community-submission`, `ci`, `local`,
  `unofficial-research`) that the explorer surfaces as trust badges. Trace
  whether a community-submitted bundle could end up mislabeled as
  maintainer-run anywhere in the publish → sync → explorer-build pipeline.
- **Orphaned/dead code and tests**: anything that imports a module or reads
  a fixture path that no longer exists, anything gated by a Makefile target
  whose script is missing, any test asserting behavior of a component this
  review determines is absent.
- **Process/governance debt**: ADRs marked "Accepted" whose consequences
  section was never fully executed; audit contracts (`develop_sha:`
  frontmatter, `make audit-sha-check`) that nothing currently exercises
  because the audits directory is empty; QA processes describing
  "pass-1 confirmed bugs" with no corresponding findings file on disk.

### Output contract

Write your findings to
`_project/audits/results-explorer-publication-adversarial-review.md`.
Start the file with the frontmatter contract used by every other audit in
that directory:

```yaml
---
develop_sha: <output of `git rev-parse origin/develop` or the actual base branch, if `develop` doesn't exist here — say which>
---
```

Structure the body as:

1. **Executive summary** — 3-6 sentences: what you reviewed, what you could
   and couldn't verify given what actually exists in this checkout, and the
   headline risk.
2. **Findings grouped by topic** (not by file). Use topic headers you
   derive from what you actually find — likely candidates given the seeds
   above are things like *Doc/Reality Drift*, *Architectural Boundary &
   Naming Collisions*, *CI/Pipeline Integrity*, *Dead Code & Orphaned
   Tests*, *Publication Path Correctness & Security*, *Process &
   Governance Debt* — but don't force a finding into a bad-fit bucket
   just to match this list.

   For every finding, use this exact shape:

   ```markdown
   ### <short title>

   - **Evidence**: <file:line and/or the exact command you ran and its
     output — enough for a reader to reproduce your check>
   - **Impact**: <what actually goes wrong, and for whom — a maintainer
     following stale docs, a contributor's PR being mislabeled, CI
     silently no-op'ing, etc.>
   - **Severity**: Critical / Required / Advisory (apply the defect gate:
     Critical/Required = defect, materially affects correctness, security,
     or maintainer trust in the docs; Advisory = real but lower-stakes)
   - **Remediation**: <a specific, actionable fix — "update ADR X to mark
     status as superseded and point at Y", "delete orphaned test file Z",
     "add a CI check that fails when doc path W doesn't resolve" — not
     "investigate further">
   ```

3. **L2 — what this review's method didn't cover** — name the class of
   issue your approach is structurally blind to (e.g., you couldn't
   evaluate frontend runtime behavior at all if `results-explorer/` isn't
   in this checkout; you didn't check performance budgets; you didn't
   verify claims in docs you didn't have time to read). Do not put
   already-confirmed defects here — this section is for gaps in the
   review itself.

When you're done, reply with `Recorded: _project/audits/results-explorer-publication-adversarial-review.md` plus a one-line count of findings by severity, and stop — per the review protocol, remediation lands only if the user authorizes it in a separate turn.
