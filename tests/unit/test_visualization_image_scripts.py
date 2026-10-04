from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import validate_visualization_images as vvi
from capture_chart_images import sync_existing_images
from validate_visualization_images import find_mismatches


def test_sync_existing_images_copies_to_all_targets(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_a = tmp_path / "docs"
    target_b = tmp_path / "mirror"
    source_dir.mkdir()

    (source_dir / "query_histogram.png").write_bytes(b"png-a")
    (source_dir / "summary_box.png").write_bytes(b"png-b")

    copied = sync_existing_images(
        source_dir=source_dir,
        target_dirs=(target_a, target_b),
        names=["query_histogram", "summary_box"],
    )

    assert copied == 4
    assert (target_a / "query_histogram.png").read_bytes() == b"png-a"
    assert (target_a / "summary_box.png").read_bytes() == b"png-b"
    assert (target_b / "query_histogram.png").read_bytes() == b"png-a"
    assert (target_b / "summary_box.png").read_bytes() == b"png-b"


def test_sync_existing_images_raises_for_missing_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="Missing source screenshot"):
        sync_existing_images(source_dir=source_dir, target_dirs=(tmp_path / "docs",), names=["query_histogram"])


def test_find_mismatches_detects_missing_and_different_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()

    (source_dir / "query_histogram.png").write_bytes(b"source-a")
    (source_dir / "summary_box.png").write_bytes(b"source-b")
    (target_dir / "query_histogram.png").write_bytes(b"changed")
    (target_dir / "stale_extra.png").write_bytes(b"stale")

    mismatches = find_mismatches(source_dir=source_dir, target_dir=target_dir)

    assert any("Image differs" in mismatch for mismatch in mismatches)
    assert any("Missing docs image" in mismatch for mismatch in mismatches)
    assert any("Missing source image" in mismatch for mismatch in mismatches)


def test_main_fails_on_seeded_image_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "source"
    docs_dir = tmp_path / "docs"
    source_dir.mkdir()
    docs_dir.mkdir()
    (source_dir / "chart.png").write_bytes(b"new")
    (docs_dir / "chart.png").write_bytes(b"old")
    monkeypatch.setattr(vvi, "PRIMARY_DIR", source_dir)
    monkeypatch.setattr(vvi, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(vvi, "find_mismatches", lambda: find_mismatches(source_dir, docs_dir))

    assert vvi.main() == 1

    (docs_dir / "chart.png").write_bytes(b"new")
    assert vvi.main() == 0
