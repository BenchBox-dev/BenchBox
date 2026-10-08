#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

from __future__ import annotations

import re
import sys
from pathlib import Path


def has_fast_marker(content: str) -> bool:
    return bool(re.search(r"@pytest\.mark\.fast|pytest\.mark\.fast", content))


def has_slow_marker(content: str) -> bool:
    return bool(re.search(r"@pytest\.mark\.slow|pytestmark.*slow", content))


def has_pytestmark(content: str) -> bool:
    return bool(re.search(r"^pytestmark\s*=", content, re.MULTILINE))


def add_fast_to_pytestmark(content: str) -> str:
    pattern = r"^(pytestmark\s*=\s*)(pytest\.mark\.\w+)(\s*)$"
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        return re.sub(
            pattern,
            r"\1[\2, pytest.mark.fast]\3",
            content,
            flags=re.MULTILINE,
        )

    pattern = r"^(pytestmark\s*=\s*\[)([^\]]+)(\]\s*)$"
    match = re.search(pattern, content, re.MULTILINE)
    if match:
        markers = match.group(2).strip()
        if "pytest.mark.fast" not in markers:
            return re.sub(
                pattern,
                rf"\1{markers}, pytest.mark.fast\3",
                content,
                flags=re.MULTILINE,
            )

    return content


def find_insert_position(content: str) -> int:
    lines = content.split("\n")

    in_docstring = False
    docstring_char = None
    in_multiline_import = False
    paren_depth = 0
    last_import_end = -1

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not in_docstring:
            if stripped.startswith(('"""', "'''")):
                docstring_char = stripped[:3]
                if stripped.count(docstring_char) >= 2 and len(stripped) > 3:
                    continue
                in_docstring = True
                continue
        else:
            if docstring_char in stripped:
                in_docstring = False
            continue

        if in_multiline_import:
            paren_depth += line.count("(") - line.count(")")
            if paren_depth <= 0:
                in_multiline_import = False
                last_import_end = i
            continue

        if stripped.startswith(("import ", "from ")):
            if "(" in line and ")" not in line:
                in_multiline_import = True
                paren_depth = line.count("(") - line.count(")")
            else:
                last_import_end = i
        elif stripped.startswith(("@", "class ", "def ", "pytestmark")) or (
            stripped and not stripped.startswith("#") and last_import_end >= 0
        ):
            break

    if last_import_end >= 0:
        return last_import_end + 1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")):
            docstring_char = stripped[:3]
            if stripped.count(docstring_char) >= 2:
                return i + 1
            for j in range(i + 1, len(lines)):
                if docstring_char in lines[j]:
                    return j + 1

    return 0


def add_pytestmark(content: str) -> str:
    lines = content.split("\n")
    insert_pos = find_insert_position(content)

    has_pytest_import = bool(re.search(r"^import pytest|^from pytest", content, re.MULTILINE))

    marker_line = "pytestmark = pytest.mark.fast"

    new_lines = lines[:insert_pos]

    if new_lines and new_lines[-1].strip():
        new_lines.append("")

    if not has_pytest_import:
        new_lines.append("import pytest")
        new_lines.append("")

    new_lines.append(marker_line)

    if insert_pos < len(lines) and lines[insert_pos].strip():
        new_lines.append("")

    new_lines.extend(lines[insert_pos:])

    return "\n".join(new_lines)


def process_file(filepath: Path, dry_run: bool = False) -> tuple[bool, str]:
    content = filepath.read_text(encoding="utf-8")

    if has_fast_marker(content):
        return False, "already has fast marker"

    if has_slow_marker(content):
        return False, "marked as slow (keeping)"

    if has_pytestmark(content):
        new_content = add_fast_to_pytestmark(content)
        action = "extended pytestmark"
    else:
        new_content = add_pytestmark(content)
        action = "added pytestmark"

    if new_content == content:
        return False, "no changes needed"

    if not dry_run:
        filepath.write_text(new_content, encoding="utf-8")

    return True, action


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Add pytest.mark.fast to unit test files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all files")
    parser.add_argument("path", nargs="?", default="tests/unit", help="Path to process")
    args = parser.parse_args()

    test_dir = Path(args.path)
    if not test_dir.exists():
        print(f"Error: {test_dir} does not exist")
        sys.exit(1)

    test_files = sorted(test_dir.rglob("test_*.py"))

    changed = 0
    skipped = 0
    errors = 0

    for filepath in test_files:
        try:
            was_changed, message = process_file(filepath, dry_run=args.dry_run)
            if was_changed:
                changed += 1
                print(f"{'[DRY RUN] ' if args.dry_run else ''}Modified: {filepath} ({message})")
            else:
                skipped += 1
                if args.verbose:
                    print(f"Skipped: {filepath} ({message})")
        except Exception as e:
            errors += 1
            print(f"Error processing {filepath}: {e}")

    print("\nSummary:")
    print(f"  Modified: {changed}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Total: {len(test_files)}")

    if args.dry_run:
        print("\n[DRY RUN - no files were modified]")


if __name__ == "__main__":
    main()
