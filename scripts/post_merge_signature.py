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
Failure IDs no classifier understands escalate: the verdict carries
``action: escalate`` with the unrecognized IDs and the workflow must fail
loudly for human classification instead of reverting. The verdict always
records the blamed ``sha`` and ``attribution_basis`` so evidence applies
only to the commit it was computed against.

Stdlib-only by design (see scripts/path_filter_decision.py for the same
precedent): this runs in a bare `python` step with no dependency sync.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
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


def _with_source_inputs(signature: dict[str, object], source_inputs: dict[str, str] | None) -> dict[str, object]:
    if source_inputs:
        signature["source_inputs"] = dict(sorted(source_inputs.items()))
    return signature


def _parse_source_inputs(raw_inputs: list[str]) -> dict[str, str]:
    source_inputs: dict[str, str] = {}
    for raw in raw_inputs:
        name, separator, identity = raw.partition("=")
        if not separator or not name.strip() or not identity.strip():
            raise SignatureError(f"source input must be NAME=IDENTITY: {raw!r}")
        source_inputs[name.strip()] = identity.strip()
    return source_inputs


def build_signature_from_junit(
    job: str, junit_path: Path, source_inputs: dict[str, str] | None = None
) -> dict[str, object]:
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

    return _with_source_inputs(
        {
            "job": job,
            "kind": "junit",
            "failure_ids": sorted(set(failure_ids)),
        },
        source_inputs,
    )


def build_signature_from_job_failure(
    job: str, failed_step: str | None, source_inputs: dict[str, str] | None = None
) -> dict[str, object]:
    """Build a signature from a plain job-name + failed-step descriptor.

    Used for gates with no junit output (lint, explorer-tokens). When
    `failed_step` is None (the job succeeded), the signature has no
    failure IDs.
    """
    if failed_step:
        return _with_source_inputs(
            {
                "job": job,
                "kind": "job-failure",
                "failure_ids": [f"{job}:{failed_step}"],
            },
            source_inputs,
        )
    return _with_source_inputs(
        {
            "job": job,
            "kind": "none",
            "failure_ids": [],
        },
        source_inputs,
    )


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


def classify_failure_id(raw: object) -> tuple[str, str | None]:
    """Classify one failure ID, returning (class, test path or None).

    Classes: ``file-path`` (``tests/unit/foo.py::...``), ``dotted-module``
    (``tests.unit.foo[.TestFoo]::...``), ``job-level`` (``lint:...`` with no
    test path), ``unrecognized`` (a form no classifier understands — these
    must escalate, never silently drop, so the next unknown writer becomes a
    loud failure instead of a wrong revert).
    """
    if not isinstance(raw, str):
        return "unrecognized", None
    candidate = raw.split("::", 1)[0].strip()
    if candidate.endswith(".py"):
        # Any .py candidate has a test-path shape; a bare filename that
        # matches nothing resolves to advisory downstream, not escalation.
        return "file-path", candidate
    if candidate.startswith("tests.") and "." in candidate:
        # pytest's JUnit fallback classname is the dotted test module,
        # optionally followed by the test class. Class names conventionally
        # start with an uppercase letter; preserve module-level test IDs.
        parts = candidate.split(".")
        if parts[-1] and parts[-1][0].isupper():
            parts = parts[:-1]
        return "dotted-module", "/".join(parts) + ".py"
    if ":" in raw and not candidate.startswith(("tests", ".")):
        return "job-level", None
    return "unrecognized", None


def failure_id_test_paths(failure_ids: list[object]) -> list[str]:
    """Extract repository test paths from junit-style failure IDs.

    ``tests/unit/foo.py::test_bar`` yields ``tests/unit/foo.py``. Some JUnit
    writers omit the testcase ``file`` attribute, leaving pytest's dotted
    classname instead (for example,
    ``tests.unit.foo.TestFoo::test_bar``); that form is normalized back to
    ``tests/unit/foo.py`` as well. Job-level IDs such as ``lint:Run CI lint
    mirror`` yield nothing. Unrecognized forms yield nothing here and are
    reported separately by :func:`unrecognized_failure_ids`.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for raw in failure_ids:
        _class, path = classify_failure_id(raw)
        if path is None or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def unrecognized_failure_ids(failure_ids: list[object]) -> list[str]:
    """Failure IDs no classifier understands. Never silently dropped."""
    return [str(raw) for raw in failure_ids if classify_failure_id(raw)[0] == "unrecognized"]


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
    """Return ``revert`` or ``advisory`` for a blamed SHA.

    See :func:`attribution_detail` for the deciding basis.
    """
    return attribution_detail(failure_ids, changed_paths, repo_root)[0]


def attribution_detail(
    failure_ids: list[object],
    changed_paths: list[str],
    repo_root: Path | None = None,
) -> tuple[str, str]:
    """Return ``(action, basis)`` for a blamed SHA's changed paths.

    Actions: ``revert`` (evidence ties a failure to the SHA) or ``advisory``
    (the evidence does not prove ownership). Basis records which signal
    decided: ``test-path``, ``import``, ``no-ownership-evidence``, or
    ``unrecognized-class``.

    Checks two owning signals before downgrading to advisory: the test
    path/stem heuristic (``paths_related_to_test``) and real import analysis
    (``imported_module_paths``) - a changed path the test file actually
    imports still triggers revert even when neither its name nor its stem
    matches.
    """
    unrecognized = unrecognized_failure_ids(failure_ids)
    if unrecognized:
        return "advisory", "unrecognized-class"
    test_paths = failure_id_test_paths(failure_ids)
    if not test_paths:
        return "advisory", "no-ownership-evidence"
    root = repo_root or Path.cwd()
    changed = set(changed_paths)
    changed_names = {Path(path).name for path in changed_paths}
    for test_path in test_paths:
        for related in paths_related_to_test(test_path):
            if related in changed or Path(related).name in changed_names:
                return "revert", "test-path"
        for imported in imported_module_paths(test_path, root):
            if imported in changed:
                return "revert", "import"
    return "advisory", "cleared"


ATTRIBUTION_CLASSES = {
    "code-regression",
    "external-ref-drift",
    "environment/transient-failure",
    "stale-run",
    "unknown",
    "persistent-failure",
}


def incident_key(failure_ids: list[object]) -> str:
    """Return a stable key for one failure signature, independent of run order."""
    canonical = json.dumps(sorted({str(failure_id) for failure_id in failure_ids}), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _source_inputs_changed(evidence: dict[str, object]) -> bool:
    current = evidence.get("source_inputs")
    predecessor = evidence.get("predecessor_source_inputs")
    return isinstance(current, dict) and isinstance(predecessor, dict) and current != predecessor


def classify_attribution(evidence: dict[str, object]) -> dict[str, object]:
    """Classify explicit attribution evidence; chronology alone never owns a failure."""
    failure_ids = evidence.get("failure_ids", [])
    if not isinstance(failure_ids, list):
        failure_ids = []
    failing_sha = str(evidence.get("failing_sha", "")).strip()
    target_sha = str(evidence.get("current_target_sha", "")).strip()
    predecessor = evidence.get("predecessor_evidence")
    ownership_match = evidence.get("ownership_match") is True
    rerun = evidence.get("rerun")
    proposed_revert = evidence.get("proposed_revert")
    comparison_state = str(evidence.get("comparison_state", "")).strip()
    comparison_failure = str(evidence.get("comparison_failure", "")).strip()
    reasons: list[str] = []

    if comparison_state == "unknown" or comparison_failure:
        classification = "unknown"
        reasons.append(comparison_failure or "signature comparison did not complete")
    elif not failing_sha or not target_sha:
        classification = "unknown"
        reasons.append("missing immutable failing or current target SHA")
    elif target_sha != failing_sha:
        classification = "stale-run"
        reasons.append("current develop target moved after the failing run")
    elif not isinstance(predecessor, dict) or not predecessor.get("run_url"):
        classification = "unknown"
        reasons.append("missing predecessor run evidence")
    elif unrecognized_failure_ids(failure_ids):
        classification = "unknown"
        reasons.append("failure identifier is not safely mappable")
    elif isinstance(rerun, dict) and rerun.get("conclusion") in {"success", "passed"}:
        classification = "environment/transient-failure"
        reasons.append("the failure did not reproduce on the exact commit")
    elif _source_inputs_changed(evidence) and not ownership_match:
        classification = "external-ref-drift"
        reasons.append("a relevant external source identity changed across the predecessor")
    elif ownership_match:
        classification = "code-regression"
        reasons.append("the failing test/job has a positive changed-subsystem ownership match")
    else:
        classification = "unknown"
        reasons.append("no positive changed-subsystem ownership evidence")

    if isinstance(proposed_revert, dict) and proposed_revert.get("introduced_failure") is True:
        classification = "unknown"
        reasons.append("the proposed revert introduced another failure")

    if classification not in ATTRIBUTION_CLASSES:
        classification = "unknown"
    next_actions = {
        "code-regression": "Inspect the current develop target and proposed inverse diff, then open a reviewable revert PR.",
        "external-ref-drift": "Reconcile the changed external reference or generated input; do not revert an unrelated commit.",
        "environment/transient-failure": "Rerun the affected job on the exact failing commit and inspect runner evidence.",
        "stale-run": "Re-evaluate the failure against the current develop target; do not revert the stale SHA.",
        "persistent-failure": "Investigate the existing red incident; no new revert is needed.",
        "unknown": "An owner must classify the evidence and choose fix-forward or a reviewed revert; keep develop red.",
    }
    owner = str(evidence.get("owner", "")).strip() or "unassigned"
    return {
        "classification": classification,
        "action": "revert" if classification == "code-regression" else "advisory",
        "attribution_basis": "owned-subsystem" if classification == "code-regression" else "evidence-required",
        "reasons": reasons,
        "next_action": next_actions[classification],
        "owner": owner,
        "incident_key": incident_key(failure_ids),
    }


def build_incident_artifact(evidence: dict[str, object], attribution: dict[str, object]) -> dict[str, object]:
    """Build the durable evidence record used by the idempotent incident flow."""
    failure_ids = evidence.get("failure_ids", [])
    if not isinstance(failure_ids, list):
        failure_ids = []
    return {
        "schema_version": 2,
        "incident_key": attribution["incident_key"],
        "failing_commit": {"sha": evidence.get("failing_sha", ""), "run_url": evidence.get("run_url", "")},
        "failing_pr": evidence.get("failing_pr", {}),
        "failure_ids": failure_ids,
        "jobs": evidence.get("jobs", []),
        "test_ids": failure_ids,
        "source_input_identities": {
            "current": evidence.get("source_inputs", {}),
            "predecessor": evidence.get("predecessor_source_inputs", {}),
        },
        "predecessor_evidence": evidence.get("predecessor_evidence", {}),
        "comparison_state": evidence.get("comparison_state", ""),
        "comparison_failure": evidence.get("comparison_failure", ""),
        "ownership_match": evidence.get("ownership_match"),
        "classification": attribution["classification"],
        "action": attribution["action"],
        "next_action": attribution["next_action"],
        "owner": attribution["owner"],
        "reasons": attribution["reasons"],
    }


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
        source_inputs = _parse_source_inputs(args.source_input)
        if args.junit:
            signature = build_signature_from_junit(args.job, args.junit, source_inputs)
            # A gate can fail for a reason junit never records - e.g. pytest-cov's
            # --cov-fail-under gate, which fails the step (and job) while every
            # individual testcase passes, leaving zero <failure>/<error> elements.
            # Trusting an empty junit-derived signature in that case would make
            # the diff see no new failures and silently suppress a real revert.
            # Only override when the job actually failed AND junit found nothing -
            # a job that failed WITH real testcase failures keeps its junit
            # signature (more precise than the coarse job-level descriptor).
            if args.job_failed and not signature["failure_ids"]:
                signature = build_signature_from_job_failure(args.job, args.failed_step, source_inputs)
        else:
            signature = build_signature_from_job_failure(args.job, args.failed_step, source_inputs)
    except SignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(signature, indent=2, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def changed_paths_for_sha(sha: str) -> list[str]:
    """List paths changed by ``sha`` (stdlib git, no shell).

    Diffed against the first parent so merge commits report their
    feature-side paths: a bare multi-parent diff-tree yields no paths and
    would downgrade real failures to advisory. Root commits (no parent)
    diff against the empty tree.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{sha}^1", sha],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise SignatureError(result.stderr.strip() or f"git diff failed for {sha}")
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
    evidence: dict[str, object] = {}
    if args.evidence:
        try:
            evidence_payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: could not read attribution evidence: {exc}", file=sys.stderr)
            return 1
        if not isinstance(evidence_payload, dict):
            print("error: attribution evidence must be a JSON object", file=sys.stderr)
            return 1
        evidence = evidence_payload

    legacy_action, legacy_basis = attribution_detail(failure_ids, changed_paths)
    evidence.update(
        {
            "failing_sha": args.sha,
            "failure_ids": failure_ids,
            "changed_paths": changed_paths,
            "test_paths": failure_id_test_paths(failure_ids),
            "unrecognized_ids": unrecognized_failure_ids(failure_ids),
            "ownership_match": evidence.get("ownership_match", legacy_action == "revert"),
            "ownership_basis": evidence.get("ownership_basis", legacy_basis),
        }
    )
    attribution = classify_attribution(evidence)
    result = build_incident_artifact(evidence, attribution)
    result.update(
        {
            "sha": args.sha,
            "test_paths": failure_id_test_paths(failure_ids),
            "changed_paths": changed_paths,
            "unrecognized_ids": unrecognized_failure_ids(failure_ids),
            "ownership_basis": evidence["ownership_basis"],
        }
    )
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
    build_parser.add_argument(
        "--source-input",
        action="append",
        default=[],
        help="Immutable source identity in NAME=IDENTITY form; may be repeated.",
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
    attribute_parser.add_argument(
        "--evidence",
        type=Path,
        help="JSON object containing immutable run, predecessor, source, target, and owner evidence.",
    )
    attribute_parser.add_argument("--out", type=Path, help="Path to write the attribution JSON")
    attribute_parser.set_defaults(func=_attribute_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
