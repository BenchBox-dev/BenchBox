"""Collision handling for `result_id` in the Explorer publication loop.

`result_id` ends in only 8 hex characters (32 bits) of a sha256 over the
published bytes, so its birthday bound is far below what the id's length
suggests. Before the guard these tests cover, two bundles deriving one id both
wrote `{result_id}.json` and both assigned `details_map[result_id]`: the second
replaced the first in the published corpus *and* in the read model, with no
error, no warning, and no count mismatch any existing check would notice.

A real collision cannot be constructed on demand, so these tests force the
derivation to collide and assert on what the loop does about it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _project.scripts.explorer_pipeline.pipeline import DuplicateResultIdError, ExplorerPipeline
from _project.scripts.explorer_pipeline.transformer import BundleTransformer
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]

COLLIDING_ID = "tpch-duckdb-sf0.1-20260315-deadbeef"


@pytest.fixture()
def force_id_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every bundle derive the same result_id."""
    monkeypatch.setattr(
        BundleTransformer,
        "result_id_from_bundle",
        lambda *args, **kwargs: COLLIDING_ID,
    )


def _write_bundle(bundles_dir: Path, name: str, *, total_duration_ms: int) -> Path:
    bundles_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(json.dumps(MINIMAL_BUNDLE))
    payload["run"]["total_duration_ms"] = total_duration_ms
    path = bundles_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_duplicate_result_id_with_differing_content_fails_the_build(
    tmp_path: Path,
    force_id_collision: None,
) -> None:
    """Two distinct results competing for one public URL must stop the build.

    Silently publishing one of them is evidence loss: the corpus would claim a
    result that the read model no longer describes.
    """
    data_dir = tmp_path / "data"
    bundles = data_dir / "bundles"
    _write_bundle(bundles, "first.json", total_duration_ms=45000)
    _write_bundle(bundles, "second.json", total_duration_ms=99000)

    with pytest.raises(DuplicateResultIdError) as excinfo:
        ExplorerPipeline().run(data_dir, tmp_path / "out")

    message = str(excinfo.value)
    assert COLLIDING_ID in message
    # Both sources must be named - a collision report that identifies only one
    # of the two files leaves the maintainer with nothing to compare.
    assert "first.json" in message
    assert "second.json" in message


def test_duplicate_result_id_error_escapes_the_per_bundle_handler() -> None:
    """The guard must not be catchable by the loop's own error handling.

    The publication loop wraps each bundle in
    `except (json.JSONDecodeError, KeyError, ValueError, TypeError)` and
    downgrades whatever it catches to `skipped_bundles += 1` plus a warning. If
    the collision were raised as a ValueError the build would finish green
    having published exactly one of the two colliding results - the original
    defect, reintroduced through the exception type.
    """
    assert not issubclass(DuplicateResultIdError, ValueError)
    assert not issubclass(DuplicateResultIdError, (json.JSONDecodeError, KeyError, TypeError))


def test_duplicate_result_id_with_identical_content_publishes_once(
    tmp_path: Path,
    force_id_collision: None,
) -> None:
    """A byte-identical copy is a redundant file, not a collision.

    Publishing it once is the correct outcome, so this must not fail the build.
    Failing here would make the pipeline intolerant of a duplicated corpus file
    that costs nothing and loses nothing.
    """
    data_dir = tmp_path / "data"
    bundles = data_dir / "bundles"
    _write_bundle(bundles, "original.json", total_duration_ms=45000)
    _write_bundle(bundles / "nested", "copy.json", total_duration_ms=45000)

    output = tmp_path / "out"
    ExplorerPipeline().run(data_dir, output)

    published = sorted(p.name for p in (output / "bundles").glob("*.json"))
    assert published == [f"{COLLIDING_ID}.json"]


def test_duplicate_result_id_identical_primaries_with_differing_companions_fail(
    tmp_path: Path,
    force_id_collision: None,
) -> None:
    """Byte-identical primaries are not identical results if their sidecars differ.

    Companions publish as `{result_id}.plans.json`, keyed by the same id. If the
    guard hashed only the primary bundle, a copy carrying plans that the first
    lacked would be treated as redundant and skipped, silently dropping that
    evidence - the same loss the guard exists to prevent, one file over.
    """
    data_dir = tmp_path / "data"
    bundles = data_dir / "bundles"
    _write_bundle(bundles, "first.json", total_duration_ms=45000)
    second = _write_bundle(bundles / "nested", "second.json", total_duration_ms=45000)
    second.with_name("second.plans.json").write_text(json.dumps({"q1": "PLAN"}), encoding="utf-8")

    with pytest.raises(DuplicateResultIdError):
        ExplorerPipeline().run(data_dir, tmp_path / "out")


def test_duplicate_result_id_guard_leaves_the_normal_path_untouched(tmp_path: Path) -> None:
    """Distinct ids still publish one file each.

    Guards that only ever say "no" are indistinguishable from a broken loop, so
    pin that the ordinary two-bundle case is unaffected.
    """
    data_dir = tmp_path / "data"
    bundles = data_dir / "bundles"
    _write_bundle(bundles, "first.json", total_duration_ms=45000)
    _write_bundle(bundles, "second.json", total_duration_ms=99000)

    output = tmp_path / "out"
    ExplorerPipeline().run(data_dir, output)

    published = sorted(p.name for p in (output / "bundles").glob("*.json"))
    assert len(published) == 2, f"expected both bundles published, got {published}"
