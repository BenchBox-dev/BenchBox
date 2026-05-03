# UAT Methodology Remediation — W2 Per-Finding Proposals

> Source TODO: `_project/TODO/main/active/results-explorer-uat-methodology-blind-spot-remediation.yaml`
> Inputs: the three blind-spot files (2026-05-03-08192{0,1,2}), the
> 2026-05-02 sweep retrospective, the 2026-04-28 / 2026-04-29 dry-run
> retrospectives, the parent UAT TODO, `_project/TODO_ENTRY_TEMPLATE.yaml`,
> `_project/TODO_SCHEMA.yaml`, `_project/scripts/validate_todo.py`.
> Outputs: per-finding root cause, template change with YAML snippets,
> verification mechanism, migration plan. Feeds the W4 design document.

## Schema reality check (matters for every proposal)

`validate_todo.py` runs without `--strict` by default. Top-level
`additionalProperties: true` (TODO_SCHEMA.yaml:331) is the active
behaviour — new top-level fields validate today without a schema edit.
Work-unit objects (TODO_SCHEMA.yaml:86–117) do not set
`additionalProperties: false` either, so per-work-unit additions also
validate.

**Important exception (caught while testing the W2 snippets):**
`open_questions` items are explicitly typed `string` (TODO_SCHEMA.yaml:303–307).
Object-form entries — proposed below for Finding 3 — fail validation
today regardless of strict mode. Empirically tested:

```text
$ uv run --project _project/scripts -- python _project/scripts/validate_todo.py /tmp/uat_test.yaml
❌ /tmp/uat_test.yaml is invalid:
   • open_questions -> 1: {'question': '...', 'gating': True, ...} is not of type 'string'
```

So the cost picture is:
- **Findings 1 & 2** (coverage_checklist on a work unit;
  validator-clean-rate strings in success_metrics): zero schema change.
  Tested empirically — both validate today.
- **Finding 3** (object-form `open_questions`): requires a small,
  backwards-compatible schema relaxation to `oneOf [string, object]`.
  String-form gating questions can land as a convention without a
  schema change, but the structured `affects:` link — the value-add
  over a string — is what needs the relaxation.

The authoring/enforcement cost decision (does tooling enforce, or only
reviewer attention?) lives with the user. Per-finding recommendations are
embedded in each section's verification mechanism.

---

## Finding 1 — Cross-scale coverage not guarded

**Blind-spot file:** `2026-05-03-081920-uat-cross-scale-deliverable-not-guarded.md`

### a. Root cause

The parent UAT (`results-explorer-uat-multi-scale-corpus-sweep.yaml`)
declared the headline deliverable in *prose*, in the W6 work unit's
`notes`:

> Defects you would NOT have found without a multi-scale multi-platform
> corpus are the highest-signal findings -- call them out separately.
> Cross-scale comparison UX (SF=0.01 vs 0.1 vs 1.0 for the same
> platform/benchmark) is the headline thing this corpus enables; does the
> explorer let you actually see it cleanly?

The W7 final report (`results-explorer-uat-retrospective-20260502.md` §
"W6 Explorer UAT") lists four findings — build help docs, facet label
ambiguity, cloud facet coverage, favicon nit. None are cross-scale
findings. The W7 reviewer cannot detect the gap because every prose ask
got *some* answer, just not on the headline axis. The TODO had no
structured slot the W7 report had to fill, so absence of cross-scale
findings registered as "complete" instead of "uncovered."

The pattern generalises beyond cross-scale: any TODO whose value rests on
a specific cross-cutting surface (cross-platform, cold-vs-warm,
before-vs-after) is vulnerable when the headline is prose-only.

### b. Proposed template change

Introduce a per-work-unit `coverage_checklist:` block. Each entry pairs a
specific exercise with the evidence the W7 report (or final delivery) must
produce. Keeping it on the work unit (not the top level) localises the
obligation to the unit that actually needs to demonstrate coverage.

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
  notes: |
    The coverage_checklist is the load-bearing part of W6. Treat any
    missing evidence_required as 'unit not done'; do not mark w6 done
    until every entry is satisfied or explicitly waived in the W7 report.
```

The block is additive: legacy TODOs without it validate today
(work-unit objects already allow extra fields), and existing UATs are
unaffected unless explicitly retrofitted.

### c. Verification mechanism

**Recommendation: convention only, no tooling.** Coverage gaps are easy
to spot in the W7 report (an empty subsection or missing
absence-of-findings note is obvious to a reviewer), and false-positive
risk from tooling — refusing `done` on a unit whose checklist entry is
satisfied via an absence-of-findings note — is non-trivial. The cost
of tooling exceeds its catch.

What this looks like:
- TODO authors include `coverage_checklist:` on cross-cutting work units
  (W4 design doc lists when this applies).
- The W7 / final-report writer addresses each entry by ID.
- A reviewer flags any unaddressed entry before the TODO is moved to DONE.

If a future UAT shows the convention drifting (an entry was missed and
not caught by review), revisit and file a tooling TODO at that point
with concrete evidence of the failure mode.

### d. Migration plan

- **Apply to next UAT** authored after this plan lands (mandatory).
- **Retrofit nothing.** No currently-active UAT/dry-run TODO has a
  cross-cutting surface deliverable; the parent UAT is Completed and
  retrofitting Completed TODOs is out of scope per the parent's
  `deferred[]` list.
- **Surface limit.** This is a UAT-shaped pattern. Don't promote it to
  every TODO with a work unit — most work units don't have cross-cutting
  coverage obligations. Generalisation is itself one of the patterns the
  blind-spots flag.

---

## Finding 2 — Validator-clean rate not tracked

**Blind-spot file:** `2026-05-03-081921-uat-invalid-bundle-rate-not-tracked.md`

### a. Root cause

Parent UAT `success_metrics` (lines 690–696) included two corpus-shape
metrics — "Run matrix completed for >=80% of viable cells" and "Result
JSONs successfully submitted" — but no metric for *bundle quality*.

Concretely: W3 reported 434 passed cells. W5 reported that
`scripts/validate_submission.py` rejected 171 of 376 packaged bundles
(45%). The W3-pass-rate and W5-validator-clean-rate diverged by ~2x, and
the divergence had no structured slot. W4 triage classified failures
*per-cluster* (FlightData, Spark/PySpark, Dask, etc.) but the
"passed-but-rejected" *category itself* — silent corpus pollution where
run-time success is overcounted relative to publishability — was missing
from the rubric.

The two corpus-integrity defect TODOs that resulted
(`results-explorer-uat-defect-normalized-cost-unavailable-bundles` and
`results-explorer-uat-defect-zero-query-timing-bundles`) treat the
specific contract violations as platform/contract bugs. They are. But
the *rate* is a methodology signal that warrants its own metric and budget.

### b. Proposed template change

This is purely a `success_metrics` convention. No schema change. The new
convention is: any TODO that produces or consumes a corpus declares an
explicit validator-clean-rate floor with an evidence command, and the
W7 report (or analogous deliverable) reports the actual rate.

```yaml
success_metrics:
- "Run matrix completed for >=80% of viable cells under the 10-minute cap"
- "Validator-clean rate: >=80% of W3-passed cells produce bundles that pass `scripts/validate_submission.py`"
- "W7 report includes per-platform and per-benchmark validator-clean rates; clusters below 50% trigger a defect TODO"
```

The first two are gates. The third is a reporting requirement. Together
they make the divergence visible *at completion time*, not after the fact.

### c. Verification mechanism

**Recommendation: convention + a small runner step (one new
implementation TODO).** No `todo_cli.py` enforcement.

1. **Authoring convention.** The validator-clean rate metric is
   *required* for any UAT that produces a result corpus. The W4 design
   document lists the canonical phrasing for the W5 author to copy.
2. **Runner step.** File ONE implementation TODO to add a sweep-driver
   step (or post-sweep helper) that runs `validate_submission.py` over
   every captured bundle and emits a roll-up TSV. The parent UAT
   effectively did this by hand; formalising it removes the manual
   reconciliation step from every future W7. Cheap to write, high
   leverage; the metric otherwise relies on the W5 author remembering
   to capture it.
3. **Floor surfacing at completion.** Manual reviewer check during W7.
   Tooling enforcement is out of scope — false-positive cost (a
   defensible exception to the floor blocks `done`) is higher than
   reviewer-catch cost.

### d. Migration plan

- **Apply to next UAT** with corpus output (mandatory).
- **Retrofit `external-contributor-submission-dry-run`?** No — that
  TODO is a single-result submission flow (one contributor submits one
  bundle), so a "rate" doesn't apply. Add a singular variant ("submitted
  bundle passes `scripts/validate_submission.py`") if the success metric
  there is found ambiguous in Finding 3's review (it is — see below).
- **Project-wide policy doc?** Open Question 2 in the parent TODO. The
  recommendation is per-TODO for now: project-wide creates a second
  surface to drift from and is harder to audit. Promote to project-wide
  after the next two UATs use the convention and we see that it sticks.

---

## Finding 3 — Submit success-metric terminal-state ambiguity

**Blind-spot file:** `2026-05-03-081922-uat-submit-success-metric-ambiguity.md`

### a. Root cause

Parent UAT `success_metrics` (line 692) reads:

> Result JSONs successfully submitted via the BenchBox submission flow for
> the successful cells.

"Submitted via the submission flow" has at least four readable terminal
states:
- `local-stage` — packaged via `benchbox submit --output`, no upstream action
- `cloud-uploaded` — posted via `benchbox submit --service`
- `draft-pr` — PR opened against `published-results` in draft state
- `merged-to-published-results` — PR landed and CI green

The agent picked `local-stage` (correctly, given the validation failures
discovered along the way). But that choice was inferred from evidence,
not authorised by the TODO. Open Question 3 (lines 704–705) asked
explicitly:

> Does the agent need permission to publish results, or should it stage
> submissions as draft PRs against `published-results` for human review?
> Draft-PR is the safer default.

— and it sat in the *deferred* `open_questions:` list while gating the
W5 deliverable. That position permits deferral; the question deserved
gating.

The pattern repeats in `external-contributor-submission-dry-run.yaml`:
its `verification` block names "External contributor's PR is merged with
community-submission trust label" (an unambiguous terminal state), but
its prose `success_metrics` and W3/W4 work units talk about "watching
them perform the full submission" and "the resulting PR" — leaving the
terminal state implicit again.

### b. Proposed template change

Two pieces, both additive.

**Piece 1 — Terminal-state vocabulary for submission-flow success metrics.**
A small canonical list, used verbatim. The W4 design document includes a
copy-pastable table.

```yaml
# Submission-flow vocabulary (use one):
#   local-stage                 — packaged via `benchbox submit --output`
#   cloud-uploaded              — posted via `benchbox submit --service`
#   draft-pr                    — PR open against `published-results`, not merged
#   merged-to-published-results — PR merged, CI green
success_metrics:
- "Submission terminal state: local-stage for every passed cell (no upstream action; W6 reads from local stage)"
- "Validator-clean rate: >=80% of locally-staged bundles pass `scripts/validate_submission.py`"
```

**Piece 2 — `gating: true` on open questions that change `success_metrics`.**
Allow `open_questions:` entries to be either a string (legacy) or an
object with `question`, `gating`, `affects`. **This requires a small
schema relaxation** — the current schema explicitly types
`open_questions` items as `string`, so the object form fails validation
today. Schema change is backwards-compatible: string-form entries continue
to validate.

```yaml
open_questions:
# Legacy string form still validates:
- "Should the agent attempt cloud platforms (Snowflake/etc) at SF=0.01 only?"

# Object form for gating questions:
- question: "Does the agent need permission to publish results, or should it stage as draft PRs against published-results?"
  gating: true
  affects: ["w5 success_metric: submission terminal state"]
  default: "local-stage if validator-clean rate < 80%; draft-pr otherwise"
```

The convention: any `open_questions` entry with `gating: true` blocks
the work unit named in `affects` from being marked `done` until the
question is resolved (either deleted or answered with `resolved_with:`).

### c. Verification mechanism

**Recommendation: convention + schema relaxation (one
implementation TODO bundling both pieces). No `todo_cli.py` enforcement
in this plan.**

1. **Authoring convention.** Submission-flow success metrics use the
   four-word vocabulary verbatim. The W4 design document is the reference.
2. **Schema relaxation** (required for Piece 2 to validate). Update
   `TODO_SCHEMA.yaml` `open_questions` to:

   ```yaml
   open_questions:
     type: array
     items:
       oneOf:
         - type: string
         - type: object
           required: [question]
           properties:
             question: { type: string }
             gating: { type: boolean }
             affects: { type: array, items: { type: string } }
             default: { type: string }
             resolved_with: { type: string }
   ```

   Backwards-compatible: string-form entries still pass.
3. **`gating: true` runtime enforcement** (refusing `todo_cli.py done`
   on a unit listed in `affects:` of a still-gating question) is **out of
   scope for this plan.** File only if a future UAT shows the convention
   drifting. Reviewer attention is sufficient initially because the
   `affects:` field makes the gate visible at completion-time review.

### d. Migration plan

- **Apply to next UAT** (mandatory). Submission terminal state must be
  named explicitly.
- **Retrofit `external-contributor-submission-dry-run`** —
  recommended. The terminal state is implicit (PR merged, per
  `verification`), but the `success_metrics` and prose don't say so.
  One-line additions; minimal author cost; high clarity benefit. The
  W4 design document includes the exact diff.
- **Don't retrofit Completed UATs.** Audit confusion outweighs benefit.
- **`gating: true` adoption** is opt-in initially. Recommend authors use
  it for any open_question whose answer would change a success_metric or
  must_preserve entry.

---

## Cross-cutting decisions left for the user (W4 will surface)

1. **Implementation TODO count.** Recommended: **two** TODOs filed in W5,
   not three.
   - `uat-template-validator-clean-rate-runner` — runner step that
     reports validator-clean rate after every UAT sweep. Covers Finding
     2's runner step.
   - `uat-template-success-metric-terminal-state-and-gating` — combined:
     adds the terminal-state vocabulary doc and the schema relaxation
     for object-form `open_questions`. Covers Finding 3.
   - Finding 1 (coverage_checklist) is convention-only; **no
     implementation TODO** beyond merging this plan's example into the
     W4 design document.
   - Plus optional retrofit of `external-contributor-submission-dry-run`
     (one-line success-metrics tightening), which can be folded into
     either the Finding 3 TODO or filed as its own micro-TODO depending
     on review preference.
2. **Schema strict-mode default?** Today `additionalProperties: true` at
   top level means even malformed conventions validate. Flipping the
   default to strict would catch typos but breaks any legacy TODO with
   extra fields. Recommend: leave as-is; rely on reviewer attention plus
   explicit documentation.
3. **Project-wide UAT policy doc vs per-TODO conventions?** Per-TODO is
   easier to drift from but easier to author. Recommend: per-TODO for
   the next two UATs; promote to a `UAT_TEMPLATE.yaml` subtemplate once
   the conventions have proven their cost/benefit.
