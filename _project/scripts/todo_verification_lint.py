#!/usr/bin/env python3
"""Lint hosted TODO verification commands for deterministic semantic drift."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

RETIRED_ENTRYPOINT_RE = re.compile(
    r"_project/scripts/(?:todo_db|todo_cli|validate_todo|todo_findings|findings_parity_report)\.py\b"
)
NEGATIVE_EXISTENCE_RE = re.compile(r"!\s*test\s+(?:!\s+)?-e\b")
WILDCARD_QUERY_RE = re.compile(r"--queries(?:=|\s+)[\"']?[^\s,\"']*[*?\[]")
WILDCARD_DUCKDB_RE = re.compile(r"(?:^|[\s\"'])[^\s\"']*[*?\[][^\s\"']*\.duckdb\b", re.IGNORECASE)
RUNTIME_DATE_RE = re.compile(r"\$\(date(?:\s|\))")
SHELL_BOUNDARIES = {";", "&&", "||", "|"}


@dataclass(frozen=True)
class Finding:
    item_id: str
    seq: int
    rule: str


def _has_malformed_find_newer(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    for index, token in enumerate(tokens):
        if token != "-newer":
            continue
        operands: list[str] = []
        for following in tokens[index + 1 :]:
            if following in SHELL_BOUNDARIES or following.startswith("-"):
                break
            operands.append(following)
        if len(operands) > 1:
            return True
    return False


def _uses_retired_entrypoint(command: str) -> bool:
    for segment in re.split(r"(?:&&|\|\||[;|])", command):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            continue
        while tokens and ("=" in tokens[0] and not tokens[0].startswith("_project/")):
            tokens.pop(0)
        if tokens[:1] == ["!"]:
            tokens.pop(0)
        if tokens[:2] == ["uv", "run"]:
            tokens = tokens[2:]
            if tokens[:1] == ["--"]:
                tokens.pop(0)
        if tokens and Path(tokens[0]).name in {"python", "python3"}:
            tokens.pop(0)
        if tokens and RETIRED_ENTRYPOINT_RE.fullmatch(tokens[0]):
            return True
    return False


def lint_command(command: str) -> list[str]:
    rules: list[str] = []
    if _uses_retired_entrypoint(command) and not NEGATIVE_EXISTENCE_RE.search(command):
        rules.append("retired-entrypoint")
    if WILDCARD_QUERY_RE.search(command):
        rules.append("wildcard-queries")
    if _has_malformed_find_newer(command):
        rules.append("find-newer-extra-operand")
    if WILDCARD_DUCKDB_RE.search(command):
        rules.append("wildcard-duckdb")
    if RUNTIME_DATE_RE.search(command):
        rules.append("runtime-date")
    return rules


def lint_items(items: Sequence[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for item in items:
        item_id = str(item.get("id") or "(unknown)")
        for verification in item.get("verifications") or []:
            if not isinstance(verification, dict):
                continue
            command = str(verification.get("command") or "")
            seq = int(verification.get("seq") or 0)
            findings.extend(Finding(item_id, seq, rule) for rule in lint_command(command))
    return findings


def filter_items(items: Sequence[dict[str, Any]], *, since: str | None, until: str | None) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if item.get("state") != "done":
            continue
        created = str(item.get("created_at") or "")[:10]
        if since and created < since:
            continue
        if until and created > until:
            continue
        filtered.append(item)
    return filtered


def _load_hosted_items() -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="benchbox-todo-verification-lint-") as directory:
        result = subprocess.run(
            [
                "_project/scripts/todo",
                "export",
                "--out",
                directory,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "todo export failed")
        items_path = Path(directory) / "items.jsonl"
        return [json.loads(line) for line in items_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items-json", type=Path, help="Lint an exported item list instead of the hosted tracker.")
    parser.add_argument("--since", help="Include DONE items created on or after YYYY-MM-DD.")
    parser.add_argument("--until", help="Include DONE items created on or before YYYY-MM-DD.")
    args = parser.parse_args(argv)
    items = json.loads(args.items_json.read_text(encoding="utf-8")) if args.items_json else _load_hosted_items()
    findings = lint_items(filter_items(items, since=args.since, until=args.until))
    for finding in findings:
        print(f"{finding.item_id}: verification {finding.seq}: {finding.rule}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
