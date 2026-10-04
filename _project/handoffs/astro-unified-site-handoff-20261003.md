# Handoff: Unified Astro site for benchbox.dev (astro-site-*) plus its dlv2 prerequisites

**Revision:** 2, 2026-10-03
**Authority:** This file does not grant authority by itself. The user's message that hands it to a session grants that session the write workflow for the item set below, under the standing approvals S1–S4 recorded in tracker item `astro-site-00-decisions-adr` (context field). It does not grant anything those approvals or `AGENTS.md` withhold.

## 1. Objective and item set

Replace the Sphinx docs/blog site and the static landing page with one Astro site that also hosts the Results Explorer. Finish every item below in dependency order, until production is served entirely by Astro and Sphinx is retired. Use the Todo skill's `implement` workflow per item, driven by the coordinator. Do not use `closeout`.

Astro items (23): `astro-site-00-decisions-adr`, `-01-url-content-inventory`, `-02-api-reference-decision`, `-03-visual-change-procedure`, `-10-spike-and-go-gate`, `-20-package-scaffold-and-ci`, `-21-single-design-token-source`, `-22-shared-layout-shell`, `-30-rst-to-myst-in-place`, `-31-myst-to-mdx-converter`, `-32-port-docs-generators`, `-33-blog-collection-and-feed`, `-34-api-reference-implementation`, `-35-landing-and-prompts-port`, `-36-site-metadata-and-404`, `-40-explorer-shell-integration`, `-50-parity-harness`, `-51-visual-gate-transition`, `-52-site-deploy-integration`, `-53-cutover`, `-54-retire-sphinx-and-legacy-site`, `-60-results-embeds`, `-61-results-discovery-pages`.

dlv2 prerequisite chain (in scope per S2): `dlv2-f0-stabilize-queue-and-open-prs` → `dlv2-f3-flip-window` → `dlv2-60-publication-integration` → `dlv2-62-publication-cutover-and-retirement` → `dlv2-61-retire-docs-yml-pages-fallback`. Other dlv2 items are out of scope unless one becomes an unmet need of these.

Each item's description, acceptance and context in the tracker are the specification. This handoff sets order, roles and rules only. If the two conflict, the tracker item wins; record the conflict in the item's context.

Design reference (mockups and evaluation): <https://claude.ai/artifact/J43yBKwtQAbL6d6fTWVfQB>

## 2. Tracker preflight

1. Call `get_instructions` before any tracker write.
2. State remote: `https://github.com/BenchBox-dev/BenchBox.git`, state branch `todo-state` (`.todo-db/config.json`).
3. Read `astro-site-00-decisions-adr` in full, including the context sections (guardrails G-a…G-k and standing approvals S1–S4).
4. Run `list_items(text="astro-site")` and `list_items(text="dlv2")` and reconcile with the state in §3 before claiming anything.
5. Only the coordinator session calls todo-db tools. Subagents never claim, update, prepare or finish items.

## 3. Live state

Live state (claims, branches, PRs, the develop head and the ruleset) lives in the tracker and on GitHub, not in this file. Read it at the start of every session:

- each item's status, `needs` and context (`show_item`), including resumption notes left by earlier sessions;
- open PRs against `develop` and the merge-queue state;
- the live `develop` ruleset's required contexts, which dlv2-f3 changes; re-read them before relying on any.

Some dlv2 item contexts cite `/tmp/HANDOFF-dlv2-*` files on the owner's machine. They may not exist in your environment, so rely on tracker contexts and PR history instead.

## 4. Order and dependencies

The tracker `needs` edges are authoritative. Waves below mark points where work can run in parallel; stay inside one claim at a time (§5.3).

| Wave | Items | Why this order |
| --- | --- | --- |
| A | 00 | G0: all other astro items need it. Approve under S1 once its acceptance passes. |
| B | 01, 02, 03 · dlv2-f0 (if unclaimed or takeover-eligible) · dlv2-60 | Inventory, API decision and visual procedure are spike inputs. The dlv2 work runs alongside because 52 needs dlv2-62. |
| C | 10 (G1) · dlv2-f3 | Spike needs 01 and 02. NO-GO → S4 (drop 20–61, keep 01–03, report, end). |
| D | 20, 30 | 30 needs 03 and 10 and changes live Sphinx output, so it uses the 03 procedure. |
| E | 21, 31 · dlv2-62 | 21 needs 20 and 03; 31 needs 20 and 30. |
| F | 22, 32, 34 | 34 changes live Sphinx output, so it uses the 03 procedure. |
| G | 33, 35, 36, 40 · dlv2-61 after dlv2-62 | All need 22 (33 also 31; 35 also 32). |
| H | 50 (G2) | Needs 33, 34, 35, 36, 40. |
| I | 51, 52 | 52 also needs dlv2-62. |
| J | 53 (G3) | Release-driven atomic cutover; owner triggers the PyPI release (S3). |
| K | 54 | Evidence-based retirement; needs ≥5 working days of observation after 53. |
| L | 60, 61 | Post-cutover features; start under S1. |

## 5. Roles, delegation and model use

### 5.1 Primary session (Opus): coordinator, reviewer, gatekeeper

The primary session never does bulk implementation itself. It owns:

- tracker claims, releases, context notes and finishes
- decomposition into subagent tasks with explicit paths, acceptance and output contract
- review of every subagent diff before `make pr-open`
- integration across items, merge conflicts and CI triage
- all gate decisions under S1, and design-level calls: 00, 02, G1 (10), G2 (50), 52, 53, and the D14 overlap agreements
- the dlv2 flip (f3) and site-deploy design (dlv2-60/62), which are soundness and production-control work

### 5.2 Sonnet subagents: low-complexity, parallel work

Dispatch with the Agent tool, `model: "sonnet"`, in the background, several per message when independent. Use them for:

- 01 inventory script and tests
- 03 runbook draft
- 20 scaffold, make targets and CI job
- 21 token extraction
- 30 rst→MyST conversion, fanned out per docs section with one subagent each, integrated into the single astro-site-30 PR (G-i)
- 31 converter, one construct handler per subagent, each with its own tests
- 32 generator repointing, one generator per subagent
- 33 blog collection and feed
- 34 drafting contract pages, one area per subagent (benchmarks, platforms, results, utilities)
- 35 landing and prompts port
- 36 metadata and 404
- 40 shell extraction under strict "no logic change" instructions
- 50 harness implementation
- 51 capture switch
- the 54 deletion sweep
- 60 and 61 implementation
- read-only research (counts, call sites, URL lists) for any item

Every subagent prompt must include:

- the item id, with acceptance copied verbatim
- the exact worktree path and branch
- allowed paths and forbidden paths (never `git add -A`; stage explicit paths)
- the narrowest proving commands (§8)
- G-d, G-f, G-g and G-j restated
- "no tracker calls; no push or PR unless told; return: summary, files changed, commands run with results, open risks"

A subagent may open a PR only if the coordinator explicitly delegates `make pr-open`/`make pr-arm` for that branch after review.

### 5.3 Reviews and independence

- **Sonnet-authored work.** The primary session reviews it adversarially before PR: correctness, scope creep, guardrails, comment policy, tests that prove the acceptance.
- **Opus-authored gate evidence and design.** 00, 02, the 10 report, 50 sign-off, 52, 53 and dlv2 work need an independent reviewer: a separate Opus subagent at high effort, findings-only, forbidden from editing, that did not author the work. Its findings are resolved before the gate is approved (S1).
- **Soundness paths.** Follow AGENTS.md line 92 and the dlv2 ADR D4 exactly: a dedicated external adversarial review (Codex connector / codex, muse or agy), with resolved findings linked in the PR. Subagent reviews do not substitute.

### 5.4 Claims and parallelism

One todo-db server is one worker identity, so only one live claim exists at a time. To pipeline:

1. take the item
2. delegate, review, `make pr-open`, `make pr-arm`
3. when the PR is only waiting on the queue or CI, write resumption notes (branch, PR, head SHA, next action) to the item's context and `release` it
4. take the next ready item
5. re-`take` the earlier item to `finish` after merge

Fan-out inside a single item (sections, generators, contract areas) needs no extra claims. Never take over a live claim (e.g. dlv2-f0) unless the `takeover` rules hold: inspected holder, and evidence that the session cannot resume.

Keep a local ledger at `.todo-batch/astro-unified-site.txt` (git-ignored via `.git/info/exclude`) in the format of `.claude/skills/todo/references/batch.md`.

## 6. Rules and boundaries

- `AGENTS.md`, `CLAUDE.md` and `docs/agent/review-protocol.md` bind. Key points:
  - worktrees via `make worktree-create`, then `make agent-write-preflight`; in a disposable clone set `BENCHBOX_EPHEMERAL_CLONE=1`
  - PRs to `develop` only, squash, no stacked PRs
  - close-out = `make pr-open` → `make pr-arm` → monitor to merge (WRITE-CLOSEOUT-001)
  - Python via `uv` only
  - COMMENT-POLICY-001 applies to TS, Astro and CSS too
  - a drift guard and required-CI wiring land in the same PR
- Guardrails G-a…G-k and decisions D1–D14 in item 00 are pre-approved defaults. Do not re-open them. Change one only if spike or parity evidence contradicts it; then decide under S1 and record the reason in the ADR.
- Pre-decided defaults, so no question is needed:
  - package dir `website/`
  - Starlight docs inside a custom shell
  - Node 22 for `website/` and the site CI job (Astro 7 requires 22.12 or later; spike finding, allowed by D10)
  - landing copy unchanged
  - `.html` URLs kept
  - Atom feed ids unchanged
  - `_blog/` excluded
  - API reference = curated authored Markdown contracts, verified against the released wheel
  - one renderer per production artifact
  - release version = whatever the owner triggers next; the agent prepares release notes per `docs/operations/release-guide.md`
- Stop only for:
  - an owner-only action not covered by the standing approvals
  - a denied permission
  - live-cloud spend
  - a HOLD or unresolved Critical/High review
  - a production probe failure that rollback does not fix
  - S4 NO-GO, which is terminal: report and end

  The PyPI release is not a stop (S3): notify the owner once with the TestPyPI evidence, keep working ready items, and schedule wake-ups with `send_later` / `ScheduleWakeup`. Waiting windows (the ≥5 working days before 54, dlv2 shadow/observe windows) are handled the same way: set `not_before` on the item, work elsewhere, wake up later.
- Prohibited:
  - weakening, skipping or disabling a required or visual check
  - an empty commit or close/reopen to kick CI
  - mixed-renderer production artifacts
  - editing content in two places
  - adding docstrings or explanatory comments
  - committing screenshots or binaries
  - CDN scripts or analytics
  - changing Explorer query, metric or admission logic

## 7. Known failure modes

| Symptom | Cause | Safe action |
| --- | --- | --- |
| PR fails the fast-lane baseline guard | Base more than ~1 day behind develop; exact-SHA cache expired | Rebase on develop, then enqueue |
| Follower in a merge group fails visual acceptance at the baseline download | The group base is the leader's synthetic SHA, which has no baseline | Re-queue after the leader merges; land site-changing PRs one at a time |
| Visual approval set on the PR is ignored in the merge group | Approvals are bound per exact tree (PR head vs `merge_group.head_sha`) | Set both slots per the astro-site-03 runbook |
| Every PR fails ruleset-drift after a queue/ruleset change | Live ruleset differs from values pinned in `scripts/ruleset_drift_check.py` (G11) | Change pinned values and the live ruleset together, as in dlv2-f3 |
| Queue ejection at ~60 min | Runner starvation | Re-enqueue (spurious ejection). Investigate only if it repeats on the same PR |
| Sphinx build regenerates `docs/benchmarks/queries/` | `config-inited` hook in `docs/conf.py` | During the dual build, run the generator once as an explicit step (astro-site-32); never let both renderers write it |
| Explorer build fails for missing data | `results-explorer/public/` is generated by `explorer_publish.py build` | Run the CI order: publish → snapshot invariants → `npm run build` |
| Static API symbol scan misses exports | `benchbox/__init__.py` lazy `__getattr__` | Verify by importing the listed symbols from the released wheel in an isolated env (astro-site-02) |
| todo `E_MULTIPLE_CLAIMS` | Coordinator still holds a claim | Release with notes or finish first (§5.4) |
| `lint` fails at `guard-agent-commit-range` | Commits are authored by an agent identity ([COMMIT-IDENTITY-001]) | Author commits with the maintainer identity, which needs the owner's authorization; otherwise the owner re-authors or squashes before merge |
| `test_ledger_coverage.py` fails | A new `tests/unit/scripts` file is missing from `docs/development/dev-loop-property-ledger.md` | Add its row in the same PR |
| Pre-commit comment-policy hook fails on a file you did not stage | The hook checks the whole staged tree, including inline program strings it cannot analyze | Move executable code out of strings into its own module |
| A file under `_project/<new dir>/` is not tracked | `_project/*` is gitignored except listed directories | Put data under a tracked directory such as `_project/design/` |
| A pending `github-pages` deployment never starts | Only a required-reviewer user can approve it; `GITHUB_TOKEN` cannot | The owner approves, or gives the session a reviewer token |

## 8. Verification and review gates

Per PR, before `make pr-open`:

- `make agent-write-preflight` and `make pr-preflight`
- `make comment-policy-check`
- `make duplicate-check-delta`
- targeted pytest: `uv run -- python -m pytest <touched tests>`
- docs: `cd docs && uv run sphinx-build -b html -W --keep-going . _build/html`, while Sphinx exists
- site (after 20): `make site-build` and `make site-check`
- Explorer: `cd results-explorer && npm ci && npm run typecheck && npm test -- --run && npm run test:e2e:chromium`
- `npm run audit:high` in each Node package
- after 01: `site_inventory diff` against the committed baseline
- the PR's own acceptance items, each proven by a command or artifact linked in the PR

Gates (approved under S1 only with independent review recorded):

| Gate | Pass evidence |
| --- | --- |
| G0 (00) | ADR merged with D1–D14, guardrails, S1–S4, D14 agreements |
| 02 | Public-symbol list verified against the wheel; URL/anchor map; template page |
| 03 | Runbook merged; one real two-slot rehearsal with run ids |
| G1 (10) | Spike report covering all 10 scope points; GO criteria met, or NO-GO → S4 |
| G2 (50) | URL compatibility report: zero broken URLs/fragments; allow-list approved; re-run on the cutover base |
| G3 (53) | All-Astro preview with rollback drill (52); develop PR merged with both visual slots; owner's release tag contains `website/`; production receipt all-Astro; production rollback drill done |
| 54 start | Evidence pack per item 54; last Sphinx artifact retained and redeployable |

Finish an item only after its PR is merged and every acceptance line is verified on develop or in production.

## 9. Decisions and unavailable evidence

- G-i amendment (owner, 2026-10-03): put as much work as possible into each PR. One PR may carry several items; each item finishes when that PR merges.
- Owner actions this plan needs, outside S1–S4's reach: approving `github-pages` deployments (dlv2-60 drill, dlv2-62, 53), the GitHub admin removals in dlv2-62, setting the four visual approval variables for the astro-site-03 rehearsal, and authorizing the maintainer commit identity.

- All owner decisions are captured in S1–S4 and D1–D14. None are pending.
- Not verified while writing: live ruleset contents, the queue's health today, whether external review harnesses (codex, muse, agy) are reachable from your environment. Check each before relying on it. If external review is unreachable for a soundness-path PR, that PR waits per AGENTS.md; work other items meanwhile.
- dlv2-f0 may be claimed by another worker. Coordinate through the tracker; do not duplicate its PRs.
