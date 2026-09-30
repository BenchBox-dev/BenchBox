from __future__ import annotations

import argparse
import codecs
import io
import json
import os
import re
import stat
import subprocess
import sys
import tokenize
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path, PurePosixPath

from comment_syntax import Finding, javascript_requests, language, scan, source_language

POLICY_PATH = "quality/comment-policy.json"
BOOTSTRAP_BASE = "ed5c263c513ba65499f4918d3a7de607f280c65b"
DIRECTIVES = (
    r"# noqa: [A-Z]+[0-9]+(?:, ?[A-Z]+[0-9]+)*",
    r"# type: ignore\[[a-z0-9_-]+(?:, ?[a-z0-9_-]+)*\]",
    r"# pragma: no (?:cover|branch)",
    r"# fmt: (?:off|on|skip)",
    r"# (?:ruff|flake8): noqa: [A-Z]+[0-9]+(?:, ?[A-Z]+[0-9]+)*",
    r"# shellcheck (?:disable=SC[0-9]+(?:,SC[0-9]+)*|shell=(?:bash|sh|dash|ksh))",
    r"/// <reference (?:types|path)=\"[^\"\n]+\" ?/>",
    r"// @ts-(?:expect-error|ignore|check|nocheck)",
    r"/\*\* @vitest-environment (?:jsdom|node|happy-dom) \*/",
    r"// @vitest-environment (?:jsdom|node|happy-dom)",
    r"/\*\+ [A-Z_]+\([A-Za-z0-9_., ]+\) \*/",
)


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def validate_path(path: str) -> None:
    if not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
        raise ValueError(f"invalid policy path: {path!r}")
    if any(char in path for char in "*?[]"):
        raise ValueError("policy paths must be exact files or directory prefixes")


def load_policy(raw: bytes) -> dict:
    policy = json.loads(raw)
    if set(policy) != {"version", "external", "completed", "exceptions"} or policy["version"] != 1:
        raise ValueError("invalid comment-policy schema")
    for key in ("external", "completed", "exceptions"):
        if not isinstance(policy[key], list):
            raise ValueError(f"{key} must be a list")
    for entry in policy["external"]:
        if set(entry) != {"path", "owner", "provenance"} or not all(
            isinstance(v, str) and v.strip() for v in entry.values()
        ):
            raise ValueError("external scope requires path, owner and provenance")
        validate_path(entry["path"])
    for path in policy["completed"]:
        validate_path(path)
        if any(matches(path, entry["path"]) or matches(entry["path"], path) for entry in policy["external"]):
            raise ValueError("completed and external scopes cannot overlap")
    identities = set()
    for entry in policy["exceptions"]:
        required = {"path", "symbol", "text", "kind", "consumer", "necessity", "alternative", "owner", "removal"}
        fixture_fields = {"payload", "finding_kind"} if entry.get("kind") == "fixture" else set()
        required |= fixture_fields
        if (
            set(entry) - {"expires", "count"} != required
            or not all(isinstance(v, str) for k, v in entry.items() if k != "count")
            or type(entry.get("count", 1)) is not int
            or entry.get("count", 1) < 1
        ):
            raise ValueError(
                "exception requires an exact identity, consumer, necessity, alternative, owner and removal"
            )
        if any(not entry[key].strip() for key in required - {"symbol"}):
            raise ValueError("exception evidence must not be empty")
        validate_path(entry["path"])
        validate_path(entry["consumer"])
        if entry["kind"] not in {"directive", "notice", "fixture"}:
            raise ValueError("explanatory comment and docstring exceptions are prohibited")
        if entry["kind"] == "fixture" and entry["finding_kind"] not in {"comment", "payload-error"}:
            raise ValueError("fixture must identify an actual comment or malformed parser input")
        if entry["kind"] == "directive":
            if not any(re.fullmatch(pattern, entry["text"]) for pattern in DIRECTIVES):
                raise ValueError("directive must match an exact registered grammar without explanatory suffixes")
            suppression = re.search(
                r"noqa|type: ignore|pragma: no|fmt: (?:off|skip)|disable=|@ts-(?:expect-error|ignore|nocheck)",
                entry["text"],
            )
            if (suppression and "expires" not in entry) or (
                "expires" in entry and date.fromisoformat(entry["expires"]) < date.today()
            ):
                raise ValueError("directive exception needs an unexpired review date")
        identity = (
            entry["path"],
            entry["symbol"],
            entry["text"],
            entry["kind"],
            entry.get("payload", ""),
            entry.get("finding_kind", "comment"),
        )
        if identity in identities:
            raise ValueError("duplicate exception identity")
        identities.add(identity)
    return policy


def check_ratchet(policy: dict, baseline: dict) -> None:
    if not set(baseline["completed"]).issubset(policy["completed"]):
        raise ValueError("completed scopes cannot be removed")
    if any(entry not in baseline["external"] for entry in policy["external"]):
        raise ValueError("candidate policy cannot add or expand external exclusions")


def matches(path: str, scope: str) -> bool:
    return path.startswith(scope) if scope.endswith("/") else path == scope


def bootstrap_base_allowed(root: Path, base: str) -> bool:
    contains_rollout = (
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", BOOTSTRAP_BASE, base], capture_output=True
        ).returncode
        == 0
    )
    installed = any(
        subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{base}:{path}"], capture_output=True).returncode
        == 0
        for path in ("scripts/run_comment_policy.py", "quality/comment-policy.json")
    )
    return contains_rollout and not installed


def allowed(finding: Finding, policy: dict, source: str, budget: Counter | None = None) -> bool:
    text = finding.text
    if finding.kind == "comment" and not finding.symbol:
        if (
            source_language(finding.path, source) in {"python", "bash", "javascript", "unsupported"}
            and finding.line == 1
            and re.fullmatch(
                r"#!(?:/usr/bin/env (?:bash|sh|zsh|ksh|python3|node)|/(?:bin|usr/bin)/(?:bash|sh|zsh|ksh|python3|node))",
                text,
            )
        ):
            return True
        cookie = re.fullmatch(r"# (?:-\*- )?coding[:=] ?([\w.-]+)(?: -\*-)?", text)
        if (
            source_language(finding.path, source) == "python"
            and cookie
            and finding.line <= 2
            and (finding.line == 1 or not source.splitlines()[0].strip() or source.splitlines()[0].startswith("#"))
        ):
            return codecs.lookup(cookie.group(1)).name != "utf-8"
    for index, entry in enumerate(policy["exceptions"]):
        if (
            finding.path == entry["path"]
            and finding.symbol == entry["symbol"]
            and text == entry["text"]
            and finding.kind == entry.get("finding_kind", "comment")
            and (entry["kind"] != "fixture" or finding.payload == entry["payload"])
            and (budget is None or budget[index] > 0)
        ):
            if budget is not None:
                budget[index] -= 1
            return True
    return False


def decode(path: str, raw: bytes) -> str:
    if language(path) == "python" or re.match(rb"#![^\r\n]*\bpython[0-9.]*\b", raw):
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return raw.decode(encoding)
    return raw.decode("utf-8-sig")


def native_results(root: Path, requests: dict[str, str]) -> dict[str, list[dict]]:
    results = {}
    pending = requests
    while pending:
        response = subprocess.run(
            ["node", str(Path(__file__).with_name("comment_syntax_js.cjs"))],
            input=json.dumps(pending),
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "COMMENT_POLICY_ROOT": str(root)},
        )
        batch = json.loads(response.stdout)
        if set(batch) != set(pending):
            raise ValueError("native parser returned a different request set")
        results.update(batch)
        pending = {
            key: text
            for rows in batch.values()
            for row in rows
            if row["kind"] == "payload"
            for key, text in javascript_requests("payload." + row["language"], row["text"], row["language"]).items()
            if key not in results
        }
    return results


def scan_sources(root: Path, sources: dict[str, bytes], policy: dict) -> list[Finding]:
    decoded = {}
    errors = []
    for path, raw in sources.items():
        excluded = any(matches(path, e["path"]) for e in policy["external"])
        if excluded and ("external_members" not in policy or path in policy["external_members"]):
            continue
        if language(path) or raw.startswith(b"#!"):
            try:
                decoded[path] = decode(path, raw)
            except (UnicodeError, SyntaxError) as exc:
                errors.append(Finding(path, 1, "coverage-error", str(exc)))
    requests = {
        key: text
        for path, source in decoded.items()
        for key, text in javascript_requests(path, source, language(path)).items()
    }
    js_results = native_results(root, requests)
    budget = Counter({index: entry.get("count", 1) for index, entry in enumerate(policy["exceptions"])})
    return errors + [
        finding
        for path, text in decoded.items()
        for finding in scan(path, text, source_language(path, text), js_results)
        if not allowed(finding, policy, text, budget)
    ]


def introduced(current: list[Finding], baseline: list[Finding], completed: list[str]) -> list[Finding]:
    remaining = Counter(f.identity for f in baseline)
    result = []
    for finding in current:
        if (
            finding.kind in {"coverage-error", "payload-error"}
            or any(matches(finding.path, scope) for scope in completed)
            or not remaining[finding.identity]
        ):
            result.append(finding)
        else:
            remaining[finding.identity] -= 1
    return result


def source_paths(root: Path, staged: bool) -> list[str]:
    paths = (
        git(root, "ls-files", "-z", "--cached", *([] if staged else ["--others", "--exclude-standard"]))
        .decode()
        .split("\0")
    )
    executables = {
        entry.split("\t", 1)[1]
        for entry in git(root, "ls-files", "--stage", "-z").decode().split("\0")
        if entry.startswith("100755 ")
    }
    selected = []
    for path in sorted(set(paths) - {""}):
        if language(path):
            selected.append(path)
        elif path in executables or (
            not staged and (root / path).is_file() and (root / path).stat().st_mode & stat.S_IXUSR
        ):
            if staged:
                header = git(root, "show", f":{path}")[:128]
            else:
                with (root / path).open("rb") as stream:
                    header = stream.read(128)
            if header.startswith(b"#!"):
                selected.append(path)
    paths = selected
    return paths


def validate_consumers(root: Path, policy: dict) -> None:
    for entry in policy["exceptions"]:
        if not (root / entry["consumer"]).is_file():
            raise ValueError(f"exception consumer missing: {entry['consumer']}")
    for entry in policy["external"]:
        validate_path(entry["provenance"])
        if not (root / entry["provenance"]).is_file():
            raise ValueError(f"external provenance missing: {entry['provenance']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject discretionary comments and docstrings in maintained source.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("strict", "transition", "report"), default="strict")
    parser.add_argument("--base")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--policy", default=POLICY_PATH)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if args.policy != POLICY_PATH:
            raise ValueError("policy location is fixed")
        policy = load_policy(git(root, "show", f":{POLICY_PATH}") if args.staged else (root / POLICY_PATH).read_bytes())
        if args.mode == "transition" and not args.base:
            raise ValueError("transition requires an explicit immutable base SHA")
        if args.base and not re.fullmatch(r"[a-f0-9]{40}", args.base):
            raise ValueError("base must be a full commit SHA")
        if args.bootstrap and (args.mode != "transition" or not bootstrap_base_allowed(root, args.base or "")):
            raise ValueError("bootstrap requires a base that contains the initial rollout commit")
        baseline_policy = policy
        if args.base and not args.bootstrap:
            baseline_policy = load_policy(git(root, "show", f"{args.base}:{POLICY_PATH}"))
            check_ratchet(policy, baseline_policy)
        paths = source_paths(root, args.staged)
        if not paths:
            raise ValueError("empty source inventory")
        for scope in args.path:
            validate_path(scope)
            if not any(matches(path, scope) for path in paths):
                raise ValueError(f"scope matches no registered source: {scope}")
        if args.mode == "transition":
            revoked = [e["path"] for e in baseline_policy["exceptions"] if e not in policy["exceptions"]]
            revoked.extend(e["path"] for e in baseline_policy["external"] if e not in policy["external"])
            changed = set(
                git(
                    root, "diff", "--name-only", "--no-renames", "-z", *(["--cached"] if args.staged else []), args.base
                )
                .decode()
                .split("\0")
            )
            if not args.staged:
                changed.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
            paths = [
                path
                for path in paths
                if path in changed or any(matches(path, scope) for scope in [*policy["completed"], *revoked])
            ]
        if args.path:
            paths = [path for path in paths if any(matches(path, scope) for scope in args.path)]
        sources = {
            path: git(root, "show", f":{path}") if args.staged else (root / path).read_bytes()
            for path in paths
            if args.staged or (root / path).is_file()
        }
        validate_consumers(root, policy)
        effective_policy = {
            **policy,
            "exceptions": [e for e in policy["exceptions"] if e in baseline_policy["exceptions"]],
        }
        base_paths = []
        if args.mode == "transition":
            base_paths = git(root, "ls-tree", "-r", "--name-only", "-z", args.base).decode().split("\0")
            effective_policy["external_members"] = set(base_paths)
        current = scan_sources(root, sources, effective_policy)
        failed = current
        if args.mode == "transition":
            base_sources = {path: git(root, "show", f"{args.base}:{path}") for path in base_paths if path in sources}
            baseline = scan_sources(root, base_sources, baseline_policy)
            failed = introduced(current, baseline, policy["completed"])
        if args.json_out:
            args.json_out.write_text(
                json.dumps(
                    {
                        "mode": args.mode,
                        "base": args.base,
                        "findings": [asdict(f) for f in current],
                        "failed": [asdict(f) for f in failed],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        for finding in failed[:100]:
            excerpt = finding.text.splitlines()[0][:160] if finding.text else ""
            print(f"{finding.path}:{finding.line}: CP {finding.kind}: {excerpt}")
        print(
            f"comment-policy: {len(sources)} source files, {len(current)} violations, {len(failed)} enforced failures ({args.mode})"
        )
        return int(bool(failed) and args.mode != "report")
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"comment-policy: configuration or parser failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
