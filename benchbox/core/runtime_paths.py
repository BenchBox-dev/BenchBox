"""Centralized runtime path resolution for BenchBox components.

This module provides shared path resolution with clear precedence rules:
explicit override > environment variable > project default.

It is intentionally interface-agnostic so both CLI internals and MCP internals
can reuse the same logic without coupling their user-facing flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_BENCHMARK_RUNS_ROOT = Path("benchmark_runs")
DEFAULT_RESULTS_SUBDIR = "results"
DEFAULT_CHARTS_SUBDIR = "charts"


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved benchmark run root and derived subdirectories."""

    benchmark_runs_root: Path
    results_dir: Path
    charts_dir: Path


def _normalize_path(path: str | Path) -> Path:
    """Normalize an explicit/configured path without forcing absolute resolution."""
    return Path(path).expanduser()


def _read_env_path(env: Mapping[str, str] | None, key: str) -> Path | None:
    """Return a normalized path from an environment variable if set/non-empty."""
    env_map = env if env is not None else {}
    value = env_map.get(key)
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return _normalize_path(stripped)


def default_benchmark_runs_root(start: Path | None = None) -> Path:
    """Return the worktree-sibling default, or a cwd-local root outside Git."""
    origin = Path.cwd() if start is None else Path(start).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / ".git").exists():
            return candidate.parent / DEFAULT_BENCHMARK_RUNS_ROOT
    return origin / DEFAULT_BENCHMARK_RUNS_ROOT


def resolve_benchmark_runs_root(
    explicit_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    env_var: str = "BENCHBOX_OUTPUT_DIR",
) -> Path:
    """Resolve benchmark_runs root with precedence explicit > env > default."""
    if explicit_root is not None:
        return _normalize_path(explicit_root)

    env_root = _read_env_path(env, env_var)
    if env_root is not None:
        return env_root

    return default_benchmark_runs_root()


def resolve_results_dir(
    explicit_results_dir: str | Path | None = None,
    *,
    benchmark_runs_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    results_env_var: str = "BENCHBOX_RESULTS_DIR",
    benchmark_runs_env_var: str = "BENCHBOX_OUTPUT_DIR",
) -> Path:
    """Resolve results directory with precedence explicit > env > derived default."""
    if explicit_results_dir is not None:
        return _normalize_path(explicit_results_dir)

    env_results = _read_env_path(env, results_env_var)
    if env_results is not None:
        return env_results

    runs_root = resolve_benchmark_runs_root(
        explicit_root=benchmark_runs_root,
        env=env,
        env_var=benchmark_runs_env_var,
    )
    return runs_root / DEFAULT_RESULTS_SUBDIR


def resolve_charts_dir(
    explicit_charts_dir: str | Path | None = None,
    *,
    benchmark_runs_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    charts_env_var: str = "BENCHBOX_CHARTS_DIR",
    benchmark_runs_env_var: str = "BENCHBOX_OUTPUT_DIR",
) -> Path:
    """Resolve charts directory with precedence explicit > env > derived default."""
    if explicit_charts_dir is not None:
        return _normalize_path(explicit_charts_dir)

    env_charts = _read_env_path(env, charts_env_var)
    if env_charts is not None:
        return env_charts

    runs_root = resolve_benchmark_runs_root(
        explicit_root=benchmark_runs_root,
        env=env,
        env_var=benchmark_runs_env_var,
    )
    return runs_root / DEFAULT_CHARTS_SUBDIR


def resolve_runtime_paths(
    *,
    benchmark_runs_root: str | Path | None = None,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimePaths:
    """Resolve benchmark runs root, results dir, and charts dir consistently."""
    resolved_runs_root = resolve_benchmark_runs_root(explicit_root=benchmark_runs_root, env=env)
    resolved_results = resolve_results_dir(
        explicit_results_dir=results_dir,
        benchmark_runs_root=resolved_runs_root,
        env=env,
    )
    resolved_charts = resolve_charts_dir(
        explicit_charts_dir=charts_dir,
        benchmark_runs_root=resolved_runs_root,
        env=env,
    )

    return RuntimePaths(
        benchmark_runs_root=resolved_runs_root,
        results_dir=resolved_results,
        charts_dir=resolved_charts,
    )
