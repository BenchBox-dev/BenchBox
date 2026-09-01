from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.publication.assembler import (
    LaneArtifact,
    PathOwnershipError,
    SiteAssembler,
    compute_tree_digest,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_site_assembler_mount_and_determinism(tmp_path: Path):
    lane1_src = tmp_path / "lane1"
    lane1_src.mkdir()
    (lane1_src / "index.html").write_text("<html>Landing</html>", encoding="utf-8")
    (lane1_src / "styles.css").write_text("body { margin: 0; }", encoding="utf-8")

    lane2_src = tmp_path / "lane2"
    lane2_src.mkdir()
    (lane2_src / "docs.html").write_text("<html>Docs</html>", encoding="utf-8")

    art1 = LaneArtifact(
        lane_name="prose",
        digest="d1",
        size_bytes=100,
        source_path="lane1",
        output_prefix="",
    )
    art2 = LaneArtifact(
        lane_name="api_docs",
        digest="d2",
        size_bytes=50,
        source_path="lane2",
        output_prefix="api",
    )

    out_dir = tmp_path / "out"
    assembler = SiteAssembler(out_dir)
    receipt = assembler.assemble([(art1, lane1_src), (art2, lane2_src)])

    assert (out_dir / "index.html").is_file()
    assert (out_dir / "styles.css").is_file()
    assert (out_dir / "api/docs.html").is_file()
    assert (out_dir / "publication-receipt.json").is_file()
    assert receipt["total_files"] == 3
    assert len(receipt["assembly_digest"]) == 64


def test_site_assembler_path_collision_rejection(tmp_path: Path):
    lane1_src = tmp_path / "lane1"
    lane1_src.mkdir()
    (lane1_src / "shared.js").write_text("console.log(1);", encoding="utf-8")

    lane2_src = tmp_path / "lane2"
    lane2_src.mkdir()
    (lane2_src / "shared.js").write_text("console.log(2);", encoding="utf-8")

    art1 = LaneArtifact(
        lane_name="prose",
        digest="d1",
        size_bytes=10,
        source_path="lane1",
        output_prefix="",
    )
    art2 = LaneArtifact(
        lane_name="explorer",
        digest="d2",
        size_bytes=10,
        source_path="lane2",
        output_prefix="",
    )

    out_dir = tmp_path / "out"
    assembler = SiteAssembler(out_dir)
    with pytest.raises(PathOwnershipError, match="Path collision on 'shared.js'"):
        assembler.assemble([(art1, lane1_src), (art2, lane2_src)])
