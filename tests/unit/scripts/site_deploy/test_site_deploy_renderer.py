from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.assemble_public_site import REPO_ROOT, STAGE_BUILDERS, assemble_astro_stage, assemble_public_site, main
from scripts.publication.assembler import compute_file_sha256
from scripts.site_deploy import candidate, cli, gates, generation, mixed_version, receipt, renderer, routes
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, SHA_B, FakeGitHub, make_receipt

pytestmark = [pytest.mark.unit, pytest.mark.medium]

MANIFEST = REPO_ROOT / "deploy" / "routes.yml"
TRUNK_PATH = ".github/workflows/trunk.yml"
SPHINX_PAGE = '<html><head><script src="../_static/documentation_options.js?v=1"></script></head></html>'
ASTRO_PAGE = '<html><head><link rel="stylesheet" href="/_astro/site.{label}.css"></head><body>{label}</body></html>'
RECIPE = "site-build: docs-generate site-deps\n\t@npm --prefix website run build\n"
V041_SHAPE = (
    "docs/conf.py",
    "docs/index.rst",
    "docs/usage/getting-started.rst",
    "docs/blog/2026-05-18-v0-3-0-release-overview.md",
    "landing/index.html",
    "make/documentation.mk",
    "results-explorer/package.json",
    "pyproject.toml",
)


def _ready_paths() -> list[str]:
    paths = list(renderer.ASTRO_REQUIRED_FILES)
    paths += [f"{name}/entry.astro" for name in renderer.ASTRO_REQUIRED_DIRS]
    return [*paths, "docs/index.md", "docs/usage/getting-started.md"]


def _ready_text(path: str) -> str | None:
    return RECIPE if path == "make/documentation.mk" else None


def _write(path: Path, content: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit_tree(root: Path, files: dict[str, str], tag: str | None = None) -> str:
    for name, content in files.items():
        _write(root / name, content)
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), *env, "commit", "-q", "-m", "fixture"], check=True)
    if tag:
        subprocess.run(["git", "-C", str(root), *env, "tag", tag], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_a_release_without_website_selects_sphinx_for_every_route() -> None:
    readiness = renderer.astro_readiness(V041_SHAPE, lambda path: None)
    selection = renderer.select(renderer.POLICY_AUTO, readiness)
    assert selection.renderer == renderer.SPHINX
    assert "website/package.json" in readiness.missing
    assert readiness.legacy_sources == ("docs/index.rst", "docs/usage/getting-started.rst")


def test_a_release_with_website_and_migrated_docs_selects_astro() -> None:
    selection = renderer.select(renderer.POLICY_AUTO, renderer.astro_readiness(_ready_paths(), _ready_text))
    assert selection.renderer == renderer.ASTRO
    assert selection.to_dict()["astro_ready"] is True


@pytest.mark.parametrize("dropped", [*renderer.ASTRO_REQUIRED_FILES, *renderer.ASTRO_REQUIRED_DIRS])
def test_each_missing_website_input_keeps_sphinx(dropped: str) -> None:
    paths = [path for path in _ready_paths() if path != dropped and not path.startswith(f"{dropped}/")]
    selection = renderer.select(renderer.POLICY_AUTO, renderer.astro_readiness(paths, _ready_text))
    assert selection.renderer == renderer.SPHINX
    assert any(entry.startswith(dropped) for entry in selection.readiness.missing)


def test_one_unmigrated_docs_source_keeps_sphinx() -> None:
    paths = [*_ready_paths(), "docs/reference/legacy.rst"]
    selection = renderer.select(renderer.POLICY_AUTO, renderer.astro_readiness(paths, _ready_text))
    assert selection.renderer == renderer.SPHINX
    assert selection.readiness.legacy_sources == ("docs/reference/legacy.rst",)


def test_a_release_without_the_site_build_recipe_keeps_sphinx() -> None:
    selection = renderer.select(renderer.POLICY_AUTO, renderer.astro_readiness(_ready_paths(), lambda path: "docs:\n"))
    assert selection.renderer == renderer.SPHINX
    assert selection.readiness.missing == ("make/documentation.mk:site-build",)


def test_the_sphinx_policy_holds_sphinx_even_for_a_ready_release() -> None:
    selection = renderer.select(renderer.SPHINX, renderer.astro_readiness(_ready_paths(), _ready_text))
    assert selection.renderer == renderer.SPHINX


@pytest.mark.parametrize("policy", ["astro", "", "Auto"])
def test_no_policy_can_force_astro(policy: str) -> None:
    with pytest.raises(renderer.RendererError, match="not one of"):
        renderer.select(policy, renderer.astro_readiness(_ready_paths(), _ready_text))
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    data["renderer"] = policy
    with pytest.raises(routes.RouteManifestError, match="renderer policy"):
        routes.parse_manifest(data)


def test_committed_manifest_selects_the_renderer_from_the_release_tag() -> None:
    assert routes.load_manifest(MANIFEST).renderer_policy == renderer.POLICY_AUTO
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    del data["renderer"]
    assert routes.parse_manifest(data).renderer_policy == renderer.SPHINX


def test_selection_reads_the_tag_tree_not_the_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = dict.fromkeys(V041_SHAPE, "x")
    files["make/documentation.mk"] = "docs:\n"
    _commit_tree(repo, files, tag="v0.4.1")
    for name in _ready_paths():
        _write(repo / name, _ready_text(name) or "x")
    for name in V041_SHAPE:
        if name.endswith(".rst"):
            (repo / name).unlink()
    assert renderer.select_for_commit(renderer.POLICY_AUTO, repo, "v0.4.1").renderer == renderer.SPHINX


def test_an_unreadable_commit_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _commit_tree(repo, {"README.md": "x"})
    with pytest.raises(renderer.RendererError, match="cannot list"):
        renderer.select_for_commit(renderer.POLICY_AUTO, repo, "f" * 40)


def test_the_current_latest_release_tag_selects_sphinx() -> None:
    tags = candidate.release_tags(REPO_ROOT)
    if not tags:
        pytest.skip("this checkout carries no release tags")
    tag = candidate.latest_release_tag(tags)
    policy = routes.load_manifest(MANIFEST).renderer_policy
    selection = renderer.select_for_commit(policy, REPO_ROOT, candidate.tag_commit(REPO_ROOT, tag))
    assert selection.renderer == renderer.SPHINX, f"{tag} selects astro: {selection.reason}"
    assert "website/package.json" in selection.readiness.missing


def test_trunk_still_satisfies_the_astro_release_definition() -> None:
    readiness = renderer.readiness_at(REPO_ROOT, "HEAD")
    assert readiness.ready, readiness.summary()


def _astro_checkout(
    root: Path, label: str, *, shared: str = "shared asset", extra: dict[str, str] | None = None
) -> Path:
    dist = root / "website" / "dist"
    page = ASTRO_PAGE.format(label=label)
    for name in ("index.html", "prompts/index.html", "docs/index.html", "docs/api.html", "blog/post.html", "404.html"):
        _write(dist / name, page)
    _write(dist / "_astro" / f"site.{label}.css", f"{label} css")
    _write(dist / "_astro" / "shared.js", shared)
    _write(dist / "_images" / "logo.svg", "logo")
    _write(dist / "pagefind" / "index.json", label)
    _write(dist / "CNAME", "benchbox.dev\n")
    _write(dist / ".nojekyll", "")
    _write(dist / "results" / "index.html", f"{label} explorer")
    _write(dist / "results" / "assets" / "app.js", f"{label} explorer js")
    _write(dist / "results" / "data" / "results.duckdb", f"{label} snapshot")
    for name, content in (extra or {}).items():
        _write(dist / name, content)
    return root


def _assemble_astro(tmp_path: Path, release: Path, trunk: Path) -> dict[str, Any]:
    return routes.assemble_routes(
        manifest=routes.load_manifest(MANIFEST),
        ref_roots={"release": release, "trunk": trunk},
        site_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        stage_builder=assemble_astro_stage,
        resolve_sha=lambda root: root.name,
        renderer=renderer.ASTRO,
    )


def test_astro_assembly_takes_stable_routes_from_the_release_and_dev_routes_from_trunk(tmp_path: Path) -> None:
    release = _astro_checkout(tmp_path / "release", "release")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk")
    summary = _assemble_astro(tmp_path, release, trunk)
    site = tmp_path / "out"

    def read(name: str) -> str:
        return (site / name).read_text(encoding="utf-8")

    assert "release" in read("index.html")
    assert "release" in read("prompts/index.html")
    assert "release" in read("docs/index.html")
    assert "release" in read("docs/api.html")
    assert "trunk" in read("docs/dev/index.html")
    assert "trunk" in read("blog/post.html")
    assert "trunk" in read("404.html")
    assert read("results/index.html") == "trunk explorer"
    assert read("_astro/site.release.css") == "release css"
    assert read("_astro/site.trunk.css") == "trunk css"
    assert read("pagefind/index.json") == "release"
    assert summary["renderer"] == renderer.ASTRO
    assert {route["renderer"] for route in summary["routes"]} == {renderer.ASTRO}
    owners = summary["file_owners"]
    assert owners["_astro/shared.js"] == "/:."
    assert owners["_astro/site.trunk.css"] == "/blog/:_astro"
    assert owners["_images/logo.svg"] == "/:."
    assert routes.owner_ref(routes.load_manifest(MANIFEST), "/docs/api.html", renderer.ASTRO) == "release"


def test_astro_explorer_pins_the_ui_and_the_snapshot_separately(tmp_path: Path) -> None:
    release = _astro_checkout(tmp_path / "release", "release")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk")
    summary = _assemble_astro(tmp_path, release, trunk)
    explorer = next(route for route in summary["routes"] if route["builder"] == "explorer")
    pins = explorer["pins"]
    assert pins["ui"]["source_sha"] == "trunk"
    assert pins["snapshot"]["sha256"] == compute_file_sha256(tmp_path / "out" / "results" / "data" / "results.duckdb")
    assert pins["ui"]["sha256"] != next(iter(explorer["lane_sha256"].values()))
    built = receipt.build_receipt(
        mode="deploy",
        target="github-pages",
        run_id=1,
        deployment_id=None,
        trunk_sha=SHA_A,
        release_tag="v1.0.0",
        release_sha=SHA_B,
        corpus_sha="1" * 40,
        assembly=summary,
        artifact_name="x",
        versions={},
        gates={"ok": True, "results": {}},
        probes={"ok": True},
        parent=None,
        certifying_run_id=None,
    )
    assert built["renderer"] == renderer.ASTRO
    assert built["explorer"]["pins"]["snapshot"]["corpus_sha"] == "1" * 40


def test_astro_assembly_refuses_shared_assets_whose_bytes_differ(tmp_path: Path) -> None:
    release = _astro_checkout(tmp_path / "release", "release", shared="one")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk", shared="two")
    with pytest.raises(routes.RouteManifestError, match="different bytes at shared path _astro/shared.js"):
        _assemble_astro(tmp_path, release, trunk)


def test_astro_assembly_refuses_a_stage_that_is_not_an_astro_build(tmp_path: Path) -> None:
    release = _astro_checkout(tmp_path / "release", "release")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk")
    (trunk / "website" / "dist" / "_astro" / "shared.js").unlink()
    (trunk / "website" / "dist" / "_astro" / "site.trunk.css").unlink()
    (trunk / "website" / "dist" / "_astro").rmdir()
    with pytest.raises(routes.RouteManifestError, match="ref trunk did not produce an astro build"):
        _assemble_astro(tmp_path, release, trunk)


def test_astro_assembly_refuses_a_stage_carrying_sphinx_pages(tmp_path: Path) -> None:
    release = _astro_checkout(tmp_path / "release", "release")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk", extra={"blog/legacy.html": SPHINX_PAGE})
    with pytest.raises(routes.RouteManifestError, match="ref trunk stage for astro carries sphinx output"):
        _assemble_astro(tmp_path, release, trunk)


def _sphinx_checkout(root: Path, label: str, *, astro_page: str | None = None) -> Path:
    html = root / "docs" / "_build" / "html"
    _write(html / "index.html", SPHINX_PAGE)
    _write(html / "blog" / "post.html", SPHINX_PAGE)
    _write(html / "_static" / "documentation_options.js", label)
    _write(html / "_images" / "logo.svg", label)
    if astro_page:
        _write(html / astro_page, ASTRO_PAGE.format(label=label))
    _write(root / "docs" / "CNAME", "benchbox.dev\n")
    _write(root / "landing" / "index.html", f"{label} landing")
    _write(root / "results-explorer" / "package.json", "{}")
    _write(root / "results-explorer" / "dist" / "index.html", f"{label} explorer")
    return root


def test_sphinx_assembly_refuses_a_ref_whose_build_carries_astro_output(tmp_path: Path) -> None:
    release = _sphinx_checkout(tmp_path / "release", "release")
    trunk = _sphinx_checkout(tmp_path / "trunk", "trunk", astro_page="guide.html")
    with pytest.raises(routes.RouteManifestError, match="ref trunk stage for sphinx carries astro output"):
        routes.assemble_routes(
            manifest=routes.load_manifest(MANIFEST),
            ref_roots={"release": release, "trunk": trunk},
            site_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            stage_builder=assemble_public_site,
            resolve_sha=lambda root: root.name,
        )


def test_assembly_refuses_and_removes_a_mixed_artifact_from_per_ref_builders(tmp_path: Path) -> None:
    release = _sphinx_checkout(tmp_path / "release", "release")
    trunk = _astro_checkout(tmp_path / "trunk", "trunk")

    def per_ref(*, repo_root: Path, site_dir: Path, prose_only: bool) -> None:
        if repo_root == trunk:
            assemble_astro_stage(repo_root=repo_root, site_dir=site_dir, prose_only=prose_only)
        else:
            assemble_public_site(repo_root=repo_root, site_dir=site_dir, prose_only=prose_only)

    for selected in renderer.RENDERERS:
        with pytest.raises(routes.RouteManifestError, match="did not produce an astro build|carries astro output"):
            routes.assemble_routes(
                manifest=routes.load_manifest(MANIFEST),
                ref_roots={"release": release, "trunk": trunk},
                site_dir=tmp_path / "out",
                work_dir=tmp_path / "work",
                stage_builder=per_ref,
                resolve_sha=lambda root: root.name,
                renderer=selected,
            )
        assert not (tmp_path / "out").exists()


def test_the_final_artifact_check_names_the_foreign_pages(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "index.html", SPHINX_PAGE)
    _write(tmp_path / "blog" / "post.html", ASTRO_PAGE.format(label="x"))
    _write(tmp_path / "results" / "index.html", ASTRO_PAGE.format(label="explorer"))
    with pytest.raises(mixed_version.RendererMixError, match=r"astro: 1 \(first: blog/post.html\)"):
        mixed_version.require_single_renderer(tmp_path, renderer.SPHINX)
    with pytest.raises(mixed_version.RendererMixError, match=r"sphinx: 1 \(first: docs/index.html\)"):
        mixed_version.require_single_renderer(tmp_path, renderer.ASTRO)


def test_a_page_with_both_renderers_markers_is_mixed(tmp_path: Path) -> None:
    _write(tmp_path / "index.html", SPHINX_PAGE + ASTRO_PAGE.format(label="x"))
    for selected in renderer.RENDERERS:
        with pytest.raises(mixed_version.RendererMixError, match="mixed: 1"):
            mixed_version.require_single_renderer(tmp_path, selected)


def test_marker_text_inside_escaped_code_is_not_a_renderer_page(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "index.html", SPHINX_PAGE + "<pre>&lt;link href=&quot;/_astro/x.css&quot;&gt;</pre>")
    assert mixed_version.require_single_renderer(tmp_path, renderer.SPHINX) == {renderer.SPHINX: 1}


def test_cli_refuses_a_renderer_that_differs_from_the_release_selection(tmp_path: Path) -> None:
    release = _sphinx_checkout(tmp_path / "release", "release")
    trunk = _sphinx_checkout(tmp_path / "trunk", "trunk")
    _commit_tree(release, {})
    _commit_tree(trunk, {})
    base = ["--routes", str(MANIFEST), "--ref-root", f"release={release}", "--ref-root", f"trunk={trunk}"]
    base += ["--site-dir", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work")]
    with pytest.raises(SystemExit, match="--renderer astro differs from the release selection sphinx"):
        main([*base, "--renderer", "astro"])
    assert main([*base, "--renderer", "sphinx", "--receipt-out", str(tmp_path / "assembly.json")]) == 0
    assembly = json.loads((tmp_path / "assembly.json").read_text(encoding="utf-8"))
    assert assembly["renderer"] == renderer.SPHINX
    assert assembly["renderer_selection"]["astro_ready"] is False
    assert set(STAGE_BUILDERS) == set(renderer.RENDERERS)


def _use(monkeypatch: pytest.MonkeyPatch, api: FakeGitHub, ready: bool) -> None:
    monkeypatch.setattr(cli, "_client", api.client)
    monkeypatch.setattr(cli, "gh_receipt_loader", lambda repo: api.load_receipt)
    monkeypatch.setattr(candidate, "release_tags", lambda repo_dir: ["v0.4.1", "v0.5.0"])
    monkeypatch.setattr(candidate, "tag_commit", lambda repo_dir, tag: SHA_A)
    monkeypatch.setattr(candidate, "first_parent_shas", lambda repo_dir, ref, limit=50: [SHA_B])
    monkeypatch.setattr(candidate, "is_ancestor", lambda repo_dir, ancestor, descendant: ancestor == SHA_A)
    paths = _ready_paths() if ready else list(V041_SHAPE)
    monkeypatch.setattr(renderer, "tree_paths", lambda repo_dir, commit: paths)
    monkeypatch.setattr(renderer, "tree_text", lambda repo_dir, commit, path: _ready_text(path))
    api.runs.append(
        {
            "id": 5,
            "head_sha": SHA_B,
            "head_branch": "develop",
            "event": "push",
            "conclusion": "success",
            "path": TRUNK_PATH,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )


def _resolve(tmp_path: Path, *args: str) -> tuple[int, dict[str, Any]]:
    output = tmp_path / "resolved.json"
    code = cli.main(["resolve", "--output", str(output), *args])
    return code, json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}


def _astro_receipt(run_id: int, trunk: str) -> dict[str, Any]:
    built = make_receipt(run_id=run_id, trunk=trunk)
    built["renderer"] = renderer.ASTRO
    return built


@pytest.mark.parametrize(
    ("ready", "deployed_astro", "expected", "visual"),
    [
        (False, False, renderer.SPHINX, False),
        (True, False, renderer.ASTRO, True),
        (True, True, renderer.ASTRO, True),
        (False, True, renderer.SPHINX, True),
    ],
)
def test_resolve_records_the_renderer_and_when_the_visual_guard_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready: bool, deployed_astro: bool, expected: str, visual: bool
) -> None:
    api = FakeGitHub()
    deployed = _astro_receipt(1, SHA_A) if deployed_astro else make_receipt(run_id=1, trunk=SHA_A)
    api.record_deployment(10, deployed, "2026-01-01T00:00:01Z")
    _use(monkeypatch, api, ready)
    outputs = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    code, resolved = _resolve(tmp_path, "--mode", "deploy")
    assert code == 0
    assert resolved["renderer"] == expected
    assert resolved["deployed_renderer"] == (renderer.ASTRO if deployed_astro else renderer.SPHINX)
    assert resolved["visual_required"] is visual
    lines = outputs.read_text(encoding="utf-8").splitlines()
    assert f"renderer={expected}" in lines
    assert f"visual_required={'true' if visual else 'false'}" in lines


def test_resolve_fails_closed_when_the_tag_tree_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    _use(monkeypatch, api, ready=False)

    def unreadable(repo_dir: Path, commit: str) -> list[str]:
        raise renderer.RendererError("cannot list the tree")

    monkeypatch.setattr(renderer, "tree_paths", unreadable)
    code, resolved = _resolve(tmp_path, "--mode", "deploy")
    assert code == 1
    assert resolved == {}
    assert "renderer selection for v0.5.0 failed" in capsys.readouterr().err


def test_rollback_restores_the_target_renderer_without_the_visual_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    api.record_deployment(11, _astro_receipt(2, SHA_B), "2026-01-01T00:00:02Z")
    _use(monkeypatch, api, ready=True)
    code, resolved = _resolve(tmp_path, "--mode", "rollback", "--rollback-run-id", "1")
    assert code == 0
    assert resolved["renderer"] == renderer.SPHINX
    assert resolved["deployed_renderer"] == renderer.ASTRO
    assert resolved["visual_required"] is False


def test_ui_first_rollback_across_renderers_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeGitHub()
    api.record_deployment(10, make_receipt(run_id=1, trunk=SHA_A), "2026-01-01T00:00:01Z")
    api.record_deployment(11, _astro_receipt(2, SHA_B), "2026-01-01T00:00:02Z")
    _use(monkeypatch, api, ready=True)
    code, _ = _resolve(tmp_path, "--mode", "rollback", "--rollback-run-id", "1", "--rollback-phase", "ui-first")
    assert code == 1
    assert "roll back with the full phase" in capsys.readouterr().err


def test_deployed_generation_reads_the_receipt_renderer_and_defaults_old_receipts_to_sphinx() -> None:
    assert generation.deployed_from_receipt(make_receipt(run_id=1, trunk=SHA_A), "0" * 64).renderer == "sphinx"
    assert generation.deployed_from_receipt(_astro_receipt(1, SHA_A), "0" * 64).renderer == "astro"


def test_gates_refuse_an_assembly_whose_renderer_differs_from_the_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved = tmp_path / "resolved.json"
    resolved.write_text(json.dumps({"renderer": "sphinx", "trunk_sha": SHA_A}), encoding="utf-8")
    assembly = tmp_path / "assembly.json"
    assembly.write_text(json.dumps({"renderer": "astro", "routes": []}), encoding="utf-8")
    args = ["gates", "--repo-root", str(tmp_path), "--site-dir", str(tmp_path / "site"), "--resolved", str(resolved)]
    assert cli.main([*args, "--assembly", str(assembly), "--out-dir", str(tmp_path / "out")]) == 1
    assert "differs from the resolved sphinx" in capsys.readouterr().err


def test_the_final_artifact_check_refuses_and_removes_a_mix_the_stage_checks_missed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _sphinx_checkout(tmp_path / "release", "release")
    trunk = _sphinx_checkout(tmp_path / "trunk", "trunk", astro_page="guide.html")
    monkeypatch.setattr(routes, "_check_stage", lambda ref, stage, selected: None)
    with pytest.raises(routes.RouteManifestError, match="refusing a mixed-renderer artifact"):
        routes.assemble_routes(
            manifest=routes.load_manifest(MANIFEST),
            ref_roots={"release": release, "trunk": trunk},
            site_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            stage_builder=assemble_public_site,
            resolve_sha=lambda root: root.name,
        )
    assert not (tmp_path / "out").exists()


def test_the_mixed_version_gate_also_refuses_a_mixed_renderer_tree(tmp_path: Path) -> None:
    site = tmp_path / "site"
    _write(site / "docs" / "index.html", SPHINX_PAGE)
    _write(site / "blog" / "post.html", ASTRO_PAGE.format(label="x"))
    inputs = gates.GateInputs(
        repo_root=tmp_path,
        site_dir=site,
        work_dir=tmp_path / "work",
        trunk_sha=SHA_A,
        corpus_sha=SHA_B,
        mode="rollback",
        deployed=None,
        deployed_snapshot=None,
        renderer=renderer.ASTRO,
    )
    result = gates.mixed_version_gate(inputs, lambda command, cwd: (0, ""))
    assert result["status"] == gates.FAIL
    assert "sphinx: 1" in result["detail"]
    assert "mixed_version" in gates.ROLLBACK_GATES
