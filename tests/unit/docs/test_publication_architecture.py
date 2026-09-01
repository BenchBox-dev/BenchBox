"""Keep independent-publication authority documents aligned."""

import json
import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ROOT = Path(__file__).resolve().parents[3]
ADR = ROOT / "docs/development/adr/adr-independent-publication-authorities.md"
THREAT_MODEL = ROOT / "docs/development/independent-publication-threat-model.md"
OPERATIONS = ROOT / "docs/operations/independent-publication-contract.md"
ADR_INDEX = ROOT / "docs/development/adr/README.md"
HOSTED_CONTRACT = ROOT / "docs/reference/hosted-results-contract.md"
PHASE3_THREAT_MODEL = ROOT / "docs/reference/threat-model.md"
PUBLIC_ID_ADR = ROOT / "docs/development/adr/adr-public-result-id-permanence.md"
PHASE3_RUNBOOK = ROOT / "docs/operations/results-phase-3-runbook.md"
PHASE2_RUNBOOK = ROOT / "docs/operations/results-phase-2-runbook.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_text(path).split())


def test_adr_names_all_authority_surfaces_and_corpus_ownership() -> None:
    text = _normalized(ADR)
    required = {
        "Package releases",
        "Prose and site content",
        "Versioned API documentation",
        "Explorer application artifacts",
        "Accepted corpus archive",
        "Publication desired state",
        "Observed live state",
        "`published-results` owns the accepted corpus archive",
        "`develop` owns Explorer code and admission policy",
        "every validator-clean result",
        "exact `published-results` commit",
    }
    assert not (required - set(filter(lambda phrase: phrase in text, required)))


def test_states_are_orthogonal_and_only_receipt_proves_live() -> None:
    combined = _normalized(ADR) + " " + _normalized(OPERATIONS)
    for state in (
        "`accepted`",
        "`promotion_pending`",
        "`live`",
        "`promotion_failed`",
        "`withdrawn`",
        "Visibility",
        "Trust",
        "Ranking eligibility",
        "Deployment state",
    ):
        assert state in combined
    assert "Only an attested live receipt proves publication" in combined
    assert "A `published-results` merge proves acceptance only" in combined


def test_threat_model_covers_required_control_plane_failures() -> None:
    text = _text(THREAT_MODEL)
    required_headings = {
        "### Pull-request code execution and malicious data",
        "### GitHub token recursion and confused deputy behavior",
        "### Promotion races and stale completion",
        "### Rollback confusion and downgrade",
        "### Takedown abuse, delay, and resurrection",
    }
    assert required_headings <= set(text.splitlines())
    assert "Pull-request validation receives no publication secret" in text
    assert "compare-and-set" in text
    assert "One authorized maintainer may order emergency takedown" in text


def test_manual_review_and_single_maintainer_contract() -> None:
    combined = " ".join((_normalized(ADR), _normalized(THREAT_MODEL), _normalized(OPERATIONS)))
    assert "One authorized maintainer may approve normal promotion" in combined
    assert "One authorized maintainer may also order an emergency takedown" in combined
    assert "require manual maintainer review and MUST NOT auto-merge" in combined
    assert "A branch deletion alone must never be described as erasure" in combined


def test_existing_public_ids_are_already_compatibility_contracts() -> None:
    text = _normalized(PUBLIC_ID_ADR)

    assert "Link permanence attached when those routes first became publicly available" in text
    assert "The A0 observed baseline proves the initial protected surface" in text
    assert "The A0 observed baseline is the initial freeze line" in text
    assert "they do not postpone the compatibility obligation" in text
    assert "post-receipt id rotations" not in text
    assert "until an attested live receipt" not in text


def test_adr_is_indexed_and_accepted() -> None:
    assert "Accepted (2026-08-31)" in _text(ADR)
    assert "adr-independent-publication-authorities.md" in _text(ADR_INDEX)


def test_canonical_hosted_contract_does_not_equate_merge_with_live() -> None:
    text = _normalized(HOSTED_CONTRACT)
    operations = _normalized(OPERATIONS)
    policy_text = " ".join(
        _normalized(path) for path in (ADR, THREAT_MODEL, OPERATIONS, HOSTED_CONTRACT, PHASE3_RUNBOOK)
    )

    assert "No single `published` flag" in text
    assert "must never translate a Git merge directly into `live`" in text
    assert "Visibility is orthogonal to archive acceptance" in text
    assert "All six visibility states apply" in text
    assert "All five visibility states apply" not in text
    assert "Accepted source bytes remain preserved during the A0 freeze" in text
    assert "Accepted-but-not-live results must not be described as already published" in text
    assert '"acceptance_status": "<pending|validated|accepted|rejected>"' in _text(HOSTED_CONTRACT)
    assert '"promotion_status": "<not_requested|promotion_pending|live|promotion_failed>"' in _text(HOSTED_CONTRACT)
    assert '"presentation_status": "<active|withdrawal_requested|withdrawn|readmission_requested>"' in _text(
        HOSTED_CONTRACT
    )
    assert '"current_live_generation": "<integer or null>"' in _text(HOSTED_CONTRACT)
    assert '"current_live_receipt": "<receipt identifier or null>"' in _text(HOSTED_CONTRACT)
    assert "does not replace the currently observed live generation" in text
    assert "Keep desired state at `withdrawal_requested`" in operations
    assert "Record `withdrawn` only in observed live state" in operations
    assert "| withdrawal_requested | Authorized withdrawal event is present in desired state" in _text(OPERATIONS)
    assert "| withdrawn | A matching live receipt confirms" in _text(OPERATIONS)
    assert "affected results withdrawn and republish" not in _text(ADR)
    assert "withdrawn results are excluded from visible and ranking views before republish" not in _text(THREAT_MODEL)
    assert "The result is recorded as `withdrawn` only after a matching live receipt" in _normalized(THREAT_MODEL)
    assert "The idempotent `POST /v1/submissions` `200 OK` response MUST return this same status payload" in text
    assert "including presentation and current-live receipt fields" in text
    assert "Sets status to `withdrawn` immediately" not in _text(PHASE3_RUNBOOK)
    assert "status becomes `withdrawn` only when a matching live receipt" in _normalized(PHASE3_RUNBOOK)
    assert "| `withdrawn` | Removed by actor or admin" not in _text(PHASE3_RUNBOOK)
    assert "is withdrawn pending investigation" not in _text(PHASE3_RUNBOOK)
    assert "Withdrawal is an orthogonal presentation state, not a trust tier" in _normalized(PHASE3_RUNBOOK)
    assert "| `published` | Ingest pipeline" not in _text(PHASE3_RUNBOOK)
    assert "`validated` → `published`" not in _text(PHASE3_RUNBOOK)
    assert "| `accepted` | Ingest pipeline commits validator-clean input" in _text(PHASE3_RUNBOOK)
    assert "| `live-receipt-issued` | Attestor confirms" in _text(PHASE3_RUNBOOK)
    for forbidden in (
        "immediate presentation withdrawal",
        "add `withdrawn` to desired state",
        "mark affected results withdrawn",
        "Sets status to `withdrawn` immediately",
        "withdrawn results are excluded from visible and ranking views before republish",
    ):
        assert forbidden not in policy_text

    polling_match = re.search(
        r"#### Status polling contract.*?Response:\s*```json\s*(\{.*?\})\s*```",
        _text(HOSTED_CONTRACT),
        re.DOTALL,
    )
    assert polling_match is not None
    status_payload = json.loads(polling_match.group(1))
    assert {
        "acceptance_status",
        "promotion_status",
        "presentation_status",
        "target_generation",
        "current_live_generation",
        "current_live_receipt",
        "current_live_observed_at",
    } <= status_payload.keys()
    assert "Ingest status: `published`" not in _text(HOSTED_CONTRACT)
    assert "Withdrawn result URL behavior (Phases 1-2)" not in _text(HOSTED_CONTRACT)
    assert "accepted|live → withdrawn" not in _text(HOSTED_CONTRACT)
    assert "Acceptance or policy state" not in _text(HOSTED_CONTRACT)
    assert "tombstone remains in the index" not in _text(HOSTED_CONTRACT)
    assert "Presentation: active → withdrawal_requested → withdrawn" in text
    assert "Presentation: withdrawn → readmission_requested → active" in text
    assert "the result remains suppressed and tombstoned until a matching live receipt" in text
    assert "`readmission_requested` records an authorized desired restoration" in _normalized(ADR)
    assert "remains suppressed and tombstoned until a matching live receipt confirms" in _normalized(ADR)
    assert "## Authorized readmission" in _text(OPERATIONS)
    assert "Keep observed presentation `withdrawn` and retain the public tombstone" in operations
    assert "Record presentation `active` only after a matching live receipt confirms" in operations
    assert "Promotion: promotion_failed → promotion_pending" in text
    assert "Promotion: live → promotion_pending" in text
    assert "the prior `current_live_generation` and receipt remain observed live" in text
    assert "separate tombstone lookup registry" in text
    assert "`DELETE /v1/submissions/{submission_id}`" in text
    assert "Withdrawal must not mint or expose a `public_result_id`" in text
    assert "Because no public URL ever existed, no public tombstone is created" in text
    assert "A withdrawn result that previously had a" in text
    assert "Withdraw a never-public private result" in text
    assert "Yes, except never-public `private` results" in text
    assert "Yes for minted public IDs; no for never-public `private` results" in text
    assert "In every phase, a withdrawn result retains its" not in text
    assert "| Stable tombstone on withdrawal | Yes | Yes | Yes |" not in _text(HOSTED_CONTRACT)
    assert "| `accepted` |" in _text(HOSTED_CONTRACT)
    assert "| `live` |" in _text(HOSTED_CONTRACT)
    assert "| `published` | On commit" not in _text(HOSTED_CONTRACT)


def test_phase3_threat_model_extends_cross_phase_contract() -> None:
    text = _normalized(PHASE3_THREAT_MODEL)

    assert "independent-publication-threat-model.md" in text
    assert "public-vendor-reported" in text
    assert "vendor-supplied" in text
    assert "manual maintainer review with no auto-merge" in text
    assert "one explicit authorized-maintainer approval" in text


def test_freeze_preserves_accepted_archive_bytes_during_rollback_and_withdrawal() -> None:
    phase2 = _normalized(PHASE2_RUNBOOK)
    phase3 = _normalized(PHASE3_RUNBOOK)

    assert "For an accepted bundle, do **not** run `git revert` against `published-results`" in phase2
    assert "Removing those bytes requires a separately approved erasure exception" in phase2
    assert "`published-results` uses squash merges" in phase2
    assert "Do not use `git log --merges` or `git revert -m`" in phase2
    assert "Accepted source bytes remain in the accepted archive indefinitely" in phase3
    assert "Withdrawal suppresses presentation and ranking only" in phase3
    assert "A 180-day purge applies only to unaccepted staging data" in phase3
    assert "Rejection is valid only before archive acceptance" in phase3
    assert "rejection must never purge accepted source bytes" in phase3
    assert "The bundle is retained for 30 days" not in phase3
