# Results provenance labels + funding disclosure

**Worktree:** `results-labels-funding`
**Branch:** `claude/results-labels-funding-r030xb`
**Created:** 2026-07-06
**Status:** Planning

## Goal

Give every result in the results explorer two provenance signals it lacks today:

1. **A source/provenance label** that distinguishes **vendor-supplied** results
   from **internal (maintainer)** and **community-submitted** results. Today the
   explorer only derives two trust labels (`maintainer-run` vs
   `community-submission`) from the *presence of a submission-manifest sidecar*
   (`scripts/generate_corpus_inventory.py:41`, explorer pipeline). A vendor
   running its own product has a conflict of interest and is neither category.
2. **A funding disclosure** — who/how the run was paid for (employer, personal,
   free trial, vendor-sponsored, grant, unspecified). Nothing records this today.

## Resolved decisions (locked with the requester, 2026-07-06)

| # | Decision | Outcome |
|---|---|---|
| D1 | How `vendor-supplied` relates to trust labels | **New trust-label value** `vendor-supplied` (visibility state `public-vendor-reported`), not a separate orthogonal flag. |
| D2 | Ranking eligibility of vendor-supplied results | **Ranked, clearly badged** — `is_ranking_eligible = true`, with a distinct badge + legend note (disclose the conflict of interest without demoting to browse-only). |
| D3 | Funding vocabulary | `employer` · `personal` · `free-trial` · `vendor-sponsored` · `grant` · `unspecified`. |

## Open decision gates (resolved inside the owning work item)

| Gate | Work item | Status |
|---|---|---|
| G-VENDOR-SIGNAL | `submit-manifest-and-validator` | Resolved (Option A: vendor subtree) — but the *enforced* CODEOWNERS half is split out to item 6, still open. |
| G-FUNDING-PRIVACY | `corpus-inventory-and-read-model` | Resolved — funding is public, non-redactable; `unspecified` allowed. |
| G-READMODEL-COORD | `explorer-pipeline-frontend-handoff` | Resolved (PR #1021) — version bumped with the populate logic; contract tests guard it. |
| **G-CODEOWNERS-MECHANISM** | `vendor-label-codeowners-governance` | **Open** — how to add the vendor owner rule given the CODEOWNERS↔SOUNDNESS_PREFIXES 1:1 mirror test. |
| **G-CODEOWNERS-BRANCH** | `vendor-label-codeowners-governance` | **Open** — which branch(es) (develop / published-results) must carry the vendor owner rule. |

## Design in one paragraph

Two **orthogonal** fields. `result_source` extends the existing trust-label
spectrum: `internal → maintainer-run`, `community → community-submission`,
`vendor → vendor-supplied` (new). `funding` is a new independent axis (a vendor
result may be employer-funded; a community result may be free-trial-funded). Both
are **declared, not inferred**: `funding` is captured at run time (`--funding`)
and carried in an optional `provenance` block in the schema-v2 bundle; the vendor
label is applied by maintainers at merge (never self-asserted). Canonical
vocabulary lives in one module so the CLI, submit path, corpus inventory,
validator, and read model agree.

## Sequenced work items (each shipped via the delivery loop below)

| Order | Item | Depends on | Status (2026-07-07) |
|---|---|---|---|
| 1 | `provenance-vocabulary-and-labels` | — | ✅ done (PR #1021) |
| 2 | `bundle-schema-and-run-cli` | 1 | ✅ done (PR #1021) |
| 3 | `submit-manifest-and-validator` | 1 | ✅ done (PR #1021) |
| 4 | `corpus-inventory-and-read-model` | 1, 2, 3 | ✅ done (PR #1021) |
| 5 | `explorer-pipeline-frontend-handoff` | 4 | 🟡 pipeline + badge done; funding **view projection + chip + legend + e2e** remain |
| 6 | `vendor-label-codeowners-governance` | 3 | ⛔ blocked — enforced CODEOWNERS control for the vendor label (needs a maintainer decision) |

**Correction:** item 5 was originally scoped as a hand-off spec on the assumption
that `_project/scripts/explorer_pipeline/` and `results-explorer/` were absent;
they are in fact present in the checkout, so item 5 is real in-repo code — the
pipeline half (funding column, vendor derivation, read_model_version bump) and the
vendor badge are done; the funding **disclosure surface** (view projection → chip
→ legend → e2e) remains.

**Item 6** was added after the item-3 security review found that the vendor label's
*enforced* control (CODEOWNERS on `results-data/bundles/vendor/`) does not yet
exist — only the advisory validator guard does. It is blocked on a maintainer
decision (it couples to the auto-merge soundness-mirror machinery).

## Standard delivery loop (per work item)

Every work item is delivered with the same **create → review → fix → submit-pr**
loop:

1. **create** — implement the item strictly within its `scope_limit`; keep the
   change back-compatible (absent fields ⇒ today's behavior).
2. **review** — run `/code-review` (and `/security-review` for the validator
   item, which parses attacker-controlled PR JSON); run the item's
   `verification` commands and `make pr-preflight`.
3. **fix** — address review findings and any failing gate; re-run verification.
4. **submit-pr** — open a PR against `develop` using
   `.github/PULL_REQUEST_TEMPLATE.md`, linking this work item; on merge move the
   item's YAML from `_project/TODO/results-labels-funding/planning/` to
   `_project/DONE/results-labels-funding/planning/` and set
   `status: Completed` + `completed_date`.

A work item does not start until its `deps.needs` are merged and any blocking
decision gate is resolved.
