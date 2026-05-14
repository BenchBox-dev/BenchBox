# Decision record: /prompts/ landing route

**Status:** Accepted · **Date:** 2026-05-13
**Owner:** @joeharris76
**Drives TODOs:** `landing-prompts-decision-gates`,
`landing-prompts-catalog-generator`, `landing-prompts-static-route`,
`landing-prompts-launch-gates`.

## Correction (2026-05-14)

The launch implementation conflated two separate ideas: a generic
coding-agent option and a no-agent terminal recipe. That made the
default selector label and output contract too broad. The follow-up PR
for `landing-prompts-generic-semantics-and-layout-fixes` corrects the
route so `generic` is a first-class coding-agent option for Pi,
OpenCode, Cline, Aider, and similar agents, while the copyable agent
prompt remains the primary artefact.

## Context

BenchBox is adding a static `/prompts/` route on the landing surface
(under `landing/`, deployed alongside the root marketing page via
`.github/workflows/docs.yml`). Its job is conversion: turn a casual
landing-page visitor into someone who actually runs a benchmark by
copy-pasting an agent prompt or a CLI/MCP setup snippet. It is **not** a
new runtime BenchBox surface and must not add a new `benchbox prompts ...`
CLI command, a new MCP prompt-rendering tool, or an unversioned public
data API.

This record resolves the six gates required by
`landing-prompts-decision-gates` so the implementation TODOs can move
out of `planning/` without re-litigating product choices.

## Public label

- **Nav label:** `Instruct an agent`
- **Page H1 / `<title>`:** `Instruct a coding agent to use BenchBox`
- **URL slug:** `/prompts/` (unchanged — the path is internal jargon and
  matches the generator artefact name)

Rationale: the nav slot needs to be short and verb-led to compete with
`Docs / Blog / Results`. The page H1 carries the full intent for users
who arrive directly. "Prompts" was rejected as too generic next to the
existing nav items.

`landing-prompts-launch-gates` w1 must use these strings verbatim in
`landing/index.html` and `docs/_templates/page.html`. The page title
appears in `landing/prompts/index.html`.

## Default agent and surface

- **Default agent:** `Generic` (registry key: `generic`)
- **Default surface:** `CLI`
- **Default goal:** `Test one platform`
- **Default interface:** `SQL`
- **Default deployment:** `Local`
- **Default platform:** `duckdb`
- **Default benchmark:** `tpch`
- **Default scale:** `0.01`

The page must render a coherent, copyable prompt for this default state
without any user interaction.

Rationale for `Generic` over `Codex` or `Claude Code`: the default is a
vendor-neutral coding-agent option that does not pre-bias toward OpenAI
or Anthropic. Codex and Claude Code remain selectable and
well-supported, while Generic covers other agents with shell or MCP
capability (see `## Generic-agent semantics`).

## Cloud safety

Cloud platforms (`mode: managed` per
`benchbox/core/platform_registry.py:42` —
`Literal["local", "self-hosted", "managed"]`) remain visible in MVP.
The catalog generator and the page MUST enforce:

1. Use registry vocabulary internally: `local`, `self-hosted`, `managed`.
   UI labels: `Local`, `Self-hosted`, `Managed cloud`.
2. For any `managed` selection, the **first copyable command** is a
   dependency / status check (e.g. `benchbox check-dependencies <platform>`)
   or setup instruction — never a live run.
3. The second block is a dry-run (`--dry-run` or equivalent), never a
   live run.
4. Live-run commands appear only behind an explicit
   "After setup is complete" sub-section, with one-line warnings about
   billing and credentials.
5. The page never asks the user (or instructs the agent to ask the
   user) to paste secrets, API keys, or service-account JSON into chat
   or the browser. Credential setup is delegated to standard platform
   docs.
6. If a managed platform is missing required credentials/config, the
   prompt MUST instruct the agent to **stop and summarise** what is
   missing rather than guess.

The catalog generator (`landing-prompts-catalog-generator` w4) MUST
fail validation when a managed-cloud recipe lacks the dependency-check
+ dry-run-first + no-secret guidance.

## Generic-agent semantics

- **Selector label:** `Generic`
- **Registry key:** `generic`
- **Hint:** `Pi, OpenCode, Cline, Aider, …`
- **Intent:** any coding agent with shell or MCP capability that is not
  one of the named Codex / Claude Code options.

Output contract for `generic`:

- The page emits the same block shape as the named-agent options: one
  primary copyable agent prompt, plus MCP server config only when the
  `MCP` surface is selected.
- Generic output uses vendor-neutral wording and does not name Codex or
  Claude Code as the active agent.
- The prompt MUST NOT assume BenchBox is installed; it must include the
  `uv add benchbox[<platform>]` step before any run command.
- There is no separate no-agent recipe mode on this route.

When `Codex`, `Claude Code`, or `Generic` with the MCP surface is
selected, the page emits agent-targeted prompt copy that names existing
MCP tools/prompts (e.g. `run_benchmark`, `benchbox.run_benchmark`) where
applicable. See `benchbox/mcp/prompts/registry.py` and
`benchbox/mcp/tools/benchmark.py` for the canonical names; the generator
validates against these.

## Analytics posture

**Analytics are deferred for MVP launch.**

- No analytics provider (Plausible, GoatCounter, GA, Segment) is wired
  into `landing/prompts/` or root `landing/` for this launch.
- The conversion question ("is the prompt builder useful?") will be
  evaluated qualitatively via informal feedback and any organic GitHub
  / Substack signal during the deferral window.

**Revisit date: 2026-08-13** (3 months from this record).

On the revisit date, `landing-prompts-launch-gates` w6 owner re-evaluates:

- Has there been any qualitative signal (feedback, issues, traffic
  spikes) that warrants instrumenting?
- Is the page still in production, or has it been deprecated?
- If instrumenting, the preferred path is **Plausible (self-hosted)**
  because it is privacy-respecting and doesn't require cookie banners.
  Pageview-only via GoatCounter is the fallback if Plausible setup is
  too heavy.

If at revisit the page is shipping selectable cloud platforms with a
live-run section, the bar for instrumenting rises (we should know if
visitors are accidentally triggering managed-cloud commands).

Kill criteria are recorded by `landing-prompts-launch-gates` w6 once
the page has been in production long enough to read qualitative signal;
they are not pre-defined here because we have no baseline.

## API and JSON posture

**No standalone public JSON catalog is shipped in MVP.**

- The generator (`scripts/generate_landing_quickstarts.py`) emits
  `landing/prompts/catalog.generated.js`, which assigns
  `window.__BENCHBOX_PROMPT_CATALOG__ = {...};` and is loaded by the
  page via a `<script>` tag. This is page implementation detail.
- A standalone `landing/prompts/recipes.json` (or any equivalent
  fetchable JSON endpoint) is **forbidden** for MVP because third
  parties would treat it as a public, versioned API. Adding such an
  API in future requires a separate, versioned API decision record.
- The generator and tests MUST fail if a fetchable JSON catalog file is
  introduced (`landing-prompts-catalog-generator` w4 verification).

## Why the route stays on the landing surface (not Sphinx)

- `/prompts/` is a marketing conversion surface, not reference
  documentation. Sphinx pages route through `docs/_templates/page.html`
  and inherit the docs chrome; that chrome is wrong for a single-page
  builder.
- `landing/` already deploys as static files via
  `.github/workflows/docs.yml` — no new build step is required.
- The results-explorer SPA stack (Vite/Preact under `results-explorer/`)
  is explicitly out of scope for this small static builder.

## Why no new public CLI / MCP APIs

- Adding a `benchbox prompts ...` CLI command or a new MCP
  prompt-rendering tool would turn a marketing artefact into a supported
  runtime surface — increasing maintenance cost and constraining future
  refactors of `benchbox/cli/commands/` and `benchbox/mcp/tools/`.
- The page composes copy from registry/platform/benchmark metadata that
  already exists; it does not need a new runtime API to do that.

## Launch status (recorded by launch-gates w6, 2026-05-13)

The full chain (#400 decision, #401 catalog generator, #403 static page,
this PR) has landed on `develop` with the values below. The decision
record above remains the policy source of truth; this block records the
concrete state at launch.

- **Final public label:** nav `Instruct an agent`; page H1
  `Instruct a coding agent to use BenchBox`. Used verbatim in
  `landing/index.html` and `docs/_templates/page.html`.
- **Default state on first load:** Goal=Test one platform,
  Agent=Generic, Surface=CLI, Interface=SQL, Deployment=Local,
  Platform=duckdb, Benchmark=tpch, Scale=0.01.
- **Analytics:** deferred. No analytics provider wired into
  `landing/prompts/` or root landing. **Revisit on 2026-08-13.** If
  re-evaluating, prefer self-hosted Plausible; fall back to GoatCounter.
- **Cloud safety behaviour:** managed-cloud recipes start with a
  `benchbox check-dependencies <platform>` block, then a `--dry-run`,
  then a live command behind an explicit "After credentials are
  configured outside this chat" comment. Catalog generator validates
  that managed platforms declare safety_terms covering
  dependency / dry-run / no-pasted-secrets, and fails CI if missing.
- **Known limitations (MVP):**
  - Curated platform subset (8 platforms, 4 benchmarks). Adding more
    requires editing `landing/prompts/catalog.yaml` and re-running the
    generator.
  - No automated a11y tooling. Manual checklist at
    `landing/prompts/a11y-checklist.md` is the gate.
  - No qualitative feedback channel beyond GitHub issues; the deferral
    window assumes informal signal is sufficient.
- **Kill criteria (qualitative pending baseline):**
  - At the 2026-08-13 revisit, if there is no organic signal (no
    issues, no inbound feedback referencing `/prompts/`, no
    measurable docs / blog traffic referring users to it) and the
    landing surface has not changed direction, deprecate the route or
    instrument it before continuing to ship updates.
  - At any time: if a managed-cloud recipe ships without
    dependency-check + dry-run-first + no-secrets warnings, treat that
    as a hard regression (catalog-generator CI already gates this) and
    block the affected PR.

## Review gate (decision-gates w6 checklist)

The following risk topics have been addressed by the sections above:

- Existing MCP prompt overlap (`benchbox/mcp/prompts/registry.py`) →
  Generic-agent semantics §, API and JSON posture §.
- Compare CLI dual-mode (SQL vs DataFrame in
  `benchbox/cli/commands/compare.py`) → covered by catalog-generator
  w4 validation rules; this record does not introduce dual-mode
  ambiguity.
- Deployment vocabulary (`local`, `self-hosted`, `managed` per
  `benchbox/core/platform_registry.py` `DeploymentCapability.mode`) →
  Cloud safety §.
- Hidden JSON API risk → API and JSON posture §.
- Cloud safety (dependency check, dry-run-first, no pasted secrets) →
  Cloud safety §.
- Generic-agent ambiguity → Generic-agent semantics §.
- Conversion measurement → Analytics posture §.

Implementation TODOs are cleared to move from `planning/` to `active/`.
