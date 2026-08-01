# Phase 1 — Adversarial review of BenchBox credential egress

Date: 2026-07-31. Branch reviewed: `claude/benchbox-credential-egress-emxkl9` at b12c609
(current develop head). All conclusions below were verified by driving real entry points
with sentinel values, not by reading predicates; observed outputs are quoted or summarized
with the command noted. Review was read-only; the sentinel sweep is a throwaway script in
the session scratchpad (`sweep.py`) and is NOT committed.

## 1. Verdict on the claimed root cause

**The RCA's structural claim is partially falsified: the "~25 x 7 cells" model is wrong,
and the single-remedy framing (typed secrets everywhere) does not fit the evidence.**
The two-families hypothesis (c) and the untested-area hypothesis (a) are both supported;
they compose rather than compete.

Evidence:

- **The map-egress channels are centralized, not per-adapter.** `sanitize_platform_options`
  has exactly three production call sites (`runner.py:718`, `runtime_metadata.py:105`,
  `runtime_metadata.py:450`); `anonymize_result_payload` has one (`exporter.py:320`).
  A sentinel sweep constructing every registered adapter and driving the internal metadata
  build plus public anonymization showed **all 24 constructible adapters leak the identical
  key set** — the failure is one incomplete list applied everywhere, not N adapter-specific
  cells. Fixing one list fixes every adapter at once for these channels.
- **Two distinct defect families, confirmed:**
  - *Family A — value-materialisation egress* (#1333 ATTACH echo, #1345 chained cause):
    a secret is materialised into a real string (SQL literal, DSN) and a driver echoes it
    back. Key-name lists cannot help; only the code that holds the value can redact it —
    which is exactly what the ducklake fix does (`_redact_secrets` replaces the *values*
    in three encodings). SecretStr cannot help either: the value must be unwrapped to build
    the SQL.
  - *Family B — key/value-map egress* (#1346, #1364, the keyid divergence, and every new
    leak found below): a central list fails to match a key name. One-list-of-truth plus an
    invariant test fixes the whole family.
  The five prior instances split cleanly: #1333/#1345 are family A, #1346/#1364 and the
  anonymization gap are family B. A single remedy aimed at one family misses the other.
- **The untested-area hypothesis has the strongest predictive power**: a ~100-line sentinel
  sweep found five previously unknown leaking keys in under an hour (below). The gaps
  persisted because nothing measured them, not because redaction knowledge was
  architecturally unrecoverable.
- **The kernel of truth in the RCA**: for family A only the holder of the value can redact,
  and today that discipline exists in exactly 2 of 47 adapters with no base-class support.
  That argues for a shared value-aware redaction helper (ducklake's `_redact_secrets`
  generalized) — not for a 47-adapter SecretStr refactor.
- Hypothesis (b) (credentials module is the real defect) is not supported as a root cause:
  most adapters receive credentials via env/CLI/config, not the credentials module, and
  adapters must materialise raw secrets to connect. (The module has its own minor issues —
  see F12.)

## 2. Prior measurements, re-verified

| Claim | Verdict |
|---|---|
| 25 adapters hold credential-ish config | **Wrong: 47 registered adapters** (static tuple `platform_registry.py:1248-1294`, no `@register_platform` decorator exists), plus 4 dataframe adapters outside the registry. ~29 hold credential-ish config keys; 9 hold none; ~7 are env/SDK-only. |
| Only 2 adapters contain redaction | Confirmed (ducklake, motherduck). Redshift's `_sanitize_copy_credential` is quote-injection validation, not masking. |
| 6 independent redaction implementations | **Overstated: effectively 4.** `sanitize_error_message` (input_validation.py:585) redacts table/column identifiers, not credentials, and has **zero production call sites** — dead code. The two motherduck redactors are copy-paste duplicates of the same function. |
| Lists diverged: 'keyid' missing from yaml | Confirmed by execution: `AssertionError: ['keyid']`. But see F6 — *both* lists are also jointly incomplete, which the one-source-of-truth fix alone will not cure. |
| ~7 egress channels | Count roughly right, structure wrong: metadata export, public export, and MCP funnel through ~2 chokepoints; exceptions/causes/logging/SQL text are per-adapter and are effectively unprotected outside ducklake+motherduck. |
| 0 cross-cutting tests | Confirmed. |
| 25 x 7 = 175 correctness cells | **Wrong by ~7x.** Central channels: ~4 functions. Per-adapter error channels: ~10-12 adapters actually interpolate credential values into strings (ducklake, motherduck, databend, azure_synapse, redshift, clickhouse-cloud, firebolt, pg_duckdb, starrocks, doris, onehouse). True surface ≈ 25-30 cells. |

## 3. New leaks found (sentinel sweep, all verified by driving entry points)

Sweep: construct each of 47 registered adapters with sentinel credentials; drive
`build_default_normalized_result_metadata` (internal export), `anonymize_result_payload`
(public export), `get_platform_info` -> `_extract_platform_config` (the bypass path), and
constructor exception text.

| # | Leak | Channels | Severity |
|---|---|---|---|
| F1 | `api_key` / `onehouse_api_key` exported **verbatim** — quanton's only credential | internal AND public/anonymized | **high** |
| F2 | `storage_account_key` (Azure storage master key, azure_synapse) exported verbatim | internal AND public/anonymized | **high** |
| F3 | `dsn` (databend; carries `user:password@host`) exported verbatim internally; public path catches it only via the value-shape heuristic | internal | medium |
| F4 | `pg_user` and `tenant_id` bypass the public path's username/identifier pseudonymization (compact key `pguser` matches nothing) | public/anonymized | medium |
| F5 | `s3_key_id`/`kms_key_id` leak through `anonymize_result_payload` (the known TODO) — confirmed: `AKIA-SENTINEL`/`KMS-SENTINEL` survive | public layer (see §4 for severity nuance) | medium (revised, was high) |
| F6 | The planned "one source of truth" fix for F5 is insufficient as scoped: neither list contains `apikey` or `accountkey`, so unifying them still leaks F1/F2 | both | — |
| F7 | MCP tools run `ResultExporter(anonymize=False)` (benchmark.py:289, analytics.py:346) and return `exception_message=str(exception)` verbatim (errors.py:338) | MCP output | medium |
| F8 | `logger.debug(..., extra={"platform_options": platform_options})` and full `DatabaseConfig` logged raw (cli/database.py:425-433, 485-488); invisible on plain formatters, fully serialized by structured/JSON handlers incl. MCP's | logging | medium-low |
| F9 | CSV/HTML exports and `.tuning.json` bypass anonymization entirely (exporter.py:515, :579, :279-284); CSV carries a raw `error_message` column | public artifacts | medium |
| F10 | `~/.benchbox/results.db` stores full raw `platform_info` in `metadata_json` (database.py:355-412) — structural today (adapters keep secrets out of `platform_info`; verified empty leak set), but nothing enforces that | local sink | low |
| F11 | `platform.config` (`schema.py:526` via `_extract_platform_config`) and the `raw_config` fallbacks (`schema.py:538`, `builder.py:1093`) have **no secret filtering**; safe today only by adapter convention (verified: 0 sentinel leaks across all constructible adapters' `get_platform_info`) | internal export | low (structural) |
| F12 | singlestore setup persists the plaintext password to `credentials.yaml` even when validation FAILS (credentials/singlestore.py:134) and seeds the prompt with the stored plaintext | local disk | low |
| F13 | `sanitize_error_message` is dead code that redacts identifiers, not credentials — misleading inventory | — | low |
| F14 | `_redact_motherduck_token` duplicated verbatim in two modules | — | hygiene |

Constructor exceptions leaked **zero** sentinels across all 47 adapters. The dataframe
`ducklake_maintenance` ATTACH flagged during review interpolates local file paths only —
false positive, no credential exposure.

## 4. Severity revision for the anonymization TODO (F5)

On the standard pipeline, `platform_raw_config` is sanitized at capture time
(`runtime_metadata.py:105`), so a `s3_key_id` is already `<redacted>` before
anonymization runs — the missing `keyid` in the yaml is **defense-in-depth**, not a
first-line live leak. It becomes live only where raw config reaches the public payload
via the unsanitized `platform.config`/fallback paths (F11) — possible but not observed
with current adapters. Severity accordingly revised from "confirmed live security impact"
to "real defect, second-layer": still worth fixing (and the item's own w0 anticipated
re-validation), but the *actually live* public-path leaks are F1/F2/F4, which the item as
scoped does not cover.

## 5. The 4-layer proposal, assessed against this evidence

- **L3 (sentinel invariant sweep): strongly justified — build first.** It found every new
  leak above and directly measures both families' map-side. Cheap (~100 lines).
- **L2 (one source of truth for key lists): justified.** The divergence is real and
  recurring. Must ship together with list *completion* (F6), or it preserves agreement on
  an incomplete list.
- **L1 (pydantic SecretStr everywhere): not justified by observed failures.** It protects
  the accidental-repr family, which has zero observed instances (constructor sweep: 0
  leaks). It cannot protect family A (#1333: the value must be materialised into SQL) and
  is redundant with L2/L3 for family B on the export chokepoints. A 47-adapter refactor
  for a hypothetical family is over-engineering; revisit only if L3's sweep ever catches a
  repr-style leak.
- **L4 (lint on `raise ... from e` in credential-bearing excepts): marginal.** One known
  instance (#1345). A cheaper equivalent: a shared base-class redaction helper for family-A
  adapters plus L3 coverage of error paths. Fine as a follow-up, not a pillar.
- Recommended sequencing stands partially: **L3 -> L2(+list completion)**; L1 demoted to
  "only if evidence appears"; L4 optional. The proposal remains unapproved and none of it
  was built (the phase-1 sweep is throwaway and uncommitted).

## 6. Notes for phase 2 (TODO audit) fed by this review

- `anonymization-path-misses-key-id-secrets`: premise re-validated (rungs fail as
  documented) but severity revised down (§4); new items needed for F1/F2/F4 (F6 means the
  fix list must grow beyond keyid).
- `internal-result-metadata-exports-connection-usernames`: premise re-validated verbatim
  (`username`/`user` survive `sanitize_platform_options`; public path pseudonymizes) —
  exactly the internal-vs-public asymmetry the item describes.
- The environment brief's claim "every item has a w0 unit for exactly this" is wrong for
  7 of the 9 items (only the two credential items have w0 units).
