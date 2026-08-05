"""No browser spec may hardcode a content-addressed fixture identifier.

`result_id` ends in a SHA prefix of the published bundle bytes and `short_id`
is derived from `result_id`, so both move whenever fixture content *or*
anonymization output changes. Specs hardcoded them and drifted: the literals
checked in matched neither the pre- nor the post-#1512 build, and the Chromium
job - which is named "blocking" - failed on every PR that ran it while nobody
noticed.

The first fix replaced only the three literals someone had a list of and left
four more in the same files, so the suite stayed red. This gate exists because
enumerating by hand is exactly what failed: it matches the *shape*, so a new
spec cannot reintroduce the class.

The supported way to address a fixture is `fixtureIds.ids.<role>` /
`fixtureIds.shortIds.<role>` from `e2e/support/fixtures.ts`, which reads the
`fixture-ids.json` emitted by `scripts/generate-browser-fixtures.mjs`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
E2E_ROOT = REPO_ROOT / "results-explorer" / "e2e"

# `tpch-duckdb-sf0.01-20260403-6fa432a0` and friends. The trailing hex is the
# content address, which is the part that moves.
LONG_ID_RE = re.compile(r"[a-z_]+-[a-z0-9-]*sf[0-9.]+-\d{8}-[0-9a-f]{8}")

# A short id is an 8+-hex run (widened by 2 on collision, see `_build_short_ids`).
#
# Deliberately NOT anchored to quote characters. The literal that survived the
# first fix was interpolated into a template string - `ids=${SHORT},0f0add9f` -
# where the character before it is a comma, so a quote-anchored pattern reports
# the file clean. The lookarounds instead reject the two things that are hex but
# not identifiers: a CSS colour (preceded by `#`) and a longer word.
#
# Requiring at least one digit AND at least one a-f letter rejects the two
# false positives this tree actually contains: an all-alphabetic word, and an
# eight-digit `YYYYMMDD` inside an audit filename. The cost is a blind spot -
# an all-digit short id, about 2.3% of sha256 prefixes - which is accepted
# because the alternative is a gate that fails on every dated path and gets
# disabled. The long-id detector above covers the `-YYYYMMDD-<hash>` form
# regardless.
SHORT_ID_RE = re.compile(r"(?<![#\w])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{8}(?:[0-9a-f]{2})*(?![\w])")

_LINE_COMMENT_RE = re.compile(r"//.*$", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    """Drop comments so prose about ids is not mistaken for a used id."""
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def _spec_sources() -> list[Path]:
    """Every TypeScript source under e2e/, excluding captured output.

    Capture specs write DOM snapshots and reports into `*-output/` directories;
    those are generated evidence that legitimately contains real ids.
    """
    return sorted(
        path
        for path in E2E_ROOT.rglob("*.ts")
        if not any(part.endswith("-output") for part in path.relative_to(E2E_ROOT).parts)
    )


def test_the_spec_tree_is_present() -> None:
    """Without this, a move or rename makes every assertion below vacuous."""
    assert E2E_ROOT.is_dir(), f"missing spec tree: {E2E_ROOT}"
    assert _spec_sources(), "no e2e TypeScript sources found - this gate would be vacuous"


def test_no_spec_hardcodes_a_long_result_id() -> None:
    offenders: list[str] = []
    for path in _spec_sources():
        for number, line in enumerate(_strip_comments(path.read_text(encoding="utf-8")).splitlines(), start=1):
            if LONG_ID_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "spec(s) hardcode a content-addressed result id; use fixtureIds.ids.<role> instead:\n" + "\n".join(offenders)
    )


def test_no_spec_hardcodes_a_short_id() -> None:
    offenders: list[str] = []
    for path in _spec_sources():
        for number, line in enumerate(_strip_comments(path.read_text(encoding="utf-8")).splitlines(), start=1):
            if SHORT_ID_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "spec(s) hardcode a short id; use fixtureIds.shortIds.<role> instead:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "planted",
    [
        'const DETAIL_ID = "tpch-duckdb-sf0.01-20260403-010ee756";',
        'const AWS_ID = "tpch-fixture-aws-sql-sf0.01-20260403-e73da6ce";',
        "await page.goto(`/results/r/star_schema-duckdb-sf0.01-20260403-d040a5b7`);",
    ],
)
def test_the_long_id_detector_fires_on_a_planted_literal(planted: str) -> None:
    """A clean tree and a broken detector look identical, so pin the detector.

    The third case is the one a `const NAME = "..."` pattern would miss: an id
    interpolated straight into a URL. An earlier hand-written grep matched only
    the assignment form and reported the tree clean with four literals in it.
    """
    assert LONG_ID_RE.search(planted)


@pytest.mark.parametrize(
    "planted",
    [
        'const SHORT_DUCKDB = "ba6a8c83";',
        '  shortId: "009ee9fd",',
        "ids=${SHORT_DUCKDB},0f0add9f",
    ],
)
def test_the_short_id_detector_fires_on_a_planted_literal(planted: str) -> None:
    assert SHORT_ID_RE.search(planted)


@pytest.mark.parametrize(
    "benign",
    [
        "const ACCENT = `#ff00ff`;",
        "const ACCENT_ALPHA = `#0f0add9f`;",
        "await expect(page.getByTestId(`facadeface`)).toBeVisible();",
        "const WIDTHS = [390, 768, 1280, 1600];",
        # A dated audit path. This one is real: it lives in
        # pr246-final-evidence.spec.ts and failed an earlier draft of this gate.
        'baseline_audit: "_project/audits/results-explorer-usability-20260507.md",',
    ],
)
def test_the_short_id_detector_ignores_non_identifier_hex(benign: str) -> None:
    """Eight hex characters are common; a colour, a word, or a date is not an id."""
    assert not SHORT_ID_RE.search(benign)


def test_comments_are_not_scanned() -> None:
    """Prose naming a historical id must not fail the gate that removed it."""
    assert not LONG_ID_RE.search(_strip_comments("// was tpch-duckdb-sf0.01-20260403-010ee756"))
    assert not SHORT_ID_RE.search(_strip_comments("/* short ids look like 0f0add9f */"))
