from __future__ import annotations

from pathlib import Path

import pytest

from scripts.publication.assembler import (
    DigestMismatchError,
    LaneArtifact,
    PathOwnershipError,
    SiteAssembler,
    build_lane_artifact,
    compute_tree_digest,
    main,
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

    d1, s1, m1 = compute_tree_digest(lane1_src)
    d2, s2, m2 = compute_tree_digest(lane2_src)
    art1 = LaneArtifact(
        lane_name="prose",
        digest=d1,
        size_bytes=s1,
        source_path="lane1",
        output_prefix="",
        file_manifest=m1,
    )
    art2 = LaneArtifact(
        lane_name="api_docs",
        digest=d2,
        size_bytes=s2,
        source_path="lane2",
        output_prefix="api",
        file_manifest=m2,
    )

    out_dir = tmp_path / "out"
    receipt_path = tmp_path / "out-receipt.json"
    assembler = SiteAssembler(out_dir, receipt_path=receipt_path)
    receipt, written_receipt = assembler.assemble([(art1, lane1_src), (art2, lane2_src)])

    assert (out_dir / "index.html").is_file()
    assert (out_dir / "styles.css").is_file()
    assert (out_dir / "api/docs.html").is_file()
    assert not (out_dir / "publication-receipt.json").exists()
    assert written_receipt == receipt_path
    assert receipt_path.is_file()
    assert receipt["total_files"] == 3
    assert len(receipt["assembly_digest"]) == 64


def test_site_assembler_path_collision_rejection(tmp_path: Path):
    lane1_src = tmp_path / "lane1"
    lane1_src.mkdir()
    (lane1_src / "shared.js").write_text("console.log(1);", encoding="utf-8")

    lane2_src = tmp_path / "lane2"
    lane2_src.mkdir()
    (lane2_src / "shared.js").write_text("console.log(2);", encoding="utf-8")

    art1 = build_lane_artifact("prose", lane1_src, "")
    art2 = build_lane_artifact("explorer", lane2_src, "")

    out_dir = tmp_path / "out"
    assembler = SiteAssembler(out_dir)
    with pytest.raises(PathOwnershipError, match="Path collision on 'shared.js'"):
        assembler.assemble([(art1, lane1_src), (art2, lane2_src)])


def test_site_assembler_wrong_digest_raises(tmp_path: Path):
    lane_src = tmp_path / "lane"
    lane_src.mkdir()
    (lane_src / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    digest, size, manifest = compute_tree_digest(lane_src)
    art = LaneArtifact(
        lane_name="prose",
        digest="0" * 64,
        size_bytes=size,
        source_path="lane",
        output_prefix="",
        file_manifest=manifest,
    )
    assert digest != art.digest
    assembler = SiteAssembler(tmp_path / "out")
    with pytest.raises(DigestMismatchError, match="digest mismatch"):
        assembler.assemble([(art, lane_src)])


def test_assembler_cli_builds_and_writes_external_receipt(tmp_path: Path):
    lane_src = tmp_path / "lane"
    lane_src.mkdir()
    (lane_src / "index.html").write_text("<html>cli</html>", encoding="utf-8")
    out_dir = tmp_path / "site"
    receipt_path = tmp_path / "site-receipt.json"
    rc = main(
        [
            "--output-dir",
            str(out_dir),
            "--receipt-path",
            str(receipt_path),
            "--lane",
            f"name=prose,src={lane_src},prefix=",
        ]
    )
    assert rc == 0
    assert (out_dir / "index.html").is_file()
    assert receipt_path.is_file()
    assert not (out_dir / "publication-receipt.json").exists()
