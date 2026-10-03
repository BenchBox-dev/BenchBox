#!/usr/bin/env python3
"""Aggregate one merge unit's job results into a single pass/fail.

Used by the always-reporting unit result jobs in ``ci.yml``. Feed it the
``toJson(needs)`` of the result job and one ``--expect NAME=true|false`` per
gated job:

* ``NAME=true``: the job was required; its result must be ``success``.
* ``NAME=false``: the job was not required; its result must be ``skipped``
  (or ``success`` when it ran anyway).

A skipped required job is a failure, not a pass, so a path filter or a broken
``if:`` can never silently green a tier. ``--always NAME`` marks jobs that
must succeed on every run. ``--must-succeed`` is a synonym kept for
readability. Any ``failure`` or ``cancelled`` result always fails.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_DESCRIPTION = (
    "Aggregate one merge unit's job results into a single pass/fail.\n"
    "\n"
    "Used by the always-reporting unit result jobs in ``ci.yml``. Feed it the\n"
    "``toJson(needs)`` of the result job and one ``--expect NAME=true|false`` per\n"
    "gated job:\n"
    "\n"
    "* ``NAME=true``: the job was required; its result must be ``success``.\n"
    "* ``NAME=false``: the job was not required; its result must be ``skipped``\n"
    "  (or ``success`` when it ran anyway).\n"
    "\n"
    "A skipped required job is a failure, not a pass, so a path filter or a broken\n"
    "``if:`` can never silently green a tier. ``--always NAME`` marks jobs that\n"
    "must succeed on every run. ``--must-succeed`` is a synonym kept for\n"
    "readability. Any ``failure`` or ``cancelled`` result always fails.\n"
)

OK_WHEN_NOT_REQUIRED = {"skipped", "success"}


def evaluate(needs: dict[str, dict], expectations: dict[str, bool], always: list[str]) -> list[str]:
    """Return human-readable problems; empty means the unit passes."""
    problems: list[str] = []

    for name, info in sorted(needs.items()):
        result = str(info.get("result", ""))
        if result in {"failure", "cancelled"}:
            problems.append(f"{name}={result}")

    for name in always:
        result = str(needs.get(name, {}).get("result", "missing"))
        if result != "success":
            problems.append(f"{name}={result} (must succeed on every run)")

    for name, required in sorted(expectations.items()):
        if name not in needs:
            problems.append(f"{name}: not in needs (job missing from the result job's needs list)")
            continue
        result = str(needs[name].get("result", ""))
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
    return unique


def parse_expectation(text: str) -> tuple[str, bool]:
    name, _, value = text.partition("=")
    value = value.strip().lower()
    if not name or value not in {"true", "false"}:
        raise argparse.ArgumentTypeError(f"expected NAME=true|false, got {text!r}")
    return name.strip(), value == "true"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
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

    problems = evaluate(needs, dict(args.expect), list(args.always))
    if problems:
        print(f"{args.unit}: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    ran = sorted(name for name, info in needs.items() if info.get("result") == "success")
    print(f"{args.unit}: ok ({len(ran)} job(s) succeeded, rest skipped as expected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
