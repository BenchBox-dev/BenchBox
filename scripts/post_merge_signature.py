#!/usr/bin/env python3
"""Build and diff develop-post-merge gate-job failure signatures.

Each develop-post-merge gate job (lint, fast-test, explorer-tokens,
medium-test) emits a small JSON "signature" describing what, if anything,
failed in that job's run:

- pytest-backed jobs (fast-test, medium-test) build the signature from the
  job's junit XML (``--junit``), extracting the failed/errored test node IDs.
- non-pytest jobs (lint, explorer-tokens) build the signature from a plain
  "job name + failed step" descriptor (``--failed-step``), since there is no
  junit output to parse.

``diff`` compares the current run's signature against the previous run's and
reports the failure IDs that are new (present now, absent before). This lets
auto-revert-on-failure attribute a red develop run to the merge that actually
introduced a new failure, instead of blaming whichever commit merged last
while develop was already red for an unrelated reason.

Stdlib-only by design (see scripts/path_filter_decision.py for the same
precedent): this runs in a bare `python` step with no dependency sync.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class SignatureError(Exception):
    """Raised when a signature cannot be built or read."""


def _node_id(case: ET.Element) -> str:
    """Build a pytest-style node ID from a junit <testcase> element.

    Prefers the `file` attribute (present in pytest's default junit XML)
    combined with the test name, falling back to `classname` when `file`
    is absent (older/other junit writers).
    """
    name = case.get("name", "")
    file_attr = case.get("file")
    if file_attr:
        return f"{file_attr}::{name}"
    classname = case.get("classname", "")
    if classname:
        return f"{classname}::{name}"
    return name


def build_signature_from_junit(job: str, junit_path: Path) -> dict[str, object]:
    """Build a signature from a junit XML report's failed/errored testcases.

    Skipped and passing testcases are excluded; a testcase counts as a
    failure if it has a `<failure>` or `<error>` child element.
    """
    if not junit_path.exists():
        raise SignatureError(f"junit xml file not found: {junit_path}")
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        raise SignatureError(f"could not parse junit xml {junit_path}: {exc}") from exc

    root = tree.getroot()
    failure_ids: list[str] = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failure_ids.append(_node_id(case))

    return {
        "job": job,
        "kind": "junit",
        "failure_ids": sorted(set(failure_ids)),
    }


def build_signature_from_job_failure(job: str, failed_step: str | None) -> dict[str, object]:
    """Build a signature from a plain job-name + failed-step descriptor.

    Used for gates with no junit output (lint, explorer-tokens). When
    `failed_step` is None (the job succeeded), the signature has no
    failure IDs.
    """
    if failed_step:
        return {
            "job": job,
            "kind": "job-failure",
            "failure_ids": [f"{job}:{failed_step}"],
        }
    return {
        "job": job,
        "kind": "none",
        "failure_ids": [],
    }


def load_signature(path: Path) -> dict[str, object]:
    """Load a signature JSON file, validating its minimal shape."""
    if not path.exists():
        raise SignatureError(f"signature file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SignatureError(f"signature file is not valid json: {path} ({exc})") from exc
    if not isinstance(data, dict) or "failure_ids" not in data:
        raise SignatureError(f"signature file missing 'failure_ids' key: {path}")
    return data


def diff_signatures(previous: dict[str, object], current: dict[str, object]) -> list[str]:
    """Return the failure IDs present in `current` but absent from `previous`.

    `previous` may be an empty/partial mapping (e.g. a genuinely green prior
    run, or a caller with no prior signature at all) - a missing
    `failure_ids` key is treated as "no prior failures", so every current
    failure counts as new.
    """
    previous_raw = previous.get("failure_ids", [])
    previous_ids: set[object] = set(previous_raw) if isinstance(previous_raw, list) else set()
    current_raw = current.get("failure_ids", [])
    current_ids: list[object] = current_raw if isinstance(current_raw, list) else []
    return sorted({fid for fid in current_ids if fid not in previous_ids})


def _build_command(args: argparse.Namespace) -> int:
    try:
        if args.junit:
            signature = build_signature_from_junit(args.job, args.junit)
            # A gate can fail for a reason junit never records - e.g. pytest-cov's
            # --cov-fail-under gate, which fails the step (and job) while every
            # individual testcase passes, leaving zero <failure>/<error> elements.
            # Trusting an empty junit-derived signature in that case would make
            # the diff see no new failures and silently suppress a real revert.
            # Only override when the job actually failed AND junit found nothing -
            # a job that failed WITH real testcase failures keeps its junit
            # signature (more precise than the coarse job-level descriptor).
            if args.job_failed and not signature["failure_ids"]:
                signature = build_signature_from_job_failure(args.job, args.failed_step)
        else:
            signature = build_signature_from_job_failure(args.job, args.failed_step)
    except SignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(signature, indent=2, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def _diff_command(args: argparse.Namespace) -> int:
    try:
        previous = load_signature(args.previous)
        current = load_signature(args.current)
    except SignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    new_ids = diff_signatures(previous, current)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"new_failure_ids": new_ids}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for failure_id in new_ids:
        print(failure_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a failure signature JSON.")
    build_parser.add_argument("--job", required=True, help="Gate job name, e.g. fast-test")
    build_parser.add_argument("--junit", type=Path, help="Path to a junit XML report")
    build_parser.add_argument(
        "--failed-step",
        help="Name of the failed step, for non-junit jobs (omit if the job succeeded). "
        "Combined with --junit and --job-failed, this is also the fallback descriptor "
        "used when the job failed but junit recorded no testcase-level failures.",
    )
    build_parser.add_argument(
        "--job-failed",
        action="store_true",
        help="The job failed overall (e.g. job.status == 'failure'). With --junit, an "
        "empty junit-derived signature is then treated as untrustworthy (a job can fail "
        "for a reason junit never records, e.g. a coverage-threshold gate) and replaced "
        "with a --failed-step job-failure descriptor instead of a false-clean signature.",
    )
    build_parser.add_argument("--out", type=Path, required=True, help="Path to write the signature JSON")
    build_parser.set_defaults(func=_build_command)

    diff_parser = subparsers.add_parser("diff", help="Diff two signature JSONs for new failure IDs.")
    diff_parser.add_argument("--previous", type=Path, required=True, help="Path to the previous run's signature JSON")
    diff_parser.add_argument("--current", type=Path, required=True, help="Path to the current run's signature JSON")
    diff_parser.add_argument("--out", type=Path, help="Path to write {new_failure_ids: [...]}")
    diff_parser.set_defaults(func=_diff_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
