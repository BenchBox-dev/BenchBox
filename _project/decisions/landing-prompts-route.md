# Decision record: /prompts/ landing route

**Status:** Accepted · **Date:** 2026-05-13
**Owner:** @joeharris76
**Drives TODOs:** `landing-prompts-decision-gates`,
`landing-prompts-catalog-generator`, `landing-prompts-static-route`,
`landing-prompts-launch-gates`.

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

- **Default agent:** `Generic / manual` (registry key: `generic`)
- **Default surface:** `CLI`
- **Default goal:** `Test one platform`
- **Default interface:** `SQL`
- **Default deployment:** `Local`
- **Default platform:** `duckdb`
- **Default benchmark:** `tpch`
- **Default scale:** `0.01`

The page must render a coherent, copyable prompt for this default state
without any user interaction.

Rationale for `Generic / manual` over `Codex` or `Claude Code`: the
default has to be safe for visitors who arrive without an MCP-capable
agent. Defaulting to `Codex` or `Claude Code` would render copy that
assumes shell or MCP access; that is fine when the user selects it
explicitly, but a wrong default makes the first impression feel
unworkable. Codex and Claude Code remain selectable and well-supported
(see `## Generic-agent semantics`).

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

- **Selector label:** `Generic / manual`
- **Registry key:** `generic`
- **Intent:** the option is correct both for visitors who only have a
  generic chatbot (no shell, no MCP) and for visitors who want to run
  BenchBox manually from a terminal.

Output contract for `generic`:

- The primary copyable block is a **human-readable recipe**: numbered
  steps with shell commands the user can run themselves.
- A second, optional block titled "If your agent has shell access" can
  add an agent-targeted prompt that asks the agent to run the commands
  end-to-end. This block is OFF by default; the recipe is the canonical
  form.
- The recipe MUST NOT assume the user has BenchBox installed; it must
  start with the `uv add benchbox[<platform>]` step.
- The recipe MUST NOT reference MCP tools — that is the `MCP` surface,
  not the generic agent.

When `Codex` or `Claude Code` is selected, the page emits agent-targeted
prompt copy that names existing MCP tools/prompts (e.g. `run_benchmark`,
`benchbox.run_benchmark`) where applicable. See
`benchbox/mcp/prompts/registry.py` and `benchbox/mcp/tools/benchmark.py`
for the canonical names; the generator validates against these.

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
  Agent=Generic / manual, Surface=CLI, Interface=SQL, Deployment=Local,
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
