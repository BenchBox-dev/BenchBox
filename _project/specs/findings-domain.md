# Findings domain

Status: design accepted (2026-07-22 adversarial review); implemented in
phases (see [Roadmap](#roadmap)). This is the master spec; each phase's TODO
carries the executable work order.

## Problem

Blind-spot findings live as tracked Markdown under `_project/blind-spots/`.
Two costs follow: (1) every capture is a new record committed to Git, so the
review-protocol's "capture is local-only" contract is honoured only until the
next commit, and the directory accretes tracked files that never integrate
with the work tracker; (2) findings are surfaced by a bespoke `make
blind-spots-*` sweep that no planning surface routes to, so findings are not
naturally considered when deciding what to work on.

The findings domain moves capture **out of the Git tree** and lands findings
in the shared tracker DB as a sibling module, surfaced through the commands
agents already run.

## Goals

Derived from the 2026-07-22 adversarial review. The review's numbered
requirements referenced by the phase work orders:

- **R2 — findings are naturally considered during planning.** Satisfied by
  riding the commands agents already run (`todo ready`, `todo stats`), not by
  a new entry-point command they would never be routed to.
- **R4 — no new findings records in Git.** New captures never land as tracked
  files; the tracked corpus is imported once and then retired.
- **R5 — zero-credential capture.** Capturing a finding must work with no DB
  credentials and no network — a plain local file write.

Supporting goals: keep the existing Markdown schema as the capture format
(no new storage tech); keep the review-protocol two-step contract (capture is
one authorized write, landing is a separate authorized turn); keep git
*history* intact.

## Governance amendments (phase 0)

Two standing documents are amended **before** any capture or schema work, so
the design does not silently contradict a settled decision:

1. **`_project/specs/todo-db-tracker.md` — "No offline write queue"** is
   narrowed to *work state* (items, work units, claims, deferrals). Append-only
   **finding draft files** are a permitted local write: they carry no
   cross-session consistency contract and are landed later through the ordinary
   sync + PR cycle, never queued into the primary.
2. **`docs/development/review-protocol.md` §4** (and its `SHARED/review-protocol`
   skill mirror) name the append-only draft file under
   `~/.benchbox/finding-drafts/` as the **sole** in-review finding write.
   Writing a finding straight into the hosted DB during a review is *landing*
   (§1) and is forbidden without a separate authorized turn; `todo finding
   sync` is that separate step.

Unchanged by design: the §2 defect gate (defects never enter any findings
surface), the §1 authorization boundary, and the write-queue rejection for
work state.

## Capture (phase 1)

New drafts are written to `~/.benchbox/finding-drafts/` — outside every
worktree (survives worktree churn; per-machine; no credentials). The existing
Markdown schema **is** the offline draft format.

- **Required frontmatter is unchanged**: `id` (= filename stem), `date`,
  `status`, `finding_kind`, `review_context`.
- **New optional frontmatter only**: `observed_sha` (provenance, not a lookup
  key); `evidence` (list of `{path, pattern, note}` — grep-pattern-based per
  the `suggested_sweep` precedent; line ranges permitted but discouraged, since
  legacy records rarely carry them and they rot); `urgency`, `breadth`,
  `confidence` (set at triage, never required at capture).
- Body sections stay verbatim: `## Finding`, `## Why this matters`,
  `## Suggested next steps`.

`validate_blind_spot.py` is retargeted at the drafts directory and taught the
optional fields; it must stay green over the full legacy corpus (that corpus
is the phase-5 import set). The `/blind-spot` command is rewritten to write
drafts there while keeping the §2 defect gate and the class-not-instance step
verbatim. The tracked `_project/blind-spots/` tree is untouched in this phase —
capture simply stops adding to it.

## Schema (phase 3)

Lands in the shared tracker DB as a sibling module,
`_project/scripts/todo_findings.py`, imported by `todo_db.py` (keeps the
monolith from growing). Migration is **additive**, `SCHEMA_VERSION` 2 → 3:

- **`findings`** — `id` (filename-stem, regex-enforced), `date`,
  `finding_kind`, `review_context`, `observed_sha`; verbatim body columns
  `title`, `finding_text`, `why_matters`, `next_steps`; `disposition`
  `CHECK IN (open, actionable, actioned, dismissed, promoted)` `DEFAULT open`;
  `disposition_reason` (CHECK-required for `actionable`/`dismissed`); nullable
  `urgency`, `breadth`, `confidence`, `reconsider_after`; `created_at`;
  `imported_from`.
- **`finding_evidence`** — `path`, `pattern`, optional `line_start`/`line_end`,
  `note`.
- **`finding_links`** — `kind` `CHECK IN (promoted-to, informs, resolved-by,
  related-finding, duplicate-of)`, target item / target finding.
- **`finding_events`** — append-only provenance (mirrors the `events` table);
  triage-log lines import here in phase 5.

The disposition set mirrors the deferral shape already in the tracker (a
disposition + a required reason for the terminal branches), so findings reuse
the tracker's existing triage ergonomics rather than inventing a parallel one.

`todo_db.py` is **not** CODEOWNERS/soundness-gated, so the real risk of this
phase is the **manual-only hosted acceptance** (w8): PR CI covers fakes only,
so the `SCHEMA_VERSION` 2 → 3 migration is accepted against the live
`benchbox-todo` DB by hand, as a gate of this phase.

> **Operational coupling.** The CLI refuses to run against a DB whose
> `schema_version` is below the CLI's `SCHEMA_VERSION` (it raises "run
> `todo migrate`"; migrations are never auto-applied). Landing phase 3 to
> `develop` therefore *requires* a coordinated `todo migrate` on production —
> until it runs, every collaborator's CLI is inert against the live DB. Land
> the code and run the hosted migration together.

## CLI (phase 3)

`todo finding create | list | show | candidates | dismiss | triage | link |
promote | sync`.

- **`create`** prints the review-protocol §2 defect-gate question and requires
  a `--gate class-not-instance` attestation; refuses `finding_kind bug-class`
  without `--fixed-by <ref>` (mechanises §2: a bug-class finding requires an
  already-landed fix). `create` writes the **draft file only, never the DB** —
  capture and landing are always two steps.
- **`sync`** walks `~/.benchbox/finding-drafts/`, validates each via the
  phase-1 validator, and inserts-if-absent by filename-stem id. Same-id /
  different-content is a **loud error, never a merge**. This is the authorized
  landing step.
- `candidates` lists unsynced drafts; `list`/`show` read the DB; `dismiss`,
  `triage`, `link`, `promote` move a finding through its disposition and record
  a `finding_events` row.

## Surfacing (phase 4)

R2 is satisfied by riding existing planning surfaces, not a new command:
`todo ready` is the hardcoded planning entry in a dozen places (skills,
references, `AGENTS.md`, this spec, `CLAUDE.md`), and agents follow skills
mechanically — a `todo plan` command they are never routed to would never run.

A one-line banner is added to `todo ready` and `todo stats`:

```
N open findings, M unsynced drafts — todo finding candidates
```

Suppressed cleanly when both counts are zero, so it never breaks the
machine-readable output of `todo ready`. The open-findings count piggybacks
the query batch the command already issues (zero extra hosted round-trips);
the unsynced-draft count is a local directory glob (no credentials). Every
routing surface is updated in the same change. `todo plan` is **deferred**
until the banner is measured insufficient — precedent: deferrals already
surface through the claim work order and `stats` counts without a dedicated
command.

## Export boundary (phase 2)

The deterministic export committed to `_project/todo-db-export/` must **never**
leak findings tables (findings hold review prose that is deliberately not
version-controlled). Enforced structurally:

- Introduce `EXPORT_TABLE_ALLOWLIST` (= today's `TRANSFER_TABLES` set) and
  iterate it **explicitly** when exporting.
- A pinning test asserts `exported tables == allowlist`, so any future
  `finding%` table fails closed **by construction** (it is absent from the
  allowlist until deliberately added, which the test forbids).
- Fix the pre-existing M3 bug: the `events` table is in `TRANSFER_TABLES` but
  was omitted from `_export_all_unlocked`; add it, deterministically ordered.

This phase has **no dependency** on the findings schema — it hardens the
boundary before findings tables exist, so the boundary is proven closed before
there is anything to leak.

## Migration & parity (phase 5)

Import the legacy corpus — the tracked `_project/blind-spots/*.md` records plus
any untracked local capture (≈67 at the 2026-07-22 design; the phase-5 parity
report computes the live count, which drifts as captures accrue before the
freeze) — into the findings tables with a **falsifiable** parity definition
(the review's M4 found "lossless parity for triage history" unfalsifiable as
written, since triage history is free-text `## Triage log` prose):

- **Body parity**: verbatim `## Finding` / `## Why this matters` /
  `## Suggested next steps` sections and every frontmatter field preserved.
- **Triage history**: each `## Triage log` line imports as one
  `finding_events` row, `action = 'imported_triage_log'`, prose intact.
- **Status map**: `open→open`, `actionable→actionable`, `actioned→actioned`,
  `dismissed→dismissed`, `merged-to-todo→promoted`.
- **Dangling `todo_id` policy**: drop semantics reserve ids forever and
  YAML-era ids may not exist, so resolve each `todo_id` against the live DB;
  danglers import as `finding_links(kind='promoted-to', target_item=NULL)` plus
  a note, and the parity report counts them explicitly.

Process: dry-run into a scratch DB first, produce a machine-checkable parity
report (all-records-imported count, per-record field diff, dangling-link
count), review it, **then**
production import. Use the importer's Hrana-pipeline **bulk** path — never a
per-row loop against the primary (write delegation is ~0.15 s/statement). One
artifact-restore proof: export a findings-inclusive snapshot to the CI artifact
channel and restore it into a clean DB, verifying `finding_events` round-trip.

This phase **starts the freeze** that precedes demolition.

## Demolition (phase 6)

A single mechanical PR after the phase-5 freeze cycle completes and all gates
hold. Deletes the tracked `_project/blind-spots/*.md` records and retires the
machinery inventoried by the review's M6: `sweep_blind_spots.py` and its
tests; the `Makefile` `blind-spots-{list,report,sweep}` targets (+ `.PHONY`
and help entries); the `.gitignore` un-ignore line for `_project/blind-spots/`;
the `path-filters.yml` safe-content and content-guard entries; the `CLAUDE.md`
pre-approved `make blind-spots-*` commands and capture-path bindings.

**Kept**: `validate_blind_spot.py` (retargeted in phase 1 as the draft
validator); the `/blind-spot` command (rewritten in phase 1); the directory
`README.md` content, relocated to `docs/development/` as the findings-domain
doc.

Git **history is untouched** — see Assumptions.

## Assumptions & owner decisions

- **"Out of Git" means current-tree-only.** Removing findings from Git covers
  the *working tree*: the tracked records are deleted in phase 6, but the
  commit history (61 commits at the 2026-07-22 design) and the record contents
  therein stay readable in history.
  Rewriting history to expunge past findings is a **separate, owner-authorized
  destructive action** and is explicitly out of scope here. Owner sign-off on
  this history stance is recorded by this spec (phase-0 decision, 2026-07-22).
- The Markdown schema is the capture format — no new storage technology is
  introduced for capture.
- The findings module reuses the tracker DB and its client/adapter; it adds no
  new backend or credential path.

## Metrics & success criteria

- **R4 holds**: no `finding%` table appears in `_project/todo-db-export/`
  (pinned by the phase-2 test); no new tracked records under
  `_project/blind-spots/` after phase 6.
- **R5 holds**: `todo finding create` succeeds with no DB credentials and no
  network (writes only the draft file).
- **R2 signal**: the `todo ready` / `todo stats` banner surfaces open-findings
  and unsynced-draft counts on every planning pass; `todo plan` stays deferred
  until this banner is measured insufficient.
- **Parity**: the phase-5 report shows every legacy record imported (N/N for
  the live corpus count), per-record field diffs
  empty, and dangling links counted; the artifact-restore proof round-trips
  `finding_events`.

## Roadmap

Dependency order (enforced by the tracker):

| Phase | Item | Needs |
| --- | --- | --- |
| 0 | `findings-phase0-governance` | — |
| 2 | `findings-phase2-export-boundary` | — |
| 1 | `findings-phase1-capture-redirect` | 0 |
| 3 | `findings-phase3-schema-cli` | 0, 2 |
| 4 | `findings-phase4-surfacing` | 3 |
| 5 | `findings-phase5-migration` | 1, 3 |
| 6 | `findings-phase6-demolition` | 4, 5 |

**Phase 3 ↔ phase 1 coupling.** Phase 3's `todo finding create`/`sync` share
phase 1's draft directory (`~/.benchbox/finding-drafts/`) and its retargeted
`validate_blind_spot.py`. The tracker models phase 3's hard deps as `{0, 2}`
(not `{1, 3}`), and that is deliberate: phase 3 can land its schema, module,
and CLI against an empty drafts directory without phase 1 present — no draft
exists to sync yet, and the CLI ships its own validation entry point. The
*real* corpus sync is phase 5, which correctly hard-depends on `{1, 3}`, so the
validator-and-drafts coupling is enforced exactly where it bites. In practice
phase 1 lands before phase 3 (it is earlier in the batch order); the missing
`3 → 1` edge only means the tracker would not *block* phase 3 on phase 1, which
is safe for schema-and-CLI work.

## Non-goals

- Rewriting Git history to remove past findings (separate destructive
  decision — see Assumptions).
- A new `todo plan` entry-point command (deferred; see Surfacing).
- Any new storage technology, backend, or credential path for capture.
- Routing defects through any findings surface — defects follow the §2 gate
  into the severity table / TODOs, never into findings.
