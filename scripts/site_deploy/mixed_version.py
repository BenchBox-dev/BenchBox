from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from scripts.site_deploy.renderer import ASTRO, RENDERERS, SPHINX

EXPECTED_VERSION_PATTERN = re.compile(r"^const EXPECTED_READ_MODEL_VERSION\s*=\s*(\d+);", re.MULTILINE)
SNAPSHOT_QUERY = "SELECT read_model_version FROM metadata LIMIT 1"
UI_SOURCE = Path("results-explorer/src/db.ts")

FORWARD = "forward"
ROLLBACK = "rollback"
PHASE_FULL = "full"
PHASE_UI_FIRST = "ui-first"


class VersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pair:
    name: str
    ui: int
    snapshot: int

    @property
    def ok(self) -> bool:
        return self.snapshot >= self.ui

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "ui": self.ui, "snapshot": self.snapshot, "ok": self.ok}


@dataclass(frozen=True)
class Versions:
    ui: int
    snapshot: int


def parse_ui_expected(source: str) -> int:
    matches = EXPECTED_VERSION_PATTERN.findall(source)
    if len(matches) != 1:
        raise VersionError(f"expected exactly one EXPECTED_READ_MODEL_VERSION constant, found {len(matches)}")
    return int(matches[0])


def ui_expected_from_tree(root: Path) -> int:
    path = root / UI_SOURCE
    if not path.is_file():
        raise VersionError(f"explorer UI source is missing: {path}")
    return parse_ui_expected(path.read_text(encoding="utf-8"))


def snapshot_version(database: Path) -> int:
    import duckdb

    if not database.is_file():
        raise VersionError(f"snapshot is missing: {database}")
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            row = connection.execute(SNAPSHOT_QUERY).fetchone()
    except duckdb.Error as exc:
        raise VersionError(f"snapshot version is unreadable in {database}: {exc}") from exc
    if row is None:
        raise VersionError(f"snapshot has no read_model_version row: {database}")
    return int(row[0])


def required_pairs(candidate: Versions, current: Versions | None, kind: str, phase: str = PHASE_FULL) -> list[Pair]:
    if kind == ROLLBACK and phase == PHASE_UI_FIRST:
        pairs = [Pair("restored-ui/composed-snapshot", candidate.ui, candidate.snapshot)]
    else:
        pairs = [Pair("candidate-ui/candidate-snapshot", candidate.ui, candidate.snapshot)]
    if current is None:
        return pairs
    if kind == FORWARD:
        pairs.append(Pair("deployed-ui/candidate-snapshot", current.ui, candidate.snapshot))
        return pairs
    pairs.append(Pair("restored-ui/current-snapshot", candidate.ui, current.snapshot))
    second = "current-ui/composed-snapshot" if phase == PHASE_UI_FIRST else "current-ui/restored-snapshot"
    pairs.append(Pair(second, current.ui, candidate.snapshot))
    return pairs


@dataclass(frozen=True)
class Evaluation:
    ok: bool
    pairs: list[Pair]
    plan: list[str]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "pairs": [pair.to_dict() for pair in self.pairs],
            "plan": self.plan,
            "reason": self.reason,
        }


def evaluate(candidate: Versions, current: Versions | None, kind: str, phase: str = PHASE_FULL) -> Evaluation:
    pairs = required_pairs(candidate, current, kind, phase)
    if kind == FORWARD:
        failed = [pair.name for pair in pairs if not pair.ok]
        if failed:
            return Evaluation(False, pairs, [], f"snapshot older than UI for: {failed}")
        return Evaluation(True, pairs, [PHASE_FULL], "every required pair has snapshot >= ui")
    internal = pairs[0]
    if not internal.ok:
        return Evaluation(False, pairs, [], "restored artifact pairs its UI with an older snapshot")
    if current is None:
        return Evaluation(True, pairs, [PHASE_FULL], "no current generation to order against")
    ui_first_possible = pairs[1].ok
    single_step = pairs[2].ok
    plan = [PHASE_FULL] if single_step else ([PHASE_UI_FIRST, PHASE_FULL] if ui_first_possible else [])
    if not plan:
        return Evaluation(False, pairs, [], "no rollback order keeps snapshot >= ui at every step")
    if phase == PHASE_FULL and not single_step:
        return Evaluation(False, pairs, plan, "restore the UI first: run the ui-first phase before the full phase")
    if phase == PHASE_UI_FIRST and not ui_first_possible:
        return Evaluation(False, pairs, plan, "restored UI is newer than the current snapshot")
    return Evaluation(True, pairs, plan, f"rollback phase {phase} is safe")


RENDERER_MARKERS: dict[str, tuple[re.Pattern[bytes], ...]] = {
    SPHINX: (re.compile(rb"""(?:src|href)=["'][^"']*_static/documentation_options\.js"""),),
    ASTRO: (
        re.compile(rb"""(?:src|href)=["']/_astro/"""),
        re.compile(rb"""<meta[^>]+name=["']generator["'][^>]+content=["']Astro"""),
    ),
}
RENDERER_EXEMPT_PREFIXES = ("results/",)
ASTRO_ASSET_DIR = "_astro"
EXAMPLE_LIMIT = 3


class RendererMixError(VersionError):
    pass


def page_renderer(content: bytes) -> str | None:
    found = {name for name, markers in RENDERER_MARKERS.items() if any(marker.search(content) for marker in markers)}
    if len(found) > 1:
        return "mixed"
    return next(iter(found), None)


def tree_renderers(tree: Path, exempt: Iterable[str] = RENDERER_EXEMPT_PREFIXES) -> dict[str, list[str]]:
    exempt = tuple(exempt)
    pages: dict[str, list[str]] = {}
    for path in sorted(tree.rglob("*.html")):
        relative = path.relative_to(tree).as_posix()
        if not path.is_file() or relative.startswith(exempt):
            continue
        kind = page_renderer(path.read_bytes())
        if kind is not None:
            pages.setdefault(kind, []).append(relative)
    if (tree / ASTRO_ASSET_DIR).is_dir():
        pages.setdefault(ASTRO, []).append(f"{ASTRO_ASSET_DIR}/")
    return pages


def require_single_renderer(tree: Path, expected: str) -> dict[str, int]:
    if expected not in RENDERERS:
        raise RendererMixError(f"unknown renderer {expected!r}; expected one of {RENDERERS}")
    pages = tree_renderers(tree)
    foreign = {kind: names for kind, names in pages.items() if kind != expected}
    if foreign:
        detail = "; ".join(
            f"{kind}: {len(names)} (first: {', '.join(names[:EXAMPLE_LIMIT])})"
            for kind, names in sorted(foreign.items())
        )
        raise RendererMixError(f"artifact selected for {expected} also carries other renderer output: {detail}")
    return {kind: len(names) for kind, names in pages.items()}
