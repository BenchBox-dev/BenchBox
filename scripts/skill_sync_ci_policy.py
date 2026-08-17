#!/usr/bin/env python3
"""Fail-closed trust policy for BenchBox skill-sync CI routing.

The verifier revision is a trust anchor owned by BenchBox maintainers. It is
intentionally independent of every revision selected by ``skill-sync.yaml``.
Advance it only with a clean-runner clone/build/verify proof and full CI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

VERIFIER_REPOSITORY = "https://github.com/joeharris76/skill-sync.git"
VERIFIER_REF = "6d09682dabe2ff0d68f400d60f8ba8b87f8c02aa"
MANIFEST_PATH = Path("skill-sync.yaml")
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SOURCE_START_RE = re.compile(r"^  - name: ([A-Za-z0-9_-]+)$")
_SOURCE_FIELD_RE = re.compile(r"^    ([A-Za-z0-9_-]+): (.+)$")
_REF_LINE_RE = re.compile(r"^(    ref: )([0-9a-f]{40})$")

ALLOWED_SOURCES = {
    "canonical": ("git", "https://github.com/joeharris76/skill-sync-skills.git", "skills"),
    "todo-context-efficiency": ("git", "https://github.com/joeharris76/skill-sync-skills.git", "skills"),
    "product": ("git", VERIFIER_REPOSITORY, "skills"),
}


class PolicyError(ValueError):
    """Manifest or Git evidence violates the skill CI trust boundary."""


@dataclass(frozen=True)
class ManifestDecision:
    narrow_eligible: bool
    reason: str
    base_ref: str | None = None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _source_blocks(text: str) -> dict[str, dict[str, str]]:
    lines = text.splitlines()
    try:
        start = lines.index("sources:") + 1
    except ValueError as exc:
        raise PolicyError("manifest has no top-level sources block") from exc

    sources: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_name: str | None = None
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        match = _SOURCE_START_RE.match(line)
        if match:
            current_name = match.group(1)
            if current_name in sources:
                raise PolicyError(f"duplicate source name: {current_name}")
            current = {"name": current_name}
            sources[current_name] = current
            continue
        field = _SOURCE_FIELD_RE.match(line)
        if field and current is not None:
            key, value = field.groups()
            if key in current:
                raise PolicyError(f"duplicate source field: {current_name}.{key}")
            current[key] = _unquote(value)
    return sources


def validate_manifest_text(text: str) -> None:
    """Validate immutable source provenance and tracked-target containment."""
    sources = _source_blocks(text)
    if set(sources) != set(ALLOWED_SOURCES):
        raise PolicyError(f"source names must be exactly {sorted(ALLOWED_SOURCES)}; got {sorted(sources)}")
    for name, expected in ALLOWED_SOURCES.items():
        source = sources[name]
        allowed_fields = {"name", "type", "url", "ref", "subdir"}
        if set(source) != allowed_fields:
            raise PolicyError(f"source {name} fields must be exactly {sorted(allowed_fields)}")
        actual = (source["type"], source["url"], source["subdir"])
        if actual != expected:
            raise PolicyError(f"source {name} trust tuple is not approved: {actual!r}")
        if not _FULL_SHA_RE.fullmatch(source["ref"]):
            raise PolicyError(f"source {name} ref must be a lowercase 40-character commit SHA")

    required_fragments = (
        "targets:\n  claude:\n    dir: .claude/skills\n    tracked: true",
        "install_mode: mirror",
        "overrides:\n  skill-sync:\n    source_name: product\n  todo:\n    source_name: todo-context-efficiency",
    )
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise PolicyError(f"tracked target/install/override policy missing: {missing!r}")
    if text.count("tracked: true") != 1:
        raise PolicyError("exactly one tracked target is permitted")
    if "dir: .." in text or "dir: /" in text:
        raise PolicyError("target directories must not escape the repository")


def normalize_ref_only_manifest(text: str) -> str:
    """Return a manifest with only approved immutable source refs erased."""
    validate_manifest_text(text)
    normalized: list[str] = []
    replacements = 0
    for line in text.splitlines():
        match = _REF_LINE_RE.match(line)
        if match:
            normalized.append(f"{match.group(1)}<immutable-ref>")
            replacements += 1
        else:
            normalized.append(line)
    if replacements != len(ALLOWED_SOURCES):
        raise PolicyError(f"expected {len(ALLOWED_SOURCES)} source refs, normalized {replacements}")
    return "\n".join(normalized) + "\n"


def compare_manifest_texts(base_text: str, head_text: str, *, base_ref: str | None = None) -> ManifestDecision:
    """Allow only immutable-ref changes inside the approved manifest shape."""
    try:
        base_normalized = normalize_ref_only_manifest(base_text)
        head_normalized = normalize_ref_only_manifest(head_text)
    except PolicyError as exc:
        return ManifestDecision(False, f"manifest_policy_error:{exc}", base_ref)
    if base_normalized != head_normalized:
        return ManifestDecision(False, "manifest_structural_change", base_ref)
    return ManifestDecision(True, "approved_ref_only_change", base_ref)


def _git_show(base_ref: str, path: Path) -> str:
    if not _FULL_SHA_RE.fullmatch(base_ref):
        raise PolicyError("CI manifest comparison requires an immutable 40-character base SHA")
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{path.as_posix()}"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise PolicyError(f"cannot read base manifest at {base_ref}: {result.stderr.strip()}")
    return result.stdout


def compare_repository_manifest(base_ref: str, *, manifest: Path = MANIFEST_PATH) -> ManifestDecision:
    """Compare HEAD's manifest with the immutable pull-request event base."""
    try:
        base_text = _git_show(base_ref, manifest)
        head_text = manifest.read_text(encoding="utf-8")
    except (OSError, PolicyError) as exc:
        return ManifestDecision(False, f"manifest_evidence_error:{exc}", base_ref)
    return compare_manifest_texts(base_text, head_text, base_ref=base_ref)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--base-sha", required=True)
    compare.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            validate_manifest_text(args.manifest.read_text(encoding="utf-8"))
        except (OSError, PolicyError) as exc:
            print(json.dumps({"valid": False, "reason": str(exc)}, sort_keys=True))
            return 1
        print(json.dumps({"valid": True, "verifier_ref": VERIFIER_REF}, sort_keys=True))
        return 0

    decision = compare_repository_manifest(args.base_sha, manifest=args.manifest)
    print(json.dumps(asdict(decision), sort_keys=True))
    return 0 if decision.narrow_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
