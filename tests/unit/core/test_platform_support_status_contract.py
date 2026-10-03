from __future__ import annotations

import re
from pathlib import Path

import pytest

from benchbox.core.platform_registry import PlatformRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUPPORT_STATUS_DOC = PROJECT_ROOT / "docs/platforms/support-status.md"

_SNAPSHOT_ROW = re.compile(
    r"^\|\s*`(?P<status>[a-z_]+)`\s*\|\s*(?P<entries>\d+)\s*\|\s*(?P<sql>\d+)\s*\|\s*(?P<df>\d+)\s*\|"
    r"\s*(?P<dep_group>.*?)\s*\|\s*(?P<cli>.*?)\s*\|\s*(?P<mcp>.*?)\s*\|\s*(?P<docs>.*?)\s*\|",
)

_EXPECTED_STATUSES = {
    "stable",
    "beta",
    "experimental",
    "repo_only",
    "deprecated",
    "document_only",
}


def _parse_snapshot_rows(doc_text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in doc_text.splitlines():
        match = _SNAPSHOT_ROW.match(line)
        if match is None:
            continue
        status = match.group("status")
        rows[status] = {
            "entries": match.group("entries"),
            "sql": match.group("sql"),
            "df": match.group("df"),
            "dep_group": match.group("dep_group"),
            "cli": match.group("cli"),
            "mcp": match.group("mcp"),
            "docs": match.group("docs"),
        }
    return rows


def _expected_snapshot() -> dict[str, dict[str, int]]:
    metadata = PlatformRegistry.get_all_platform_metadata()
    expected: dict[str, dict[str, int]] = {}
    for status in _EXPECTED_STATUSES:
        platforms = PlatformRegistry.get_platforms_by_support_status(status)  # type: ignore[arg-type]
        sql = 0
        df = 0
        for name in platforms:
            caps = PlatformRegistry.get_platform_capabilities(name)
            if caps is not None:
                if caps.supports_sql:
                    sql += 1
                if caps.supports_dataframe:
                    df += 1
            else:
                meta = metadata.get(name, {})
                caps_meta = meta.get("capabilities", {})
                if caps_meta.get("supports_sql"):
                    sql += 1
                if caps_meta.get("supports_dataframe"):
                    df += 1
        expected[status] = {
            "entries": len(platforms),
            "sql": sql,
            "df": df,
        }
    return expected


def test_platform_support_status_snapshot_covers_every_status() -> None:
    rows = _parse_snapshot_rows(SUPPORT_STATUS_DOC.read_text(encoding="utf-8"))

    assert set(rows) == _EXPECTED_STATUSES, (
        f"snapshot rows {sorted(rows)} vs expected statuses {sorted(_EXPECTED_STATUSES)}"
    )


def test_platform_support_status_counts_match_registry() -> None:
    doc_text = SUPPORT_STATUS_DOC.read_text(encoding="utf-8")
    rows = _parse_snapshot_rows(doc_text)
    expected = _expected_snapshot()

    mismatched: dict[str, dict[str, dict[str, int]]] = {}
    for status in _EXPECTED_STATUSES:
        doc_entries = int(rows[status]["entries"])
        doc_sql = int(rows[status]["sql"])
        doc_df = int(rows[status]["df"])
        exp = expected[status]
        if doc_entries != exp["entries"] or doc_sql != exp["sql"] or doc_df != exp["df"]:
            mismatched[status] = {
                "doc": {"entries": doc_entries, "sql": doc_sql, "df": doc_df},
                "registry": exp,
            }

    assert mismatched == {}, f"platform support-status snapshot counts differ from registry: {mismatched}"


def test_platform_support_status_exposure_columns_are_nonempty() -> None:
    rows = _parse_snapshot_rows(SUPPORT_STATUS_DOC.read_text(encoding="utf-8"))

    missing: list[str] = []
    for status, row in rows.items():
        if not row["cli"].strip():
            missing.append(f"{status}: empty CLI exposure")
        if not row["mcp"].strip():
            missing.append(f"{status}: empty MCP exposure")
        if not row["docs"].strip():
            missing.append(f"{status}: empty Docs exposure")

    assert missing == [], f"platform snapshot rows with empty exposure cells: {missing}"


def test_platform_registry_counts_comment_matches_live_snapshot() -> None:
    summary = PlatformRegistry.get_platform_count_summary()
    doc_text = SUPPORT_STATUS_DOC.read_text(encoding="utf-8")

    start_marker = "<!-- benchbox-registry-counts:start -->"
    end_marker = "<!-- benchbox-registry-counts:end -->"
    start = doc_text.index(start_marker)
    end = doc_text.index(end_marker, start)
    block = doc_text[start:end]

    [
        f"**{summary['total']}** metadata entries",
        f"**{summary['sql_capable']}** SQL-capable",
        f"**{summary['dataframe_capable']}** DataFrame-capable",
        f"**{summary['dual_mode']}** dual-mode",
    ]
    missing: list[str] = []
    unexpected: list[str] = []
    for status in sorted(summary["support_status"]):
        count = summary["support_status"][status]
        fragment = f"{status}={count}"
        if count == 0:
            continue
        if fragment not in block:
            missing.append(fragment)
    for match in re.finditer(r"(\w+)=(\d+)", block):
        status, doc_count = match.group(1), int(match.group(2))
        if status in summary["support_status"]:
            if doc_count != summary["support_status"][status]:
                unexpected.append(f"{status}={doc_count} (expected {status}={summary['support_status'][status]})")

    assert missing == [], f"platform registry-counts comment missing fragments: {missing}\nblock: {block!r}"
    assert unexpected == [], f"platform registry-counts comment has stale counts: {unexpected}\nblock: {block!r}"
