# Handoff: split the public site into its own repo

Date: 2026-10-06. Base: `origin/develop` at `f10ebb1cb`.
Owner: Joe Harris (`joeharris76`). Commit as `Joe Harris <joeharris76@gmail.com>`.

## Goal

Move every site asset out of `BenchBox-dev/BenchBox` (core) into a new repo,
`BenchBox-dev/benchbox-site` (site). benchbox.dev must stay up, keep its URLs,
and keep its deploy receipts and rollback.

When the split is done:

- The site repo builds and deploys benchbox.dev without Python and without
  importing `benchbox`. The deploy control plane is the only exception until
  Phase 5.
- Core holds no Astro, Explorer UI, landing, blog, or deploy code. Core makes
  one versioned **site-inputs bundle**. The site repo consumes that bundle.
- Sphinx is gone from both repos.

## Where things stand

- **The Astro cutover is done.**
  - `deploy/routes.yml` has `renderer: auto`.
  - Every route uses `ref: trunk`. The `release` ref is defined but unused
    (#2702 skips release builds).
  - The last `site-deploy.yml` run, 37406123669, succeeded.
- **Sphinx is still wired as a fallback.** It appears in:
  - `site-deploy.yml` L166-209;
  - `scripts/site_deploy/renderer.py` and `gates.py`;
  - `docs.yml`, `ci.yml` `docs-build`, and `nightly-v2.yml` linkcheck;
  - `docs/conf.py`, `_templates/`, `_static/`, `_extensions/`;
  - the `docs` extra and the dev group in `pyproject.toml`;
  - `tox.ini [testenv:docs]`.
- **The legacy publication Pages writers are disabled, not deleted.** These
  are `publication-deploy`, `-transaction`, `-preview-deploy` and
  `-corpus-cutover`. The other `publication-*` workflows only probe the site.
- **The site repo does not exist yet.** `list_repos` shows only core and an
  archived private repo.
- **One branch is still open.** `claude/bold-newton-uudn48` holds the cutover
  handoff (`astro-cutover-handoff-20261005.md`) plus this file. No PR is open
  for it. Reconcile tracker items 21 and 50-53, and dlv2-62, with Phase 0.
- **Size:** about 870 tracked files move. The largest parts are `results-explorer/`
  (338 files), `website/` (231), `_blog/` (168), and `docs/blog/`.

## The coupling, in one paragraph

The Astro app never imports `benchbox`. The coupling comes from four places:

1. **Generated content.** Scripts that import `benchbox` write site content:
   - query docs (`generate_query_docs.py`, gitignored output);
   - the compat matrix (`generate_compat_docs.py`);
   - the landing prompt catalog (`generate_landing_quickstarts.py`);
   - `adding-new-platforms.md` (`_project/scripts/platform_manifest.py`);
   - the Explorer snapshot `results.duckdb` (`_project/scripts/explorer_publish.py`
     plus `explorer_pipeline/*`);
   - the Explorer test fixtures (`results-explorer/scripts/*.mjs` call
     `uv run python`).
2. **Reads outside `website/`.** `astro.config.ts:18` sets `repoRoot = ..` and
   reads from it:
   - `docs/`, `docs/CNAME`, `docs/blog/images`;
   - `landing/shared/*.css`, `landing/hero.png`;
   - `results-explorer/dist`;
   - `pyproject.toml` (the version);
   - `_project/design/site-inventory/`.

   In addition, `src/converter/handlers/links.ts:35-75` `stat`s every docs link
   that points outside `docs/`. There are about 1,058 such links into
   `benchbox/` and 45 into `examples/`, and a missing file fails the build.
3. **Git and Actions state of core.**
   - `site_deploy/candidate.py` reads core `v*` tags and requires a green
     `trunk.yml` push run on `develop`.
   - `renderer.py` inspects the release tree.
   - `gates.py:117` reads `results-data` at a SHA.
4. **Deploy gates that import `benchbox`.**
   - `explorer_compat_gate` runs `scripts/publication/check_explorer_compat.py`,
     which uses `explorer_pipeline.contract`.
   - `corpus_bijection_gate` runs `check_corpus_bijection.py`, which uses
     `explorer_pipeline.transformer`.
   - `explorer_compat` is also a rollback gate (`gates.py:301`).

## Target architecture

```
core (BenchBox-dev/BenchBox)                site (BenchBox-dev/benchbox-site)
  benchbox/ package                           website/      Astro app
  docs/**.md  (source, edited with code)      explorer/     ex results-explorer
  results-data/ corpus + corpus workflows     landing/      theme, hero, landing page
  generators that import benchbox             blog/         ex _blog + docs/blog
  explorer_pipeline (snapshot + fixtures)     deploy/       routes.yml, control plane
  site-inputs.yml  ──bundle + dispatch──▶     inventory/    ex _project/design/site-inventory
                                              site-deploy.yml, CI, Pages, github-pages env
```

### The site-inputs bundle (the one contract)

Core builds it with `make site-inputs OUT=<dir>` and uploads it as
`site-inputs-<core_sha>.tar.zst`. Its `manifest.json` has:

- `schema` (an integer major version) and `core_sha`;
- `package_version` (replaces the `pyproject.toml` read);
- `certified_by` (the `trunk.yml` run id);
- a sha256 per member.

Members:

| Member | Producer (stays in core) | Replaces |
|---|---|---|
| `docs/` tree, with generated query and compat docs in place; `docs/blog/` and `docs/CNAME` excluded | `docs-generate` minus the image checks | `../docs` reads |
| `repo-files.txt`: every tracked path at `core_sha` | `git ls-files` | the `links.ts` `stat` check and `check_doc_relative_links.py` |
| `explorer/results.duckdb`, `explorer/contract.json` (schema, tuning vocabulary, `browser-duckdb-schema.sql`) | `explorer_publish.py build` / `build-contract` | `uv run` in the explorer scripts; the `explorer_compat` gate |
| `explorer/fixtures/` (browser fixture DBs) | the fixture generator, ported to Python in core | `generate-browser-fixtures.mjs:798` and `verify-browser-fixtures.mjs:201` |
| `landing/prompt-catalog.json` | `generate_landing_quickstarts.py`. `catalog.yaml` stays in core next to it | `catalog.generated.js` |
| `api-public-symbols.json` | `check_api_contract_symbols.py` | `_project/design/site-inventory` copy |
| `attestations.json`: `corpus_bijection` and `explorer_compat` results with input digests | the two gates, run in core | the `benchbox`-importing site gates |

**Delivery.**

- `site-inputs.yml` in core runs on `workflow_run` of a successful `trunk.yml`
  push on `develop`. It uploads the bundle as an Actions artifact with 90-day
  retention.
- It then sends `repository_dispatch` (`core-bundle`) to the site repo with
  `core_sha`, the artifact id and the digest.
- The site repo downloads the bundle with a GitHub App token that has
  `actions:read` and `contents:read` on core. Use a dedicated app; do not reuse
  the oracle app.
- Rejected alternative: a rolling prerelease asset in core. It needs no token,
  but it pollutes the releases list that the release tooling and
  `get_latest_release` read.

**The site repo verifies the bundle before use.** It checks that:

- the digest matches;
- `schema` is a major version it supports;
- `certified_by` names a successful `trunk.yml` run on `core_sha`. This
  replaces `candidate.py`'s same-repo lookup. Core is public, so a read of its
  runs needs only the app token.

**Receipts.** Receipts record `core_sha`, the bundle digest and the site SHA.
Rollback redeploys a prior *site* artifact and re-checks it against its
recorded `attestations.json`. It never needs core or `benchbox`.

## Decisions (confirm with the user before the phase that needs them)

| # | Decision | Recommendation | Why | Needed by |
|---|---|---|---|---|
| D1 | Where do user docs (`docs/**.md`) live? | **Keep them in core.** The site pulls them via the bundle | About 30% of recent docs commits also touch `benchbox/`. About 20 core tests lock code against doc text (`test_cli_documentation`, `test_quickstart_commands_are_real`, `test_platform_registry`, `test_run_surface_contract`, and others). `README.md` has 27 relative `docs/` links. `benchbox/utils/version.py:61` reads `docs/README.md`. Moving the docs means two-repo PRs and cross-repo contract tests | Phase 1 |
| D2 | Repo name and visibility | `BenchBox-dev/benchbox-site`, public | Pages on the org plan; same posture as core | Phase 2 |
| D3 | Rehearsal host | Add a `next.benchbox.dev` CNAME (needs DNS access) and point it at the site repo's Pages before the cutover | A project Pages URL (`/benchbox-site/` subpath) breaks the root-absolute links, so it cannot rehearse faithfully | Phase 3 |
| D4 | Port the Python deploy control plane (`site_deploy`, `assemble_public_site`, `site_parity`, `site_inventory`, privacy check; about 4k lines plus tests) to TypeScript now or later | **Later (Phase 5).** Move it as-is, with `uv` + PyYAML only and no `benchbox` | Porting the receipt and rollback logic during a repo and domain move stacks two risks | Phase 2 |
| D5 | Should core PRs that touch `docs/` be gated on a site build? | **Yes.** Add a required `site-compat` job in the core `docs` unit. It builds the bundle and runs the site build at the SHA pinned in `.github/site-ref` (Node only) | Without it, a docs PR merges green and then breaks the next deploy | Phase 4 |
| D6 | Deploy trigger in the site repo | Keep **dispatch-only with a required reviewer**, as today. Resolve to the newest certified bundle. Auto-deploy on `core-bundle` is a follow-up | Auto-deploy with a reviewer means an approval on every trunk merge. Auto-deploy without one is a policy change | Phase 3 |

## Phases

Each phase is one PR (Phase 2 is two: one per repo). Each has to be green and
merged before the next starts. Delegate the mechanical parts to Sonnet workers.
Keep review and coordination on Opus. Use explicit-path staging; never
`git add -A`.

### Phase 0: core clean-up (single repo, no behavior change on Astro)

This removes most of the Python before anything moves.

1. Delete the Sphinx path:
   - `site-deploy.yml` sphinx steps; `renderer.py` and its tests; the `SPHINX`
     uses in `gates.py`;
   - the `renderer:` key in `routes.yml` and its parser;
   - `docs/conf.py`, `Makefile`, `make.bat`, `_extensions/`, `_templates/`,
     `_static/` (keep any image an Astro page still references; grep the
     converter output), `_tags/`, `script.js`, `style.css`;
   - `linkcheck_ignore.txt` and its policy test;
   - in `docs.yml`, the sphinx and linkcheck jobs (move the example-validation
     and codespell jobs to `ci.yml` if `docs.yml` empties);
   - `ci.yml` `docs-build` and `nightly-v2.yml` linkcheck;
   - the `docs-build`, `docs-serve`, `docs-linkcheck` and `site-parity-sphinx`
     targets in `make/documentation.mk`, and `ci-docs`/`ci-linkcheck` in the
     `Makefile`;
   - `tox.ini [testenv:docs]`;
   - the `docs` extra and the Sphinx stack in the `dev` group (keep
     `pygments`/`markdown-it-py` if other code imports them), then regenerate
     `uv.lock` with `uv lock`;
   - `tests/docs/test_sphinx_warnings.py`, `tests/unit/docs/test_docs_build.py`,
     and the conf.py parts of `test_docs_generate_wiring.py`.

   **Linkcheck needs a replacement:** add an external-link check to the Astro
   build, or accept losing it. Ask the user.
2. Delete the retired publication Pages writers and their tests:
   - workflows `publication-deploy`, `-transaction`, `-preview-deploy`,
     `-recover`, `-preview-soak`, `rehearse-release-isolation`;
   - `tests/unit/workflows/test_publication_*` and `test_release_isolation`,
     plus the scripts only they call.

   Keep the probes (`publication-canaries`, `-soak-monitor`) for now; they move
   in Phase 2. Keep `publication-corpus-cutover` (corpus lane). After the
   deletes, remove the `publication-attestation` environment and the
   `PUBLICATION_ATTESTOR_PRIVATE_KEY` secret (the user does this in the UI).
3. Drop the unused `release` ref:
   - `routes.yml` `refs.release`, the release checkout in `site-deploy.yml`
     L132-157, and the release-tag logic in `candidate.py` and `mixed_version`;
   - `check_release_curation.py` `REQUIRED_RELEASE_PATHS` entries for `website`
     and `results-explorer`;
   - the `git rm _blog` step in `make release-cut`, only if `_blog` is no
     longer on the release tree after Phase 4.
4. Fix stale items:
   - `soundness-paths.txt` L77-78 (workflows that don't exist);
   - `pyproject.toml` `Documentation` URL → `https://benchbox.dev/docs/`;
   - `index.html` at the repo root (a stub; delete it after confirming nothing
     reads it).
5. Keep the ledgers in sync: `tests/unit/ledger_cutover_files.txt` and
   `docs/development/dev-loop-property-ledger.md` (enforced by
   `test_ledger_coverage.py`). Same for `.github/path-filters.yml`,
   `.github/ci-units.yml`, `scripts/path_filter_decision.py`, and the
   path-filter tests.

**Done when:** CI is green; a `site-deploy` preview passes; no `sphinx` string
remains outside `CHANGELOG.md` and `_project/`. Since this touches
`site_deploy/` and workflow files, oracle-review applies. The user must post the
stand-in attestation (exact body, no footer).

### Phase 1: draw the boundary inside core (still one repo)

This proves the contract while rollback is still trivial.

1. Add `make site-inputs OUT=<dir>`. It produces the bundle described above;
   its manifest schema is 1. Port the Explorer fixture generation (the inline
   Python in `generate-browser-fixtures.mjs` and `verify-browser-fixtures.mjs`)
   into a core Python entry point under `_project/scripts/explorer_pipeline/`.
   Move the fixture *inputs* next to it if they are Python-pipeline inputs.
2. Make `website/` and `results-explorer/` read only from `$SITE_INPUTS` (or
   from their own dir):
   - `astro.config.ts`: version from the manifest; docs root and repo-files
     from the bundle;
   - `links.ts`: look up `repo-files.txt` instead of `stat`, and pin the GitHub
     URLs to `core_sha` (not `develop`) so links stay true;
   - `edit-url.ts`: docs → core `develop`; blog and site pages → site repo;
   - `prompt-catalog.ts`: read the JSON;
   - the explorer scripts: no `uv run`, and use the bundle's fixtures and
     contract;
   - `e2e/not-found.mjs:48-51`: drop the `python3 -c` call and read
     `RESULTS_FALLBACK` from a JSON export;
   - `scripts/audit-high.mjs` and the CSS imports from `landing/shared` (fine
     for now; `landing/` moves too).
3. Run the `explorer_compat` and `corpus_bijection` gates in the bundle step.
   Write `attestations.json`. In `site_deploy/gates.py`, replace both gates
   with checks that the attestation digests match the deployed snapshot.
   `rollback` keeps a pure-digest `explorer_compat` check.
4. Add a guard test, `tests/unit/scripts/test_site_boundary.py`. It fails if
   any file under `website/`, `results-explorer/`, `landing/` or `deploy/`
   references `..` outside those dirs, `uv`, `python`, or `benchbox/`, apart
   from an explicit allowlist that Phase 2 empties.
5. Change `site-deploy.yml` `build` to: `make site-inputs` → Node-only site
   build from the bundle. The deploy output must be byte-identical to Phase 0
   apart from the edit-link and source-link URL changes. Prove it with the
   parity gate and a tree diff in the PR.

**Done when:** a preview and one production deploy from the new build pass
the probes, and the receipt carries the bundle digest.

### Phase 2: create the site repo and run it in shadow

1. **The user creates `BenchBox-dev/benchbox-site`** (D2), or you do, if
   `mcp__github__create_repository` has org rights. Then:
   - install the Claude GitHub App on it and add it to the session (`add_repo`);
   - create the bundle-reader GitHub App and store its id and key as site repo
     secrets.
2. Seed it with history: `git filter-repo` on a fresh clone of core. Keep
   `website/`, `results-explorer/`, `landing/`, `_blog/`, `docs/blog/`,
   `docs/CNAME`, `deploy/`, `_project/design/site-inventory/`,
   `scripts/site_deploy/`, `scripts/assemble_public_site.py`,
   `site_inventory.py`, `site_parity.py`, `scripts/publication/check_artifact_privacy.py`
   (and whatever it imports), the site tests listed in the appendix, and
   `.github/workflows/site-deploy.yml`. Rename the paths per the target diagram
   with `--path-rename`. Push to `main`.
3. Bootstrap the site repo:
   - `AGENTS.md` and `CLAUDE.md`, and a `pr` skill (main-only, squash);
   - pre-commit (markdownlint, codespell, yaml, whitespace, and the
     agent-trailer hook);
   - `package.json` workspaces for `website` and `explorer`;
   - `uv` + `pyproject.toml` for the control plane only;
   - CI: `astro check`, vitest, the explorer unit tests, e2e (`verify:*`),
     parity, the visual workflow, the `audit:high` nightly (from `nightly.yml`
     L705-737), and the control-plane pytest;
   - a ruleset with required checks;
   - `soundness-paths.txt` entries moved from core L11-18, L73-83 and L121,
     with an oracle-review gate if the user wants one (ask);
   - environment `github-pages` with required reviewer `joeharris76` and the
     `main` branch policy;
   - variables `SITE_DEPLOY_VISUAL_APPROVED_BINDING`/`_REASON` and
     `APPROVED_HEAD_SHA`/`APPROVAL_REASON`;
   - Pages source "GitHub Actions", with **no** custom domain yet.
4. Core PR: add `site-inputs.yml` (bundle plus `repository_dispatch`). The
   dispatch needs a token with `contents:write` on the site repo; use the same
   app, installed on both.
5. Site repo `site-deploy.yml`:
   - `preview` mode works against the newest certified bundle;
   - `deploy` mode is wired but blocked by a `vars.SITE_REPO_LIVE != 'true'`
     guard;
   - replace hardcoded `BenchBox-dev/BenchBox` in API calls with
     `vars.CORE_REPO`.
6. Shadow: for one week, every core deploy also triggers a site repo preview.
   Diff the two artifacts; they must be identical apart from known-allowed
   paths. Record the results in `docs/operations/site-deploy.md` (core) and the
   site repo `README`.

**Done when:** three consecutive shadow previews match, and site repo CI is
green on `main`.

### Phase 3: Pages cutover (needs the user present)

1. Rehearse on `next.benchbox.dev` (D3):
   - deploy for real from the site repo;
   - run the probes and the visual job against it;
   - check `CNAME` handling: the bundle no longer ships `docs/CNAME`; the site
     repo owns `CNAME`, and must write the *rehearsal* host during rehearsal.
2. Freeze: disable core `site-deploy.yml` via `gh workflow disable`. Leave core
   Pages and its last deployment in place; that is the rollback.
3. Move the domain:
   - remove `benchbox.dev` from core Pages and add it to site repo Pages;
   - wait for the TLS cert, then enforce HTTPS;
   - set `SITE_REPO_LIVE=true`;
   - dispatch a production deploy from the site repo (the user approves it in
     the UI; this session's token gets a 403 on `pending_deployments`).

   The domain is verified at the org, so no new TXT record is needed. Confirm
   in org settings; this proxy blocks the API path. Expect a few minutes of 404
   or a cert warning, so pick a low-traffic window. The rollback is to move the
   domain back and re-enable core's workflow.
4. Verify:
   - probes are green; a receipt exists with `core_sha` and the bundle digest;
   - spot-check `/`, `/docs/`, `/blog/`, `/results/`, `404.html`,
     `objects.inv`;
   - the old `.html` URLs that the CLI prints still resolve:
     `cli/app.py:30`, `onboarding.py:99`, `submit.py:72,99,500`,
     `submit_service.py:17`.
5. Move the probe workflows (`publication-canaries`, `-soak-monitor`) to the
   site repo, or delete them if `site-deploy` `probe` covers them. Hardcoded
   `benchbox.dev` URLs are fine.

**Done when:** the site repo has served production for 48 hours with green
probes and one practiced rollback (to a prior *site* receipt).

### Phase 4: remove the site from core

One PR. Large, but almost entirely deletes.

1. **Delete:**
   - `website/`, `results-explorer/`, `landing/` (except `prompts/catalog.yaml`),
     `_blog/`, `docs/blog/`, `docs/CNAME`, `deploy/`,
     `_project/design/site-inventory/`;
   - the site scripts and tests (see the appendix);
   - `site-deploy.yml`, the site jobs in `ci.yml` (L1544-2068: theme tokens,
     visual inputs, visual regression, site-build, site-parity, astro dry-run),
     and `nightly.yml` `website-audit`;
   - the `site-*` make targets and `lint-site-theme-tokens`/`lint-explorer-*`;
   - the MANIFEST.in prune lines for removed dirs.
2. **Keep and re-point:**
   - the generators (they now write only into the bundle dir or `docs/`);
   - `explorer_pipeline`;
   - `make site-inputs`;
   - the code-to-docs contract tests (docs stayed, per D1);
   - `benchbox/core/tuning/modes.py`: its comment naming the TS vocabulary test
     now points at `explorer/contract.json` in the bundle, plus the site repo
     test.
3. **CI contexts.** The `landing` unit goes away, and `docs` shrinks to: docs
   markdown, generators, contract tests and `site-compat` (D5).
   - Update `ci-units.yml`, `path-filters.yml`, `path_filter_decision.py`,
     `ci_units.py` and their tests.
   - Update `ruleset_drift_check.py` `APPROVED_MERGE_QUEUE_CONTEXTS` and
     `docs/operations/repo-admin-settings.md` in the **same** PR.
   - The user removes the `landing` context from hosted ruleset 15611785
     **right after** the merge. Until then, keep a stub `landing` aggregator
     that passes, so the merge queue doesn't deadlock. Delete the stub in a
     follow-up.
4. **Ledgers and soundness:** `ledger_cutover_files.txt`, the dev-loop
   ledger, and `soundness-paths.txt` (site entries out),
   `oracle-reviewers.yml` L131.
5. **Docs and agent surfaces:**
   - `AGENTS.md`, `CONTRIBUTING.md` and `.claude/skills/*` gain one line: site
     code lives in `BenchBox-dev/benchbox-site`; docs source stays here;
   - `docs/operations/site-deploy.md` → a stub pointing to the site repo, or
     move it;
   - `docs/operations/github-org-transfer.md` gets the new Pages owner.
6. **Release:** `check_release_curation.py` and the release guide no longer
   ship site dirs. The "dispatch site-deploy after release" step points at the
   site repo.

**Done when:** core CI is green; `grep -rn "website/\|results-explorer/\|landing/shared" --include=*.py --include=*.yml --include=*.mjs`
returns nothing outside `CHANGELOG.md` and `_project/`; and a docs-only core
PR passes `site-compat`, which proves the site still builds from it.

### Phase 5: remove Python from the site repo (optional, per D4)

Port `site_deploy`, `assemble_public_site`, `site_parity`, `site_inventory`
and `check_artifact_privacy` to TypeScript under `deploy/`, with the receipt
format unchanged (receipts must stay readable for rollback). Port the tests
first and run old and new side by side for one deploy cycle. Then delete
`pyproject.toml` and `uv.lock` from the site repo.

## Second-order effects to watch

- **Docs PRs break the site after merge.** Without D5, a docs edit with a bad
  MyST directive merges green in core and fails the next site deploy. Bump
  `.github/site-ref` with a bot PR from the site repo on every `main` merge,
  so `site-compat` tests against the current site.
- **Contract drift between repos.** Any bundle change needs a `schema` bump
  under these rules:
  - additive changes stay on the same major;
  - removals or renames bump the major;
  - the site supports N and N-1 for one release.

  The order is always core first, then the site. Write this into both
  `AGENTS.md` files.
- **Links into core code.** Source links in generated query docs (about 1,050)
  and ADRs must be pinned to `core_sha` blob URLs. Links to `develop` rot when
  files move. `repo-files.txt` validates them at build time.
- **The edit-this-page target splits by section.** Docs pages go to core;
  blog pages go to the site repo. Test both.
- **Corpus stays in core.** None of these change:
  - the `benchbox submit` instructions (`cli/commands/submit.py`);
  - `validate-submission*`, the `corpus-*` workflows, `seed-corpus`,
    `sync-results-data-to-published` and the `published-results` branch.

  `/results/` freshness now depends on core's `site-inputs.yml` running after
  certification. A results-data merge needs a site deploy to appear, same as
  today.
- **Artifact retention.** Bundles expire after 90 days. Rollback must use site
  artifacts, which carry everything, and never re-fetch a core bundle. Check
  that the site repo's own artifact retention covers the rollback window.
- **Approvals.** This session cannot approve `github-pages` deployments (403),
  so every production deploy in the site repo needs the user in the UI. Plan
  Phase 3 with them present.
- **Tooling scope.** Agent sessions are scoped per repo. Cross-repo work needs
  `add_repo` on the site repo, and the Claude GitHub App installed there. Some
  org API paths are blocked by this proxy, among them Pages config and domain
  verification; the user checks those in the UI.
- **Search and SEO.** The URLs are unchanged, so there is no redirect work.
  `objects.inv` keeps serving from the bundle version.
- **Duplicated registry facts.** `website/src/lib/landing-data.ts` hand-copies
  platform and benchmark cards with no drift check. Either move those facts
  into `prompt-catalog.json` in Phase 1, or file a follow-up.
- **The theme crosses the boundary.** The explorer UI imports
  `landing/shared/*.css`, but both move together, so this is fine. The
  `explorer-tokens` pre-commit hook in core must drop
  `landing/shared/site-tokens.css`.

## Appendix: file lists

**Moves to the site repo:**
`website/**`, `results-explorer/**`, `landing/**` (except `prompts/catalog.yaml`),
`_blog/**`, `docs/blog/**`, `docs/CNAME`, `deploy/routes.yml`,
`_project/design/site-inventory/**`, `scripts/site_deploy/**`,
`scripts/assemble_public_site.py`, `scripts/site_inventory.py`,
`scripts/site_parity.py`, `scripts/api_reference_url_map.py`,
`scripts/blog_content_validation.py`, `scripts/validate_visualization_images.py`,
`scripts/_render_blog_charts.py`, `scripts/capture_release_heroes.py`,
`scripts/_compose_joinorder_hero.py` (snapshot its data input),
`scripts/publication/check_artifact_privacy.py`,
`tests/unit/scripts/site_deploy/**`,
`tests/unit/scripts/{test_site_parity,test_site_inventory,test_assemble_public_site,test_blog_content_validation,test_api_reference_url_map}.py`,
`tests/unit/workflows/{test_site_deploy,test_site_parity_workflow,test_public_site_visual_workflow,test_website_dependency_audit,test_results_explorer_publication}.py`,
`tests/unit/landing/test_landing_quickstarts.py` (the render half),
`tests/unit/{test_site_header_parity,test_public_site_theme_contract}.py`,
`test_visualization_image_scripts.py`, `.github/workflows/site-deploy.yml`.

**Stays in core:**
`benchbox/**`, `docs/**.md` (including `development/`, `agent/`, `operations/`,
`compat/`), `results-data/**`, `publication/ledger-seed.json` and the corpus
`scripts/publication/*`, `_sources/**`, `generate_query_docs.py`,
`generate_compat_docs.py`, `generate_landing_quickstarts.py` plus
`landing/prompts/catalog.yaml`, `_project/scripts/platform_manifest.py`,
`_project/scripts/explorer_publish.py` and `explorer_pipeline/**`,
`check_api_contract_symbols.py`, `generate_corpus_inventory.py`,
`capture_chart_images.py` (outputs to a dir; the author commits the PNGs in
the site repo), `check_doc_relative_links.py` (now resolves against the tree,
which is still local), and the corpus and submission workflows.

**Deleted (Phase 0):** the Sphinx files listed under Phase 0, the retired
`publication-*` workflows and their tests, the `docs` extra, and
`tox [testenv:docs]`.

## Sources

The three inventories behind this plan were run on `f10ebb1cb`. They cover
the build ties, the CI and gates, and the content and refs. Line numbers above
are from that SHA; re-check them before editing.
