# ADR Audit: Day-1 Executability Dry-Run for Repo-Shape Decisions

**Date**: 2026-09-06
**Status**: Completed audit; findings captured locally per `[REVIEW-AUTH-001]`.
**Scope**: `docs/development/adr/` (19 ADR files examined; 5 candidate repo-shape ADRs audited).
**Origin**: Promoted from deferral #176 of `extend-five-axis-review-rubric` via blind-spot `2026-05-03-092657`.

---

## 1. Audit Context & Objective

Blind-spot `2026-05-03-092657` identified a systematic review blind spot in the five-axis rubric:
> When an ADR proposes an operational repository-shape change (branch-shape change, CI workflow move, cross-branch vendoring), review tends to assess narrative soundness but overlook **day-1 executability** against external consumers.

The rubric check requires:
1. Enumerate all external consumers of the affected branch or boundary (CI workflows, contributor flows, build automation, downstream branches, documentation).
2. Confirm each consumer works against the proposed end state using only the ADR stated allowlist, exclusions, and runtime requirements.

This audit spot-checks historical and active repo-shape ADRs in `docs/development/adr/` against this dry-run rubric to establish whether their proposed end states were executable at write time and what residual gaps emerged.

---

## 2. Candidate Enumeration

All 19 ADRs in `docs/development/adr/` were reviewed. Five propose operational repository-shape, branch-shape, or cross-boundary packaging changes:

1. `adr-published-results-slim-corpus-branch.md` (2026-05-03): Defines `published-results` as a slim orphan branch with a strict allowlist.
2. `adr-published-results-history-retention.md` (2026-08-04): Evaluates retaining vs rewriting git history on `published-results` following path/pseudonym exposure.
3. `adr-independent-publication-authorities.md` (2026-08-31): Separates publication into 7 independent authority surfaces across `release`, `develop`, `published-results`, manifest, and live receipts.
4. `adr-duckdb-datasketches-vendoring.md` (2026-05-06): Rejects binary vendoring in favour of extension smoke monitoring.
5. `adr-clickhouse-server-containerization.md` (2026-08-23): Establishes containerized 5.25 GiB memory envelope for ClickHouse server across Linux Docker and macOS Apple Container.

---

## 3. Detailed Audit Findings

### Candidate 1: `adr-published-results-slim-corpus-branch.md`
- **Proposed shape**: Orphan branch containing only corpus data, inventory, and minimal submission validator scripts.
- **Consumer Enumeration**:
  - CI workflow: `.github/workflows/validate-submission.yml`
  - Contributor flow: `docs/contributing-results.md` PR submissions
  - Automation: `sync-results-data-to-published.yml`
  - Explorer build pipelines: `docs.yml`, `results-explorer-browser.yml`
- **Dry-run Outcome**: **FAIL at write time (caught & amended)**.
  - The original write-time allowlist included `validate-submission.yml` but excluded `pyproject.toml` and `uv.lock`. The workflow executed `uv run scripts/validate_submission.py`, which immediately failed because `uv run` requires project configuration metadata.
  - Resolution: The ADR and implementation were updated to decouple the validator from `uv run` and provide standalone fallback imports.
- **Verdict**: Proven example validating the necessity of the Day-1 Dry-Run rubric.

### Candidate 2: `adr-published-results-history-retention.md`
- **Proposed shape**: Retain public branch history without rewriting/force-pushing.
- **Consumer Enumeration**:
  - Outside contributors with existing forks/clones
  - Sync automation and scheduled drift canaries
  - Static explorer data pipeline
- **Dry-run Outcome**: **PASS**.
  - The ADR explicitly walked consumer impact: force-pushing would corrupt existing contributor forks and tracking branches. Retaining history preserved operational continuity across all consumers.
- **Verdict**: Fully compliant with day-1 consumer executability analysis.

### Candidate 3: `adr-independent-publication-authorities.md`
- **Proposed shape**: Decouple package releases, documentation, Explorer app, and corpus into independent authority lanes with manifest-driven deployment.
- **Consumer Enumeration**:
  - Release workflows (`release.yml`)
  - Site & API docs lane (`docs.yml`)
  - Publication transaction controller (`publication-transaction.yml`)
  - Live probe & attestor infrastructure
- **Dry-run Outcome**: **PASS conceptually, PARTIAL implementation gap (subsequently remediated)**.
  - Conceptual separation is airtight. However, during subsequent transaction controller implementation (`publication-transaction.yml:427-440`), a dry-run defect surfaced: the candidate verification step expected `desired-manifest.json` on a fresh runner without an explicit artifact download step across runner boundaries.
  - Subsequent remediation: PR #2085 consolidated publication approval around immutable candidates and resolved this boundary defect by adding explicit cross-runner artifact retention (`publication-candidate-receipts-$TRANSACTION_ID`) and fallback artifact download steps to the verification runner.
  - Recommendation: Future operational ADRs specifying multi-job CI controllers must enumerate runner workspace lifecycle and artifact transfer boundaries.
- **Verdict**: Conceptually sound; implementation required artifact-transfer remediation (resolved in PR #2085).

### Candidate 4: `adr-duckdb-datasketches-vendoring.md`
- **Proposed shape**: Reject binary vendoring under `_binaries/datasketches/`; use on-demand community extension install with daily smoke canary.
- **Consumer Enumeration**:
  - Benchmark runners executing write primitives sketch operations on DuckDB
  - CI smoke test (`extension-smoke.yml`)
- **Dry-run Outcome**: **PASS with explicit accepted limitation**.
  - Consumers executing `theta` and `frequent_items` ops on DuckDB encounter known failures when the community extension build omits those families. The ADR made this an explicit, accepted trade-off to avoid bloating repo history with 40-90 MB of platform binaries.
- **Verdict**: Compliant; trade-off explicitly documented with active canary monitoring.

### Candidate 5: `adr-clickhouse-server-containerization.md`
- **Proposed shape**: 5.25 GiB containerized memory envelope on Linux Docker and macOS Apple Container.
- **Consumer Enumeration**:
  - Linux CI matrix runners
  - macOS local development and UAT runners
  - TPC-H and TPC-DS benchmark suites
- **Dry-run Outcome**: **PASS for TPC-H; PARTIAL for TPC-DS**.
  - TPC-H SF1 passes 66/66 queries within 5.25 GiB on both Linux and macOS. TPC-DS SF1 loads within the memory boundary but experiences query compatibility failures during the power phase. The ADR properly disclosed that TPC-DS is not certified until query fixes land.
- **Verdict**: Compliant; memory envelope verified; query compatibility boundary preserved.

---

## 4. Conclusion & Recommendations

1. The Day-1 Dry-Run sub-axis added to the review framework in `.claude/skills/code/references/five-axis-review.md` directly catches the failure mode demonstrated by Candidate 1 and Candidate 3.
2. No historical ADR texts require retrofitting or rewriting (preserving decision record immutability).
3. The audit findings validate that recent architectural decisions (e.g. Candidates 2 and 5) successfully incorporated consumer enumeration and executability checks during review.
