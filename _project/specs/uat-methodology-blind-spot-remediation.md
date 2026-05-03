# UAT Methodology Remediation — Design Document

> **Status:** awaiting user approval before W5 (file implementation TODOs).
> **Source TODO:** `_project/TODO/main/active/results-explorer-uat-methodology-blind-spot-remediation.yaml`
> **Triggering review:** 2026-05-03 code review of `results-explorer-uat-multi-scale-corpus-sweep`, which surfaced three L2 blind-spot findings about UAT methodology.
> **Author inputs:** `_project/handoffs/uat-methodology-w2-proposals.md` (per-finding remediation), `_project/handoffs/uat-methodology-w3-stress-test.md` (replays against three historical UATs).

## 1. Executive summary

**Recommendation:** accept all three remediations with the scoping
refinements established in W3. File **two** small implementation TODOs;
the third remediation (coverage_checklist) is convention-only and needs
no follow-up TODO. Optionally retrofit one in-flight UAT-shaped TODO
(`external-contributor-submission-dry-run`) with the terminal-state
clarification.

**Main tradeoff:** ~10 minutes of authoring overhead per future UAT in
exchange for (a) front-loaded enforcement of cross-cutting deliverables,
(b) elevated visibility on corpus quality, and (c) explicit terminal-
state declarations on submission-flow TODOs. Marginal benefit on already-
well-run UATs is small; structural benefit comes from cross-UAT
consistency and from formalising the manual reconciliations the
2026-05-02 sweep author had to do by hand.

**What's deliberately *not* in scope:** runtime tooling enforcement
(`todo_cli.py done` refusing transitions on missing checklist evidence
or unresolved gating questions). Convention + reviewer attention is the
proposed enforcement model; tooling is a lever to pull only if a future
UAT shows the convention drifting.

## 2. Per-finding remediation

### Finding 1 — Cross-scale coverage not guarded

**Source:** `_project/blind-spots/2026-05-03-081920-uat-cross-scale-deliverable-not-guarded.md`

**Root cause.** The parent UAT declared its W6 headline deliverable
("cross-scale comparison UX") in prose only. The W7 final report had no
structured slot to fill, so the agent's findings drifted to easier
surfaces (build help docs, facet labels, mobile drawer). Absence of
cross-scale findings registered as "complete" rather than "uncovered."

**Remediation.** Per-work-unit `coverage_checklist:` block, additive to
the schema (work-unit objects already accept extra fields; tested OK).
Each entry pairs a specific exercise with the evidence the W7/final
report must produce.

```yaml
work:
- id: w6
  summary: "Exercise the Results Explorer against the new corpus"
  needs: [w5]
  status: pending
  coverage_checklist:
  - id: cross_scale_per_platform
    description: |
      For >=3 platforms, view the SAME (benchmark, query) at SF=0.01, 0.1,
      and 1.0 in the explorer and capture cross-scale findings (or an
      explicit absence-of-findings note explaining why the surface was
      not exercisable).
    evidence_required: |
      W7 report contains a "Cross-scale findings" subsection with one
      entry per platform OR an explicit "no findings; here's why" note.
  - id: facet_completeness_at_scale
    description: "Apply each facet category at the SF=1.0 corpus shape"
    evidence_required: "Smoke log entry per facet category"
```

**Verification mechanism.** Convention only. The TODO author includes
the block on cross-cutting work units. The W7 reviewer flags any
unaddressed entry before the TODO moves to DONE. No tooling change.
Justification: false-positive risk from tooling enforcement (refusing
`done` on a satisfied-but-via-absence-note unit) exceeds the catch.

**Migration plan.** Apply to next UAT. No retrofit (no in-flight UAT
has a cross-cutting headline). No implementation TODO needed.

### Finding 2 — Validator-clean rate not tracked

**Source:** `_project/blind-spots/2026-05-03-081921-uat-invalid-bundle-rate-not-tracked.md`

**Root cause.** Parent UAT `success_metrics` had run-side ("80% of
viable cells passed") and submit-side ("Result JSONs successfully
submitted") metrics, but no metric for *bundle quality*. When 171/376
packaged bundles failed `validate_submission.py` (45%), the divergence
between the W3 pass count and the W5 validator-clean count had no slot
in the rubric. Per-cluster failure triage missed the structural
"passed-but-rejected" category.

**Remediation.** Two pieces:

(a) **success_metrics convention** — required on any UAT that produces
a corpus. No schema change.

```yaml
success_metrics:
- "Run matrix completed for >=80% of viable cells under the 10-minute cap"
- "Validator-clean rate: >=80% of W3-passed cells produce bundles that pass `scripts/validate_submission.py`"
- "W7 report includes per-platform and per-benchmark validator-clean rates; clusters below 50% trigger a defect TODO"
```

(b) **Runner step** — file an implementation TODO that adds an
automated `validate_submission.py` pass over every captured bundle to
the sweep driver (or as a post-sweep helper), plus a roll-up TSV the
W7 author consumes directly. Replaces the manual reconciliation the
2026-05-02 sweep author did by hand.

**Verification mechanism.** Convention + runner step (one
implementation TODO). No `todo_cli.py` floor enforcement — defensible
exceptions to the floor would otherwise block `done` and the
false-positive cost is non-trivial.

**Scope.** Runner step applies to **sweep-shape UATs only** (>1
captured bundle). Single-result UATs already implicitly run
`validate_submission.py` per bundle as part of W5.

**Migration plan.** Apply to next UAT with corpus output. No retrofit
needed (Cowork and Codex were single-result; runner step doesn't apply.
Sweep is Completed).

### Finding 3 — Submit success-metric terminal-state ambiguity

**Source:** `_project/blind-spots/2026-05-03-081922-uat-submit-success-metric-ambiguity.md`

**Root cause.** The parent UAT W5 success metric ("Result JSONs
successfully submitted via the BenchBox submission flow") had four
readable terminal states. The agent inferred `local-stage` from
validation evidence; the TODO could not have *forced* a different
choice. Open Question Q3 ("publish or stage as draft PR?") sat in the
deferable `open_questions:` list while gating the W5 deliverable —
deferable position; gating obligation.

**Remediation.** Two pieces:

(a) **Terminal-state vocabulary** for submission-flow success metrics.
Use one of:

| Term | Meaning |
|---|---|
| `local-stage` | packaged via `benchbox submit --output`, no upstream action |
| `cloud-uploaded` | posted via `benchbox submit --service` |
| `draft-pr` | PR open against `published-results`, not merged |
| `merged-to-published-results` | PR merged, CI green |

Vocab is for *intended* terminal states. Blocker-truncated runs
("stopped at validator due to hash mismatch") stay in prose; do not
expand the vocab.

```yaml
success_metrics:
- "Submission terminal state: local-stage for every passed cell (no upstream action; W6 reads from local stage)"
```

(b) **`gating: true` on open questions that change `success_metrics`.**
Allow `open_questions:` items to be either string (legacy) or object
with `question`, `gating`, `affects`, `default`, `resolved_with`.

**This requires a small backwards-compatible schema relaxation** — the
current `TODO_SCHEMA.yaml` types `open_questions` items as `string`;
the object form fails validation today (empirically tested in W2 review).

```yaml
open_questions:
- "Should the agent attempt cloud platforms at SF=0.01 only?"        # string form still valid
- question: "Does the agent need permission to publish results, or should it stage as draft PRs?"
  gating: true
  affects: ["w5 success_metric: submission terminal state"]
  default: "local-stage if validator-clean rate < 80%; draft-pr otherwise"
```

**Verification mechanism.** Convention (vocab) + schema relaxation
(`oneOf [string, object]`). No `todo_cli.py` runtime gate enforcement.
Reviewer attention is sufficient initially because the `affects:` field
makes the gate visible at completion-time review.

**Migration plan.** Apply to next UAT. **Retrofit
`external-contributor-submission-dry-run`** with one-line
terminal-state additions (its `verification` block names "PR is merged"
unambiguously, but `success_metrics` and prose don't say so). Don't
retrofit Completed UATs.

## 3. Template diff preview

No textual diff against `_project/TODO_ENTRY_TEMPLATE.yaml` is mandatory
because all three remediations validate today (Findings 1+2 require zero
schema change; Finding 3 requires the schema relaxation but the
template's example doesn't currently demonstrate `open_questions`
object form). However, **adding the example fields to the template is
recommended** so future TODO authors discover them. The template diff:

```yaml
# Add to the template (in the work[] section, with a comment):
work:
  - id: w1
    summary: "<Work unit title>"
    status: pending
    # OPTIONAL — for work units with cross-cutting deliverables only:
    coverage_checklist:
    - id: <slug>
      description: "<what to exercise>"
      evidence_required: "<what the final report must show>"

# Add to the template (in success_metrics, near submission flows):
success_metrics:
  - "Submission terminal state: <local-stage|cloud-uploaded|draft-pr|merged-to-published-results>"
  - "Validator-clean rate: >=X% of W3-passed cells pass scripts/validate_submission.py  # corpus-shaped UATs only"

# Add to the template (in open_questions, after the legacy string example):
open_questions:
  - "<Legacy string form still works>"
  - question: "<Object form for gating questions>"
    gating: true
    affects: ["<w-id> success_metric: <which one>"]
    default: "<safe default if unresolved>"
```

The schema diff (only required for Finding 3 to validate):

```yaml
# TODO_SCHEMA.yaml — replace the open_questions block (currently lines 303-307)
open_questions:
  type: array
  description: "Unresolved questions or uncertainties"
  items:
    oneOf:
      - type: string
      - type: object
        required: [question]
        properties:
          question:
            type: string
          gating:
            type: boolean
          affects:
            type: array
            items: { type: string }
          default:
            type: string
          resolved_with:
            type: string
```

The template and schema edits are themselves part of the implementation
TODOs filed in W5; this diff preview is for user review.

## 4. Migration plan

| Surface | Action | Owner |
|---|---|---|
| Next UAT | Author with all three conventions applied | UAT author |
| `external-contributor-submission-dry-run` | Optional retrofit: add explicit terminal-state line to `success_metrics` | Owner of that TODO |
| `_project/TODO_ENTRY_TEMPLATE.yaml` | Add example snippets for the three additions | Implementation TODO 2 |
| `_project/TODO_SCHEMA.yaml` | Apply `open_questions` `oneOf` relaxation | Implementation TODO 2 |
| Sweep driver / post-sweep helper | Add automated `validate_submission.py` roll-up | Implementation TODO 1 |
| Completed UATs | No action — historical record, retrofit risks audit confusion | — |
| Generalisation beyond UAT-shaped TODOs | Deferred — premature generalisation is itself a flagged pattern | — |

## 5. Open questions for the user

Each question below has a stated default and a stated consequence.
The W4 deliverable is ready to ship as-is on the defaults; user input
overrides where indicated.

1. **Accept all three remediations with W3 scoping refinements?**
   - Default: yes (W3 stress-test concluded all three survive).
   - Consequence of "no": user picks which to drop; W5 files only the
     accepted ones.

2. **Retrofit `external-contributor-submission-dry-run` with the
   terminal-state line?**
   - Default: yes (one-line addition; high clarity benefit; minimal
     author cost).
   - Consequence of "no": that TODO retains its current implicit
     terminal-state declaration. Acceptable; the `verification` block
     does name "merged" unambiguously.

3. **File two implementation TODOs (recommended) or three?**
   - Default: two — `uat-template-validator-clean-rate-runner` and
     `uat-template-success-metric-terminal-state-and-gating`. Finding 1
     is convention-only.
   - Consequence of "three": Finding 1 also files
     `uat-template-coverage-checklist-tooling` for `todo_cli.py done`
     enforcement. Recommend only if the user wants tooling teeth.

4. **Promote any of the conventions into a `_project/UAT_TEMPLATE.yaml`
   subtemplate now, or wait?**
   - Default: wait. Apply per-TODO for the next two UATs; promote once
     the conventions have proven cost/benefit.
   - Consequence of "now": file a third implementation TODO to author
     the subtemplate.

## 6. Implementation TODO list (titles only — files in W5 after approval)

Per the recommended defaults above:

1. **`uat-template-validator-clean-rate-runner`** (Small)
   Runner step that runs `validate_submission.py` over every captured
   bundle in a sweep-shape UAT and emits a per-(platform, benchmark)
   validator-clean roll-up TSV the W7 author consumes. Implements
   Finding 2's runner-side piece.

2. **`uat-template-success-metric-terminal-state-and-gating`** (Small)
   - Update `_project/TODO_SCHEMA.yaml` `open_questions` to
     `oneOf [string, object]`.
   - Update `_project/TODO_ENTRY_TEMPLATE.yaml` to demonstrate the
     terminal-state vocabulary, the validator-clean-rate metric, and
     the `coverage_checklist` block.
   - Optionally apply the one-line retrofit to
     `external-contributor-submission-dry-run` (or split into a third
     micro-TODO).

If user picks "three TODOs":
- 3. **`uat-template-coverage-checklist-tooling`** (Small) — `todo_cli.py
     done` refuses transitions when a `coverage_checklist` entry has
     no `coverage_evidence` reference. Optional teeth for Finding 1.

If user picks "promote subtemplate now":
- 4. **`uat-template-subtemplate-extract`** (Small-Medium) — extract a
     `_project/UAT_TEMPLATE.yaml` from the conventions plus the
     additions to `TODO_ENTRY_TEMPLATE.yaml`.

## Appendix — pointers to source material

- `_project/handoffs/uat-methodology-w2-proposals.md` — full per-finding
  remediation analysis (root cause / template change / verification /
  migration) plus schema reality check.
- `_project/handoffs/uat-methodology-w3-stress-test.md` — replay
  against three historical UATs plus adversarial "argument for
  dropping" framing per proposal.
- Source blind-spot files: `_project/blind-spots/2026-05-03-08192{0,1,2}-*.md`
- Review-time blind-spot findings produced by this work (recorded but
  not yet swept):
  `_project/blind-spots/2026-05-03-083859-proposals-doc-decidability-gap.md`,
  `_project/blind-spots/2026-05-03-084354-stress-test-self-bias.md`
- 2026-05-02 sweep retrospective:
  `_project/handoffs/results-explorer-uat-retrospective-20260502.md`
- Parent UAT TODO (Completed):
  `_project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml`
- Earlier dry-run retrospectives:
  `_project/handoffs/external-dry-run-retrospective-2026-04-{28,29}.md`
