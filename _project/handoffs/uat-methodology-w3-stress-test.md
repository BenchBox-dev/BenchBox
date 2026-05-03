# UAT Methodology Remediation — W3 Stress-Test

> Source TODO: `_project/TODO/main/active/results-explorer-uat-methodology-blind-spot-remediation.yaml`
> Replays each W2 proposal against the three reference UATs:
> 2026-04-28 Cowork dry-run, 2026-04-29 Codex dry-run, 2026-05-02 sweep.
> Per replay: would the proposal have caught the failure? Would it have
> generated false positives? Would the template have been onerous to
> author?

## Reference UATs at a glance

| UAT | Shape | Headline outcome |
|---|---|---|
| 2026-04-28 Cowork | Single-result, sandbox-cold, no auth | 11 friction items → 6 follow-up TODOs |
| 2026-04-29 Codex | Single-result, real env, against `published-results` clone | Surfaced Critical hash-contract mismatch; stopped at local validator |
| 2026-05-02 sweep | Multi-platform multi-scale corpus; explorer + submission | 14 follow-up TODOs; cross-scale-coverage gap, 45% invalid bundle rate, ambiguous terminal state |

The first two are **single-result** UATs (one bundle through one flow). The
third is **multi-result sweep** (388 captured bundles across 21 platforms /
19 benchmarks). The proposals must serve both shapes without becoming
ceremonial in the smaller one.

## Proposal 1 — coverage_checklist on work units (convention only)

| UAT | Catches the failure? | False-positive risk? | Authoring cost |
|---|---|---|---|
| 2026-04-28 Cowork | N/A — no cross-cutting deliverable. Cowork's W3 ("capture friction without intervening") could optionally use coverage entries like "evidence_required: at least one friction item per documented step (1–5)". Cowork already did this in practice (11 items, all steps). | Low — entries are descriptive. | 5 min if applied. |
| 2026-04-29 Codex | N/A — Codex stopped at validator step before reaching multi-axis surfaces. Same optional applicability as Cowork's W3. | Low. | 5 min if applied. |
| 2026-05-02 sweep | **Direct hit** on the cross-scale gap. The W6 prose ask ("Cross-scale comparison UX is the headline thing this corpus enables; does the explorer let you actually see it cleanly?") translates line-for-line into a checklist entry; the W7 reviewer would have flagged the missing subsection. | Low — absence-of-findings note is a documented escape. | 5 min for the UAT author; almost free if templated. |

**Verdict:** Survives replay with no false positives across three UATs.
Catches the headline failure for the source case (sweep), redundant-but-
harmless for the two single-result UATs. **No simplification needed.**
Refinement: explicitly scope coverage_checklist to work units that have
cross-cutting / multi-axis deliverables. Don't push it onto every work
unit.

## Proposal 2 — validator-clean rate metric + runner step

| UAT | Catches the failure? | False-positive risk? | Authoring cost |
|---|---|---|---|
| 2026-04-28 Cowork | Trivially: 1 bundle, 0 errors → 100% validator-clean rate. Adds ritual without signal. | Nil. | 1 line in success_metrics. |
| 2026-04-29 Codex | **Loud signal even though root cause differs.** Codex's bundle failed validation due to the hash-contract mismatch (a definitional bug, not corpus pollution); a "0/1 validator-clean" rate would still surface the failure as the headline number, which is the right outcome regardless of the underlying cause. | Low — 0% is loud no matter what. | 1 line. |
| 2026-05-02 sweep | **Direct hit.** 45% validator-clean rate would have been the headline number rather than buried in §"W5 Submission Flow". The runner step would have replaced the manual `validate_submission.py` reconciliation that the sweep author did by hand. | Low — the rate is observed, not inferred. | 1 line in success_metrics; runner step is a one-shot tool change with leverage across every future sweep. |

**Verdict:** Survives replay. The metric is universally cheap (one line);
the runner step is high-leverage for sweep-shape UATs and unnecessary
for single-result UATs.

**Refinement:** Scope the runner step to **sweep-shape UATs**
(>1 captured bundle). Single-result UATs already implicitly run
`validate_submission.py` per bundle as part of W5; no separate step
needed.

## Proposal 3 — terminal-state vocabulary + `gating: true` open questions

| UAT | Catches the failure? | False-positive risk? | Authoring cost |
|---|---|---|---|
| 2026-04-28 Cowork | Terminal state was `local-stage` ("would-have-pushed"); the parent TODO didn't specify. Vocab would have made it explicit. Cowork's blocker (no GitHub auth) was structural, not a gating-question failure — `gating: true` doesn't apply. | Low — vocab is descriptive. Reviewer-attention model for gating questions can under- or over-flag. | One-line vocab swap; gating field only used when applicable. |
| 2026-04-29 Codex | Terminal state was "stopped at local validator due to hash mismatch" — outside the four-word vocab. Recommend prose handles partial-stop states; vocab covers the intentional terminal states. The hash mismatch wasn't gated by Q3 (publish vs draft PR), so `gating: true` doesn't help here. | Low. | Minimal. |
| 2026-05-02 sweep | **Direct hit on both pieces.** Vocab disambiguates the W5 success metric. `gating: true` on Q3 would have forced resolution before W5 started, removing the "agent inferred from evidence" pattern. The schema relaxation is what makes the structured `affects:` link possible. | Schema relaxation: nil — `oneOf` is backwards-compatible. Gating-attention model: low; reviewer can flag at completion-time review. | Vocab line + optional object-form question. Minimal. |

**Verdict:** Survives replay. Direct hit on source case; harmless for
single-result UATs that don't have ambiguous terminal states.

**Refinement:** Don't try to expand the vocab to cover blocker-truncated
runs (e.g., "stopped at validator"). Prose handles stops well; vocab is
for *intended* terminal states.

## Cost rollup

Total authoring overhead per future UAT, assuming all three proposals
applied:

| Item | Time |
|---|---|
| coverage_checklist on cross-cutting work units (when applicable) | ~5 min |
| validator-clean rate line + (sweep only) runner step note | ~2 min |
| Terminal-state vocab + (when applicable) gating: true on Q | ~3 min |
| **Total per UAT** | **~10 min** |

Tooling overhead delivered by W5:

| TODO | Effort | Beneficiaries |
|---|---|---|
| `uat-template-validator-clean-rate-runner` | Small (one runner step, one TSV roll-up) | All future sweep-shape UATs |
| `uat-template-success-metric-terminal-state-and-gating` | Small (schema relaxation + doc) | Any UAT with terminal-state ambiguity or gating questions |

## Findings to feed W4

1. All three proposals survive replay. None need to be dropped.
2. Two refinements (already folded into the W2 doc by the
   `/code review` corrections):
   - coverage_checklist scoped to cross-cutting work units only
   - validator-clean runner step scoped to sweep-shape UATs
3. **Net cost:** ~10 min/UAT authoring + two small implementation TODOs.
   Marginal benefit for *well-run* UATs (they already capture most of
   this); structural benefit comes from consistency across future UATs
   and from formalising what the 2026-05-02 sweep had to do by hand.
4. **No new blind spots surfaced** during the stress test. Replays were
   all "no false positives, low cost, catches the source failure" —
   suggesting either (a) the proposals are well-targeted, or (b) the
   stress-test surface (three retrospectives) is too narrow. To partly
   address (b), a future fourth UAT (single result, on a clean release)
   would be a useful third data point for the single-result shape.
