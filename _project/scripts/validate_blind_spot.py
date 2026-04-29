#!/usr/bin/env python3
"""Validate blind-spot finding files in _project/blind-spots/.

Each finding is a markdown file with YAML frontmatter (delimited by ``---``
lines). The frontmatter schema is small and strict — see
``_project/blind-spots/README.md`` for the protocol.

Usage::

    uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py <path>
    uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py --all
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as _date
from pathlib import Path

import yaml

ALLOWED_STATUS = {"open", "actioned", "dismissed", "merged-to-todo"}
ALLOWED_KIND = {
    "framework-gap",
    "bug-class",
    "missed-axis",
    "scope-creep",
    "assumption",
    "other",
}
REQUIRED_FIELDS = {"id", "date", "status", "finding_kind", "review_context"}
OPTIONAL_FIELDS = {"related_paths", "suggested_sweep", "todo_id"}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

# YYYY-MM-DD-HHMMSS-<slug>; slug is kebab-case, lowercase letters/digits.
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9][a-z0-9-]*$")


def parse_frontmatter(text: str) -> tuple[dict | None, list[str]]:
    """Split a markdown file into (frontmatter_dict, errors).

    Returns ``(None, [...])`` if the frontmatter block is missing or malformed.
    """
    errors: list[str] = []
    if not text.startswith("---\n"):
        return None, ["file must begin with a YAML frontmatter '---' line"]

    # Find the closing fence on its own line.
    body = text[4:]
    end = body.find("\n---\n")
    if end == -1:
        # Allow trailing fence with no body after.
        if body.endswith("\n---") or body.endswith("\n---\n"):
            end = len(body) - 4
        else:
            return None, ["unterminated frontmatter block (no closing '---')"]

    raw = body[:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, [f"frontmatter is not valid YAML: {exc}"]

    if not isinstance(data, dict):
        return None, ["frontmatter must be a YAML mapping"]
    return data, errors


def _check_id_and_filename(data: dict, file_path: Path) -> list[str]:
    errors: list[str] = []
    expected_id = file_path.stem
    if "id" in data and data["id"] != expected_id:
        errors.append(f"id '{data['id']}' must equal filename stem '{expected_id}'")
    if not FILENAME_RE.match(expected_id):
        errors.append(f"filename stem '{expected_id}' does not match YYYY-MM-DD-HHMMSS-<kebab-slug>")
    return errors


def _check_date(data: dict) -> list[str]:
    if "date" not in data:
        return []
    d = data["date"]
    if isinstance(d, _date):
        return []
    if isinstance(d, str):
        try:
            _date.fromisoformat(d)
        except ValueError:
            return [f"date '{d}' is not ISO YYYY-MM-DD"]
        return []
    return [f"date must be a string or date, got {type(d).__name__}"]


def _check_enums(data: dict) -> list[str]:
    errors: list[str] = []
    if "status" in data and data["status"] not in ALLOWED_STATUS:
        errors.append(f"status '{data['status']}' not in {sorted(ALLOWED_STATUS)}")
    if "finding_kind" in data and data["finding_kind"] not in ALLOWED_KIND:
        errors.append(f"finding_kind '{data['finding_kind']}' not in {sorted(ALLOWED_KIND)}")
    return errors


def _check_optional_shapes(data: dict) -> list[str]:
    errors: list[str] = []
    if "review_context" in data:
        rc = data["review_context"]
        if not isinstance(rc, str) or not rc.strip():
            errors.append("review_context must be a non-empty string")
    if "related_paths" in data and data["related_paths"] is not None:
        rp = data["related_paths"]
        if not isinstance(rp, list) or not all(isinstance(x, str) for x in rp):
            errors.append("related_paths must be a list of strings (or null)")
    if "suggested_sweep" in data:
        ss = data["suggested_sweep"]
        if ss is not None and not isinstance(ss, str):
            errors.append("suggested_sweep must be a string or null")
    if "todo_id" in data:
        ti = data["todo_id"]
        if ti is not None and not isinstance(ti, str):
            errors.append("todo_id must be a string or null")
    return errors


def _check_status_invariants(data: dict) -> list[str]:
    if data.get("status") == "merged-to-todo" and not data.get("todo_id"):
        return ["status 'merged-to-todo' requires a non-empty todo_id"]
    return []


def validate_frontmatter(data: dict, file_path: Path) -> list[str]:
    """Validate a frontmatter dict against the blind-spot schema."""
    errors: list[str] = []
    errors.extend(f"unknown field '{f}'" for f in sorted(set(data) - ALLOWED_FIELDS))
    errors.extend(f"missing required field '{f}'" for f in sorted(REQUIRED_FIELDS - data.keys()))
    errors.extend(_check_id_and_filename(data, file_path))
    errors.extend(_check_date(data))
    errors.extend(_check_enums(data))
    errors.extend(_check_optional_shapes(data))
    errors.extend(_check_status_invariants(data))
    return errors


def validate_file(file_path: Path) -> list[str]:
    if not file_path.exists():
        return [f"file not found: {file_path}"]
    if file_path.suffix != ".md":
        return [f"not a markdown file: {file_path}"]
    if file_path.name == "README.md":
        return []  # README is the protocol doc, not a finding

    text = file_path.read_text(encoding="utf-8")
    data, parse_errors = parse_frontmatter(text)
    if data is None:
        return parse_errors
    return parse_errors + validate_frontmatter(data, file_path)


def find_blind_spots_dir(start: Path) -> Path | None:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / "_project" / "blind-spots"
        if candidate.is_dir():
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate blind-spot finding files.")
    parser.add_argument("paths", nargs="*", help="files or directories to validate")
    parser.add_argument(
        "--all",
        action="store_true",
        help="validate every finding under _project/blind-spots/",
    )
    args = parser.parse_args()

    targets: list[Path] = []
    if args.all:
        bs_dir = find_blind_spots_dir(Path.cwd())
        if bs_dir is None:
            print("error: could not locate _project/blind-spots/", file=sys.stderr)
            return 2
        targets.extend(sorted(p for p in bs_dir.glob("*.md") if p.name != "README.md"))
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            targets.extend(sorted(q for q in path.glob("*.md") if q.name != "README.md"))
        else:
            targets.append(path)

    if not targets:
        parser.print_help(sys.stderr)
        return 2

    failed = 0
    for path in targets:
        errors = validate_file(path)
        if errors:
            failed += 1
            print(f"FAIL {path}", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
        else:
            print(f"OK   {path}")
    if failed:
        print(f"\n{failed} of {len(targets)} file(s) failed validation.", file=sys.stderr)
        return 1
    print(f"\nAll {len(targets)} file(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
