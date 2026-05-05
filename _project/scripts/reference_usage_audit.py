"""Classify reference-file mentions in Claude transcript JSONL files.

This script makes instruction-pruning evidence reproducible. It separates
literal mentions from transcript tool-result filename lists, because a filename
list is not the same evidence as a file content read.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REFERENCES = (
    "code/references/to-spec.md",
    "docs/references/compare.md",
    "docs/references/shrink.md",
    "docs/references/adversarial.md",
    "blog/references/audit.md",
    "references/testing-patterns.md",
    "references/deprecation-patterns.md",
)


@dataclass(frozen=True)
class Hit:
    transcript: str
    line: int
    timestamp: str
    reference: str
    category: str
    snippet: str


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _matches_reference(value: str, reference: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized == reference or normalized.endswith(f"/{reference}") or reference in normalized


def _snippet(value: str) -> str:
    return " ".join(value.split())[:240]


def _message_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    if isinstance(content, str):
        return [{"type": "text", "content": content}]
    return []


def _tool_result_filename_hits(
    record: dict[str, Any],
    transcript: Path,
    line_number: int,
    references: tuple[str, ...],
) -> list[Hit]:
    result = record.get("toolUseResult")
    if not isinstance(result, dict):
        return []
    filenames = result.get("filenames")
    if not isinstance(filenames, list):
        return []

    hits: list[Hit] = []
    timestamp = str(record.get("timestamp", ""))
    for filename in filenames:
        if not isinstance(filename, str):
            continue
        for reference in references:
            if _matches_reference(filename, reference):
                hits.append(
                    Hit(
                        transcript=transcript.as_posix(),
                        line=line_number,
                        timestamp=timestamp,
                        reference=reference,
                        category="tool_result_filename",
                        snippet=_snippet(filename),
                    )
                )
    return hits


def _message_content_hits(
    record: dict[str, Any],
    transcript: Path,
    line_number: int,
    references: tuple[str, ...],
) -> list[Hit]:
    hits: list[Hit] = []
    timestamp = str(record.get("timestamp", ""))
    for item in _message_items(record):
        content = item.get("content")
        if not isinstance(content, str):
            continue
        item_type = str(item.get("type", "text"))
        category = "tool_result_content" if item_type == "tool_result" else "message_content"
        for reference in references:
            if _matches_reference(content, reference):
                hits.append(
                    Hit(
                        transcript=transcript.as_posix(),
                        line=line_number,
                        timestamp=timestamp,
                        reference=reference,
                        category=category,
                        snippet=_snippet(content),
                    )
                )
    return hits


def collect_hits(
    transcripts_dir: Path,
    references: tuple[str, ...],
    since: datetime | None,
    exclude_session: str | None,
) -> tuple[list[Hit], int]:
    hits: list[Hit] = []
    parse_errors = 0

    for transcript in sorted(transcripts_dir.glob("*.jsonl")):
        if exclude_session and transcript.stem == exclude_session:
            continue
        with transcript.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(record, dict):
                    continue
                timestamp = _parse_timestamp(record.get("timestamp"))
                if since and timestamp and timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if since and timestamp and timestamp < since:
                    continue
                hits.extend(_tool_result_filename_hits(record, transcript, line_number, references))
                hits.extend(_message_content_hits(record, transcript, line_number, references))
    return hits, parse_errors


def _summary(hits: list[Hit]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for hit in hits:
        per_ref = summary.setdefault(hit.reference, {})
        per_ref[hit.category] = per_ref.get(hit.category, 0) + 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        default=Path.home() / ".claude/projects/-Users-joe-Developer-BenchBox",
    )
    parser.add_argument("--since", default="2026-01-01", help="ISO date/datetime lower bound")
    parser.add_argument("--reference", action="append", help="Reference suffix to audit; repeatable")
    parser.add_argument("--exclude-session", help="Transcript stem to exclude, usually the current session")
    parser.add_argument("--summary", action="store_true", help="Print a compact human summary")
    parser.add_argument("--json", action="store_true", help="Print full JSON hit payload")
    args = parser.parse_args()

    if not args.transcripts_dir.is_dir():
        print(f"error: transcripts dir not found: {args.transcripts_dir}")
        return 2

    since = _parse_timestamp(args.since)
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    references = tuple(args.reference or DEFAULT_REFERENCES)
    hits, parse_errors = collect_hits(args.transcripts_dir, references, since, args.exclude_session)
    summary = _summary(hits)

    payload = {
        "transcripts_dir": args.transcripts_dir.as_posix(),
        "since": args.since,
        "references": references,
        "parse_errors": parse_errors,
        "summary": summary,
        "hits": [asdict(hit) for hit in hits],
    }

    if args.json or not args.summary:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Reference usage hits: {len(hits)}")
        print(f"Parse errors: {parse_errors}")
        for reference, counts in sorted(summary.items()):
            pieces = ", ".join(f"{category}={count}" for category, count in sorted(counts.items()))
            print(f"- {reference}: {pieces}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
