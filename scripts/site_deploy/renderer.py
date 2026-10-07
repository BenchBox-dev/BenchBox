from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

SPHINX = "sphinx"
ASTRO = "astro"
RENDERERS = (SPHINX, ASTRO)
POLICY_AUTO = "auto"
POLICIES = (POLICY_AUTO, SPHINX)

ASTRO_REQUIRED_FILES = (
    "website/package.json",
    "website/package-lock.json",
    "website/astro.config.ts",
    "website/src/converter/cli.ts",
    "website/src/pages/index.astro",
    "website/src/pages/404.astro",
    "website/src/pages/blog.astro",
    "make/documentation.mk",
)
ASTRO_REQUIRED_DIRS = (
    "website/src/pages/docs",
    "website/src/pages/blog",
    "website/src/pages/prompts",
)
SITE_BUILD_RECIPE = ("make/documentation.mk", re.compile(r"^site-build:", re.MULTILINE))
LEGACY_SOURCE_ROOT = "docs/"
LEGACY_SOURCE_SUFFIXES = (".rst",)


class RendererError(RuntimeError):
    pass


@dataclass(frozen=True)
class Readiness:
    ready: bool
    missing: tuple[str, ...] = ()
    legacy_sources: tuple[str, ...] = ()

    def summary(self) -> str:
        if self.ready:
            return "the release tree carries website/ and no legacy docs sources"
        parts = []
        if self.missing:
            parts.append(f"missing {', '.join(self.missing)}")
        if self.legacy_sources:
            parts.append(f"{len(self.legacy_sources)} unmigrated docs sources (first: {self.legacy_sources[0]})")
        return "; ".join(parts)


@dataclass(frozen=True)
class Selection:
    renderer: str
    policy: str
    reason: str
    readiness: Readiness = field(default_factory=lambda: Readiness(False))

    def to_dict(self) -> dict[str, object]:
        return {
            "renderer": self.renderer,
            "policy": self.policy,
            "reason": self.reason,
            "astro_ready": self.readiness.ready,
            "missing": list(self.readiness.missing),
            "legacy_sources": len(self.readiness.legacy_sources),
        }


def astro_readiness(paths: Iterable[str], read_text: Callable[[str], str | None]) -> Readiness:
    present = set(paths)
    missing = [name for name in ASTRO_REQUIRED_FILES if name not in present]
    missing += [f"{name}/" for name in ASTRO_REQUIRED_DIRS if not any(p.startswith(f"{name}/") for p in present)]
    recipe_path, recipe = SITE_BUILD_RECIPE
    if recipe_path in present and not recipe.search(read_text(recipe_path) or ""):
        missing.append(f"{recipe_path}:site-build")
    legacy = tuple(
        sorted(p for p in present if p.startswith(LEGACY_SOURCE_ROOT) and p.endswith(LEGACY_SOURCE_SUFFIXES))
    )
    return Readiness(ready=not missing and not legacy, missing=tuple(missing), legacy_sources=legacy)


def select(policy: str, readiness: Readiness) -> Selection:
    if policy not in POLICIES:
        raise RendererError(f"renderer policy {policy!r} is not one of {POLICIES}")
    if policy == SPHINX:
        return Selection(SPHINX, policy, "the routes manifest holds every route on sphinx", readiness)
    if readiness.ready:
        return Selection(ASTRO, policy, f"astro for every route: {readiness.summary()}", readiness)
    return Selection(SPHINX, policy, f"sphinx for every route: {readiness.summary()}", readiness)


def _git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True, check=False)


def tree_paths(repo_dir: Path, commit: str) -> list[str]:
    result = _git(repo_dir, "ls-tree", "-r", "--name-only", "-z", commit)
    if result.returncode != 0:
        raise RendererError(f"cannot list the tree of {commit}: {result.stderr.strip()}")
    return [path for path in result.stdout.split("\0") if path]


def tree_text(repo_dir: Path, commit: str, path: str) -> str | None:
    result = _git(repo_dir, "show", f"{commit}:{path}")
    return result.stdout if result.returncode == 0 else None


def readiness_at(repo_dir: Path, commit: str) -> Readiness:
    return astro_readiness(tree_paths(repo_dir, commit), lambda path: tree_text(repo_dir, commit, path))


def select_for_commit(policy: str, repo_dir: Path, commit: str) -> Selection:
    return select(policy, readiness_at(repo_dir, commit))


def require_trunk_ready(selection: Selection, trunk: Callable[[], Readiness], trunk_label: str) -> Selection:
    if selection.renderer != ASTRO:
        return selection
    readiness = trunk()
    if not readiness.ready:
        raise RendererError(
            f"the release tree is ready for astro but trunk {trunk_label} is not ({readiness.summary()}); "
            "trunk routes would need sphinx, and one artifact never mixes renderers"
        )
    return selection


def select_for_commits(policy: str, repo_dir: Path, release_commit: str, trunk_commit: str) -> Selection:
    selection = select_for_commit(policy, repo_dir, release_commit)
    return require_trunk_ready(selection, lambda: readiness_at(repo_dir, trunk_commit), trunk_commit)
