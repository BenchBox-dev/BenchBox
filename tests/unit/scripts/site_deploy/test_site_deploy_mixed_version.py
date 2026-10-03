from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from scripts.assemble_public_site import REPO_ROOT
from scripts.site_deploy import mixed_version as mv
from scripts.site_deploy.mixed_version import FORWARD, PHASE_FULL, PHASE_UI_FIRST, ROLLBACK, Versions

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _snapshot(path: Path, version: int | None) -> Path:
    with duckdb.connect(str(path)) as connection:
        if version is None:
            connection.execute("CREATE TABLE other(x INTEGER)")
        else:
            connection.execute("CREATE TABLE metadata(read_model_version INTEGER)")
            connection.execute("INSERT INTO metadata VALUES (?)", [version])
    return path


def test_ui_expected_version_is_read_from_the_real_explorer_source() -> None:
    assert mv.ui_expected_from_tree(REPO_ROOT) >= 1


def test_ui_expected_version_requires_exactly_one_constant() -> None:
    assert mv.parse_ui_expected("const EXPECTED_READ_MODEL_VERSION = 12;\n") == 12
    with pytest.raises(mv.VersionError):
        mv.parse_ui_expected("const OTHER = 1;")
    with pytest.raises(mv.VersionError):
        mv.parse_ui_expected("const EXPECTED_READ_MODEL_VERSION = 1;\nconst EXPECTED_READ_MODEL_VERSION = 2;\n")


def test_snapshot_version_reads_the_metadata_row(tmp_path: Path) -> None:
    assert mv.snapshot_version(_snapshot(tmp_path / "a.duckdb", 11)) == 11
    with pytest.raises(mv.VersionError):
        mv.snapshot_version(_snapshot(tmp_path / "b.duckdb", None))
    with pytest.raises(mv.VersionError):
        mv.snapshot_version(tmp_path / "missing.duckdb")


@pytest.mark.parametrize(
    ("candidate", "current", "ok"),
    [
        (Versions(11, 11), Versions(11, 11), True),
        (Versions(11, 12), Versions(11, 11), True),
        (Versions(12, 12), Versions(11, 11), True),
        (Versions(12, 11), Versions(11, 11), False),
        (Versions(11, 10), Versions(11, 11), False),
        (Versions(11, 11), Versions(12, 12), False),
        (Versions(11, 11), None, True),
        (Versions(12, 11), None, False),
    ],
)
def test_forward_deploys_need_snapshot_at_least_ui_for_every_pair(
    candidate: Versions, current: Versions | None, ok: bool
) -> None:
    evaluation = mv.evaluate(candidate, current, FORWARD)
    assert evaluation.ok is ok
    assert all(pair.ok for pair in evaluation.pairs) is ok


def test_forward_deploy_checks_the_old_ui_against_the_new_snapshot_and_the_new_pair() -> None:
    names = {pair.name for pair in mv.required_pairs(Versions(12, 12), Versions(11, 11), FORWARD)}
    assert names == {"candidate-ui/candidate-snapshot", "deployed-ui/candidate-snapshot"}


def test_rollback_to_a_generation_with_an_older_snapshot_restores_the_ui_first() -> None:
    restored = Versions(ui=11, snapshot=11)
    current = Versions(ui=12, snapshot=12)
    full = mv.evaluate(restored, current, ROLLBACK, PHASE_FULL)
    assert full.ok is False
    assert full.plan == [PHASE_UI_FIRST, PHASE_FULL]
    ui_first = mv.evaluate(restored, current, ROLLBACK, PHASE_UI_FIRST)
    assert ui_first.ok is True


def test_rollback_without_a_snapshot_regression_is_a_single_step() -> None:
    evaluation = mv.evaluate(Versions(11, 12), Versions(12, 12), ROLLBACK, PHASE_FULL)
    assert evaluation.ok is True
    assert evaluation.plan == [PHASE_FULL]


def test_rollback_refuses_when_no_order_keeps_the_snapshot_at_least_the_ui() -> None:
    evaluation = mv.evaluate(Versions(ui=13, snapshot=13), Versions(ui=12, snapshot=12), ROLLBACK, PHASE_UI_FIRST)
    assert evaluation.ok is False
    broken = mv.evaluate(Versions(ui=13, snapshot=11), Versions(ui=12, snapshot=12), ROLLBACK, PHASE_FULL)
    assert broken.ok is False
    assert broken.plan == []


def test_rollback_refuses_an_artifact_pairing_its_ui_with_an_older_snapshot() -> None:
    assert mv.evaluate(Versions(12, 11), Versions(12, 12), ROLLBACK).ok is False


def test_ui_first_pairs_describe_the_composed_artifact_not_a_restored_snapshot() -> None:
    restored = Versions(ui=11, snapshot=11)
    current = Versions(ui=12, snapshot=12)
    names = [pair.name for pair in mv.required_pairs(restored, current, ROLLBACK, PHASE_UI_FIRST)]
    assert names == ["restored-ui/composed-snapshot", "restored-ui/current-snapshot", "current-ui/composed-snapshot"]
    full = [pair.name for pair in mv.required_pairs(restored, current, ROLLBACK, PHASE_FULL)]
    assert full == ["candidate-ui/candidate-snapshot", "restored-ui/current-snapshot", "current-ui/restored-snapshot"]
    evaluation = mv.evaluate(restored, current, ROLLBACK, PHASE_UI_FIRST)
    assert [pair["name"] for pair in evaluation.to_dict()["pairs"]] == names
