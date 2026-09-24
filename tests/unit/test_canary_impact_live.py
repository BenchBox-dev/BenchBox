"""Live-tree tests for the canary-impact selector (medium tier).

These tests collect the real canary suite and build the full dependency
map (~30s); they live in their own module so this file carries a single
top-level speed marker per the marker-strategy contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.canary_impact import (
    FileDeps,
    build_dependency_map,
    compute_selection,
    files_from_node_ids,
)

pytestmark = [pytest.mark.unit, pytest.mark.medium]

REPO_ROOT = Path(__file__).resolve().parents[2]


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
