"""Validate the independent publication authority decision records."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/development/adr/adr-independent-publication-authorities.md"
ADR_INDEX = ROOT / "docs/development/adr/README.md"
THREAT_MODEL = ROOT / "docs/development/independent-publication-threat-model.md"
OPERATIONS = ROOT / "docs/operations/independent-publication-contract.md"


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
            ),
        )
    )
    failures.extend(_require(ADR_INDEX, ("adr-independent-publication-authorities.md",)))

    if failures:
        print("Publication architecture decision validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Publication architecture decision records OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
