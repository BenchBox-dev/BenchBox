# Query-Plan Capture Subsystem Remediation

Source: adversarial review of the query-plan capture pipeline (capture → parse →
model/fingerprint → serialize → load → consume) conducted 2026-07-04 on branch
`claude/query-plan-capture-review-hjwlm2`. Findings are referenced below by the
review's numbering (e.g. F1.1 = finding 1.1 "loader discards plans").

Each YAML item in `planning/` is one PR-sized work package and carries the
standard delivery loop as explicit work steps:

1. **create** — implement the change with tests
2. **review** — adversarial code review of the diff
3. **fix** — address review findings, re-run verification
4. **submit PR** — push branch, open PR referencing the TODO item id

## Sequencing (dependency order)

| # | Item | Priority | Findings | Depends on |
|---|------|----------|----------|------------|
| 01 | plan-rehydration-and-phases-view | Critical | F1.1, F1.3, F7.1, F8.1 (keystone test) | — |
| 02 | loader-roundtrip-fidelity | High | F1.4 | 01 |
| 03 | fingerprint-signature-v2 | High | F2.1, F2.2 | — |
| 04 | capture-timeout-and-analyze-default | High | F4.1, F5.2 | — |
| 05 | silent-failure-surfacing | Medium | F4.2, F4.3, F4.4, F2.3 | 01 |
| 06 | cross-platform-capture-wiring | High (large) | F3.1, F3.2, F3.3, F3.4 | 01, 03 |
| 07 | plans-companion-hardening | Medium | F1.5, F1.6, F1.7 | 01 |
| 08 | history-and-plan-metadata-wiring | Medium | F1.2, F7.2 | 01 |
| 09 | df-timing-semantics | Medium | F5.1 | — |
| 10 | concurrency-and-depth-limits | Low | F6.1, F5.3 | — |
| 11 | plan-cli-test-democking | Medium | F8.1 (sweep) | 01 |

Items 01–02 restore basic end-to-end function; 03–05 make the data trustworthy;
06 extends the pipeline beyond DuckDB; 07–11 harden the tail. Items without
dependencies (03, 04, 09, 10) can proceed in parallel with 01/02.

## Ground rules for every item

- No new plan feature ships without a no-mock round-trip test
  (export → load → consume on real files).
- Fingerprint changes must bump `fingerprint_version`; never compare
  fingerprints across versions.
- Failures must be distinguishable by users: "not captured" vs "capture
  failed: <reason>" vs "captured but file failed to load: <reason>".
- Review-stage repro scripts exist as a starting point for regression tests
  (export→load→show-plan, fingerprint collisions, timeout ineffectiveness).
