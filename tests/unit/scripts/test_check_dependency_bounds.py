"""Unit tests for scripts/check_dependency_bounds.py.

Pinned invariants:
  * The PEP 508 parser extracts the upper-bound major from the forms
    BenchBox actually uses (``<N``, ``<N.0``, ``<N.0.0``).
  * A dep with no upper bound is skipped (not mis-reported).
  * ``cap-reached`` blocks only when locked_major >= cap_major.
  * ``ceiling-minus-one`` blocks when locked_major == cap_major - 1.
  * ``--report-only`` never fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_dependency_bounds import (
    CappedDep,
    _extract_cap_major,
    _split_requirement,
    collect_capped_deps,
    main,
    render_report,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestUpperBoundExtraction:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            (">=20.0.0,<31.0.0", 31),
            (">=8.0.0,<9.0.0", 9),
            ("<4", 4),
            ("<4.0", 4),
            ("<4.0.0", 4),
            ("~=2.12", None),
            (">=1.0", None),
            ("", None),
        ],
    )
    def test_extracts_cap_major(self, spec: str, expected: int | None) -> None:
        assert _extract_cap_major(spec) == expected


class TestRequirementSplit:
    def test_splits_name_and_spec(self) -> None:
        name, spec = _split_requirement("pydantic>=2.0.0,<3.0.0")
        assert name == "pydantic"
        assert spec == ">=2.0.0,<3.0.0"

    def test_strips_extras(self) -> None:
        name, spec = _split_requirement("pydantic[email]>=2,<3")
        assert name == "pydantic"

    def test_strips_env_marker(self) -> None:
        name, spec = _split_requirement("tomli ; python_version<'3.11'")
        assert name == "tomli"


def _write(tmp_path: Path, pyproject_body: str, lock_body: str) -> tuple[Path, Path]:
    py = tmp_path / "pyproject.toml"
    lk = tmp_path / "uv.lock"
    py.write_text(pyproject_body)
    lk.write_text(lock_body)
    return py, lk


class TestCollectCappedDeps:
    def test_collects_from_project_dependencies(self, tmp_path: Path) -> None:
        py, lk = _write(
            tmp_path,
            """
[project]
name = "demo"
version = "0.0.0"
dependencies = [
    "sqlglot>=20.0.0,<31.0.0",
    "requests",
]
""",
            """
[[package]]
name = "sqlglot"
version = "30.2.1"

[[package]]
name = "requests"
version = "2.31.0"
""",
        )
        deps = collect_capped_deps(py, lk)
        assert [d.name for d in deps] == ["sqlglot"]
        assert deps[0].cap_major == 31
        assert deps[0].locked_version == "30.2.1"

    def test_collects_from_dependency_groups(self, tmp_path: Path) -> None:
        py, lk = _write(
            tmp_path,
            """
[project]
name = "demo"
version = "0.0.0"
dependencies = []

[dependency-groups]
dev = ["duckdb>=1.0,<2.0"]
""",
            """
[[package]]
name = "duckdb"
version = "1.5.1"
""",
        )
        deps = collect_capped_deps(py, lk)
        assert len(deps) == 1
        assert deps[0].name == "duckdb"
        assert deps[0].cap_major == 2

    def test_deduplicates_multiple_declarations(self, tmp_path: Path) -> None:
        py, lk = _write(
            tmp_path,
            """
[project]
name = "demo"
version = "0.0.0"
dependencies = ["click>=8,<9"]

[dependency-groups]
dev = ["click>=8,<9"]
""",
            '[[package]]\nname = "click"\nversion = "8.3.2"\n',
        )
        deps = collect_capped_deps(py, lk)
        assert len(deps) == 1


class TestSeverityFlags:
    def test_cap_reached_when_locked_major_at_cap(self) -> None:
        dep = CappedDep(name="x", cap_major=3, locked_version="3.0.0")
        assert dep.cap_reached
        assert not dep.ceiling_minus_one

    def test_cap_reached_when_locked_major_above_cap(self) -> None:
        dep = CappedDep(name="x", cap_major=3, locked_version="4.1.0")
        assert dep.cap_reached

    def test_ceiling_minus_one_when_locked_major_is_cap_minus_one(self) -> None:
        dep = CappedDep(name="x", cap_major=3, locked_version="2.12.5")
        assert dep.ceiling_minus_one
        assert not dep.cap_reached

    def test_healthy_when_locked_major_well_under_cap(self) -> None:
        dep = CappedDep(name="x", cap_major=5, locked_version="2.0.0")
        assert not dep.cap_reached
        assert not dep.ceiling_minus_one

    def test_unlocked_dep_is_neither(self) -> None:
        dep = CappedDep(name="x", cap_major=3, locked_version=None)
        assert not dep.cap_reached
        assert not dep.ceiling_minus_one


class TestRenderReport:
    def test_renders_markdown_table(self) -> None:
        deps = [
            CappedDep(name="ok", cap_major=5, locked_version="2.0.0"),
            CappedDep(name="edge", cap_major=3, locked_version="2.12.5"),
            CappedDep(name="over", cap_major=3, locked_version="3.0.0"),
        ]
        report = render_report(deps)
        assert "| `ok` |" in report
        assert "healthy" in report
        assert "ceiling-minus-one" in report
        assert "CAP REACHED" in report


class TestMainCli:
    def _fixture(self, tmp_path: Path, locked: str, cap: str = "<3") -> tuple[Path, Path]:
        return _write(
            tmp_path,
            f"""
[project]
name = "demo"
version = "0.0.0"
dependencies = ["pydantic>=2{cap}"]
""",
            f'[[package]]\nname = "pydantic"\nversion = "{locked}"\n',
        )

    def test_cap_reached_exits_non_zero_when_at_cap(self, tmp_path: Path) -> None:
        py, lk = self._fixture(tmp_path, "3.0.0")
        rc = main(["--fail-on=cap-reached", f"--pyproject={py}", f"--lock={lk}"])
        assert rc == 1

    def test_cap_reached_exits_zero_when_below_cap(self, tmp_path: Path) -> None:
        py, lk = self._fixture(tmp_path, "2.12.5")
        rc = main(["--fail-on=cap-reached", f"--pyproject={py}", f"--lock={lk}"])
        assert rc == 0

    def test_ceiling_minus_one_exits_non_zero_when_at_cap_minus_one(self, tmp_path: Path) -> None:
        py, lk = self._fixture(tmp_path, "2.12.5")
        rc = main(["--fail-on=ceiling-minus-one", f"--pyproject={py}", f"--lock={lk}"])
        assert rc == 1

    def test_report_only_never_fails(self, tmp_path: Path) -> None:
        py, lk = self._fixture(tmp_path, "3.0.0")
        rc = main(["--report-only", f"--pyproject={py}", f"--lock={lk}"])
        assert rc == 0

    def test_output_file_written(self, tmp_path: Path) -> None:
        py, lk = self._fixture(tmp_path, "2.12.5")
        out = tmp_path / "report.md"
        rc = main(["--report-only", f"--pyproject={py}", f"--lock={lk}", f"--output={out}"])
        assert rc == 0
        assert out.exists()
        assert "pydantic" in out.read_text(encoding="utf-8")
