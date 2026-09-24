"""Tests for the canary-impact selector (scripts/canary_impact.py)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import canary_impact
from scripts.canary_impact import (
    CANT_AFFECT_CANARY,
    WHOLE_SUITE_PATHS,
    FileDeps,
    build_dependency_map,
    compute_selection,
    files_from_node_ids,
)
from scripts.release_canary_sharding import MARKER_EXPRESSION as SHARDING_MARKER

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]


# -- fixture-tree helpers -----------------------------------------------------


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _fixture_root(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a minimal repo tree with an empty tests/conftest.py."""
    merged = {"tests/conftest.py": "", **files}
    _write_tree(tmp_path, merged)
    return tmp_path


def _select(root: Path, test_files: list[str], node_ids: list[str], changed: list[str]) -> dict:
    dep_map, fallback = build_dependency_map(root, test_files)
    assert fallback is None, fallback
    return compute_selection(changed, dep_map, node_ids)


def _nodes(test_file: str, names: list[str]) -> list[str]:
    return [f"{test_file}::{name}" for name in names]


# -- dependency rules ----------------------------------------------------------


@pytest.mark.fast
class TestDependencyRules:
    def test_static_import_includes_parent_init(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "mypkg/__init__.py": "from . import base\n",
                "mypkg/base.py": "VALUE = 1\n",
                "mypkg/sub.py": "from mypkg import base\n",
                "tests/test_x.py": "import mypkg.sub\n\ndef test_a(): ...\n",
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        deps = dep_map["tests/test_x.py"].deps
        assert "mypkg/sub.py" in deps
        # Python executes every parent package __init__ on import.
        assert "mypkg/__init__.py" in deps

        selection = _select(root, ["tests/test_x.py"], _nodes("tests/test_x.py", ["test_a"]), ["mypkg/__init__.py"])
        assert selection["whole_suite"] is False
        assert [s["node_id"] for s in selection["selected"]] == ["tests/test_x.py::test_a"]

    def test_importlib_literal_is_a_dependency(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "mypkg/__init__.py": "",
                "mypkg/sub.py": "VALUE = 1\n",
                "tests/test_x.py": 'import importlib\nmod = importlib.import_module("mypkg.sub")\n',
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        assert "mypkg/sub.py" in dep_map["tests/test_x.py"].deps

    def test_repo_root_join_is_a_dependency(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "data/spec.yaml": "version: 1\n",
                "tests/test_x.py": (
                    "from pathlib import Path\n"
                    "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
                    'SPEC = REPO_ROOT / "data" / "spec.yaml"\n'
                ),
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        assert "data/spec.yaml" in dep_map["tests/test_x.py"].deps

        selection = _select(root, ["tests/test_x.py"], _nodes("tests/test_x.py", ["test_a"]), ["data/spec.yaml"])
        assert [s["node_id"] for s in selection["selected"]] == ["tests/test_x.py::test_a"]
        reasons = selection["selected"][0]["reasons"]
        assert {"changed_path": "data/spec.yaml", "edge": "dependency"} in reasons

    def test_with_name_selects_sibling(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "tests/helper.py": "VALUE = 1\n",
                "tests/test_x.py": ('from pathlib import Path\nHELPER = Path(__file__).with_name("helper.py")\n'),
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        assert "tests/helper.py" in dep_map["tests/test_x.py"].deps

    def test_directory_dependency_covers_files_under_it(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "datadir/a.txt": "a\n",
                "datadir/nested/b.txt": "b\n",
                "tests/test_x.py": (
                    "from pathlib import Path\n"
                    "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
                    'DATA = REPO_ROOT / "datadir"\n'
                ),
            },
        )
        selection = _select(
            root,
            ["tests/test_x.py"],
            _nodes("tests/test_x.py", ["test_a"]),
            ["datadir/nested/b.txt"],
        )
        assert [s["node_id"] for s in selection["selected"]] == ["tests/test_x.py::test_a"]

    def test_pytest_plugins_apply_to_every_test(self, tmp_path: Path) -> None:
        root = tmp_path
        _write_tree(
            root,
            {
                "tests/conftest.py": 'pytest_plugins = ["myplug"]\n',
                "myplug.py": "import mypkg.base\n",
                "mypkg/__init__.py": "",
                "mypkg/base.py": "VALUE = 1\n",
                "tests/test_x.py": "def test_a(): ...\n",
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        deps = dep_map["tests/test_x.py"].deps
        assert "myplug.py" in deps
        assert "mypkg/base.py" in deps
        assert "tests/conftest.py" in deps

    def test_same_directory_non_python_selects_importers(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "benchbox/widget/__init__.py": "",
                "benchbox/widget/engine.py": "VALUE = 1\n",
                "benchbox/widget/spec.yaml": "version: 1\n",
                "benchbox/other/__init__.py": "",
                "benchbox/other/engine.py": "VALUE = 2\n",
                "benchbox/other/spec.yaml": "version: 2\n",
                "tests/test_widget.py": "import benchbox.widget.engine\n",
                "tests/test_other.py": "import benchbox.other.engine\n",
            },
        )
        test_files = ["tests/test_widget.py", "tests/test_other.py"]
        node_ids = _nodes("tests/test_widget.py", ["test_a"]) + _nodes("tests/test_other.py", ["test_b"])
        selection = _select(root, test_files, node_ids, ["benchbox/widget/spec.yaml"])
        assert selection["whole_suite"] is False
        selected = {s["node_id"]: s["reasons"] for s in selection["selected"]}
        assert "tests/test_widget.py::test_a" in selected
        assert selected["tests/test_widget.py::test_a"] == [
            {"changed_path": "benchbox/widget/spec.yaml", "edge": "same_directory"}
        ]
        assert "tests/test_other.py::test_b" not in selected

    def test_changed_canary_test_selects_itself(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {"tests/test_x.py": "def test_a(): ...\n", "tests/test_y.py": "def test_b(): ...\n"},
        )
        test_files = ["tests/test_x.py", "tests/test_y.py"]
        node_ids = _nodes("tests/test_x.py", ["test_a"]) + _nodes("tests/test_y.py", ["test_b"])
        selection = _select(root, test_files, node_ids, ["tests/test_y.py"])
        assert selection["whole_suite"] is False
        selected = {s["node_id"]: s["reasons"] for s in selection["selected"]}
        assert selected == {"tests/test_y.py::test_b": [{"changed_path": "tests/test_y.py", "edge": "self"}]}

    def test_no_changes_selects_nothing(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {"tests/test_x.py": "import importlib\nmod = importlib.import_module(name)\n"},
        )
        selection = _select(root, ["tests/test_x.py"], _nodes("tests/test_x.py", ["test_a"]), [])
        assert selection["whole_suite"] is False
        assert selection["selected"] == []
        assert selection["selected_count"] == 0


# -- fail-safe rules ------------------------------------------------------------


@pytest.mark.fast
class TestFailSafeRules:
    def test_dynamic_import_always_selects(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "mypkg/__init__.py": "",
                "mypkg/base.py": "VALUE = 1\n",
                "tests/test_x.py": "import importlib\nimport mypkg.base\nmod = importlib.import_module(name)\n",
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        assert dep_map["tests/test_x.py"].dynamic
        selection = _select(root, ["tests/test_x.py"], _nodes("tests/test_x.py", ["test_a"]), ["mypkg/base.py"])
        assert selection["whole_suite"] is False
        reasons = selection["selected"][0]["reasons"]
        assert {"changed_path": "mypkg/base.py", "edge": "dependency"} in reasons
        assert {"changed_path": "mypkg/base.py", "edge": "unresolvable_dynamic_edge"} in reasons

    def test_dynamic_path_from_constant_selects(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "tests/test_x.py": (
                    "from pathlib import Path\n"
                    "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
                    "def load(name):\n"
                    "    return open(REPO_ROOT / name).read()\n"
                ),
            },
        )
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        assert dep_map["tests/test_x.py"].dynamic

    @pytest.mark.parametrize("trigger", sorted(WHOLE_SUITE_PATHS))
    def test_whole_suite_triggers(self, tmp_path: Path, trigger: str) -> None:
        root = _fixture_root(tmp_path, {"tests/test_x.py": "def test_a(): ...\n"})
        node_ids = _nodes("tests/test_x.py", ["test_a", "test_b"])
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        selection = compute_selection([trigger], dep_map, node_ids)
        assert selection["whole_suite"] is True
        assert trigger in selection["whole_suite_reason"]
        assert selection["selected_count"] == 2
        for selected in selection["selected"]:
            assert {"changed_path": trigger, "edge": "whole_suite"} in selected["reasons"]

    def test_unmapped_path_runs_whole_suite(self, tmp_path: Path) -> None:
        root = _fixture_root(tmp_path, {"tests/test_x.py": "def test_a(): ...\n"})
        node_ids = _nodes("tests/test_x.py", ["test_a"])
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        selection = compute_selection(["some/random/file.txt"], dep_map, node_ids)
        assert selection["whole_suite"] is True
        assert selection["unmapped_changed_paths"] == ["some/random/file.txt"]
        assert selection["selected_count"] == 1

    def test_safe_listed_path_selects_nothing(self, tmp_path: Path) -> None:
        assert CANT_AFFECT_CANARY, "the reviewed safe list must not be empty"
        root = _fixture_root(tmp_path, {"tests/test_x.py": "def test_a(): ...\n"})
        node_ids = _nodes("tests/test_x.py", ["test_a"])
        dep_map, fallback = build_dependency_map(root, ["tests/test_x.py"])
        assert fallback is None
        selection = compute_selection(sorted(CANT_AFFECT_CANARY - {"_project/audits/"}), dep_map, node_ids)
        assert selection["whole_suite"] is False
        assert selection["selected"] == []

    def test_json_contract_shape(self, tmp_path: Path) -> None:
        root = _fixture_root(
            tmp_path,
            {
                "mypkg/__init__.py": "",
                "mypkg/sub.py": "VALUE = 1\n",
                "tests/test_x.py": "import mypkg.sub\n",
            },
        )
        collection = tmp_path / "nodeids.txt"
        collection.write_text("tests/test_x.py::test_a\ntests/test_x.py::test_b\n", encoding="utf-8")
        output = tmp_path / "selection.json"
        rc = canary_impact.main(
            [
                "--repo-root",
                str(root),
                "--collection-file",
                str(collection),
                "--changed-path",
                "mypkg/sub.py",
                "--output",
                str(output),
            ]
        )
        assert rc == 0
        selection = json.loads(output.read_text(encoding="utf-8"))
        assert selection["marker_expression"] == canary_impact.MARKER_EXPRESSION
        assert selection["whole_suite"] is False
        assert selection["selected_count"] == 2
        assert selection["total_count"] == 2
        assert selection["collection"]["node_count"] == 2
        for selected in selection["selected"]:
            assert selected["file"] == "tests/test_x.py"
            for reason in selected["reasons"]:
                assert set(reason) == {"changed_path", "edge"}


@pytest.mark.fast
def test_marker_expression_matches_release_canary_workflow() -> None:
    """The selector must use the canary's marker expression, not a copy."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release-canary.yml").read_text(encoding="utf-8"))
    shards = workflow["jobs"]["credential-free-non-fast"]
    run_text = "\n".join(str(step.get("run", "")) for step in shards["steps"])
    assert canary_impact.MARKER_EXPRESSION in run_text
    assert canary_impact.MARKER_EXPRESSION == SHARDING_MARKER


@pytest.mark.medium
class TestLiveTree:
    @pytest.fixture(scope="class")
    def live_canary(self) -> tuple[list[str], dict[str, FileDeps]]:
        from scripts.canary_impact import collect_canary_node_ids

        node_ids = collect_canary_node_ids(REPO_ROOT)
        assert node_ids, "expected a non-empty canary collection"
        dep_map, fallback = build_dependency_map(REPO_ROOT, files_from_node_ids(node_ids))
        assert fallback is None, fallback
        return node_ids, dep_map

    def test_every_collected_file_has_an_edge(self, live_canary: tuple[list[str], dict[str, FileDeps]]) -> None:
        _, dep_map = live_canary
        edgeless = sorted(test_file for test_file, deps in dep_map.items() if not deps.deps)
        assert edgeless == []

    @pytest.mark.parametrize(
        "commit,test_file",
        [
            ("68fb5a071", "tests/integration/test_tpcdi_full_benchmark.py"),
            ("5e9284a2c", "tests/unit/core/flightdata/test_flightdata_benchmark_resource_heavy.py"),
            ("ed3e39a9c", "tests/unit/scripts/test_validate_submission_resource_heavy.py"),
            ("2384c3ee7", "tests/unit/scripts/test_validate_submission_resource_heavy.py"),
        ],
    )
    def test_known_regressions_are_selected(
        self, live_canary: tuple[list[str], dict[str, FileDeps]], commit: str, test_file: str
    ) -> None:
        """Replay each known-regression commit's changed paths: the failing test must be selected."""
        node_ids, dep_map = live_canary
        changed = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{commit}^", commit],
            text=True,
        ).split()
        assert changed, f"expected changed paths for {commit}"
        selection = compute_selection(changed, dep_map, node_ids)
        expected = {node_id for node_id in node_ids if node_id.split("::", 1)[0] == test_file}
        assert expected, f"expected {test_file} in the live collection"
        selected = {s["node_id"] for s in selection["selected"]}
        assert expected <= selected, f"{commit} missed {sorted(expected - selected)}"
        for selected_entry in selection["selected"]:
            if selected_entry["file"] == test_file:
                assert selected_entry["reasons"], "every selection needs a reason"
