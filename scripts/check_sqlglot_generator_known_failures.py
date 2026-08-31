#!/usr/bin/env python3
"""Validate the age-bounded SQLGlot generator known-failure policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "_project/sqlglot-upstream/generator-policy.json"
EXPECTED_MODE = "advisory_with_age"
EXPECTED_OWNER = "@joeharris76"
EXPECTED_MAX_AGE_DAYS = 7
EXPECTED_REPLAY_COMMAND_TEMPLATE = (
    "uv run --with sqlglot=={sqlglot_version} -- python _project/sqlglot-upstream/repros/generator.py "
    "--seed {seed} --source-dialect {source_dialect} --target-dialect {target_dialect} "
    "--failure-artifact {failure_artifact}"
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "version",
        "mode",
        "owner",
        "max_known_failure_age_days",
        "replay_command_template",
        "known_failures",
    }
)
_KNOWN_FAILURE_FIELDS = frozenset(
    {
        "id",
        "known_fail_since",
        "owner",
        "issue_url",
        "seed",
        "sqlglot_version",
        "source_dialect",
        "target_dialect",
        "failure_artifact",
    }
)
_ARTIFACT_METADATA_FIELDS = ("id", "seed", "sqlglot_version", "source_dialect", "target_dialect")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SAFE_VERSION_RE = re.compile(r"[0-9][A-Za-z0-9._+-]*")
_SAFE_DIALECT_RE = re.compile(r"[a-z][a-z0-9_]*")
_SAFE_PATH_PART_RE = re.compile(r"[A-Za-z0-9._-]+")
_SQLGLOT_ISSUE_PATH_RE = re.compile(r"/tobymao/sqlglot/issues/[1-9][0-9]*")


def _validate_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    context: str,
    errors: list[str],
) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing:
        errors.append(f"{context}: missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{context}: unknown fields: {', '.join(unknown)}")


def _nonempty_string(value: object, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field}: must be a non-empty string")
        return None
    if value != value.strip():
        errors.append(f"{field}: must not have leading or trailing whitespace")
        return None
    return value


def _iso_date(value: object, field: str, errors: list[str]) -> date | None:
    text = _nonempty_string(value, field, errors)
    if text is None:
        return None
    if _ISO_DATE_RE.fullmatch(text) is None:
        errors.append(f"{field}: must use ISO date format YYYY-MM-DD")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append(f"{field}: must be a valid calendar date")
        return None


def _validate_issue_url(value: object, field: str, errors: list[str]) -> None:
    text = _nonempty_string(value, field, errors)
    if text is None:
        return
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
    except ValueError:
        parsed = None
        hostname = None
    if (
        parsed is None
        or parsed.scheme != "https"
        or hostname != "github.com"
        or parsed.netloc != "github.com"
        or _SQLGLOT_ISSUE_PATH_RE.fullmatch(parsed.path) is None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in text)
        or parsed.username
        or parsed.password
    ):
        errors.append(f"{field}: must be a canonical https://github.com/tobymao/sqlglot/issues/<number> URL")


def _shell_safe_token(
    value: object,
    field: str,
    pattern: re.Pattern[str],
    errors: list[str],
) -> str | None:
    text = _nonempty_string(value, field, errors)
    if text is None:
        return None
    if pattern.fullmatch(text) is None:
        errors.append(f"{field}: must be a shell-safe replay token")
        return None
    return text


def _resolve_artifact_path(value: object, field: str, repo_root: Path, errors: list[str]) -> Path | None:
    text = _nonempty_string(value, field, errors)
    if text is None:
        return None
    path = PurePosixPath(text)
    if (
        "\\" in text
        or path.is_absolute()
        or PureWindowsPath(text).drive
        or text in {".", ".."}
        or any(part in {".", ".."} for part in path.parts)
        or any(_SAFE_PATH_PART_RE.fullmatch(part) is None or part.startswith("-") for part in path.parts)
        or path.as_posix() != text
    ):
        errors.append(f"{field}: must be a shell-safe normalized repository-relative POSIX path")
        return None

    resolved_root = repo_root.resolve()
    try:
        resolved_artifact = (resolved_root / Path(*path.parts)).resolve(strict=True)
    except OSError:
        errors.append(f"{field}: must resolve to an existing regular file under the repository")
        return None
    if not resolved_artifact.is_relative_to(resolved_root) or not resolved_artifact.is_file():
        errors.append(f"{field}: must resolve to an existing regular file under the repository")
        return None
    return resolved_artifact


def _validate_artifact_metadata(
    artifact_path: Path,
    known_failure: Mapping[str, object],
    context: str,
    errors: list[str],
) -> None:
    field = f"{context}.failure_artifact"
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{field}: must contain valid UTF-8 JSON ({exc})")
        return
    if not isinstance(artifact, dict):
        errors.append(f"{field}: artifact JSON must be an object")
        return

    for metadata_field in _ARTIFACT_METADATA_FIELDS:
        if metadata_field not in artifact:
            errors.append(f"{field}: artifact is missing metadata field {metadata_field!r}")
            continue
        expected = known_failure.get(metadata_field)
        actual = artifact[metadata_field]
        if type(actual) is not type(expected) or actual != expected:
            errors.append(f"{field}: artifact metadata {metadata_field!r} does not match the policy entry")


def _validate_known_failure(
    value: object,
    index: int,
    today: date,
    repo_root: Path,
    seen_ids: set[str],
    errors: list[str],
) -> None:
    context = f"known_failures[{index}]"
    if not isinstance(value, dict):
        errors.append(f"{context}: must be an object")
        return
    _validate_fields(value, _KNOWN_FAILURE_FIELDS, context, errors)

    failure_id = _nonempty_string(value.get("id"), f"{context}.id", errors)
    if failure_id is not None:
        if failure_id in seen_ids:
            errors.append(f"{context}.id: duplicate id {failure_id!r}")
        seen_ids.add(failure_id)

    known_since = _iso_date(value.get("known_fail_since"), f"{context}.known_fail_since", errors)
    if known_since is not None:
        age_days = (today - known_since).days
        if age_days < 0:
            errors.append(f"{context}.known_fail_since: date is in the future ({known_since.isoformat()})")
        elif age_days >= EXPECTED_MAX_AGE_DAYS:
            errors.append(
                f"{context}: known failure is {age_days} days old; entries expire at age {EXPECTED_MAX_AGE_DAYS} days"
            )

    owner = _nonempty_string(value.get("owner"), f"{context}.owner", errors)
    if owner is not None and owner != EXPECTED_OWNER:
        errors.append(f"{context}.owner: must be {EXPECTED_OWNER!r}")

    _validate_issue_url(value.get("issue_url"), f"{context}.issue_url", errors)

    seed = value.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        errors.append(f"{context}.seed: must be a non-negative integer")

    _shell_safe_token(value.get("sqlglot_version"), f"{context}.sqlglot_version", _SAFE_VERSION_RE, errors)
    for field in ("source_dialect", "target_dialect"):
        _shell_safe_token(value.get(field), f"{context}.{field}", _SAFE_DIALECT_RE, errors)

    artifact_path = _resolve_artifact_path(
        value.get("failure_artifact"),
        f"{context}.failure_artifact",
        repo_root,
        errors,
    )
    if artifact_path is not None:
        _validate_artifact_metadata(artifact_path, value, context, errors)


def validate_policy(value: object, today: date, repo_root: Path = REPO_ROOT) -> list[str]:
    """Return every policy validation error in deterministic order."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["policy: top-level value must be an object"]

    _validate_fields(value, _TOP_LEVEL_FIELDS, "policy", errors)

    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        errors.append("policy.version: must be integer 1")

    mode = _nonempty_string(value.get("mode"), "policy.mode", errors)
    if mode is not None and mode != EXPECTED_MODE:
        errors.append(f"policy.mode: must be lowercase value {EXPECTED_MODE!r}")

    owner = _nonempty_string(value.get("owner"), "policy.owner", errors)
    if owner is not None and owner != EXPECTED_OWNER:
        errors.append(f"policy.owner: must be {EXPECTED_OWNER!r}")

    max_age = value.get("max_known_failure_age_days")
    if isinstance(max_age, bool) or not isinstance(max_age, int):
        errors.append("policy.max_known_failure_age_days: must be a positive bounded integer")
    elif max_age <= 0 or max_age > EXPECTED_MAX_AGE_DAYS:
        errors.append(
            f"policy.max_known_failure_age_days: must be positive and no greater than {EXPECTED_MAX_AGE_DAYS}"
        )
    elif max_age != EXPECTED_MAX_AGE_DAYS:
        errors.append(f"policy.max_known_failure_age_days: must be exactly {EXPECTED_MAX_AGE_DAYS}")

    replay_template = _nonempty_string(value.get("replay_command_template"), "policy.replay_command_template", errors)
    if replay_template is not None and replay_template != EXPECTED_REPLAY_COMMAND_TEMPLATE:
        errors.append("policy.replay_command_template: must preserve the exact deterministic replay command")

    known_failures = value.get("known_failures")
    if not isinstance(known_failures, list):
        errors.append("policy.known_failures: must be a list")
        return errors

    seen_ids: set[str] = set()
    for index, known_failure in enumerate(known_failures):
        _validate_known_failure(known_failure, index, today, repo_root, seen_ids, errors)
    return errors


def _load_policy(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None, *, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY, help="Policy JSON to validate")
    parser.add_argument("--today", help="UTC date override in YYYY-MM-DD form for deterministic checks")
    args = parser.parse_args(argv)

    if args.today is None:
        today = datetime.now(timezone.utc).date()
    else:
        today_errors: list[str] = []
        today = _iso_date(args.today, "--today", today_errors)
        if today is None:
            for error in today_errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1

    try:
        policy = _load_policy(args.policy)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not load policy {args.policy}: {exc}", file=sys.stderr)
        return 1

    errors = validate_policy(policy, today, repo_root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    known_failures = policy["known_failures"]
    print(
        f"OK: {args.policy} has {len(known_failures)} unexpired known failure(s); "
        f"maximum age is {EXPECTED_MAX_AGE_DAYS} days."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
