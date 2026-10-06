#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

OK_WHEN_NOT_REQUIRED = {"skipped", "success"}

SUPERSEDED_EXIT_CODE = 3


def evaluate(needs: dict[str, dict], expectations: dict[str, bool], always: list[str]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    cancelled: list[str] = []

    for name, info in sorted(needs.items()):
        result = str(info.get("result", ""))
        if result == "failure":
            problems.append(f"{name}=failure")
        elif result == "cancelled":
            cancelled.append(f"{name}=cancelled")

    for name in always:
        result = str(needs.get(name, {}).get("result", "missing"))
        if result == "cancelled":
            continue
        if result != "success":
            problems.append(f"{name}={result} (must succeed on every run)")

    for name, required in sorted(expectations.items()):
        if name not in needs:
            problems.append(f"{name}: not in needs (job missing from the result job's needs list)")
            continue
        result = str(needs[name].get("result", ""))
        if result == "cancelled":
            continue
        if required and result != "success":
            problems.append(f"{name}={result} (required for this change; expected success)")
        elif not required and result not in OK_WHEN_NOT_REQUIRED:
            problems.append(f"{name}={result} (not required; expected skipped or success)")

    seen = set()
    unique = []
    for problem in problems:
        if problem not in seen:
            seen.add(problem)
            unique.append(problem)
    return unique, cancelled


def parse_expectation(text: str) -> tuple[str, bool]:
    name, _, value = text.partition("=")
    value = value.strip().lower()
    if not name or value not in {"true", "false"}:
        raise argparse.ArgumentTypeError(f"expected NAME=true|false, got {text!r}")
    return name.strip(), value == "true"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, help="Unit name, used only in messages")
    parser.add_argument("--needs", required=True, help="toJson(needs) of the result job")
    parser.add_argument("--expect", action="append", default=[], type=parse_expectation, metavar="NAME=BOOL")
    parser.add_argument("--always", action="append", default=[], metavar="NAME")
    args = parser.parse_args(argv)

    try:
        needs = json.loads(args.needs)
    except json.JSONDecodeError as exc:
        print(f"{args.unit}: needs is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(needs, dict):
        print(f"{args.unit}: needs must be a JSON object", file=sys.stderr)
        return 1

    problems, cancelled = evaluate(needs, dict(args.expect), list(args.always))
    if problems:
        print(f"{args.unit}: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if cancelled:
        print(f"{args.unit}: CANCELLED (not failed): an upstream job was cancelled,")
        print("usually because a newer run superseded this one; the workflow cancels")
        print("its own run so this aggregate concludes cancelled instead of failed.")
        for name in cancelled:
            print(f"  - {name}")
        return SUPERSEDED_EXIT_CODE
    ran = sorted(name for name, info in needs.items() if info.get("result") == "success")
    print(f"{args.unit}: ok ({len(ran)} job(s) succeeded, rest skipped as expected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
