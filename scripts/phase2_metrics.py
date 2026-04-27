#!/usr/bin/env python3
"""Compute Phase 2 → Phase 3 promotion metrics.

Reads PR data from the `gh` CLI and qualitative request data from
`_project/notes/phase-2-requests.md`. Produces a markdown report
showing current values against the thresholds defined in
`_project/analysis/phase-3-promotion-metrics.md`.

Read-only: makes no GitHub writes; needs only `gh auth status` to be
green (or an unauthenticated public-only run if the repo is public).

Usage:
    python scripts/phase2_metrics.py
    python scripts/phase2_metrics.py --output _project/handoffs/review.md
    python scripts/phase2_metrics.py --repo joeharris76/BenchBox \\
        --base-branch published-results --notes _project/notes/phase-2-requests.md
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_REPO = "joeharris76/BenchBox"
DEFAULT_BASE = "published-results"
DEFAULT_NOTES = Path("_project/notes/phase-2-requests.md")

VOLUME_WINDOW_DAYS = 90
LATENCY_WINDOW_DAYS = 30
BACKLOG_AGE_DAYS = 7

THRESH_VOLUME_PER_MONTH = 50  # sustained for 3 months
THRESH_LATENCY_HOURS = 72
THRESH_BACKLOG = 5
THRESH_PRIVATE = 3
THRESH_BLOCKED_MAINTAINER = 5
THRESH_ORG_SPACES = 3

# Section names in the qualitative notes file (must match the headers
# in the `_project/notes/phase-2-requests.md` template).
SECTION_PRIVATE = "Private/Unlisted"
SECTION_BLOCKED = "Blocked-Maintainer"
SECTION_ORG = "Org-Spaces"

# Cap on PRs returned per gh call. Set 10x the volume threshold (50/mo × 3
# months = 150) so we don't silently truncate when M1 is at-or-near breach.
GH_PR_LIMIT = 500

# Per-section counting rules, keyed by the kind of request the section
# represents:
#   "distinct_requesters" — distinct **Requester** values, lowercased
#   "entry_count"         — count of entries (one per **Date** line)
#   "distinct_orgs"       — distinct **Organization** values, lowercased
REQUESTER_LINE_RE = re.compile(r"\*\*Requester\*\*:\s*(.+?)\s*$", re.MULTILINE)
ORG_LINE_RE = re.compile(r"\*\*Organization\*\*:\s*(.+?)\s*$", re.MULTILINE)
DATE_LINE_RE = re.compile(r"\*\*Date\*\*:\s*\d{4}-\d{2}-\d{2}", re.MULTILINE)


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------


@dataclass
class GhError:
    message: str


def _run_gh(args: list[str]) -> list[dict] | GhError:
    """Run `gh` and return parsed JSON, or a GhError on failure.

    Failures are not fatal — the script reports "n/a (gh error)" for
    affected metrics and keeps going.
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return GhError("`gh` CLI not installed")
    except subprocess.TimeoutExpired:
        return GhError("`gh` call timed out")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip().splitlines()[-1] if exc.stderr else ""
        return GhError(f"gh exit {exc.returncode}: {stderr}")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return GhError(f"invalid JSON from gh: {exc}")


def _gh_prs(repo: str, base: str, state: str) -> list[dict] | GhError:
    """List PRs against `base` in the given state. Empty list if base missing."""
    return _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--base",
            base,
            "--state",
            state,
            "--limit",
            str(GH_PR_LIMIT),
            "--json",
            "number,title,createdAt,closedAt,mergedAt,state,author,url",
        ]
    )


# ---------------------------------------------------------------------------
# Quantitative metrics
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@dataclass
class MetricResult:
    name: str
    value: str
    breached: bool | None  # None = could not measure
    threshold: str
    note: str = ""


def metric_merged_volume(prs: list[dict] | GhError, now: datetime) -> MetricResult:
    name = f"Merged PRs / month (last {VOLUME_WINDOW_DAYS}d, by 30d bucket)"
    threshold = f">= {THRESH_VOLUME_PER_MONTH}/mo sustained for 3 mo"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    buckets = [0, 0, 0]  # bucket 0 = most recent 30d
    for pr in prs:
        merged = _parse_iso(pr.get("mergedAt"))
        if merged is None:
            continue
        delta_days = (now - merged).days
        if delta_days < 30:
            buckets[0] += 1
        elif delta_days < 60:
            buckets[1] += 1
        elif delta_days < 90:
            buckets[2] += 1

    breached = all(b >= THRESH_VOLUME_PER_MONTH for b in buckets)
    value = f"{buckets[0]} / {buckets[1]} / {buckets[2]} (most recent 30d first)"
    return MetricResult(name, value, breached, threshold)


def metric_review_latency(prs: list[dict] | GhError, now: datetime) -> MetricResult:
    name = f"Median PR review latency, hours (last {LATENCY_WINDOW_DAYS}d merged)"
    threshold = f"> {THRESH_LATENCY_HOURS}h"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    latencies: list[float] = []
    cutoff = now - timedelta(days=LATENCY_WINDOW_DAYS)
    for pr in prs:
        merged = _parse_iso(pr.get("mergedAt"))
        created = _parse_iso(pr.get("createdAt"))
        if merged is None or created is None or merged < cutoff:
            continue
        latencies.append((merged - created).total_seconds() / 3600.0)

    if not latencies:
        return MetricResult(name, "0 PRs in window", False, threshold, "no data")
    median_h = statistics.median(latencies)
    breached = median_h > THRESH_LATENCY_HOURS
    return MetricResult(name, f"{median_h:.1f}h (n={len(latencies)})", breached, threshold)


def metric_backlog(prs: list[dict] | GhError, now: datetime) -> MetricResult:
    name = f"Open PRs > {BACKLOG_AGE_DAYS}d old (snapshot)"
    threshold = f">= {THRESH_BACKLOG} sustained for 30d"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    cutoff = now - timedelta(days=BACKLOG_AGE_DAYS)
    aged = [pr for pr in prs if (created := _parse_iso(pr.get("createdAt"))) and created < cutoff]
    breached = len(aged) >= THRESH_BACKLOG
    note = "snapshot only; sustained-for-30d check requires comparing across reviews"
    return MetricResult(name, f"{len(aged)} (of {len(prs)} open)", breached, threshold, note)


# ---------------------------------------------------------------------------
# Qualitative metrics
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> dict[str, str]:
    """Split a markdown doc into ## sections keyed by header text."""
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(body)
            current = line[3:].strip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body)
    return sections


def _count_distinct_lowercased(section_text: str, pattern: re.Pattern[str]) -> int:
    """Count distinct case-folded values matching `pattern` in a section."""
    matches = pattern.findall(section_text)
    return len({m.strip().lower() for m in matches if m.strip()})


def _count_entries(section_text: str) -> int:
    """Count entries in a section, one per **Date**: line."""
    return len(DATE_LINE_RE.findall(section_text))


def metric_qualitative(
    notes_text: str,
    section: str,
    threshold: int,
    rule: str,
    label: str,
) -> MetricResult:
    """Compute a qualitative metric.

    `rule` selects the count strategy ("distinct_requesters" /
    "distinct_orgs" / "entry_count"). `label` is the noun used in the
    report row name.
    """
    name = f"{label} in '{section}' section"
    threshold_str = f">= {threshold}"
    sections = _split_sections(notes_text)
    if section not in sections:
        return MetricResult(name, "n/a", None, threshold_str, f"section '{section}' missing")
    body = sections[section]
    if rule == "distinct_requesters":
        count = _count_distinct_lowercased(body, REQUESTER_LINE_RE)
    elif rule == "distinct_orgs":
        count = _count_distinct_lowercased(body, ORG_LINE_RE)
    elif rule == "entry_count":
        count = _count_entries(body)
    else:
        return MetricResult(name, "n/a", None, threshold_str, f"unknown rule '{rule}'")
    return MetricResult(name, str(count), count >= threshold, threshold_str)


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _glyph(breached: bool | None) -> str:
    if breached is None:
        return "?"
    return "BREACHED" if breached else "ok"


def render_report(repo: str, base: str, results: list[MetricResult], now: datetime) -> str:
    lines: list[str] = []
    lines.append(f"# Phase 3 Promotion Metrics — {now.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"- Repo: `{repo}`")
    lines.append(f"- Base branch: `{base}`")
    lines.append(f"- Generated: {now.isoformat(timespec='seconds')}")
    lines.append("- Source: `scripts/phase2_metrics.py`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    breached = [r for r in results if r.breached is True]
    nonmeasurable = [r for r in results if r.breached is None]
    if breached:
        lines.append(f"- **{len(breached)} threshold(s) BREACHED**.")
        for r in breached:
            lines.append(f"  - {r.name} — {r.value} (threshold {r.threshold})")
    else:
        lines.append("- No thresholds breached.")
    if nonmeasurable:
        lines.append(f"- {len(nonmeasurable)} metric(s) could not be measured (see notes).")
    lines.append("")
    lines.append(
        "Promotion rule (see `_project/analysis/phase-3-promotion-metrics.md`): "
        "promote Phase 3 design TODOs only when **two or more quantitative thresholds** "
        "are breached for **two consecutive quarters**, OR **two qualitative thresholds** "
        "are breached in a single review."
    )
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| # | Metric | Value | Threshold | Status | Note |")
    lines.append("|---|--------|-------|-----------|--------|------|")
    for i, r in enumerate(results, start=1):
        note = r.note.replace("|", "\\|") if r.note else ""
        lines.append(f"| {i} | {r.name} | {r.value} | {r.threshold} | {_glyph(r.breached)} | {note} |")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 → Phase 3 promotion metrics")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in OWNER/NAME form")
    parser.add_argument("--base-branch", default=DEFAULT_BASE, help="PR base branch to query")
    parser.add_argument(
        "--notes",
        type=Path,
        default=DEFAULT_NOTES,
        help="Path to qualitative requests markdown file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write report to this file instead of stdout",
    )
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)

    merged_prs = _gh_prs(args.repo, args.base_branch, "merged")
    open_prs = _gh_prs(args.repo, args.base_branch, "open")

    if args.notes.is_file():
        notes_text = args.notes.read_text(encoding="utf-8")
    else:
        notes_text = ""

    results = [
        metric_merged_volume(merged_prs, now),
        metric_review_latency(merged_prs, now),
        metric_backlog(open_prs, now),
        metric_qualitative(
            notes_text,
            SECTION_PRIVATE,
            THRESH_PRIVATE,
            rule="distinct_requesters",
            label="Distinct requesters",
        ),
        metric_qualitative(
            notes_text,
            SECTION_BLOCKED,
            THRESH_BLOCKED_MAINTAINER,
            rule="entry_count",
            label="Distinct submissions",
        ),
        metric_qualitative(
            notes_text,
            SECTION_ORG,
            THRESH_ORG_SPACES,
            rule="distinct_orgs",
            label="Distinct organizations",
        ),
    ]

    report = render_report(args.repo, args.base_branch, results, now)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
