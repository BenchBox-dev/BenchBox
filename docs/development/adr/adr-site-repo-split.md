# ADR: Split the public site into its own repository

## Status

Accepted under S1 design authority (tracker item
`site-split-00-adr-soundness-scope`). Oracle review: PR link recorded here on
merge. Plan: `_project/handoffs/site-repo-split-handoff-20261006.md`
(plan branch `origin/claude/bold-newton-uudn48`, unmerged at the time of writing).

## Context

The Astro cutover was delayed by coupling to core CI: every site change ran the
full core pipeline, and site deploys shared the core merge queue. The site
needs isolated CI and fast rollouts. This ADR moves every site asset out of
`BenchBox-dev/BenchBox` (core) into `BenchBox-dev/benchbox-site` (site),
connected by one versioned contract: the site-inputs bundle that core produces
and attests. benchbox.dev stays up, keeps its URLs, and keeps deploy receipts
and rollback throughout.

## Decisions

D1 through D6 are the plan's wording. D7 onward are owner decisions dated
2026-10-06, recorded in `site-split-*` tracker contexts (the plan predates
them). Where an item refines a plan decision, both wordings are recorded and
the refinement governs execution.

| # | Decision | Wording | Source |
|---|---|---|---|
| D1 | User docs location | `docs/**.md` stay in core; the site pulls them via the bundle. | Plan |
| D2 | Repo name and visibility | `BenchBox-dev/benchbox-site`, public. | Plan |
| D3 | Rehearsal host | `next.benchbox.dev` CNAME, pointed at the site repo Pages before cutover. | Plan; item 30 |
| D4 | Deploy control plane port | Plan: port the Python plane to TypeScript later (Phase 5); move it as-is first. Refinement (operative): replace the Python control plane with Node now; no Python in the site repo. | Plan; item 23 |
| D5 | Docs-PR site gate | Core `docs/` PRs are gated on a site build (`site-compat` job against the pinned site SHA). | Plan |
| D6 | Deploy trigger | Plan: dispatch-only with a required reviewer. Refinement (operative): auto-deploy with no reviewer on `github-pages`; no required reviewers on that environment. | Plan; items 21, 23 |
| D7 | Trunk-only docs | Trunk-only docs supersede release-pinned docs. | Item 01 |
| D8 | Visual regression | Advisory (non-blocking) in site CI. | Item 21 |
| D9 | Language boundary | Node hooks only; no JS/TS source in core; no Python source in the site repo. Run-time third-party tools are allowed (including invoking the published `benchbox` CLI at a pinned version). | Items 21, 24, 50 |
| D10 | Blog drafts | `_blog/` moves; every asset is re-evaluated (keep, delete, or port); needed Python is ported to TS. | Item 24 |
| D11 | Sphinx retirement and rollback | Sphinx rollback retention is waived at cutover; rollback until removal means moving the domain back. Sphinx is retired at cutover. | Items 01, 40, 50 |
| D12 | Publication scope | All of dlv2-62 is in this batch. | Item 51 |
| D13 | Runner pool | The runner-pool decision leaves the batch to a follow-up 30 days after cutover, using receipt queue-time and latency data. | Item 99 |
| D14 | Soundness narrowing first | Narrow the soundness paths before deleting retiring paths, so the deletions need no oracle review. | Item 00 |
| D15 | External links | lychee external-link checks are non-blocking (open or update one issue). | Item 21 |
| D16 | Unrecorded | No D16 wording was found in the plan or tracker. No batch step depends on it. | This ADR |
| D17 | Hosted ruleset edit | The agent may make exactly one hosted-ruleset edit (remove the `landing` context from ruleset 15611785) and no other. | Item 52 |
| D18 | GitHub cleanup | The agent archives (tag) then deletes the `publication` branch, the `publication-attestation` environment, the two publication secrets, and uninstalls the publication App. These are the only GitHub-object deletions the batch may make. | Item 54 |
| D19 | First production deploy | The owner approves the first production deploy live in chat before `SITE_DEPLOY_TARGET=production` is set. | Item 40 |
| D20 | Second review | Proceed with the muse review alone; run agy first in the batch. Spent 2026-10-07: agy hit quota 429 twice, the owner declined the codex substitute and chose to skip. | agy-plan-review item |

## Language rule

No Python source in the site repo, no JS/TS source in core. Run-time
third-party tools are allowed. The site-inputs bundle schema uses integer
majors; the site supports N and N-1 for one release; core lands first.

## Supersessions

- `_project/decisions/single-repo-migration.md`, in part: its A3 tree split
  places `landing/`, `website/` and `deploy/` on `main`. Those paths leave core
  under this ADR; the `main`-is-released-code rule is unchanged.
- `_project/decisions/adr-astro-unified-site.md` D12, D13 and D14, where they
  conflict: D12 plugs the site into the dlv2-60 plane (replaced by the bundle
  plus the Node plane); D13 describes the renderer cutover (done; this batch
  cuts over repositories, not renderers); D14 overlaps comment-cleanup items
  with `astro-site-*` items (those items are folded by `site-split-01`).
- `docs/development/adr/adr-independent-publication-authorities.md`:
  superseded by this ADR for the site and deploy control-plane scope. Its
  corpus authority statements stay normative until `site-split-51` re-homes
  them; that item applies the superseded marker. `scripts/check_decision_records.py`
  keeps enforcing the record set until then.

## Consumers appendix

Core tests that consume site behavior and therefore constrain the split. The
plan cited 35; verification at `d076a974d` found 40 direct consumers (plus
wiring-only references, excluded). `site-split-50` re-points or deletes each.

Site deploy plane: `tests/unit/scripts/site_deploy/test_site_deploy_candidate.py`,
`test_site_deploy_cli_flow.py`, `test_site_deploy_cli.py`,
`test_site_deploy_gates.py`, `test_site_deploy_generation.py`,
`test_site_deploy_githubapi.py`, `test_site_deploy_mixed_version.py`,
`test_site_deploy_publish.py`, `test_site_deploy_receipt.py`,
`test_site_deploy_renderer.py`, `test_site_deploy_routes.py`,
`site_deploy_fakes.py`, `tests/unit/scripts/test_site_inventory.py`,
`test_site_parity.py`, `test_assemble_public_site.py`,
`tests/unit/workflows/test_site_deploy.py`, `test_site_parity_workflow.py`.

Site content and contracts: `tests/unit/scripts/test_blog_content_validation.py`,
`tests/unit/test_site_header_parity.py`,
`test_public_site_theme_contract.py`,
`tests/unit/landing/test_landing_quickstarts.py`,
`tests/unit/explorer/test_benchmark_labels_coverage.py`,
`test_local_result_version_parity.py`, `test_results_explorer_audit_manifest.py`,
`tests/unit/scripts/explorer_pipeline/test_duckdb_browser_contract.py`,
`test_duckdb_builder.py`, `test_duckdb_readonly_fuzz.py`,
`test_legacy_artifact_guard.py`, `test_pipeline.py`, `test_read_model_contract.py`,
`tests/unit/scripts/test_explorer_build_contract.py`,
`test_explorer_receipt_ui_contract.py`,
`test_results_explorer_corpus_migrate.py`,
`test_results_explorer_cpu_attestation_backfill.py`,
`test_results_explorer_snapshot_invariants.py`,
`test_scan_explorer_stale_theme.py`,
`tests/unit/scripts/publication/test_check_explorer_compat.py`,
`tests/unit/workflows/test_results_explorer_publication.py`,
`test_results_explorer_dependency_audit.py`, `test_website_dependency_audit.py`,
`test_public_site_visual_workflow.py`, `test_publication_preview.py`,
`test_publication_rollback.py`, `test_corpus_cutover.py`.

Cross-surface pins: `tests/unit/cli/test_logo.py`,
`tests/unit/core/test_benchmark_api_contract.py`,
`tests/unit/docs/test_api_reference_contract.py`,
`tests/unit/core/tuning/test_tuning_mode_vocabulary.py`,
`tests/uat/test_explorer_smoke.py`, `tests/uat/phases/explorer_smoke.py`.

## Soundness narrowing (D14)

This ADR's companion change narrows `.github/soundness-paths.txt` before any
retiring path is deleted:

- `prefix .github/workflows/` becomes a regex that matches every workflow
  except `docs.yml`, `publication-*.yml` and `rehearse-release-isolation.yml`.
- The `file` lines for the excluded workflows and the missing
  `publication-lane-docs.yml` / `publication-lane-explorer.yml` are removed,
  as is the `verify_lane_isolation.py` entry (its only user retires).
- `prefix publication/` and `prefix scripts/publication/` become `file` entries
  for the nine corpus files with surviving users: `publication/ledger-seed.json`
  and `scripts/publication/assembler.py`, `check_artifact_privacy.py`,
  `check_corpus_bijection.py`, `check_explorer_compat.py`, `compare_db_digest.py`,
  `reconciler.py`, `validator_parity.py`, `verify_live.py`. Each is imported or
  shelled-out by a surviving workflow (`ci.yml`, `site-deploy.yml`,
  `corpus-reconciler.yml`, `sync-results-data-to-published.yml`,
  `validate-submission.yml`) or a surviving module under `scripts/site_deploy/`.
- `verify_corpus_promotion.py` and `verify_shadow_site.py` have no surviving
  workflow or module user (verified by repo-wide import search); they retire in
  `site-split-51` and receive no entries.
