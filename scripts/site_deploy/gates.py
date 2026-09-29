"""Pre-deploy gates for an assembled site.

Each gate returns a :class:`GateResult`. The privacy, Explorer compatibility,
corpus bijection, database digest, and validator parity gates delegate to the
existing checks in ``scripts/publication``; the mixed-version and cross-route
link gates are defined here.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from types import ModuleType
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_DIR = REPO_ROOT / "scripts" / "publication"
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbb56904"
SNAPSHOT_PATH = "results/data/results.duckdb"


@dataclass
class GateResult:
    name: str
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def load_publication_script(name: str) -> ModuleType:
    """Import ``scripts/publication/<name>.py`` by path (the directory is not a package)."""
    module_name = f"_site_deploy_gate_{name}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    path = PUBLICATION_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load gate script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def gate_privacy(site_dir: Path) -> GateResult:
    module = load_publication_script("check_artifact_privacy")
    findings = module.scan_directory_for_privacy(site_dir)
    if findings:
        return GateResult("privacy", False, f"{len(findings)} finding(s): " + "; ".join(findings[:5]))
    return GateResult("privacy", True, "no sensitive tokens or credentialed connection strings")


# ---------------------------------------------------------------------------
# Explorer compatibility and mixed-version transitions
# ---------------------------------------------------------------------------


def read_ui_read_model_version(trunk_root: Path) -> int:
    """The read-model version the pinned UI expects (``EXPECTED_READ_MODEL_VERSION`` in db.ts)."""
    import re

    source = (trunk_root / "results-explorer" / "src" / "db.ts").read_text(encoding="utf-8")
    match = re.search(r"^const EXPECTED_READ_MODEL_VERSION = (\d+);", source, re.MULTILINE)
    if match is None:
        raise ValueError("results-explorer/src/db.ts does not declare EXPECTED_READ_MODEL_VERSION")
    return int(match.group(1))


def read_snapshot_read_model_version(snapshot: Path) -> int:
    import duckdb

    with duckdb.connect(str(snapshot), read_only=True) as con:
        row = con.execute("SELECT read_model_version FROM metadata LIMIT 1").fetchone()
    if row is None:
        raise ValueError(f"snapshot {snapshot} has no read_model_version row")
    return int(row[0])


def check_mixed_version_transition(
    previous: tuple[int, int] | None,
    candidate: tuple[int, int],
    *,
    waive_cache_window: bool = False,
) -> list[str]:
    """Problems with moving the live site from ``previous`` to ``candidate``.

    Versions are ``(ui_read_model, snapshot_read_model)``. The UI in
    ``results-explorer/src/db.ts`` rejects a snapshot older than the version it
    expects and only warns about a newer one. During a deploy, browsers and CDN
    edges can still hold either side of the previous site, so both mixed pairs must
    be readable:

    * the candidate UI meeting the previous snapshot (deploy the snapshot first);
    * the previous UI meeting the candidate snapshot (roll the UI back first).

    The candidate's own pair must always be readable. ``waive_cache_window`` accepts
    the two cache-window pairs; it never waives the candidate's own pair.
    """
    ui, snapshot = candidate
    problems: list[str] = []
    if ui > snapshot:
        problems.append(
            f"candidate UI expects read-model v{ui} but its snapshot is v{snapshot}; the UI rejects older snapshots"
        )
    if previous is None or waive_cache_window:
        return problems
    prev_ui, prev_snapshot = previous
    if ui > prev_snapshot:
        problems.append(
            f"candidate UI expects read-model v{ui} but the live snapshot is v{prev_snapshot}; cached snapshots "
            "would be rejected. Deploy the newer snapshot before the UI that requires it"
        )
    if prev_ui > snapshot:
        problems.append(
            f"the live UI expects read-model v{prev_ui} but the candidate snapshot is v{snapshot}; cached UI "
            "would reject it. Roll the UI back before rolling the snapshot back"
        )
    return problems


def gate_mixed_versions(
    previous: tuple[int, int] | None, candidate: tuple[int, int] | None, *, waive_cache_window: bool = False
) -> GateResult:
    if candidate is None:
        return GateResult("explorer-mixed-versions", True, "no Explorer in this artifact")
    problems = check_mixed_version_transition(previous, candidate, waive_cache_window=waive_cache_window)
    if problems:
        return GateResult("explorer-mixed-versions", False, "; ".join(problems))
    where = "first deployment" if previous is None else f"from UI v{previous[0]}/snapshot v{previous[1]}"
    waived = " (cache-window pairs waived)" if waive_cache_window else ""
    return GateResult(
        "explorer-mixed-versions",
        True,
        f"UI v{candidate[0]}/snapshot v{candidate[1]} readable {where}{waived}",
    )


def gate_explorer_compat(site_dir: Path, results_mount: str = "results") -> GateResult:
    module = load_publication_script("check_explorer_compat")
    explorer_dir = site_dir / results_mount
    snapshot = explorer_dir / "data" / "results.duckdb"
    argv = ["--schema-only", "--json", "--artifact", str(explorer_dir), "--db-path", str(snapshot)]
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(io.StringIO()):
        code = module.main(argv)
    try:
        report = json.loads(captured.getvalue())
    except json.JSONDecodeError:
        return GateResult("explorer-compat", False, f"check_explorer_compat exited {code} without a JSON report")
    if code == 0:
        return GateResult(
            "explorer-compat", True, f"read-model v{report.get('current_version')} bundle and snapshot valid"
        )
    errors: list[str] = []
    for section in ("database_check", "artifact_check"):
        errors.extend(report.get(section, {}).get("errors", []))
    for version, info in report.get("schema_checks", {}).items():
        errors.extend(f"{version}: {err}" for err in info.get("errors", []))
    return GateResult("explorer-compat", False, "; ".join(errors[:5]) or f"exit code {code}")


# ---------------------------------------------------------------------------
# Corpus, snapshot digest, validator parity
# ---------------------------------------------------------------------------


def gate_corpus_bijection(*, corpus_sha: str, bundles_dir: Path, snapshot: Path, ledger_seed: Path) -> GateResult:
    module = load_publication_script("check_corpus_bijection")
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            errors = module.check(
                accepted_ref=corpus_sha, bundles_dir=bundles_dir, artifact=snapshot, ledger_seed=ledger_seed
            )
    except module.BijectionError as exc:
        return GateResult("corpus-bijection", False, str(exc))
    if errors:
        return GateResult("corpus-bijection", False, "; ".join(errors[:3]))
    return GateResult("corpus-bijection", True, f"snapshot is 1:1 with corpus {corpus_sha[:12]}")


def gate_db_digest(candidate: Path, rebuild: Callable[[], Path]) -> GateResult:
    """The shipped snapshot must equal an independent rebuild from the same corpus."""
    module = load_publication_script("compare_db_digest")
    rebuilt = rebuild()
    findings = module.compare_databases(
        rebuilt, candidate, tuple(module.DEFAULT_EXCLUDE_COLUMNS), module.DEFAULT_FLOAT_SIG_DIGITS
    )
    if findings:
        return GateResult("snapshot-digest", False, "; ".join(findings[:3]))
    digest = module.canonical_digest(candidate, tuple(module.DEFAULT_EXCLUDE_COLUMNS), module.DEFAULT_FLOAT_SIG_DIGITS)
    return GateResult(
        "snapshot-digest", True, f"independent rebuild is digest-equivalent ({digest[:16]})", {"digest": digest}
    )


def gate_validator_parity(*, base_sha: str | None, trunk_sha: str) -> GateResult:
    """Re-validate every corpus bundle changed since the last deployment."""
    module = load_publication_script("validator_parity")
    base = base_sha or EMPTY_TREE_SHA
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        code = module.main(["--base-sha", base, "--merge-sha", trunk_sha, "--head-sha", trunk_sha])
    tail = captured.getvalue().strip().splitlines()[-1:] or [""]
    if code != 0:
        return GateResult("validator-parity", False, f"exit {code}: {tail[0]}")
    return GateResult("validator-parity", True, tail[0] or "changed bundles validate")


# ---------------------------------------------------------------------------
# Cross-route links
# ---------------------------------------------------------------------------

_LINK_ATTRS = {("a", "href"), ("link", "href"), ("script", "src"), ("img", "src"), ("source", "src"), ("iframe", "src")}
_SKIPPED_SCHEMES = ("http", "https", "mailto", "tel", "javascript", "data", "blob", "ftp")


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value and (tag, name) in _LINK_ATTRS:
                self.links.append(value)


def _resolve_link(page_rel: str, raw: str) -> str | None:
    """Site-relative target of ``raw`` as seen from ``page_rel``; ``None`` if external or not a path."""
    raw = raw.strip()
    if not raw or raw.startswith("#") or raw.startswith("//"):
        return None
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return None
    path = unquote(parts.path)
    if not path:
        return None
    base = PurePosixPath("/" + page_rel).parent
    joined = PurePosixPath(path) if path.startswith("/") else base / path
    resolved: list[str] = []
    for part in joined.parts:
        if part in ("/", "."):
            continue
        if part == "..":
            if not resolved:
                return ".."  # escapes the site root
            resolved.pop()
        else:
            resolved.append(part)
    rel = "/".join(resolved)
    return rel + "/" if path.endswith("/") and rel else rel


def owning_mount(rel: str, mounts: Iterable[str]) -> str:
    """The most specific route mount containing site-relative path ``rel``."""
    url = "/" + rel
    best = "/"
    for mount in mounts:
        if mount != "/" and url.startswith(mount) and len(mount) > len(best):
            best = mount
    return best


def _target_exists(site_dir: Path, rel: str) -> bool:
    if rel == "..":
        return False
    if rel == "":
        return (site_dir / "index.html").is_file()
    target = site_dir / rel.rstrip("/")
    if target.is_file():
        return not rel.endswith("/")
    return (target / "index.html").is_file()


def check_links(site_dir: Path, mounts: Sequence[str], spa_mounts: Sequence[str] = ()) -> tuple[list[str], list[str]]:
    """Return ``(cross_route_broken, intra_route_broken)`` internal links.

    A link is cross-route when the page that contains it and the path it points at
    belong to different routes. Links into an SPA route resolve through its 404
    fallback, so they are valid whenever that route's entry page exists.
    """
    cross: list[str] = []
    intra: list[str] = []
    seen: set[tuple[str, str]] = set()
    for page in sorted(site_dir.rglob("*.html")):
        page_rel = page.relative_to(site_dir).as_posix()
        collector = _LinkCollector()
        try:
            collector.feed(page.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 - a malformed page is reported by other gates, not this one
            continue
        source_mount = owning_mount(page_rel, mounts)
        for raw in collector.links:
            target = _resolve_link(page_rel, raw)
            if target is None or (page_rel, target) in seen:
                continue
            seen.add((page_rel, target))
            if _target_exists(site_dir, target):
                continue
            target_mount = owning_mount(target, mounts)
            if target_mount in spa_mounts and _target_exists(site_dir, target_mount.strip("/")):
                continue
            message = f"/{page_rel} -> {raw}"
            (cross if target_mount != source_mount else intra).append(message)
    return cross, intra


def gate_links(site_dir: Path, mounts: Sequence[str], spa_mounts: Sequence[str] = ()) -> GateResult:
    cross, intra = check_links(site_dir, mounts, spa_mounts)
    if cross:
        return GateResult(
            "cross-route-links",
            False,
            f"{len(cross)} broken cross-route link(s): " + "; ".join(cross[:5]),
            {"cross": cross, "intra": intra},
        )
    note = f"; {len(intra)} intra-route broken link(s) not gating" if intra else ""
    return GateResult(
        "cross-route-links", True, "all cross-route links resolve" + note, {"cross": cross, "intra": intra}
    )
