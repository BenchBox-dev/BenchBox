"""Tests for scripts/phase2_metrics.py.

Covers the parsing helpers and metric functions. The gh CLI is not
exercised here — those code paths take a list[dict] | GhError and we
inject both shapes directly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from phase2_metrics import (
    DATE_LINE_RE,
    ORG_LINE_RE,
    REQUESTER_LINE_RE,
    SECTION_BLOCKED,
    SECTION_ORG,
    SECTION_PRIVATE,
    GhError,
    MetricResult,
    _count_distinct_lowercased,
    _count_entries,
    _glyph,
    _split_sections,
    _trigger_q1_size,
    _trigger_q2_pr_volume,
    build_payload,
    compute_trend,
    find_prior_review,
    metric_backlog,
    metric_merged_volume,
    metric_qualitative,
    metric_review_latency,
    parse_prior_metrics,
    render_trend_section,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)


def _pr(merged_offset_days: float | None, created_offset_days: float | None = None) -> dict:
    """Build a minimal gh-shaped PR dict.

    `*_offset_days` is days BEFORE NOW (positive = past). None = field absent.
    """
    out: dict = {}
    if merged_offset_days is not None:
        out["mergedAt"] = (NOW - timedelta(days=merged_offset_days)).isoformat().replace("+00:00", "Z")
    if created_offset_days is not None:
        out["createdAt"] = (NOW - timedelta(days=created_offset_days)).isoformat().replace("+00:00", "Z")
    return out


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


class TestSplitSections:
    def test_extracts_sections_keyed_by_h2(self):
        text = "# Title\n\n## Foo\n\nfoo body\n\n## Bar\n\nbar body\n"
        sections = _split_sections(text)
        assert "Foo" in sections and "Bar" in sections
        assert "foo body" in sections["Foo"]
        assert "bar body" in sections["Bar"]

    def test_ignores_h1_and_h3(self):
        text = "# H1\n## Real\nbody\n### Sub\nnope\n"
        sections = _split_sections(text)
        assert list(sections.keys()) == ["Real"]
        assert "### Sub" in sections["Real"]  # h3 is content of the h2

    def test_empty_text(self):
        assert _split_sections("") == {}


class TestCountDistinctLowercased:
    def test_case_folds(self):
        body = "**Requester**: Alice\n**Requester**: ALICE\n**Requester**: bob\n"
        assert _count_distinct_lowercased(body, REQUESTER_LINE_RE) == 2

    def test_strips_whitespace(self):
        body = "**Requester**:  Alice   \n**Requester**: alice\n"
        assert _count_distinct_lowercased(body, REQUESTER_LINE_RE) == 1

    def test_ignores_blank_values(self):
        body = "**Requester**: \n**Requester**: alice\n"
        assert _count_distinct_lowercased(body, REQUESTER_LINE_RE) == 1

    def test_orgs(self):
        body = "**Organization**: AcmeCorp\n**Organization**: acmecorp\n**Organization**: Other\n"
        assert _count_distinct_lowercased(body, ORG_LINE_RE) == 2

    def test_no_matches(self):
        assert _count_distinct_lowercased("nothing here", REQUESTER_LINE_RE) == 0


class TestCountEntries:
    def test_one_per_date_line(self):
        body = "**Date**: 2026-04-01\n**Date**: 2026-04-02\n**Date**: 2026-04-02\n"
        # Same date twice -> two entries (a heavy contributor blocked twice).
        assert _count_entries(body) == 3

    def test_no_dates(self):
        assert _count_entries("no dates here") == 0

    def test_rejects_malformed_dates(self):
        # The regex requires YYYY-MM-DD; bare year or text is ignored.
        body = "**Date**: 2026\n**Date**: yesterday\n**Date**: 2026-04-01\n"
        assert _count_entries(body) == 1


# ---------------------------------------------------------------------------
# metric_qualitative
# ---------------------------------------------------------------------------


def _notes_with(section: str, body: str) -> str:
    return f"# Notes\n\n## {section}\n\n{body}\n"


class TestMetricQualitative:
    def test_distinct_requesters_rule(self):
        notes = _notes_with(SECTION_PRIVATE, "**Requester**: alice\n**Requester**: ALICE\n**Requester**: bob\n")
        r = metric_qualitative(
            notes, SECTION_PRIVATE, threshold=2, rule="distinct_requesters", label="Distinct requesters"
        )
        assert r.value == "2"
        assert r.breached is True

    def test_entry_count_rule(self):
        notes = _notes_with(SECTION_BLOCKED, "**Date**: 2026-04-01\n**Date**: 2026-04-02\n")
        r = metric_qualitative(notes, SECTION_BLOCKED, threshold=5, rule="entry_count", label="Entries")
        assert r.value == "2"
        assert r.breached is False

    def test_distinct_orgs_rule(self):
        notes = _notes_with(SECTION_ORG, "**Organization**: AcmeCorp\n**Organization**: acmecorp\n")
        r = metric_qualitative(notes, SECTION_ORG, threshold=3, rule="distinct_orgs", label="Orgs")
        assert r.value == "1"
        assert r.breached is False

    def test_missing_section_is_unmeasurable(self):
        r = metric_qualitative("# empty\n", "Nope", threshold=1, rule="distinct_requesters", label="X")
        assert r.value == "n/a"
        assert r.breached is None
        assert "missing" in r.note

    def test_unknown_rule_is_unmeasurable(self):
        notes = _notes_with(SECTION_PRIVATE, "**Requester**: alice\n")
        r = metric_qualitative(notes, SECTION_PRIVATE, threshold=1, rule="not_a_rule", label="X")
        assert r.value == "n/a"
        assert r.breached is None


# ---------------------------------------------------------------------------
# Quantitative metrics
# ---------------------------------------------------------------------------


class TestMetricMergedVolume:
    def test_buckets_by_30d_window(self):
        prs = [
            _pr(merged_offset_days=5),  # bucket 0
            _pr(merged_offset_days=29),  # bucket 0
            _pr(merged_offset_days=45),  # bucket 1
            _pr(merged_offset_days=80),  # bucket 2
            _pr(merged_offset_days=120),  # outside window
        ]
        r = metric_merged_volume(prs, NOW)
        assert "2 / 1 / 1" in r.value

    def test_future_dated_merge_skipped(self):
        # mergedAt 1 day in the future -> negative delta_days -> must skip.
        prs = [_pr(merged_offset_days=-1), _pr(merged_offset_days=5)]
        r = metric_merged_volume(prs, NOW)
        assert r.value.startswith("1 / 0 / 0")

    def test_gh_error_unmeasurable(self):
        r = metric_merged_volume(GhError("nope"), NOW)
        assert r.value == "n/a"
        assert r.breached is None
        assert r.note == "nope"

    def test_breached_requires_all_three_buckets(self):
        # Threshold is 50/mo; this fails because only bucket 0 has 50.
        prs = [_pr(merged_offset_days=10) for _ in range(50)]
        r = metric_merged_volume(prs, NOW)
        assert r.breached is False


class TestMetricReviewLatency:
    def test_computes_median_open_to_merge(self):
        # PR1: 24h open->merge, PR2: 96h open->merge.
        prs = [
            _pr(merged_offset_days=1, created_offset_days=2),  # 24h
            _pr(merged_offset_days=1, created_offset_days=5),  # 96h
        ]
        r = metric_review_latency(prs, NOW)
        # median = 60h, below 72h threshold
        assert "60.0h" in r.value
        assert r.breached is False

    def test_excludes_outside_30d_window(self):
        prs = [_pr(merged_offset_days=45, created_offset_days=46)]
        r = metric_review_latency(prs, NOW)
        assert r.value == "0 PRs in window"

    def test_skips_negative_duration_rows(self):
        # createdAt after mergedAt is nonsensical; the helper must skip it.
        prs = [_pr(merged_offset_days=2, created_offset_days=1)]
        r = metric_review_latency(prs, NOW)
        assert r.value == "0 PRs in window"

    def test_note_calls_out_proxy_nature(self):
        prs = [_pr(merged_offset_days=1, created_offset_days=2)]
        r = metric_review_latency(prs, NOW)
        assert "open->merge" in r.note


class TestMetricBacklog:
    def test_counts_only_aged(self):
        prs = [
            _pr(merged_offset_days=None, created_offset_days=1),  # too new
            _pr(merged_offset_days=None, created_offset_days=10),  # aged
            _pr(merged_offset_days=None, created_offset_days=20),  # aged
        ]
        # createdAt set, mergedAt absent -> open
        r = metric_backlog(prs, NOW)
        assert "2 (of 3 open)" in r.value
        assert r.breached is False  # threshold is 5

    def test_breached_at_threshold(self):
        prs = [_pr(merged_offset_days=None, created_offset_days=10) for _ in range(5)]
        r = metric_backlog(prs, NOW)
        assert r.breached is True


# ---------------------------------------------------------------------------
# Extraction triggers
# ---------------------------------------------------------------------------


class TestQ1Size:
    def test_under_threshold(self, tmp_path: Path):
        (tmp_path / "f.txt").write_text("x" * 100)
        r = _trigger_q1_size(tmp_path)
        assert r.breached is False
        assert "MB" in r.value

    def test_missing_dir_unmeasurable(self, tmp_path: Path):
        r = _trigger_q1_size(tmp_path / "does-not-exist")
        assert r.value == "n/a"
        assert r.breached is None


class TestQ2PrVolume:
    def test_future_dated_merge_skipped(self):
        prs = [_pr(merged_offset_days=-1), _pr(merged_offset_days=5)]
        r = _trigger_q2_pr_volume(prs, NOW)
        # Most recent 30d gets the one valid PR; older buckets stay 0.
        assert r.value.startswith("1 / 0 / 0")
        assert r.breached is False


# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------


class TestGlyph:
    def test_breached_label(self):
        assert _glyph(True) == "BREACHED"

    def test_ok_label(self):
        assert _glyph(False) == "ok"

    def test_unmeasurable(self):
        assert _glyph(None) == "?"


# ---------------------------------------------------------------------------
# JSON payload + trend vs prior review
# ---------------------------------------------------------------------------


def _review_doc(rows: list[tuple[int, str, str, str]]) -> str:
    """Build a minimal review markdown with a `## Metrics` table.

    `rows` are (num, name, value, status) tuples.
    """
    lines = [
        "# Phase 3 Promotion Metrics",
        "",
        "## Summary",
        "",
        "body",
        "",
        "## Metrics",
        "",
        "| # | Metric | Value | Threshold | Status | Note |",
        "|---|--------|-------|-----------|--------|------|",
    ]
    for num, name, value, status in rows:
        lines.append(f"| {num} | {name} | {value} | thr | {status} |  |")
    lines += ["", "## results-data/ Extraction Triggers", "", "none", ""]
    return "\n".join(lines) + "\n"


class TestParsePriorMetrics:
    def test_parses_ordered_rows_only_from_metrics_section(self, tmp_path: Path):
        path = tmp_path / "phase-3-review-2026-04-27.md"
        path.write_text(_review_doc([(1, "Metric A", "0 / 0 / 0", "ok"), (2, "Metric B", "5.0h", "BREACHED")]))
        rows = parse_prior_metrics(path)
        assert [r["num"] for r in rows] == [1, 2]
        assert rows[0] == {"num": 1, "name": "Metric A", "value": "0 / 0 / 0", "status": "ok"}
        assert rows[1]["status"] == "BREACHED"

    def test_ignores_extraction_table_and_separators(self, tmp_path: Path):
        path = tmp_path / "phase-3-review-2026-04-27.md"
        path.write_text(_review_doc([(1, "Only", "1", "ok")]))
        # The extraction-trigger table rows have no leading integer and live
        # under a different ## section -> excluded.
        assert len(parse_prior_metrics(path)) == 1


class TestFindPriorReview:
    def _seed(self, d: Path):
        for name, rows in [
            ("phase-3-review-2026-01-05.md", [(1, "A", "old", "ok")]),
            ("phase-3-review-baseline-2026-04-27.md", [(1, "A", "mid", "ok")]),
            ("phase-3-review-2026-12-31.md", [(1, "A", "future", "ok")]),
        ]:
            (d / name).write_text(_review_doc(rows))

    def test_picks_most_recent_before_today(self, tmp_path: Path):
        self._seed(tmp_path)
        result = find_prior_review(tmp_path, date(2026, 5, 26))
        assert result is not None
        since, rows = result
        assert since == "2026-04-27"  # not the future-dated one
        assert rows[0]["value"] == "mid"

    def test_none_when_no_earlier_review(self, tmp_path: Path):
        self._seed(tmp_path)
        # Today before every review -> nothing strictly earlier.
        assert find_prior_review(tmp_path, date(2026, 1, 1)) is None

    def test_missing_dir_is_none(self, tmp_path: Path):
        assert find_prior_review(tmp_path / "nope", date(2026, 5, 26)) is None


class TestComputeTrend:
    def _results(self) -> list[MetricResult]:
        return [
            MetricResult("M1", "now1", breached=False, threshold="t"),
            MetricResult("M2", "now2", breached=True, threshold="t"),
        ]

    def test_none_prior_yields_none(self):
        assert compute_trend(None, self._results()) is None

    def test_pairs_by_position_and_flags_status_change(self):
        prior = (
            "2026-04-27",
            [
                {"num": 1, "name": "old-name-1", "value": "then1", "status": "ok"},
                {"num": 2, "name": "old-name-2", "value": "then2", "status": "ok"},
            ],
        )
        trend = compute_trend(prior, self._results())
        assert trend["since"] == "2026-04-27"
        m1, m2 = trend["metrics"]
        # Current name is used; prior value paired by position despite name drift.
        assert m1["name"] == "M1" and m1["value_then"] == "then1" and m1["value_now"] == "now1"
        assert m1["status_changed"] is False  # ok -> ok
        assert m2["status_then"] == "ok" and m2["status_now"] == "BREACHED"
        assert m2["status_changed"] is True

    def test_more_current_than_prior_rows_pads_na(self):
        prior = ("2026-04-27", [{"num": 1, "name": "x", "value": "then1", "status": "ok"}])
        trend = compute_trend(prior, self._results())
        assert trend["metrics"][1]["value_then"] == "n/a"
        assert trend["metrics"][1]["status_then"] == "n/a"


class TestRenderTrendSection:
    def test_header_when_present(self):
        trend = {
            "since": "2026-04-27",
            "metrics": [
                {
                    "name": "M",
                    "value_then": "a",
                    "value_now": "b",
                    "status_then": "ok",
                    "status_now": "BREACHED",
                    "status_changed": True,
                },
            ],
        }
        out = "\n".join(render_trend_section(trend))
        assert "## Trend vs 2026-04-27" in out
        assert "ok -> BREACHED" in out

    def test_placeholder_when_absent(self):
        out = "\n".join(render_trend_section(None))
        assert out.startswith("## Trend")
        assert "No prior" in out


class TestBuildPayload:
    def test_shape_and_json_serializable(self):
        import json

        now = datetime(2026, 5, 26, 9, 0, 0, tzinfo=timezone.utc)
        results = [MetricResult("M1", "v", breached=None, threshold="t", note="n")]
        triggers = [MetricResult("Q1", "1 MB", breached=False, threshold="t")]
        payload = build_payload("o/r", "published-results", results, triggers, now, trend=None)
        assert set(payload) == {"generated_at", "repo", "base_branch", "results", "extraction_triggers", "trend"}
        assert payload["results"][0]["breached"] is None  # None survives round-trip
        assert json.loads(json.dumps(payload))["base_branch"] == "published-results"
