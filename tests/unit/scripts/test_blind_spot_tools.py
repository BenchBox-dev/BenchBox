"""Tests for blind-spot finding validation and sweep tooling."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str):
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_blind_spot = _load_script("validate_blind_spot")
sweep_blind_spots = _load_script("sweep_blind_spots")


def test_blind_spot_command_uses_repo_tracked_protocol() -> None:
    command_text = (REPO_ROOT / ".claude" / "commands" / "blind-spot.md").read_text(encoding="utf-8")

    assert "docs/development/review-protocol.md" in command_text
    assert "_project/blind-spots/README.md" in command_text
    assert "~/" not in command_text
    assert ".claude/skills" not in command_text
    assert (REPO_ROOT / "docs" / "development" / "review-protocol.md").is_file()


def _finding_text(
    stem: str,
    *,
    status: str = "open",
    date: str = "2026-04-29",
    finding_kind: str = "other",
    body: str | None = None,
) -> str:
    body = (
        body
        or """# Test Finding

## Finding
The finding.

## Why this matters
The reason.

## Suggested next steps
- [ ] Do the thing.
"""
    )
    return f"""---
id: {stem}
date: {date}
status: {status}
finding_kind: {finding_kind}
review_context: "unit test"
related_paths: null
suggested_sweep: null
todo_id: null
---

{body}"""


def _write_finding(bs_dir: Path, stem: str, **kwargs) -> Path:
    bs_dir.mkdir(parents=True, exist_ok=True)
    path = bs_dir / f"{stem}.md"
    path.write_text(_finding_text(stem, **kwargs), encoding="utf-8")
    return path


def test_validator_reports_nested_enum_instead_of_traceback(tmp_path: Path) -> None:
    stem = "2026-04-29-120000-nested-status"
    path = tmp_path / f"{stem}.md"
    path.write_text(
        _finding_text(stem).replace("status: open", "status:\n  - open"),
        encoding="utf-8",
    )

    errors = validate_blind_spot.validate_file(path)

    assert "status must be a string, got list" in errors


def test_validator_accepts_crlf_frontmatter(tmp_path: Path) -> None:
    stem = "2026-04-29-120001-crlf-frontmatter"
    path = tmp_path / f"{stem}.md"
    path.write_text(_finding_text(stem).replace("\n", "\r\n"), encoding="utf-8")

    assert validate_blind_spot.validate_file(path) == []


def test_validator_rejects_frontmatter_only_files(tmp_path: Path) -> None:
    stem = "2026-04-29-120002-frontmatter-only"
    path = tmp_path / f"{stem}.md"
    path.write_text(
        f"""---
id: {stem}
date: 2026-04-29
status: open
finding_kind: other
review_context: "unit test"
---
""",
        encoding="utf-8",
    )

    errors = validate_blind_spot.validate_file(path)

    assert "body must include a top-level '# <title>' heading" in errors
    assert "body must include '## Finding' section" in errors


def test_sweep_list_handles_mixed_yaml_date_scalars(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bs_dir = tmp_path / "_project" / "blind-spots"
    _write_finding(bs_dir, "2026-04-29-120003-unquoted-date")
    _write_finding(bs_dir, "2026-04-29-120004-quoted-date", date='"2026-04-29"')

    result = sweep_blind_spots.cmd_list(bs_dir, SimpleNamespace(status="open", kind=None))

    assert result == 0
    assert "2 finding(s)." in capsys.readouterr().out


def test_find_one_rejects_path_traversal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bs_dir = tmp_path / "_project" / "blind-spots"
    bs_dir.mkdir(parents=True)

    with pytest.raises(SystemExit) as exc:
        sweep_blind_spots.find_one(bs_dir, "../audits/not-a-finding")

    assert exc.value.code == 2
    assert "invalid finding id" in capsys.readouterr().err


def test_stamp_frontmatter_preserves_unrelated_formatting(tmp_path: Path) -> None:
    stem = "2026-04-29-120005-preserve-format"
    path = tmp_path / f"{stem}.md"
    path.write_text(
        f"""---
id: {stem}
# keep this comment
date: 2026-04-29
status: open
finding_kind: other
review_context: "quoted context"
todo_id: null
---

# Test Finding

## Finding
The finding.

## Why this matters
The reason.

## Suggested next steps
- [ ] Do the thing.
""",
        encoding="utf-8",
    )
    _data, raw, body = sweep_blind_spots.split_frontmatter(path.read_text(encoding="utf-8"))

    sweep_blind_spots.stamp_frontmatter(path, raw, body, "dismissed", None)

    text = path.read_text(encoding="utf-8")
    assert "# keep this comment" in text
    assert 'review_context: "quoted context"' in text
    assert "status: dismissed" in text


def test_stamp_frontmatter_replaces_sequence_shaped_status_node(tmp_path: Path) -> None:
    stem = "2026-04-29-120006-sequence-status"
    path = tmp_path / f"{stem}.md"
    path.write_text(
        f"""---
id: {stem}
date: 2026-04-29
status:
  - open
finding_kind: other
review_context: "unit test"
todo_id: null
---

# Test Finding

## Finding
The finding.

## Why this matters
The reason.

## Suggested next steps
- [ ] Do the thing.
""",
        encoding="utf-8",
    )
    _data, raw, body = sweep_blind_spots.split_frontmatter(path.read_text(encoding="utf-8"))

    sweep_blind_spots.stamp_frontmatter(path, raw, body, "dismissed", None)

    data, raw, _body = sweep_blind_spots.split_frontmatter(path.read_text(encoding="utf-8"))
    assert data["status"] == "dismissed"
    assert raw.splitlines().count("status: dismissed") == 1
    assert "  - open" not in raw


def test_append_triage_log_inserts_before_next_section(tmp_path: Path) -> None:
    path = tmp_path / "finding.md"
    path.write_text(
        """# Test Finding

## Triage log

## Later notes

Keep this content separate.
""",
        encoding="utf-8",
    )

    sweep_blind_spots.append_triage_log(path, "2026-04-29: actioned")

    text = path.read_text(encoding="utf-8")
    assert text.index("- 2026-04-29: actioned") < text.index("## Later notes")


def test_triage_rejects_promote_reason_combo(tmp_path: Path) -> None:
    bs_dir = tmp_path / "_project" / "blind-spots"
    stem = "2026-04-29-120006-promote-reason"
    path = _write_finding(bs_dir, stem)
    args = SimpleNamespace(id=stem, action="promote", reason="because", todo_id="todo-slug")

    result = sweep_blind_spots.cmd_triage(bs_dir, args)

    assert result == 2
    assert "status: open" in path.read_text(encoding="utf-8")
