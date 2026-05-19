"""Tests for scripts/phase2_metrics.py.

Covers the parsing helpers and metric functions. The gh CLI is not
exercised here — those code paths take a list[dict] | GhError and we
inject both shapes directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    _count_distinct_lowercased,
    _count_entries,
    _glyph,
    _split_sections,
    _trigger_q1_size,
    _trigger_q2_pr_volume,
    metric_backlog,
    metric_merged_volume,
    metric_qualitative,
    metric_review_latency,
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
