"""Tests for the release curation-drift guard's Makefile parsing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_release_curation.py"

spec = importlib.util.spec_from_file_location("check_release_curation", SCRIPT_PATH)
check_release_curation = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_release_curation)


def _write_makefile(tmp_path: Path, recipe_lines: list[str]) -> Path:
    makefile = tmp_path / "Makefile"
    body = "\n".join(f"\t{line}" for line in recipe_lines)
    makefile.write_text(f"release-cut:\n{body}\n\nother-target:\n\techo hi\n", encoding="utf-8")
    return makefile


def test_parse_curation_list_handles_ignore_unmatch(tmp_path):
    """--ignore-unmatch must not be swallowed into the parsed path set."""
    makefile = _write_makefile(
        tmp_path,
        [
            "git rm -rf --ignore-unmatch _project _blog",
            "git rm -f --ignore-unmatch .mcp.json todo.config.yaml",
            "git add pyproject.toml",
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project", "_blog", ".mcp.json", "todo.config.yaml"}


def test_parse_curation_list_handles_legacy_prefixed_lines(tmp_path):
    """Pre---ignore-unmatch form (`-git rm -rf <paths>`) still parses."""
    makefile = _write_makefile(
        tmp_path,
        [
            "-git rm -rf _project",
            "-git rm -f .mcp.json",
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project", ".mcp.json"}


def test_parse_curation_list_ignores_non_rm_lines(tmp_path):
    """git ls-files guard lines and other commands contribute no paths."""
    makefile = _write_makefile(
        tmp_path,
        [
            "git rm -rf --ignore-unmatch _project",
            "@LEFTOVER=$$(git ls-files _project _blog); \\",
            'if [ -n "$$LEFTOVER" ]; then exit 1; fi',
        ],
    )
    paths = check_release_curation.parse_curation_list(makefile)
    assert paths == {"_project"}


def test_real_makefile_curation_list_parses_to_paths_only():
    """Against the repo Makefile: every parsed entry is a path, never a flag."""
    paths = check_release_curation.parse_curation_list(REPO_ROOT / "Makefile")
    assert paths, "expected a non-empty curation list from the repo Makefile"
    flags = {p for p in paths if p.startswith("-")}
    assert not flags, f"parser leaked flags into the curation list: {sorted(flags)}"
