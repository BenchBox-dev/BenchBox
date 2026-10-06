from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from benchbox.core.tpcds.qualification.classification import REQUIRED_NONEMPTY

ENGINES = ("polars", "pandas", "datafusion")


def load_results(directory: Path) -> dict[str, dict[str, dict[str, Any]]]:
    results: dict[str, dict[str, dict[str, Any]]] = {}
    for engine in ENGINES:
        path = directory / f"{engine}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        results[engine] = {record["query"]: record for record in records if record.get("event") == "query_result"}
    return results


def build_report(results: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    engines: dict[str, Any] = {}
    for engine, records in results.items():
        divergent = sorted(
            query for query, record in records.items() if record.get("dataframe_to_sql", {}).get("status") != "match"
        )
        classes: Counter[str] = Counter()
        classified: list[str] = []
        unclassified: list[str] = []
        for query, record in records.items():
            state = record.get("printed_classification", {}).get("state")
            if state == "classified":
                classified.append(query)
                classes.update(record["printed_classification"].get("classes", []))
            elif record.get("status") != "match":
                unclassified.append(query)
        required = {query: records.get(query) for query in sorted(REQUIRED_NONEMPTY)}
        engines[engine] = {
            "statements": len(records),
            "strict": sum(1 for record in records.values() if record.get("status") == "match"),
            "parity_matched": len(records) - len(divergent),
            "parity_divergent": divergent,
            "classified": sorted(classified),
            "classes": dict(sorted(classes.items())),
            "unclassified": sorted(unclassified),
            "required_compared": sum(1 for record in required.values() if record is not None),
            "required_empty": sorted(
                query for query, record in required.items() if record is not None and not record.get("sql_nonempty")
            ),
            "required_missing": sorted(query for query, record in required.items() if record is None),
            "failed": sorted(
                query for query, record in records.items() if record.get("gate", {}).get("status") != "pass"
            ),
        }
    failed = any(entry["failed"] or entry["statements"] == 0 for entry in engines.values())
    return {"engines": engines, "gate": "fail" if failed else "pass", "required": len(REQUIRED_NONEMPTY)}


def render(report: dict[str, Any]) -> str:
    lines = [
        f"## TPC-DS SF 1 qualification: {report['gate'].upper()}",
        "",
        "### DataFrame-to-SQL parity",
        "",
        "| Engine | Statements | Matched | Divergent |",
        "| --- | --- | --- | --- |",
    ]
    for engine, entry in report["engines"].items():
        divergent = ", ".join(entry["parity_divergent"]) or "none"
        lines.append(f"| {engine} | {entry['statements']} | {entry['parity_matched']} | {divergent} |")
    lines += [
        "",
        "### Printed-answer comparison",
        "",
        "| Engine | Strict | Classified | Unclassified | Classes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for engine, entry in report["engines"].items():
        classes = ", ".join(f"{name} {count}" for name, count in entry["classes"].items()) or "none"
        unclassified = ", ".join(entry["unclassified"]) or "none"
        lines.append(f"| {engine} | {entry['strict']} | {len(entry['classified'])} | {unclassified} | {classes} |")
    lines += [
        "",
        f"### Nonempty coverage of the {report['required']} statements empty at SF 0.01",
        "",
        "| Engine | Compared | Empty | Missing |",
        "| --- | --- | --- | --- |",
    ]
    for engine, entry in report["engines"].items():
        empty = ", ".join(entry["required_empty"]) or "none"
        missing = ", ".join(entry["required_missing"]) or "none"
        lines.append(f"| {engine} | {entry['required_compared']} | {empty} | {missing} |")
    failed = {engine: entry["failed"] for engine, entry in report["engines"].items() if entry["failed"]}
    lines += ["", "### Gate failures", ""]
    lines += [f"- {engine}: {', '.join(queries)}" for engine, queries in failed.items()] or ["none"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = build_report(load_results(args.directory))
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.stdout.write(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
