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

Blame rule today: revert ``github.sha`` of the first post-merge run whose
signature has new failure IDs. Residual: a latent environment-dependent
break can still make that SHA the first red run even when the blamed commit
did not touch the failing test. ``attribute`` downgrades that case to an
advisory when every extractable failing test path is outside the SHA's diff.
Job-level failures (lint, missing junit paths) stay fail-closed (revert).

Stdlib-only by design (see scripts/path_filter_decision.py for the same
precedent): this runs in a bare `python` step with no dependency sync.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
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


def failure_id_test_paths(failure_ids: list[object]) -> list[str]:
    """Extract repository test paths from junit-style failure IDs.

    ``tests/unit/foo.py::test_bar`` yields ``tests/unit/foo.py``. Job-level
    IDs such as ``lint:Run CI lint mirror`` yield nothing.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for raw in failure_ids:
        if not isinstance(raw, str):
            continue
        candidate = raw.split("::", 1)[0].strip()
        if not candidate.endswith(".py"):
            continue
        if "/" not in candidate and not candidate.startswith("tests"):
            continue
        if candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)
    return paths


def paths_related_to_test(test_path: str) -> list[str]:
    """Return the test path plus a conservative code-under-test stem match.

    ``tests/unit/test_foo.py`` also matches a changed ``foo.py`` basename so a
    PR that edits the module under test still reverts. This is not a full
    import graph.
    """
    related = [test_path]
    name = Path(test_path).name
    if name.startswith("test_") and name.endswith(".py"):
        related.append(name[len("test_") :])
    return related


def _dotted_module_to_candidate_paths(module: str) -> list[str]:
    """Return the repo-relative file path candidates for a dotted module name."""
    base = "/".join(module.split("."))
    return [f"{base}.py", f"{base}/__init__.py"]


def imported_module_paths(test_path: str, repo_root: Path) -> list[str]:
    """Return repo-relative paths ``test_path`` actually imports, via its AST.

    Real import/dependency analysis rather than basename matching: parses
    every ``import``/``from ... import`` statement anywhere in the test file
    (module-level or nested inside functions - most of these tests import
    lazily), resolves each dotted module name (relative imports included) to
    a candidate file path, and keeps only paths that exist on disk. This is
    what lets a merge that breaks a same-package dependency the test imports
    under an unrelated basename (e.g. a test file exercising
    ``throughput_test.py`` via ``from benchbox.core.tpcds.throughput_test
    import ...``) still be attributed correctly, instead of relying on
    filename overlap.

    Best-effort: returns ``[]`` if the test file cannot be read or parsed.
    Callers must not treat an empty result as proof the blamed SHA is
    innocent - only as "this signal found nothing", since it is not a full
    transitive import graph (only direct imports of the test file itself are
    resolved).
    """
    full_path = repo_root / test_path
    try:
        source = full_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(full_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    test_dir_parts = Path(test_path).parent.parts
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import: resolve against the test file's own
                # package directory. level=1 is "from . import x" (same
                # package as the test file); each extra level climbs one
                # more directory.
                climb = node.level - 1
                anchor = test_dir_parts[: len(test_dir_parts) - climb] if climb else test_dir_parts
                if anchor:
                    # The anchor package itself, not only what is imported from
                    # it. `from . import VALUE` where VALUE lives in the package
                    # initializer resolves to no alias file at all, and even a
                    # sibling import executes that initializer - so a merge that
                    # broke `__init__.py` was scored as non-owning and downgraded
                    # to advisory, skipping the revert.
                    module_names.add(".".join(anchor))
                if node.module:
                    module_names.add(".".join([*anchor, node.module]))
                elif anchor:
                    # "from . import sibling[, other]": each imported name is
                    # itself a candidate module (e.g. a same-package helper
                    # file), not just the anchor package.
                    for alias in node.names:
                        module_names.add(".".join([*anchor, alias.name]))
            elif node.module:
                module_names.add(node.module)

    paths: list[str] = []
    seen: set[str] = set()
    for module in sorted(module_names):
        for candidate in _dotted_module_to_candidate_paths(module):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (repo_root / candidate).is_file():
                paths.append(candidate)
    return paths


def attribution_action(
    failure_ids: list[object],
    changed_paths: list[str],
    repo_root: Path | None = None,
) -> str:
    """Return ``revert`` or ``advisory`` for a blamed SHA's changed paths.

    Checks two signals before downgrading to advisory: the test path/stem
    heuristic (``paths_related_to_test``) and, since that heuristic misses a
    dependency whose basename differs from the test file, real import
    analysis (``imported_module_paths``) - a changed path the test file
    actually imports still triggers revert even when neither its name nor
    its stem matches. Advisory only when both signals clear the blamed SHA
    for every extractable failing test path. No extractable test path keeps
    revert so lint/job failures stay fail-closed.
    """
    test_paths = failure_id_test_paths(failure_ids)
    if not test_paths:
        return "revert"
    root = repo_root or Path.cwd()
    changed = set(changed_paths)
    changed_names = {Path(path).name for path in changed_paths}
    for test_path in test_paths:
        for related in paths_related_to_test(test_path):
            if related in changed or Path(related).name in changed_names:
                return "revert"
        for imported in imported_module_paths(test_path, root):
            if imported in changed:
                return "revert"
    return "advisory"


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


def changed_paths_for_sha(sha: str) -> list[str]:
    """List paths changed by ``sha`` (stdlib git, no shell)."""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SignatureError(result.stderr.strip() or f"git diff-tree failed for {sha}")
    return [line for line in result.stdout.splitlines() if line]


def _attribute_command(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(Path(args.failure_ids).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read failure ids: {exc}", file=sys.stderr)
        return 1
    if isinstance(payload, dict):
        failure_ids = payload.get("new_failure_ids", payload.get("failure_ids", []))
    else:
        failure_ids = payload
    if not isinstance(failure_ids, list):
        print("error: failure id payload must be a list or signature object", file=sys.stderr)
        return 1
    try:
        changed_paths = changed_paths_for_sha(args.sha)
    except SignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    action = attribution_action(failure_ids, changed_paths)
    result = {
        "action": action,
        "test_paths": failure_id_test_paths(failure_ids),
        "changed_paths": changed_paths,
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
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

    attribute_parser = subparsers.add_parser(
        "attribute",
        help="Decide revert vs advisory from new failure IDs and the blamed SHA diff.",
    )
    attribute_parser.add_argument("--sha", required=True, help="Blamed commit SHA")
    attribute_parser.add_argument(
        "--failure-ids",
        type=Path,
        required=True,
        help="JSON list or {new_failure_ids: [...]} from diff",
    )
    attribute_parser.add_argument("--out", type=Path, help="Path to write the attribution JSON")
    attribute_parser.set_defaults(func=_attribute_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
