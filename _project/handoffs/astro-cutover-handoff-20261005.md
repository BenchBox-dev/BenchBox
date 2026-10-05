# Handoff: switch benchbox.dev from Sphinx to Astro (cutover)

**Date:** 2026-10-05
**Repo:** BenchBox-dev/BenchBox, base `develop`
**Owner:** joeharris76. The owner has authorized the cutover and approval of the
`github-pages` deployments. Confirm the authorization in your own session before
any production action; an earlier session's auto-mode classifier blocked the
`deploy/routes.yml` flip as a production deploy.

## Goal

Production benchbox.dev is served by `.github/workflows/site-deploy.yml` with the
Astro renderer for every route. Sphinx stays available as the rollback target.

## State at handoff

- **Merged:** PRs #2606, #2649, #2656 and #2671. They provide:
  - the Astro site in `website/`;
  - the parity harness;
  - the Astro visual capture;
  - single-renderer site-deploy with mixed-renderer refusal and the pre-deploy visual comparison;
  - the old writers stopped (`docs.yml` no longer deploys; the publication monitors are dispatch-only).
- **Disabled in GitHub settings:** `publication-deploy`, `publication-transaction`,
  `publication-preview-deploy` and `publication-corpus-cutover`.
  `publication-deploy` (last green run 37212040468) is the manual fallback.
- **Preview:** site-deploy preview run 37309597955 passed.
- **Bootstrap production deploy:** run **37332041883** (Sphinx, `mode=deploy`, `bootstrap=true`).
  - Build and gates passed.
  - `github-pages` was approved at 15:48 UTC.
  - At handoff the `deploy` job was still **queued waiting for a runner**: Nightly Validation 37301643110 had held runners since 11:14 UTC.
  - Confirm it finished: the deploy and probe jobs are green, a `site-deploy-receipt-*` artifact exists, and the newest `github-pages` deployment status carries the receipt digest.
  - If it is stuck, ask the owner whether to cancel the nightly runs.
- **Release:** v0.4.2 is released and its tag meets the Astro readiness definition
  (full `website/`, no `.rst` under `docs/`; see `docs/operations/site-deploy.md`
  "Renderer"). No new release is needed.
- **Policy:** `deploy/routes.yml` pins `renderer: sphinx` on develop.

## Steps

1. **Bootstrap receipt.** Verify run 37332041883 completed with a receipt (above). The first Astro deploy is refused without a receipted generation, because the visual comparison needs it as the baseline.
2. **Cutover PR**, on a branch from develop:
   - `deploy/routes.yml`: change `renderer: sphinx` to `renderer: auto`.
   - `tests/unit/scripts/site_deploy/test_site_deploy_renderer.py`:
     - `test_the_committed_policy_selects_sphinx_for_any_release_tag`: assert the policy is `renderer.POLICY_AUTO`, `v0.4.1` selects Sphinx and `v0.5.0` selects Astro.
     - `test_committed_manifest_pins_sphinx_until_the_cutover_change`: the first assert becomes `== renderer.POLICY_AUTO`. Keep the `del data["renderer"]` default assert as `SPHINX`.
     - `test_resolve_with_the_committed_manifest_stays_on_sphinx_for_a_ready_release`: expect `renderer.ASTRO` and policy `renderer.POLICY_AUTO`, and rename it.
   - Run `uv run -- python -m pytest tests/unit/scripts/site_deploy tests/unit/workflows tests/system -q -n auto`.
   - Optional, same PR: fold in the open Low findings from the #2656 stand-in review:
     - check trunk readiness at the resolved trunk SHA in `assemble_public_site.py`, as `cli` does;
     - note in the runbook that unmarked redirect stubs are refused in Astro artifacts.
   - Record the parity sign-off in `_project/decisions/astro-parity-signoff.md`:
     - use the `site-parity` CI report on the PR head;
     - the owner approved the allowances on 2026-10-04;
     - the cutover base SHA is the PR's merge base.
3. **oracle-review.** `deploy/` and `scripts/site_deploy/` are soundness paths, and the Codex connector is out of quota.
   - Get an independent stand-in review of the exact head; a subagent that did not write the change will do.
   - The owner then posts a PR comment whose **whole body** is exactly `Stand-in oracle review: APPROVE <full head SHA>`. Any extra text or footer fails `_STANDIN_MARKER.fullmatch`, and edited comments don't count.
   - Re-run the `oracle-review` run for that head. Every push needs a new attestation.
4. **Visual approval rehearsal** (closes tracker item `astro-site-21`):
   - The `Public-site visual regression` check is advisory.
   - Set the repo variables `APPROVED_HEAD_SHA=<PR head>` and `APPROVAL_REASON=<note>` (`gh variable set ...`), re-run that job, record the run ids in the ADR visual-change section, then clear both variables.
   - The current variables name an old PR's SHA (d4db5c3a…).
5. **Merge.** Auto-merge (squash) fires once the required checks pass: core, explorer, results-data, docs, landing, tooling and oracle-review.
6. **First Astro deploy.**
   - Dispatch `gh workflow run site-deploy.yml --ref develop -f mode=preview`, check it, then dispatch `-f mode=deploy`.
   - The resolve step selects Astro.
   - The pre-deploy visual comparison fails until the owner sets `SITE_DEPLOY_VISUAL_APPROVED_BINDING=<release_sha>+<candidate sha256>+<baseline sha256>` (printed by the job's `visual-binding` step, also in `visual-binding.json`) and `SITE_DEPLOY_VISUAL_APPROVAL_REASON`, then re-runs it.
   - Approve `github-pages`: `gh api -X POST repos/BenchBox-dev/BenchBox/actions/runs/<id>/pending_deployments -f "environment_ids[]=<id>" -f state=approved -f comment=...`.
   - Verify: the probes are green, the receipt has `renderer: astro`, and `/`, `/docs/`, `/docs/dev/`, `/blog/` and `/results/` all serve.
7. **Rollback, if needed.** Dispatch `-f mode=rollback -f rollback_receipt_run_id=37332041883`, then set `renderer: sphinx` again before the next forward deploy.

## After the cutover (tracker)

- **Finish:** `astro-site-21`, `22`, `33`, `34`, `35`, `36`, `40`, `50`, `51`, `52`, `53` once each item's acceptance is verified. Their contexts carry the evidence.
- **dlv2-62:**
  - a second deploy, a rollback drill and a forward deploy;
  - the ledger PR;
  - deleting the publication workflows and scripts. Keep or move the files site-deploy still uses: `scripts/publication/assembler.py`, `verify_live.py`, `publication/ledger-seed.json`, the `check_*` scripts, and the files used by `corpus-reconciler.yml` and `rehearse-release-isolation.yml`;
  - owner deletions: the `publication` branch (archive-tag it first), the `publication-attestation` environment, the `PUBLICATION_APP_*` secrets and the publication App.
- **Later:** `astro-site-54` (retire Sphinx, evidence-based), `60`, `61` and `dlv2-61`.

## Environment notes

- `gh` works for REST (`gh api ...`, `gh run`, `gh workflow`).
- GraphQL is blocked. Use the `/ccr/` routes for review threads and auto-merge, or the GitHub MCP tools.
- Artifact and log blob downloads (`gh run download`, `/logs`) are blocked by the proxy. Read logs with the MCP `get_job_logs` tool.
- benchbox.dev itself is unreachable from the sandbox (proxy 403), so verify through the probe job.
- Commits use author Joe Harris <joeharris76@gmail.com> with no `Co-Authored-By` or session trailers; a hook rejects them. Use `SKIP=markdownlint` (the hook's node env is broken) and run markdownlint by hand.
- `AGENTS.md`: no explanatory code comments, no work-item labels in committed files, `.PHONY` directly above each make rule.
