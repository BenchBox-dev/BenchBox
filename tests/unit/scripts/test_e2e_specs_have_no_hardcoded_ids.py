from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
E2E_ROOT = REPO_ROOT / "results-explorer" / "e2e"

LONG_ID_RE = re.compile(r"[a-z_]+-[a-z0-9-]*sf[0-9.]+-\d{8}-[0-9a-f]{8}")

SHORT_ID_RE = re.compile(r"(?<![#\w])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{8}(?:[0-9a-f]{2})*(?![\w])")

_LINE_COMMENT_RE = re.compile(r"//.*$", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def _spec_sources() -> list[Path]:
    return sorted(
        path
        for path in E2E_ROOT.rglob("*.ts")
        if not any(part.endswith("-output") for part in path.relative_to(E2E_ROOT).parts)
    )


def test_the_spec_tree_is_present() -> None:
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
        'baseline_audit: "_project/audits/results-explorer-usability-20260507.md",',
    ],
)
def test_the_short_id_detector_ignores_non_identifier_hex(benign: str) -> None:
    assert not SHORT_ID_RE.search(benign)


def test_comments_are_not_scanned() -> None:
    assert not LONG_ID_RE.search(_strip_comments("// was tpch-duckdb-sf0.01-20260403-010ee756"))
    assert not SHORT_ID_RE.search(_strip_comments("/* short ids look like 0f0add9f */"))
