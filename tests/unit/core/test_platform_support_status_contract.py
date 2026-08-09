"""Platform support-status docs drift guard — mirrors the benchmark pattern.

``docs/platforms/support-status.md`` exposes a per-support-status snapshot:
status rows with registry-derived counts (Entries, SQL-capable,
DataFrame-capable) and hand-written exposure claims (CLI exposure,
MCP exposure, Docs exposure).  Adding, removing, or re-classifying a platform
in ``benchbox.core.platform_registry`` must update the doc snapshot, and this
test fails until it does.

Sibling: ``tests/unit/core/test_benchmark_api_contract.py`` guards the
benchmark-side ``docs/benchmarks/support-status.md`` matrix.  This sibling
guards the platform-side snapshot, lines 20-27 of
``docs/platforms/support-status.md``.
"""

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

# Capture a snapshot row like:
# | `stable` | 5 | 3 | 3 | Core or ... | CLI exposure ... | MCP exposure ... | Docs exposure ... |
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
    """Parse the status snapshot table from the doc."""
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
    """Derive expected Entries/SQL/DF counts from the registry."""
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
                # Some metadata entries (e.g. document_only with no capability)
                # may not have a capability object; fall back to metadata field.
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
    """Every support_status value must have a table row.

    Adding or retiring a platform re-classifies it into a status; the doc's
    snapshot must carry a row for every status value, including zero-entry
    rows like ``repo_only`` and ``document_only``.  This ensures the snapshot
    cannot go stale when the registry gains a first entry in a previously empty
    status.
    """
    rows = _parse_snapshot_rows(SUPPORT_STATUS_DOC.read_text(encoding="utf-8"))

    assert set(rows) == _EXPECTED_STATUSES, (
        f"snapshot rows {sorted(rows)} vs expected statuses {sorted(_EXPECTED_STATUSES)}"
    )


def test_platform_support_status_counts_match_registry() -> None:
    """Entries/SQL/DF counts must be derived from the registry.

    This is the drift guard: adding, removing, or re-classifying a platform
    fails here until ``docs/platforms/support-status.md`` records the change.
    """
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
    """Every snapshot row must carry an exposure claim for CLI, MCP, and Docs.

    These columns are hand-written prose, not numeric.  The drift guard is
    that they cannot be silently emptied: a status row with an omitted exposure
    cell is a contract defect rather than a terse entry.
    """
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
    """The registry-counts HTML comment must match live counts.

    The comment block between ``<!-- benchbox-registry-counts:start -->`` and
    ``<!-- benchbox-registry-counts:end -->`` is the short prose snapshot
    consumed by dashboards.  It drifts independently of the table rows, so it
    needs its own check.
    """
    summary = PlatformRegistry.get_platform_count_summary()
    doc_text = SUPPORT_STATUS_DOC.read_text(encoding="utf-8")

    # Extract the comment block between start/end markers.
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
    # Support-status counts: the comment lists every non-zero status and
    # condenses zero-entry statuses (repo_only=0, document_only=0 are omitted
    # in the prose snapshot).  Assert that every non-zero registry count
    # appears and that no non-zero count is stale.
    missing: list[str] = []
    unexpected: list[str] = []
    for status in sorted(summary["support_status"]):
        count = summary["support_status"][status]
        fragment = f"{status}={count}"
        if count == 0:
            # Zero-entry statuses are not required to be listed in the prose.
            continue
        if fragment not in block:
            missing.append(fragment)
    # Also detect a stale count: if a listed status in the block disagrees
    # with the registry (e.g. "stable=3" when the registry has 5), the stale
    # fragment won't match the expected one — so additionally scan for status
    # fragments in the block and ensure their count is current.
    for match in re.finditer(r"(\w+)=(\d+)", block):
        status, doc_count = match.group(1), int(match.group(2))
        if status in summary["support_status"]:
            if doc_count != summary["support_status"][status]:
                unexpected.append(f"{status}={doc_count} (expected {status}={summary['support_status'][status]})")

    assert missing == [], f"platform registry-counts comment missing fragments: {missing}\nblock: {block!r}"
    assert unexpected == [], f"platform registry-counts comment has stale counts: {unexpected}\nblock: {block!r}"
