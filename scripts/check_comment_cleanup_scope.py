from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_PATH = "quality/comment-cleanup-scope.json"


@dataclass(frozen=True)
class Finding:
    code: str
    subject: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code} {self.subject}: {self.detail}"


class PolicyError(ValueError):
    pass


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def tracked_paths(root: Path, base: str) -> list[str]:
    if not base or len(base) != 40 or any(char not in "0123456789abcdef" for char in base):
        raise PolicyError("base must be a full lowercase commit SHA")
    return sorted(path for path in git(root, "ls-tree", "-r", "-z", "--name-only", base).decode().split("\0") if path)


def frozen_task_ids(root: Path, value: str) -> set[str]:
    path = (root / value).resolve()
    if root not in path.parents:
        raise PolicyError("task set must stay under the repository root")
    relative = path.relative_to(root)
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(relative)], check=False)
    if ignored.returncode != 0:
        raise PolicyError("task set must be ignored local evidence")
    task_ids = {
        line.removeprefix("TODO: ").strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("TODO: ") or line.startswith("comment-cleanup-")
    }
    if not task_ids or any(not task_id.startswith("comment-cleanup-") for task_id in task_ids):
        raise PolicyError("task set must contain comment-cleanup task IDs")
    return task_ids


def valid_path(path: object) -> bool:
    if not isinstance(path, str):
        return False
    parsed = PurePosixPath(path)
    return bool(path) and not parsed.is_absolute() and ".." not in parsed.parts and "\\" not in path


def matches(path: str, selector: dict[str, str]) -> bool:
    if set(selector) == {"path"}:
        return path == selector["path"]
    if set(selector) == {"prefix"}:
        return path.startswith(selector["prefix"])
    raise PolicyError("selector must contain exactly path or prefix")


def valid_selector(selector: object, *, allow_empty_prefix: bool = False) -> bool:
    if not isinstance(selector, dict) or set(selector) not in ({"path"}, {"prefix"}):
        return False
    value = next(iter(selector.values()))
    if allow_empty_prefix and selector.keys() == {"prefix"} and value == "":
        return True
    return valid_path(value)


def require_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise PolicyError(f"{label} fields must be {sorted(fields)}")


def check_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{label} must be a non-empty string")
    return value


def check_owner(value: Any, label: str, task_ids: set[str] | None = None) -> str:
    owner = check_string(value, label)
    if not owner.startswith("comment-cleanup-"):
        raise PolicyError(f"{label} must name a comment-cleanup task")
    if task_ids is not None and owner not in task_ids:
        raise PolicyError(f"{label} is not in the frozen task set")
    return owner


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    require_fields(
        policy,
        {
            "version",
            "maintained_roots",
            "ownership_rules",
            "external_entries",
            "payloads",
            "derived_rules",
            "consumer_edges",
            "directives",
            "notices",
            "obligations",
            "review_dispositions",
        },
        "policy",
    )
    if policy["version"] != 1:
        raise PolicyError("unsupported policy version")
    for name in policy:
        if name != "version" and not isinstance(policy[name], list):
            raise PolicyError(f"{name} must be a list")
    return policy


def validate_roots(policy: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, root in enumerate(policy["maintained_roots"]):
        if not isinstance(root, dict):
            raise PolicyError(f"maintained_roots[{index}] must be an object")
        require_fields(root, {"id", "selector", "kind"}, f"maintained_roots[{index}]")
        for field in ("id", "kind"):
            check_string(root[field], f"maintained_roots[{index}].{field}")
        if not valid_selector(root["selector"], allow_empty_prefix=True):
            raise PolicyError(f"invalid maintained root: {root['selector']}")
        matches("", root["selector"])
        result.append(root)
    return result


def validate_rules(policy: dict[str, Any], task_ids: set[str] | None = None) -> list[dict[str, Any]]:
    result = []
    ids = set()
    for index, rule in enumerate(policy["ownership_rules"]):
        if not isinstance(rule, dict):
            raise PolicyError(f"ownership_rules[{index}] must be an object")
        require_fields(rule, {"id", "owner", "state", "blocking_disposition", "priority", "selectors"}, f"rule {index}")
        rule_id = check_string(rule["id"], f"rule {index}.id")
        if rule_id in ids:
            raise PolicyError(f"duplicate ownership rule: {rule_id}")
        ids.add(rule_id)
        check_owner(rule["owner"], f"rule {rule_id}.owner", task_ids)
        if rule["state"] not in {"ready", "blocked"}:
            raise PolicyError(f"rule {rule_id}.state must be ready or blocked")
        check_string(rule["blocking_disposition"], f"rule {rule_id}.blocking_disposition")
        if not isinstance(rule["priority"], int):
            raise PolicyError(f"rule {rule_id}.priority must be an integer")
        if not isinstance(rule["selectors"], list) or not rule["selectors"]:
            raise PolicyError(f"rule {rule_id}.selectors must be a non-empty list")
        for selector in rule["selectors"]:
            if not valid_selector(selector):
                raise PolicyError(f"rule {rule_id} has an invalid selector")
            matches("", selector)
        result.append(rule)
    return result


def base_blob(root: Path, base: str, path: str) -> bytes:
    return git(root, "show", f"{base}:{path}")


def validate_evidence(
    policy: dict[str, Any], root: Path, base: str, paths: set[str], task_ids: set[str] | None = None
) -> None:
    for category, fields in {
        "external_entries": {"path", "owner", "provenance", "governing_requirement", "blocking_disposition"},
        "directives": {"path", "token", "consumer", "necessity", "alternative", "owner", "removal_trigger"},
        "notices": {
            "path",
            "blob_sha256",
            "byte_start",
            "byte_end",
            "retained_sha256",
            "governing_requirement",
            "source_identity",
            "owner",
            "blocking_disposition",
        },
        "obligations": {
            "path",
            "token",
            "destination",
            "tracker_reference",
            "approved_destination",
            "owner",
            "blocking_disposition",
        },
    }.items():
        for index, entry in enumerate(policy[category]):
            if not isinstance(entry, dict):
                raise PolicyError(f"{category}[{index}] must be an object")
            require_fields(entry, fields, f"{category}[{index}]")
            for field, value in entry.items():
                if category == "notices" and field in {"byte_start", "byte_end"}:
                    if not isinstance(value, int):
                        raise PolicyError(f"{category}[{index}].{field} must be an integer")
                elif category == "obligations" and field in {"tracker_reference", "approved_destination"}:
                    if not isinstance(value, str):
                        raise PolicyError(f"{category}[{index}].{field} must be a string")
                else:
                    check_string(value, f"{category}[{index}].{field}")
            if entry["path"] not in paths:
                raise PolicyError(f"{category}[{index}] path is not tracked at the immutable base")
            check_owner(entry["owner"], f"{category}[{index}].owner", task_ids)
            if category == "obligations":
                tracker_reference = entry["tracker_reference"]
                approved_destination = entry["approved_destination"]
                if bool(tracker_reference) == bool(approved_destination):
                    raise PolicyError(
                        f"obligations[{index}] must have exactly one tracker_reference or approved_destination"
                    )
            if category == "notices":
                for field in ("blob_sha256", "retained_sha256"):
                    if len(entry[field]) != 64 or any(char not in "0123456789abcdef" for char in entry[field]):
                        raise PolicyError(f"notice {entry['path']} must use a lowercase SHA-256 digest")
                blob = base_blob(root, base, entry["path"])
                if hashlib.sha256(blob).hexdigest() != entry["blob_sha256"]:
                    raise PolicyError(f"notice {entry['path']} blob digest does not match immutable base")
                start = entry["byte_start"]
                end = entry["byte_end"]
                if start < 0 or end <= start or end > len(blob):
                    raise PolicyError(f"notice {entry['path']} has an invalid retained byte range")
                if hashlib.sha256(blob[start:end]).hexdigest() != entry["retained_sha256"]:
                    raise PolicyError(f"notice {entry['path']} retained-byte digest does not match immutable base")


def validate_payloads_and_edges(policy: dict[str, Any], paths: set[str], task_ids: set[str] | None = None) -> None:
    payload_ids = set()
    for index, payload in enumerate(policy["payloads"]):
        if not isinstance(payload, dict):
            raise PolicyError(f"payloads[{index}] must be an object")
        require_fields(
            payload, {"id", "path", "carrier", "owner", "state", "blocking_disposition"}, f"payloads[{index}]"
        )
        payload_id = check_string(payload["id"], f"payloads[{index}].id")
        if payload_id in payload_ids:
            raise PolicyError(f"duplicate payload: {payload_id}")
        payload_ids.add(payload_id)
        if payload["path"] not in paths:
            raise PolicyError(f"payload {payload_id} path is not tracked at the immutable base")
        check_string(payload["carrier"], f"payload {payload_id}.carrier")
        check_owner(payload["owner"], f"payload {payload_id}.owner", task_ids)
        if payload["state"] not in {"ready", "blocked"}:
            raise PolicyError(f"payload {payload_id}.state must be ready or blocked")
        check_string(payload["blocking_disposition"], f"payload {payload_id}.blocking_disposition")
    edge_keys = set()
    graph: dict[str, set[str]] = {}
    for index, edge in enumerate(policy["consumer_edges"]):
        if not isinstance(edge, dict):
            raise PolicyError(f"consumer_edges[{index}] must be an object")
        require_fields(
            edge,
            {"producer", "consumer", "owner", "state", "blocking_disposition", "proof"},
            f"consumer_edges[{index}]",
        )
        for field in ("producer", "consumer", "proof", "blocking_disposition"):
            check_string(edge[field], f"consumer_edges[{index}].{field}")
        check_owner(edge["owner"], f"consumer_edges[{index}].owner", task_ids)
        if edge["state"] not in {"ready", "blocked"}:
            raise PolicyError(f"consumer_edges[{index}].state must be ready or blocked")
        for endpoint in (edge["producer"], edge["consumer"]):
            if endpoint not in paths and endpoint not in payload_ids:
                raise PolicyError(f"consumer edge endpoint is neither a tracked path nor a payload: {endpoint}")
        key = edge["producer"], edge["consumer"]
        if key in edge_keys:
            raise PolicyError(f"duplicate consumer edge: {key[0]} -> {key[1]}")
        edge_keys.add(key)
        graph.setdefault(key[0], set()).add(key[1])
    active = set()
    complete = set()

    def visit(endpoint: str) -> None:
        if endpoint in active:
            raise PolicyError(f"cyclic consumer edge: {endpoint}")
        if endpoint in complete:
            return
        active.add(endpoint)
        for child in graph.get(endpoint, set()):
            visit(child)
        active.remove(endpoint)
        complete.add(endpoint)

    for endpoint in graph:
        visit(endpoint)


def validate_dispositions(policy: dict[str, Any], task_ids: set[str] | None = None) -> None:
    expected = {f"R{number}" for number in range(1, 19)}
    found = set()
    for index, item in enumerate(policy["review_dispositions"]):
        if not isinstance(item, dict):
            raise PolicyError(f"review_dispositions[{index}] must be an object")
        require_fields(
            item,
            {"id", "disposition", "requirements", "owner", "original_verdict", "rationale", "acceptance_refs"},
            f"review_dispositions[{index}]",
        )
        item_id = check_string(item["id"], f"review_dispositions[{index}].id")
        if item_id in found:
            raise PolicyError(f"duplicate review disposition: {item_id}")
        found.add(item_id)
        if item["disposition"] not in {"accepted", "narrowed", "rebutted"}:
            raise PolicyError(f"invalid disposition for {item_id}")
        if not isinstance(item["requirements"], list) or not item["requirements"]:
            raise PolicyError(f"review disposition {item_id} needs requirements")
        for requirement in item["requirements"]:
            check_string(requirement, f"review disposition {item_id} requirement")
        if item["original_verdict"] not in {"accepted", "narrowed", "rebutted"}:
            raise PolicyError(f"invalid original verdict for {item_id}")
        check_string(item["rationale"], f"review disposition {item_id} rationale")
        if not isinstance(item["acceptance_refs"], list) or not item["acceptance_refs"]:
            raise PolicyError(f"review disposition {item_id} needs acceptance references")
        for reference in item["acceptance_refs"]:
            check_string(reference, f"review disposition {item_id} acceptance reference")
        check_owner(item["owner"], f"review disposition {item_id}.owner", task_ids)
    if found != expected:
        raise PolicyError(f"review dispositions must be exactly {sorted(expected)}")


def validate_derived_rules(policy: dict[str, Any], task_ids: set[str] | None = None) -> list[dict[str, Any]]:
    result = []
    ids = set()
    for index, rule in enumerate(policy["derived_rules"]):
        if not isinstance(rule, dict):
            raise PolicyError(f"derived_rules[{index}] must be an object")
        require_fields(
            rule, {"id", "method", "state", "blocking_disposition", "priority", "selectors"}, f"derived {index}"
        )
        rule_id = check_string(rule["id"], f"derived {index}.id")
        if rule_id in ids:
            raise PolicyError(f"duplicate derived rule: {rule_id}")
        ids.add(rule_id)
        if rule["method"] != "python-imports":
            raise PolicyError(f"derived {rule_id}.method must be python-imports")
        if rule["state"] not in {"ready", "blocked"}:
            raise PolicyError(f"derived {rule_id}.state must be ready or blocked")
        check_string(rule["blocking_disposition"], f"derived {rule_id}.blocking_disposition")
        if not isinstance(rule["priority"], int):
            raise PolicyError(f"derived {rule_id}.priority must be an integer")
        if not isinstance(rule["selectors"], list) or not rule["selectors"]:
            raise PolicyError(f"derived {rule_id}.selectors must be a non-empty list")
        for selector in rule["selectors"]:
            if not valid_selector(selector):
                raise PolicyError(f"derived {rule_id} has an invalid selector")
        result.append(rule)
    return result


def read_blobs(root: Path, base: str, paths: list[str]) -> dict[str, bytes]:
    if not paths:
        return {}
    request = "".join(f"{base}:{path}\n" for path in paths).encode()
    output = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input=request, capture_output=True, check=True
    ).stdout
    blobs = {}
    offset = 0
    for path in paths:
        end = output.index(b"\n", offset)
        header = output[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise PolicyError(f"cannot read {path} at the immutable base")
        size = int(header[2])
        blobs[path] = output[end + 1 : end + 1 + size]
        offset = end + 1 + size + 1
    return blobs


def imported_modules(source: bytes) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.split(".")[0] == "benchbox")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] == "benchbox":
                modules.add(node.module)
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def import_owner(source: bytes, path_owners: dict[str, str | None]) -> str | None:
    owners = set()
    for module in imported_modules(source):
        stem = module.replace(".", "/")
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate in path_owners:
                if candidate != "benchbox/__init__.py" and path_owners[candidate]:
                    owners.add(path_owners[candidate])
                break
    return owners.pop() if len(owners) == 1 else None


def apply_derived_rules(
    resolved: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    root: Path,
    base: str,
    priorities: dict[str, int],
) -> None:
    if not rules:
        return
    path_owners = {record["path"]: record["owner"] for record in resolved if record["path"].startswith("benchbox/")}
    for rule in rules:
        eligible = [
            record
            for record in resolved
            if record["path"].endswith(".py")
            and priorities.get(record["path"], -1) < rule["priority"]
            and any(matches(record["path"], selector) for selector in rule["selectors"])
        ]
        blobs = read_blobs(root, base, [record["path"] for record in eligible])
        for record in eligible:
            owner = import_owner(blobs[record["path"]], path_owners)
            if owner is None:
                continue
            record.update(
                owner=owner, state=rule["state"], blocking_disposition=rule["blocking_disposition"], rule=rule["id"]
            )
            priorities[record["path"]] = rule["priority"]


def selected_root(path: str, roots: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [root for root in roots if matches(path, root["selector"])]
    if not candidates:
        return None
    specificity = max(len(next(iter(root["selector"].values()))) for root in candidates)
    selected = [root for root in candidates if len(next(iter(root["selector"].values()))) == specificity]
    if len(selected) != 1:
        root_ids = ", ".join(sorted(root["id"] for root in selected))
        raise PolicyError(f"maintained-root collision for {path}: {root_ids}")
    return selected[0]


def owned_paths(
    paths: list[str],
    roots: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    priorities: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    results = []
    findings = []
    for path in paths:
        root = selected_root(path, roots)
        if root is None:
            continue
        candidates = [rule for rule in rules if any(matches(path, selector) for selector in rule["selectors"])]
        if not candidates:
            findings.append(Finding("SCOPE001", path, "no ownership rule"))
            results.append(
                {
                    "path": path,
                    "kind": root["kind"],
                    "owner": None,
                    "state": "blocked",
                    "blocking_disposition": "Ownership is not frozen for this maintained path.",
                    "rule": None,
                }
            )
            continue
        priority = max(rule["priority"] for rule in candidates)
        selected = [rule for rule in candidates if rule["priority"] == priority]
        owners = {rule["owner"] for rule in selected}
        if len(selected) != 1 or len(owners) != 1:
            findings.append(Finding("SCOPE002", path, "ownership rule collision"))
            results.append(
                {
                    "path": path,
                    "kind": root["kind"],
                    "owner": None,
                    "state": "blocked",
                    "blocking_disposition": "Conflicting ownership rules require integrator resolution.",
                    "rule": sorted(rule["id"] for rule in selected),
                    "competing_owners": sorted(owners),
                }
            )
            continue
        rule = selected[0]
        if priorities is not None:
            priorities[path] = priority
        results.append(
            {
                "path": path,
                "kind": root["kind"],
                "owner": rule["owner"],
                "state": rule["state"],
                "blocking_disposition": rule["blocking_disposition"],
                "rule": rule["id"],
            }
        )
    return results, findings


def dependency_findings(policy: dict[str, Any], resolved: list[dict[str, Any]]) -> list[Finding]:
    states = {record["path"]: record["state"] for record in resolved}
    states.update({payload["id"]: payload["state"] for payload in policy["payloads"]})
    findings = []
    for edge in policy["consumer_edges"]:
        producer = edge["producer"]
        consumer = edge["consumer"]
        if edge["state"] == "blocked" and states.get(producer) == "ready":
            findings.append(Finding("SCOPE003", producer, f"blocked consumer dependency: {consumer}"))
        if edge["state"] == "ready" and states.get(consumer) != "ready":
            findings.append(Finding("SCOPE004", consumer, f"unresolved consumer dependency for: {producer}"))
    return findings


def output_path(root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    path = (root / value).resolve()
    if root not in path.parents:
        raise PolicyError("output must stay under the repository root")
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path.relative_to(root))], check=False)
    if ignored.returncode != 0:
        raise PolicyError("output path must be ignored")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--task-set", required=True)
    parser.add_argument("--policy", default=POLICY_PATH)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        policy_path = root / args.policy
        if args.policy != POLICY_PATH:
            raise PolicyError("policy location is fixed")
        policy = load_policy(policy_path)
        paths = tracked_paths(root, args.base)
        path_set = set(paths)
        task_ids = frozen_task_ids(root, args.task_set)
        roots = validate_roots(policy)
        rules = validate_rules(policy, task_ids)
        derived = validate_derived_rules(policy)
        validate_evidence(policy, root, args.base, path_set, task_ids)
        validate_payloads_and_edges(policy, path_set, task_ids)
        validate_dispositions(policy, task_ids)
        priorities: dict[str, int] = {}
        resolved, findings = owned_paths(paths, roots, rules, priorities)
        apply_derived_rules(resolved, derived, root, args.base, priorities)
        owned = {record["path"] for record in resolved if record["owner"]}
        findings = [finding for finding in findings if finding.subject not in owned]
        findings.extend(dependency_findings(policy, resolved))
        output = output_path(root, args.output)
        report = {
            "base": args.base,
            "paths": resolved,
            "sha256": hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest(),
        }
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for finding in findings:
            print(finding, file=sys.stderr)
        print(f"comment-cleanup-scope: {len(resolved)} resolved paths, {len(findings)} ownership findings")
        return int(bool(findings))
    except (OSError, UnicodeError, json.JSONDecodeError, PolicyError, subprocess.CalledProcessError) as error:
        print(f"comment-cleanup-scope: configuration failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
