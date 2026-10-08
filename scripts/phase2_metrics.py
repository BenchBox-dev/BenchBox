#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULT_REPO = "BenchBox-dev/BenchBox"
DEFAULT_BASE = "published-results"
DEFAULT_NOTES = Path("_project/notes/phase-2-requests.md")
DEFAULT_HANDOFFS_DIR = Path("_project/handoffs")

VOLUME_WINDOW_DAYS = 90
LATENCY_WINDOW_DAYS = 30
BACKLOG_AGE_DAYS = 7

THRESH_VOLUME_PER_MONTH = 50
THRESH_LATENCY_HOURS = 72
THRESH_BACKLOG = 5
THRESH_PRIVATE = 3
THRESH_BLOCKED_MAINTAINER = 5
THRESH_ORG_SPACES = 3

RESULTS_DATA_DIR = Path("results-data")
EXTRACTION_SIZE_THRESHOLD_BYTES = 250 * 1024 * 1024
EXTRACTION_PR_VOLUME_PER_MONTH = 20
EXTRACTION_PR_VOLUME_MONTHS = 3

SECTION_PRIVATE = "Private/Unlisted"
SECTION_BLOCKED = "Blocked-Maintainer"
SECTION_ORG = "Org-Spaces"

GH_PR_LIMIT = 500

REQUESTER_LINE_RE = re.compile(r"\*\*Requester\*\*:\s*(.+?)\s*$", re.MULTILINE)
ORG_LINE_RE = re.compile(r"\*\*Organization\*\*:\s*(.+?)\s*$", re.MULTILINE)
DATE_LINE_RE = re.compile(r"\*\*Date\*\*:\s*\d{4}-\d{2}-\d{2}", re.MULTILINE)

REVIEW_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
METRIC_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|(.+)\|\s*$")


@dataclass
class GhError:
    message: str


def _run_gh(args: list[str]) -> list[dict] | GhError:
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


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@dataclass
class MetricResult:
    name: str
    value: str
    breached: bool | None
    threshold: str
    note: str = ""


def metric_merged_volume(prs: list[dict] | GhError, now: datetime) -> MetricResult:
    name = f"Merged PRs / month (last {VOLUME_WINDOW_DAYS}d, by 30d bucket)"
    threshold = f">= {THRESH_VOLUME_PER_MONTH}/mo sustained for 3 mo"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    buckets = [0, 0, 0]
    for pr in prs:
        merged = _parse_iso(pr.get("mergedAt"))
        if merged is None:
            continue
        delta_days = (now - merged).days
        if delta_days < 0:
            continue
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
    name = f"Median PR open->merge time, hours (last {LATENCY_WINDOW_DAYS}d merged)"
    threshold = f"> {THRESH_LATENCY_HOURS}h"
    note_def = "open->merge; includes draft + author-iteration time, so this over-reports strict review-only latency"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    latencies: list[float] = []
    cutoff = now - timedelta(days=LATENCY_WINDOW_DAYS)
    for pr in prs:
        merged = _parse_iso(pr.get("mergedAt"))
        created = _parse_iso(pr.get("createdAt"))
        if merged is None or created is None or merged < cutoff:
            continue
        if merged < created:
            continue
        latencies.append((merged - created).total_seconds() / 3600.0)

    if not latencies:
        return MetricResult(name, "0 PRs in window", False, threshold, "no data")
    median_h = statistics.median(latencies)
    breached = median_h > THRESH_LATENCY_HOURS
    return MetricResult(name, f"{median_h:.1f}h (n={len(latencies)})", breached, threshold, note_def)


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


def _split_sections(text: str) -> dict[str, str]:
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
    matches = pattern.findall(section_text)
    return len({m.strip().lower() for m in matches if m.strip()})


def _count_entries(section_text: str) -> int:
    return len(DATE_LINE_RE.findall(section_text))


def metric_qualitative(
    notes_text: str,
    section: str,
    threshold: int,
    rule: str,
    label: str,
) -> MetricResult:
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


def _results_data_size(root: Path) -> int | None:
    if not root.is_dir():
        return None
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _trigger_q1_size(root: Path) -> MetricResult:
    name = "[Q1] results-data/ total size"
    threshold = f"> {EXTRACTION_SIZE_THRESHOLD_BYTES // (1024 * 1024)} MB"
    size = _results_data_size(root)
    if size is None:
        return MetricResult(name, "n/a", None, threshold, "results-data/ not found")
    breached = size > EXTRACTION_SIZE_THRESHOLD_BYTES
    return MetricResult(name, f"{size / (1024 * 1024):.1f} MB", breached, threshold)


def _trigger_q2_pr_volume(prs: list[dict] | GhError, now: datetime) -> MetricResult:
    name = f"[Q2] PR volume to base, last {EXTRACTION_PR_VOLUME_MONTHS} mo (each)"
    threshold = f">= {EXTRACTION_PR_VOLUME_PER_MONTH}/mo for {EXTRACTION_PR_VOLUME_MONTHS} consecutive months"
    if isinstance(prs, GhError):
        return MetricResult(name, "n/a", None, threshold, prs.message)

    buckets = [0] * EXTRACTION_PR_VOLUME_MONTHS
    for pr in prs:
        merged = _parse_iso(pr.get("mergedAt"))
        if merged is None:
            continue
        delta_days = (now - merged).days
        if delta_days < 0:
            continue
        bucket = delta_days // 30
        if 0 <= bucket < EXTRACTION_PR_VOLUME_MONTHS:
            buckets[bucket] += 1

    breached = all(b >= EXTRACTION_PR_VOLUME_PER_MONTH for b in buckets)
    value = " / ".join(str(b) for b in buckets) + " (most recent 30d first)"
    return MetricResult(name, value, breached, threshold)


def evaluate_extraction_triggers(
    root: Path,
    merged_prs: list[dict] | GhError,
    now: datetime,
) -> list[MetricResult]:
    return [
        _trigger_q1_size(root),
        _trigger_q2_pr_volume(merged_prs, now),
    ]


def _glyph(breached: bool | None) -> str:
    if breached is None:
        return "?"
    return "BREACHED" if breached else "ok"


def render_report(
    repo: str,
    base: str,
    results: list[MetricResult],
    extraction_triggers: list[MetricResult],
    now: datetime,
    trend: dict | None = None,
) -> str:
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
    lines.append("## results-data/ Extraction Triggers")
    lines.append("")
    lines.append(
        "Quantitative triggers from "
        "`_project/analysis/results-data-extraction-trigger.md`. Either firing "
        "surfaces an EXTRACTION EVALUATION RECOMMENDED line below."
    )
    lines.append("")
    lines.append("| Metric | Value | Threshold | Status |")
    lines.append("|--------|-------|-----------|--------|")
    for r in extraction_triggers:
        lines.append(f"| {r.name} | {r.value} | {r.threshold} | {_glyph(r.breached)} |")
    lines.append("")
    triggered = [r for r in extraction_triggers if r.breached is True]
    if triggered:
        for r in triggered:
            lines.append(f"**EXTRACTION EVALUATION RECOMMENDED**: {r.name} — {r.value}")
        lines.append("")
        lines.append(
            "See `_project/analysis/results-data-extraction-trigger.md` for the "
            "evaluation procedure. Open `evaluate-results-data-extraction-decision` "
            "and copy `docs/development/adr/TEMPLATE-results-data-extraction.md` "
            "to start the ADR."
        )
    else:
        lines.append("No extraction triggers fired.")
    lines.append("")
    lines.extend(render_trend_section(trend))
    return "\n".join(lines) + "\n"


def _result_to_dict(r: MetricResult) -> dict:
    return {
        "name": r.name,
        "value": r.value,
        "breached": r.breached,
        "threshold": r.threshold,
        "note": r.note,
    }


def build_payload(
    repo: str,
    base: str,
    results: list[MetricResult],
    extraction_triggers: list[MetricResult],
    now: datetime,
    trend: dict | None,
) -> dict:
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "repo": repo,
        "base_branch": base,
        "results": [_result_to_dict(r) for r in results],
        "extraction_triggers": [_result_to_dict(r) for r in extraction_triggers],
        "trend": trend,
    }


def parse_prior_metrics(path: Path) -> list[dict]:
    rows: list[dict] = []
    in_metrics = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_metrics = line.strip() == "## Metrics"
            continue
        if not in_metrics:
            continue
        match = METRIC_ROW_RE.match(line)
        if not match:
            continue
        cells = [c.strip() for c in match.group(2).split("|")]
        if len(cells) < 4:
            continue
        rows.append(
            {
                "num": int(match.group(1)),
                "name": cells[0],
                "value": cells[1],
                "status": cells[3],
            }
        )
    return rows


def find_prior_review(handoffs_dir: Path, today: date) -> tuple[str, list[dict]] | None:
    if not handoffs_dir.is_dir():
        return None
    today_iso = today.isoformat()
    candidates: list[tuple[str, Path]] = []
    for path in handoffs_dir.glob("phase-3-review-*.md"):
        match = REVIEW_DATE_RE.search(path.name)
        if match and match.group(1) < today_iso:
            candidates.append((match.group(1), path))
    if not candidates:
        return None
    date_str, path = max(candidates, key=lambda item: item[0])
    return date_str, parse_prior_metrics(path)


def compute_trend(
    prior: tuple[str, list[dict]] | None,
    results: list[MetricResult],
) -> dict | None:
    if prior is None:
        return None
    since, prior_rows = prior
    metrics: list[dict] = []
    for i, r in enumerate(results):
        prior_row = prior_rows[i] if i < len(prior_rows) else None
        status_then = prior_row["status"] if prior_row else "n/a"
        status_now = _glyph(r.breached)
        metrics.append(
            {
                "name": r.name,
                "value_then": prior_row["value"] if prior_row else "n/a",
                "value_now": r.value,
                "status_then": status_then,
                "status_now": status_now,
                "status_changed": status_then != status_now,
            }
        )
    return {"since": since, "metrics": metrics}


def render_trend_section(trend: dict | None) -> list[str]:
    if not trend:
        return [
            "## Trend",
            "",
            "No prior `phase-3-review-*.md` found to diff against.",
            "",
        ]
    lines = [
        f"## Trend vs {trend['since']}",
        "",
        "Per-metric change since the most recent prior review. The promotion "
        'rule\'s "two consecutive quarters" hysteresis (see '
        "`_project/analysis/phase-3-promotion-metrics.md`) keys off the "
        "Status-change column, so a reviewer does not have to diff by hand.",
        "",
        "| Metric | Value (then) | Value (now) | Status (then -> now) | Changed |",
        "|--------|--------------|-------------|----------------------|---------|",
    ]
    for m in trend["metrics"]:
        changed = "yes" if m["status_changed"] else ""
        lines.append(
            f"| {m['name']} | {m['value_then']} | {m['value_now']} | "
            f"{m['status_then']} -> {m['status_now']} | {changed} |"
        )
    lines.append("")
    return lines


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
    parser.add_argument(
        "--results-data-dir",
        type=Path,
        default=RESULTS_DATA_DIR,
        help="Path to results-data/ for the extraction-trigger size check",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. markdown (default) is the human handoff; json is "
        "the machine-readable payload for automation.",
    )
    parser.add_argument(
        "--handoffs-dir",
        type=Path,
        default=DEFAULT_HANDOFFS_DIR,
        help="Directory of prior phase-3-review-*.md files for the trend diff",
    )
    parser.add_argument(
        "--exit-non-zero-on-breach",
        action="store_true",
        help="Exit 1 if any threshold is breached (off by default; the "
        "quarterly review always generates the report regardless of breach "
        "state). Intended for ad-hoc non-quarterly CI gating.",
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

    extraction_triggers = evaluate_extraction_triggers(args.results_data_dir, merged_prs, now)
    prior = find_prior_review(args.handoffs_dir, now.date())
    trend = compute_trend(prior, results)

    if args.format == "json":
        payload = build_payload(args.repo, args.base_branch, results, extraction_triggers, now, trend)
        output = json.dumps(payload, indent=2) + "\n"
    else:
        output = render_report(args.repo, args.base_branch, results, extraction_triggers, now, trend)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)

    if args.exit_non_zero_on_breach and any(r.breached for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
