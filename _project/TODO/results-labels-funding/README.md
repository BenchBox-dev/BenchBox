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

| Gate | Work item | Question |
|---|---|---|
| G-VENDOR-SIGNAL | `submit-manifest-and-validator` | Exact maintainer-controlled mechanism that applies `vendor-supplied` at merge so it cannot be self-asserted in a community PR. |
| G-FUNDING-PRIVACY | `corpus-inventory-and-read-model` | Whether `funding` is a public, non-redactable field (proposed: yes — it is a disclosure) and whether `unspecified` is allowed on curated results. |
| G-READMODEL-COORD | `explorer-pipeline-frontend-handoff` | How the `read_model_version` bump + private `explorer_pipeline`/`results-explorer` edits are coordinated, since that source is not in this checkout. |

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

| Order | Item | Depends on | In-repo? |
|---|---|---|---|
| 1 | `provenance-vocabulary-and-labels` | — | Yes |
| 2 | `bundle-schema-and-run-cli` | 1 | Yes |
| 3 | `submit-manifest-and-validator` | 1 | Yes |
| 4 | `corpus-inventory-and-read-model` | 1, 2, 3 | Yes (DDL + inventory) |
| 5 | `explorer-pipeline-frontend-handoff` | 4 | **No** — spec only; `_project/scripts/explorer_pipeline/` and `results-explorer/` are gitignored and absent from this checkout. |

Items 1–3 are independent of each other after item 1 lands and can proceed in
parallel. Item 4 integrates them into the explorer ingest. Item 5 is a
hand-off spec because the code it changes lives in maintainer-private trees.

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
