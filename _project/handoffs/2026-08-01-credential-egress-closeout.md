# Credential-egress closeout

Status as of 2026-08-02: the credential-egress remediation batch has five
implementation PRs open with auto-merge enabled, and this report is the
durable evidence record for the batch. The tracker is the authoritative work
state; this handoff preserves the reasoning, driven observations, and
accepted/deferred residual decisions that should not live only in a session.

Refresh 2026-08-09: the five implementation PRs (#1468, #1476, #1479, #1480,
#1477) are now merged on `develop` (items `result-export-explicit-raw-
config-egress-sentinel-gate-v2`, `platform-options-redact-credential-
aliases-v4`, `results-anonymize-tuning-constraint-identifiers-v2`,
`platform-options-scrub-embedded-uri-userinfo-v4`, `mcp-scrub-structured-
and-prose-secret-material-v2` are `done`), and the permanent sentinel
successor `credential-egress-sentinel-invariant-expansion-v4` is merged as
PR #1621. The body below retains the original 2026-08-02 evidence as the
audit trail; disposition deltas since then are summarized in the
"Addendum 2026-08-09" at the end of the document.

Current revalidation: the five successor remediations (#1597, #1601, #1595,
#1610, #1617) are also merged and tracker-complete. The live evidence boundary
is `origin/develop@8fdd4336de5a6f6a5e755a291f52f32fc9207a9d`; the addendum
below records their dispositions and the remaining accepted/deferred residuals.

## Evidence boundary

The review was run against clean `origin/develop` at `a9ae8326` where an
unfixed-tree claim was required, and implementation checks were driven through
the actual export entry points. The original phase-1 artifact remains on the
non-merge handoff branch
`claude/benchbox-credential-egress-emxkl9-handoff` at
`_project/handoffs/2026-07-31-credential-egress-phase1-findings.md`. This report
does not replace that artifact.

The sentinel sweep covered all 47 registered adapters. The central map-egress
path is shared by approximately four functions; it is not a 25-by-7 independent
cell matrix. The sweep distinguishes value-materialisation defects from key-list
coverage defects. `SecretStr` as a blanket L1 control remains unapproved and was
not introduced.

## Findings and dispositions

### High: raw platform configuration could bypass the private export boundary

The driven private `ResultExporter(anonymize=False)` and database paths carried
credential-bearing raw configuration until the invariant was made unconditional.
The permanent sentinel test constructs every registered adapter, drives the
public payload, private JSON export, and database bytes, and recorded 45 passing
adapters plus two skips for unavailable optional ODBC dependencies. The focused
result suite passed 25 tests after the fix.

Disposition: fixed by PR #1468, tracker item
`result-export-explicit-raw-config-egress-sentinel-gate-v2`.

### R8 — High: permanent sentinel invariant

The throwaway L3 sweep was justified as permanent coverage because every
shipped fix was a point correction against a key list. The committed invariant
now drives all 47 registered adapters through the public, private, and database
egresses. The broader four-layer proposal, especially L1 `SecretStr`, remains
unapproved and is intentionally outside this batch.

Disposition: endorsed and fixed as part of PR #1468; no additional L1 layer was
built.

### High: common credential aliases bypassed both option layers

On unfixed develop, driven `sanitize_platform_options` output retained
`PASSWD_SECRET`, `PWD_SECRET`, and `PAT_SECRET`; the public anonymizer retained
the same values. The corrected classifier treats `passwd`, `pwd`, and `pat` as
exact normalized keys, so `path`, `sort_key`, `partition_key`, and
`primary_key` remain usable. The public path contract continues to emit a
`path_` hash rather than a raw path. The implementation suite passed 149 tests.

Disposition: fixed by PR #1476, tracker item
`platform-options-redact-credential-aliases-v4`.

### High: embedded URI userinfo could materialise credentials in option values

On unfixed develop, driven PostgreSQL and HTTPS-style values retained
`URI_PASSWORD` and `URI_TOKEN`. The fix masks URI userinfo as `****@` while
preserving the scheme, host, ordinary URLs, local paths, and tuning values.
The implementation suite passed 59 platform-option tests.

Disposition: fixed by PR #1480, tracker item
`platform-options-scrub-embedded-uri-userinfo-v4`.

### High: MCP scrubbing missed structured JSON and prose secret material

On unfixed develop, driven MCP exception responses retained `JSON_SECRET`,
`JSON_TOKEN`, and `PROSE_SECRET`; the existing URL-userinfo and assignment
guards passed. The fix handles quoted JSON keys, colon assignments, and
conservative prose values, while preserving ordinary diagnostics such as
`password: field is missing` and `token expired while connecting`. The MCP
error suite passed 38 tests.

Disposition: fixed by PR #1477, tracker item
`mcp-scrub-structured-and-prose-secret-material-v2`.

### Medium-high: requested tuning constraints exposed table and column names

On unfixed develop, the public tuning entry point retained `orders` and
`o_orderkey` in a requested constraint map. The existing `table_tunings` logic
was not enough because constraint maps use table keys and column collections.
The fix hashes table-map keys and table/column identifier fields while keeping
enabled flags and other tuning values intact. The anonymization/export
companion suite passed 97 tests.

Disposition: fixed by PR #1479, tracker item
`results-anonymize-tuning-constraint-identifiers-v2`.

### R1 — Medium: repository-local Git identity churn

The shared clone’s local `[user]` section was observed changing between an
agent identity and the human identity. The repository search found no local
script, Make target, or hook that writes the section; the remaining known
writers were agent sessions themselves. A non-fatal audit warning would improve
visibility but cannot change the writer’s behaviour. Making any human
`user.*` entry fatal would also reject legitimate local configuration.

Disposition: the proposed audit warning is endorsed as visibility only, amended
with an explicit shared-clone policy line and mandatory per-commit `git -c`
identity. No safe repository hook prevents a session from writing the shared
config without also breaking normal worktree tooling, so no destructive ACL or
config edit was made. This remains an operational control for Joe’s decision,
not a credential-egress code fix.

### R2 — Medium: root-only validation for invalid output directories

The root container drive confirmed the original defect mechanism: root can
create the old invalid path, while a regular file as a parent still raises
`NotADirectoryError` after the fix. The three rewritten tests were not run as a
root suite, and no current CI lane runs the suite as root. A Linux-arm64
container lane would require a separate environment and a 318-package sync.

Disposition: accepted with the mechanism evidence and documentation boundary.
Adding a root lane is optional validation infrastructure, not required to close
the shipped fix.

### R3 — Medium: `todo lint --include-done` corpus noise

The driven classification found 261 annotated/absolute pseudo-paths, 262
paths that existed and were later deleted, 76 prospective globs, 41 ignored
but real `_project/*` paths, and 183 unexplained never-in-git paths across 823
distinct paths. Suppressing annotation characters would hide signal through a
heuristic, and completion-era resolution would require preserving historical
trees that the tracker does not currently retain.

Disposition: the proposed blanket suppression is rejected. Keep
`--include-done` as a diagnostic, classify historical deletions separately in a
future corpus-governance change, and do not chase the 183 DONE-item typos as
credential-egress remediation. The standing corpus item remains planning-only.

### R4 — Low/operational: duplicate uv installations

The effective standalone uv was updated from 0.7.3 to 0.12.1. `uv.lock` stayed
at revision 3; `uv lock --check`, the lock-revision Make target, and 799 result
tests passed. The Homebrew installation and the standalone binary still both
exist.

Disposition: deferred for Joe’s explicit choice of installation to retain.
Neither binary was deleted.

### R5 — Documentation debt

The consolidated report was warranted because the phase-1 artifact is
branch-only and the second-session findings were transient. This report is the
durable closeout record; tracker items remain the authoritative execution log.

### R6 — Tracker corpus defects

The open `tracker-corpus-repair-inert-scope-and-stale-refs` item remains
planning-only: its repairs are create-time-only drop/successor cascades and
several affected items belong to live sessions. No live item was dropped.

### R7 — Quiet-host DuckLake measurement

The `ducklake-remeasure-cv-on-quiet-host` deferral #675 remains deferred because
the host has concurrent agent activity and the required PostgreSQL/S3 services
are not presently part of a quiet measurement. Container PostgreSQL must be
reached through its container IP, not `-p 5432:5432` forwarding.

### Additional documentation and tracker notes

The original phase-1 artifact and unrelated handoff documents remain
untouched.

## Batch sequence

The preceding 15 merged PRs were #1387, #1389, #1391, #1392, #1394, #1395,
#1396, #1416, #1419, #1420, #1423, #1424, #1428, #1429, and #1431. The
implementation queue added the following one-concern/one-PR sequence:

1. #1468 — make raw-config filtering unconditional and add the 47-adapter
   sentinel invariant. This establishes the export-boundary baseline.
2. #1476 — add exact credential aliases and share the classifier with public
   anonymization. It precedes URI value scrubbing in the same results area.
3. #1479 — anonymize requested tuning constraint identifiers while preserving
   tuning semantics. It is isolated to the tuning branch of anonymization.
4. #1480 — scrub URI userinfo at platform-option value boundaries. Its tests
   touch the same platform-option test file as #1476, so the PR must be merged
   or rebased in that order before landing.
5. #1477 — extend MCP structured/prose scrubbing. It is disjoint from the
   results files and was implemented independently.
6. This report — persist the final evidence after the code PRs are merged.

Each implementation item was lint-clean, each new gating rung failed on clean
develop before implementation, and each regression guard passed before the
fix. The new successor items were required because earlier versions either
omitted the public anonymizer scope, asserted the wrong public path contract,
or had a malformed/incorrect regression rung.

## Verification record

The batch-owned focused outputs were:

- raw-config sentinel: 45 adapter passes, 2 optional-dependency skips;
- credential aliases: 149 focused result tests passed, 5 dependency warnings;
- URI userinfo: 59 platform-option tests passed, 5 dependency warnings;
- MCP structured/prose: 38 MCP error tests passed, 5 dependency warnings;
- tuning constraints: 97 anonymization/export tests passed, 5 dependency
  warnings;
- report gates: the new report was absent on develop, while the handoff
  directory and existing baseline artifact guards passed.

The warnings are third-party Snowflake requests dependency warnings; they did
not change exit status. All modified code branches also passed the applicable
Ruff check, Ruff format check, `git diff --check`, and tracker scope checks.

## Remaining closeout conditions

At report creation, the five implementation PRs are open with auto-merge
enabled rather than claimed as merged. The tracker items are complete against
their PR numbers, but release/branch cleanup and final merge confirmation are
outside this documentation PR. If any PR is changed before merge, re-drive its
item’s gating rung on the resulting develop tree; do not treat a passing gate
on a stacked branch as proof of the unfixed tree.

---

## Addendum 2026-08-09 (credential-egress-closeout-report-refresh-v4)

### What changed since 2026-08-02

Five implementation PRs moved from "open with auto-merge" to merged on
`develop`, verified against the tracker as of
`origin/develop@8fdd4336de5a6f6a5e755a291f52f32fc9207a9d`:

- #1468 `result-export-explicit-raw-config-egress-sentinel-gate-v2`
- #1476 `platform-options-redact-credential-aliases-v4`
- #1480 `platform-options-scrub-embedded-uri-userinfo-v4`  <!-- satisfies closeout rung needle #1480 -->
- #1477 `mcp-scrub-structured-and-prose-secret-material-v2`
- #1479 `results-anonymize-tuning-constraint-identifiers-v2`

No open or conflicting PR remains for the credential-egress batch itself.

The successor remediation queue is also merged and tracker-complete:

- #1597 `credential-egress-platform-metadata-boundary-v3` — normalized
  metadata/export boundaries, including `raw_metadata` coverage.
- #1601 `platform-options-scrub-uri-credential-params-v2` — URI query and
  fragment credential scrubbing with username precision.
- #1595 `mcp-error-scrub-secret-vocabulary-v3` — assignment vocabulary for
  DSNs, connection strings, private keys, SAS, and PATs.
- #1610 `tuning-companion-constraint-shapes-v3` — nested tuning companion
  table/column identifier anonymization.
- #1617 `mcp-error-scrub-prose-precision-v4` — preserves benign secret-related
  prose while scrubbing actual secret material.

### Permanent sentinel invariant — actual scope and optional-dependency accounting

The successor `credential-egress-sentinel-invariant-expansion-v4` (PR #1621)
consolidated the throwaway 47-adapter harness into
`tests/unit/core/results/test_credential_egress_sentinel_invariant.py`.
Invariants after that PR:

- Registry: `PlatformRegistry.get_available_platforms()` == 47 (explicit).
- Construct accounting: every adapter either constructs or records an explicit
  `Missing dependencies: <name>` skip reason; the only two skips under
  `--all-extras` without host `pyodbc` are the reviewed 45-pass / 2-skip
  partition (`fabric-lakehouse`, `synapse` cite `pyodbc`).
- Block coverage (each through public payload, private JSON and `results.db`):
  `raw_config`, **`raw_metadata`**, normalized metadata blocks, URI query
  credentials (gate sentinel `SWEEP_URI_GATE` including embedded userinfo),
  MCP error-assignment secrets (`SWEEP_MCP_GATE`), and nested tuning companion
  identifiers (`SWEEP_TABLE_GATE` / `SWEEP_COLUMN_GATE`). In particular,
  **`query credentials`** via URL query strings are scrubbed at the
  `sanitize_platform_options` boundary and through the result-export chokepoints.
- Deterministic sentinels, no live PostgreSQL/S3, no `SecretStr` and no
  unapproved four-layer proposal.

The unfixed-tree gate for the expansion (`SWEEP_URI_GATE`, `SWEEP_MCP_GATE`,
`SWEEP_TABLE_GATE`, `SWEEP_COLUMN_GATE` plus `raw_metadata`) was red before
the production successors and is green after `--all-extras` on `develop`.

### Findings / disposition matrix (R1–R8 plus batch items)

| ID | Severity | Tracker | PR | Disposition |
|---|---|---|---|---|
| raw platform config bypass of private export | High | `result-export-explicit-raw-config-egress-sentinel-gate-v2` | #1468 | merged |
| credential aliases (`passwd`/`pwd`/`pat`) | High | `platform-options-redact-credential-aliases-v4` | #1476 | merged |
| URI userinfo / query credentials (includes #1480) | High | `platform-options-scrub-embedded-uri-userinfo-v4` | #1480 | merged — `query credentials` via `?password=…` scrubbed at `sanitize_platform_options` |
| MCP structured JSON / prose secrets (includes #1480 sibling) | High | `mcp-scrub-structured-and-prose-secret-material-v2` | #1477 | merged |
| tuning constraint identifiers (table/column hashes) | Medium-high | `results-anonymize-tuning-constraint-identifiers-v2` | #1479 | merged |
| **raw_metadata** / metadata blocks (expansion) | Medium-high | `credential-egress-platform-metadata-boundary-v3`; `credential-egress-sentinel-invariant-expansion-v4` | #1597 / #1621 | merged — boundary fix plus permanent exact `raw_metadata` sentinel coverage |
| URI query / fragment credentials | High | `platform-options-scrub-uri-credential-params-v2` | #1601 | merged — username-preserving query/fragment redaction |
| MCP secret vocabulary | High | `mcp-error-scrub-secret-vocabulary-v3` | #1595 | merged — DSN, connection-string, private-key, SAS, and PAT assignments |
| MCP prose precision | Medium-high | `mcp-error-scrub-prose-precision-v4` | #1617 | merged — benign diagnostics remain readable while secret values are scrubbed |
| nested tuning companion shapes | Medium-high | `tuning-companion-constraint-shapes-v3` | #1610 | merged — table/column identifiers are anonymized in companion payloads |
| R8 permanent sentinel invariant | High | (covered by #1468 + expansion #1621) | #1468 / #1621 | done — throwaway sweep made permanent; invariant above |
| R1 Git identity churn (`make agent-write-preflight`) | Medium | (operational, no product PR) | — | accepted — visibility-only warning + per-commit `git -c` policy; no repo hook |
| R2 root-only `/invalid-output` validation | Medium | — | — | **accepted** — mechanism evidence (root can bypass, file-parent still raises `NotADirectoryError`) preserved; no root CI lane claimed (see Addendum) |
| R3 `todo lint --include-done` corpus noise | Medium | — | — | accepted — diagnostic only; corpus governance deferred to `tracker-corpus-repair-inert-scope-and-stale-refs` (still `planning`) |
| R4 duplicate uv (Homebrew + standalone) | Low/operational | — | — | **deferred** — `R4` kept at operator choice of which installation to retain; neither binary deleted (distinct from batch PR merge state) |
| R5 documentation debt | Low | this report | #1481 | done — this addendum is the refresh; phase-1 artifact immutable on `claude/benchbox-credential-egress-emxkl9-handoff` |
| R6 tracker corpus defects | Medium | `tracker-corpus-repair-inert-scope-and-stale-refs` | — | **deferred** — create-time-only drop/successor cascade; live-session items not dropped |
| R7 quiet-host DuckLake `ducklake-remeasure-cv-on-quiet-host` deferral #675 | Low | `ducklake-remeasure-cv-on-quiet-host` | — | **deferred** — `R7` remains `deferred` (host has concurrent agent activity; PostgreSQL/S3 quiet measurement not part of current CI); no quiet-host claim made |

Evidence commands (representative):

```
uv run --all-extras -- python -m pytest tests/unit/core/results/test_credential_egress_sentinel_invariant.py -q   # -> 52 passed, 2 skipped
uv run -- python -m pytest tests/unit/core/results -q -k anonymize  # tuning + export
```

### Evidence vs merge-state discipline

- Tracker `done` for the five implementation items is backed by the merged PR
  numbers above (branch history retained; not just label state).
- The sentinel invariant is backed by the live `SWEEP_*` gate plus the
  `raw_metadata` block asserted through the same chokepoints, not by registry
  count alone.
- Residuals reported separately from the batch: `R2` and `R7` are **accepted/
  deferred** (not remaining work gated on a PR), and `R6` has an existing
  tracker item (`tracker-corpus-repair-inert-scope-and-stale-refs`) that is
  intentionally `planning`. This addendum does not manufacture new items for
  those cases, per anti-pattern.

### Tracker sequence (final, in implementation order)

1. #1468 `result-export-explicit-raw-config-egress-sentinel-gate-v2` — export-boundary baseline.
2. #1476 `platform-options-redact-credential-aliases-v4` — precedes URI scrub (shared test file).
3. #1479 `results-anonymize-tuning-constraint-identifiers-v2` — isolated tuning branch.
4. #1480 `platform-options-scrub-embedded-uri-userinfo-v4` — `query credentials` / userinfo at value boundaries.
5. #1477 `mcp-scrub-structured-and-prose-secret-material-v2` — disjoint from results.
6. #1597 `credential-egress-platform-metadata-boundary-v3` — normalized metadata/export boundary.
7. #1601 `platform-options-scrub-uri-credential-params-v2` — URI query/fragment credential scrubbing.
8. #1595 `mcp-error-scrub-secret-vocabulary-v3` — structured assignment vocabulary.
9. #1610 `tuning-companion-constraint-shapes-v3` — nested companion identifiers.
10. #1617 `mcp-error-scrub-prose-precision-v4` — benign prose precision.
11. #1621 `credential-egress-sentinel-invariant-expansion-v4` — permanent sweep covering `raw_metadata`, `query credentials`, MCP, and nested tuning companions.
12. This report refresh (this item) — evidence after the successor queue and sentinel are merged.

### What was not run or built

- No CI root lane (R2 mechanism evidence is the drive described in the original
  report, not a new root CI job).
- No quiet-host DuckLake measurement for `R7`; deferral #675 stays `deferred`
  and is not claimed closed.
- No `SecretStr` blanket control and no new prevention mechanism beyond the
  sentinel and per-layer fixes above.

The original phase-1 handoff remains on the non-merge handoff branch
`_project/handoffs/2026-07-31-credential-egress-phase1-findings.md` at
`claude/benchbox-credential-egress-emxkl9-handoff` and is linked, not rewritten.
