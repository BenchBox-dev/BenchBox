"""Validate the independent publication authority decision records."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/development/adr/adr-independent-publication-authorities.md"
ADR_INDEX = ROOT / "docs/development/adr/README.md"
THREAT_MODEL = ROOT / "docs/development/independent-publication-threat-model.md"
OPERATIONS = ROOT / "docs/operations/independent-publication-contract.md"
HOSTED_CONTRACT = ROOT / "docs/reference/hosted-results-contract.md"
PHASE3_THREAT_MODEL = ROOT / "docs/reference/threat-model.md"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _require(path: Path, phrases: tuple[str, ...]) -> list[str]:
    text = _normalized(path)
    return [f"{path.relative_to(ROOT)}: missing {phrase!r}" for phrase in phrases if phrase not in text]


def main() -> int:
    failures: list[str] = []
    failures.extend(
        _require(
            ADR,
            (
                "Accepted (2026-08-31)",
                "Package releases",
                "Prose and site content",
                "Versioned API documentation",
                "Explorer application artifacts",
                "Accepted corpus archive",
                "Publication desired state",
                "Observed live state",
                "`published-results` owns the accepted corpus archive",
                "`develop` owns Explorer code and admission policy",
                "exact `published-results` commit",
                "visibility, trust, withdrawal, and ranking",
                "One authorized maintainer may approve normal promotion",
                "require manual maintainer review and MUST NOT auto-merge",
                "A branch deletion alone must never be described as erasure",
            ),
        )
    )
    failures.extend(
        _require(
            OPERATIONS,
            (
                "Only an attested live receipt proves publication",
                "A `published-results` merge proves acceptance only",
                "compare-and-set",
                "One authorized maintainer may initiate emergency takedown",
                "During the A0 migration freeze, do not delete accepted source bytes",
                "A branch deletion is not proof of erasure",
            ),
        )
    )
    failures.extend(
        _require(
            THREAT_MODEL,
            (
                "Pull-request code execution and malicious data",
                "GitHub token recursion and confused deputy behavior",
                "Promotion races and stale completion",
                "Rollback confusion and downgrade",
                "Takedown abuse, delay, and resurrection",
                "During the A0 migration freeze",
                "separately approved incident plan",
            ),
        )
    )
    failures.extend(_require(ADR_INDEX, ("adr-independent-publication-authorities.md",)))
    failures.extend(
        _require(
            HOSTED_CONTRACT,
            (
                "No single `published` flag",
                "`accepted`",
                "`promotion_pending`",
                "`live`",
                "must never translate a Git merge directly into `live`",
                "Visibility is orthogonal to archive acceptance",
                "All six visibility states apply",
                "Accepted source bytes remain preserved during the A0 freeze",
                "Accepted-but-not-live results must not be described as already published",
                "In every phase, a withdrawn result retains its",
                '"presentation_status": "<active|withdrawal_requested|withdrawn|readmission_requested>"',
                "Presentation: withdrawn → readmission_requested → active",
                "the result remains suppressed and tombstoned until a matching live receipt",
                "Presentation: active → withdrawal_requested → withdrawn",
                "separate tombstone lookup registry",
            ),
        )
    )
    failures.extend(
        _require(
            PHASE3_THREAT_MODEL,
            (
                "independent-publication-threat-model.md",
                "public-vendor-reported",
                "vendor-supplied",
                "manual maintainer review with no auto-merge",
                "one explicit authorized-maintainer approval",
            ),
        )
    )

    if failures:
        print("Publication architecture decision validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Publication architecture decision records OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
