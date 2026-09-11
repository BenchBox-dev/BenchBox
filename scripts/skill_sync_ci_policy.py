#!/usr/bin/env python3
"""Fail-closed trust policy for BenchBox skill-sync CI routing.

The tool pin is a trust anchor owned by BenchBox maintainers. It is
intentionally independent of every revision selected by ``skill-sync.conf``:
``TOOL_REF`` names the upstream commit the vendored wrapper was copied from
and ``TOOL_SHA256`` pins the exact vendored bytes, so a tampered
``tools/skill-sync`` fails validation even when the config is untouched.
Advance either only with a clean preview/apply/check/verify proof and full CI.

The wrapper never fetches: ``skill-sync.conf`` names local source checkouts,
so the config carries no origin URLs. URL identity is still checked, but on
the committed per-target receipt instead: ``skill-sync`` records each
source's ``remote.origin.url`` there at apply time, and validation requires
exactly the approved set. Advancing a skill revision only with a reviewed
receipt diff is what keeps a forked checkout from riding the narrow lane.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

TOOL_REPOSITORY = "https://github.com/joeharris76/skill-sync.git"
TOOL_REF = "25e1e47693d8b0b2aba91d3ad3dbc0c14b8d3c4c"
TOOL_SHA256 = "01f2b383318c448e3ed94aed4781432ac69dbd33f1556dae9792e65f9883eb34"
TOOL_PATH = Path("tools/skill-sync")
MANIFEST_PATH = Path("skill-sync.conf")
RECEIPT_PATH = Path(".claude/skills/skill-sync.receipt")
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")

# Approved skill-source identity, checked against the committed receipt's
# `source = <url>` lines (the config only names local checkout paths, which
# legitimately differ per machine, so the config cannot carry this binding).
APPROVED_SOURCE_URLS = frozenset(
    {
        "https://github.com/joeharris76/skill-sync-skills.git",
        TOOL_REPOSITORY,
    }
)

# Every skill the config may select, grouped by owning source in config
# order. There is no dependency resolver: shared prerequisites are listed
# explicitly, and selecting anything else (a new catalog skill, a forked
# project skill) is a structural change that forces full CI.
EXPECTED_TARGETS = [".claude/skills", ".agents/skills"]
EXPECTED_GROUPS = [
    {
        "skills": [
            "bossmode",
            "blog",
            "code",
            "test",
            "docs",
            "benchbox",
            "tidy-perms",
            "todo",
            "shared-agent-execution",
            "shared-change-framework",
            "shared-investigation-framework",
            "shared-review-protocol",
        ],
    },
    {"skills": ["skill-sync"]},
]
EXPECTED_SKILLS = frozenset(skill for group in EXPECTED_GROUPS for skill in group["skills"])

_REF_LINE_RE = re.compile(r"^(rev *= *)([0-9a-fA-F]+)( *)$")


class PolicyError(ValueError):
    """Config, receipt, tool, or Git evidence violates the skill CI trust boundary."""


@dataclass(frozen=True)
class ManifestDecision:
    narrow_eligible: bool
    reason: str
    base_ref: str | None = None


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def parse_conf_groups(text: str) -> tuple[list[str], list[dict[str, object]]]:
    """Parse targets and source groups from config text. Shared with validation."""
    targets: list[str] = []
    groups: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line:
            continue
        if "=" not in line:
            raise PolicyError(f'line {lineno}: expected "key = value"')
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "target":
            if current is not None:
                raise PolicyError(f'line {lineno}: every "target" line must come before the first "source"')
            if not value or value.startswith("/") or ".." in value.split("/"):
                raise PolicyError(f"line {lineno}: bad target path: {value!r}")
            targets.append(value)
        elif key == "source":
            if not value:
                raise PolicyError(f"line {lineno}: empty source")
            current = {"source": value, "rev": "", "dir": "skills", "skills": []}
            groups.append(current)
        elif key in ("rev", "dir", "skill"):
            if current is None:
                raise PolicyError(f'line {lineno}: {key!r} must follow a "source" line')
            if key == "skill":
                if not value:
                    raise PolicyError(f"line {lineno}: empty skill")
                skills = current["skills"]
                assert isinstance(skills, list)
                skills.append(value)
            else:
                if not value:
                    raise PolicyError(f"line {lineno}: empty {key}")
                current[key] = value
        else:
            raise PolicyError(f"line {lineno}: unknown key {key!r}")
    return targets, groups


def validate_conf_text(text: str) -> None:
    """Validate target set, group shape, rev format, and skill selection."""
    targets, groups = parse_conf_groups(text)
    if targets != EXPECTED_TARGETS:
        raise PolicyError(f"targets must be exactly {EXPECTED_TARGETS}; got {targets}")
    if len(groups) != len(EXPECTED_GROUPS):
        raise PolicyError(f"expected {len(EXPECTED_GROUPS)} source groups, got {len(groups)}")
    seen: set[str] = set()
    for index, (group, expected) in enumerate(zip(groups, EXPECTED_GROUPS)):
        rev = group["rev"]
        assert isinstance(rev, str)
        if not _FULL_SHA_RE.fullmatch(rev):
            raise PolicyError(f"source group {index + 1} rev must be a lowercase 40-character commit SHA")
        if group["dir"] != "skills":
            raise PolicyError(f'source group {index + 1} dir must be "skills"')
        skills = group["skills"]
        assert isinstance(skills, list)
        if [str(skill) for skill in skills] != expected["skills"]:
            raise PolicyError(f"source group {index + 1} skills must be exactly {expected['skills']}")
        for skill in skills:
            name = str(skill)
            if name in seen:
                raise PolicyError(f"skill {name!r} is listed more than once")
            seen.add(name)
    if seen != EXPECTED_SKILLS:
        raise PolicyError(f"skill selection must be exactly {sorted(EXPECTED_SKILLS)}")


def validate_receipt_text(text: str) -> None:
    """Validate the committed receipt's source identity and skill selection."""
    urls: list[str] = []
    revs: list[str] = []
    skills: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line:
            continue
        if "=" not in line:
            raise PolicyError(f'receipt line {lineno}: expected "key = value"')
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "source":
            urls.append(value)
        elif key == "rev":
            revs.append(value)
        elif key == "skill":
            skills.append(value)
        elif key in ("dir", "file"):
            continue
        else:
            raise PolicyError(f"receipt line {lineno}: unknown key {key!r}")
    if len(urls) != len(EXPECTED_GROUPS):
        raise PolicyError(f"receipt must record {len(EXPECTED_GROUPS)} sources, got {len(urls)}")
    unknown = [url for url in urls if url not in APPROVED_SOURCE_URLS]
    if unknown:
        raise PolicyError(f"receipt source not approved: {unknown!r}")
    for rev in revs:
        if not _FULL_SHA_RE.fullmatch(rev):
            raise PolicyError(f"receipt rev must be a lowercase 40-character commit SHA: {rev!r}")
    if set(skills) != EXPECTED_SKILLS:
        raise PolicyError(f"receipt skills must be exactly {sorted(EXPECTED_SKILLS)}; got {sorted(set(skills))}")


def validate_tool_bytes(data: bytes) -> None:
    """Pin the vendored wrapper bytes to the approved upstream revision."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != TOOL_SHA256:
        raise PolicyError(
            "tools/skill-sync does not match the pinned revision "
            f"{TOOL_REF} (sha256 {digest}); update it only by vendoring "
            "bin/skill-sync from the product repository and recording the "
            "new pin here with a full review"
        )


def validate_manifest_text(text: str) -> None:
    """Validate the skill-sync config (historic entry point name kept)."""
    validate_conf_text(text)


def normalize_ref_only_manifest(text: str) -> str:
    """Return a config with only approved immutable source revs erased."""
    validate_conf_text(text)
    normalized: list[str] = []
    replacements = 0
    for line in text.splitlines():
        # Only `rev = ...` lines match: the pattern requires `=` (after
        # optional spaces) immediately after the `rev` key, so a skill whose
        # name merely starts with "rev" cannot match.
        if _REF_LINE_RE.match(line):
            normalized.append("rev = <immutable-rev>")
            replacements += 1
        else:
            normalized.append(line)
    if replacements != len(EXPECTED_GROUPS):
        raise PolicyError(f"expected {len(EXPECTED_GROUPS)} source revs, normalized {replacements}")
    return "\n".join(normalized) + "\n"


def compare_manifest_texts(base_text: str, head_text: str, *, base_ref: str | None = None) -> ManifestDecision:
    """Allow only immutable-rev changes inside the approved config shape."""
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
        raise PolicyError(f"cannot read base config at {base_ref}: {result.stderr.strip()}")
    return result.stdout


def compare_repository_manifest(base_ref: str, *, manifest: Path = MANIFEST_PATH) -> ManifestDecision:
    """Compare HEAD's config with the immutable pull-request event base."""
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
    validate.add_argument("--receipt", type=Path, default=RECEIPT_PATH)
    validate.add_argument("--tool", type=Path, default=TOOL_PATH)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--base-sha", required=True)
    compare.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            validate_conf_text(args.manifest.read_text(encoding="utf-8"))
            validate_receipt_text(args.receipt.read_text(encoding="utf-8"))
            validate_tool_bytes(args.tool.read_bytes())
        except (OSError, PolicyError) as exc:
            print(json.dumps({"valid": False, "reason": str(exc)}, sort_keys=True))
            return 1
        print(json.dumps({"valid": True, "tool_ref": TOOL_REF}, sort_keys=True))
        return 0

    decision = compare_repository_manifest(args.base_sha, manifest=args.manifest)
    print(json.dumps(asdict(decision), sort_keys=True))
    return 0 if decision.narrow_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
