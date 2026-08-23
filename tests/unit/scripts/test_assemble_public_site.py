"""Tests for the reusable GitHub Pages site assembler."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.assemble_public_site import REPO_ROOT, RESULTS_FALLBACK, assemble_public_site

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write(path: Path, content: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pages_inputs(root: Path, *, landing: bool = True, explorer: bool = True) -> None:
    _write(root / "docs" / "_build" / "html" / "index.html", "docs root")
    _write(root / "docs" / "_build" / "html" / "guide" / "index.html", "guide")
    _write(root / "docs" / "_build" / "html" / "blog" / "post.html", "blog")
    _write(root / "docs" / "_build" / "html" / "_static" / "theme.css", "css")
    _write(root / "docs" / "_build" / "html" / "_images" / "logo.svg", "svg")
    _write(root / "docs" / "CNAME", "benchbox.dev\n")
    if landing:
        _write(root / "landing" / "index.html", "landing")
    if explorer:
        _write(root / "results-explorer" / "package.json", "{}")
        _write(root / "results-explorer" / "dist" / "index.html", "explorer")


def test_assembles_landing_docs_blog_assets_explorer_and_root_fallback(tmp_path: Path) -> None:
    _pages_inputs(tmp_path)
    site_dir = tmp_path / "output" / "site"
    _write(site_dir / "stale.txt", "stale")

    assemble_public_site(repo_root=tmp_path, site_dir=site_dir)

    assert (site_dir / "index.html").read_text(encoding="utf-8") == "landing"
    assert (site_dir / "docs" / "index.html").read_text(encoding="utf-8") == "docs root"
    assert not (site_dir / "docs" / "blog").exists()
    assert (site_dir / "blog" / "post.html").read_text(encoding="utf-8") == "blog"
    assert (site_dir / "_static" / "theme.css").is_file()
    assert (site_dir / "_images" / "logo.svg").is_file()
    assert (site_dir / "results" / "index.html").read_text(encoding="utf-8") == "explorer"
    assert (site_dir / "404.html").read_text(encoding="utf-8") == RESULTS_FALLBACK
    assert "benchbox.results.redirect" in RESULTS_FALLBACK
    assert (site_dir / "CNAME").read_text(encoding="utf-8") == "benchbox.dev\n"
    assert (site_dir / ".nojekyll").is_file()
    assert not (site_dir / "stale.txt").exists()


def test_uses_documentation_as_root_when_landing_is_absent(tmp_path: Path) -> None:
    _pages_inputs(tmp_path, landing=False, explorer=False)
    site_dir = tmp_path / "site"

    assemble_public_site(repo_root=tmp_path, site_dir=site_dir)

    assert (site_dir / "index.html").read_text(encoding="utf-8") == "docs root"
    assert (site_dir / "docs").is_dir()
    assert (site_dir / "blog" / "post.html").is_file()
    assert not (site_dir / "results").exists()
    assert not (site_dir / "404.html").exists()


def test_fails_when_tracked_explorer_has_not_been_built(tmp_path: Path) -> None:
    _pages_inputs(tmp_path, explorer=False)
    _write(tmp_path / "results-explorer" / "package.json", "{}")

    with pytest.raises(FileNotFoundError, match="Results Explorer build is missing"):
        assemble_public_site(repo_root=tmp_path, site_dir=tmp_path / "site")


@pytest.mark.parametrize("destination", [Path("/"), Path.home()])
def test_refuses_broad_output_directories(tmp_path: Path, destination: Path) -> None:
    _pages_inputs(tmp_path)

    with pytest.raises(ValueError, match="refusing unsafe site output directory"):
        assemble_public_site(repo_root=tmp_path, site_dir=destination)


def test_docs_workflow_reuses_assembler_and_binds_visual_approval_to_pr_head() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert "uv run -- python scripts/assemble_public_site.py --site-dir site" in workflow
    assert "cat > site/404.html" not in workflow
    assert (
        "PR_HEAD_SHA: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || '' }}"
        in workflow
    )
    assert "APPROVED_HEAD_SHA: ${{ github.event_name == 'pull_request' && vars.APPROVED_HEAD_SHA || '' }}" in workflow
    assert "APPROVAL_REASON: ${{ github.event_name == 'pull_request' && vars.APPROVAL_REASON || '' }}" in workflow
