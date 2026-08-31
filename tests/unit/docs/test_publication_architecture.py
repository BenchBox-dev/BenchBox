from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADR = ROOT / "docs/development/adr/adr-independent-publication-authorities.md"
THREAT_MODEL = ROOT / "docs/development/independent-publication-threat-model.md"
OPERATIONS = ROOT / "docs/operations/independent-publication-contract.md"
ADR_INDEX = ROOT / "docs/development/adr/README.md"
HOSTED_CONTRACT = ROOT / "docs/reference/hosted-results-contract.md"
PHASE3_THREAT_MODEL = ROOT / "docs/reference/threat-model.md"


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


def test_adr_is_indexed_and_accepted() -> None:
    assert "Accepted (2026-08-31)" in _text(ADR)
    assert "adr-independent-publication-authorities.md" in _text(ADR_INDEX)


def test_canonical_hosted_contract_does_not_equate_merge_with_live() -> None:
    text = _normalized(HOSTED_CONTRACT)

    assert "No single `published` flag" in text
    assert "must never translate a Git merge directly into `live`" in text
    assert "Visibility is orthogonal to archive acceptance" in text
    assert "All six visibility states apply" in text
    assert "All five visibility states apply" not in text
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
