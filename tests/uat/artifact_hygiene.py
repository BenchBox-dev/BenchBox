"""Local-artifact hygiene guardrails for external-root benchmark runs.

Background — the 2026-06-01 incident: a corpus run launched from a pool
worktree with ``BENCHBOX_OUTPUT_DIR`` pointed at an external root
(``~/Developer/benchmark_runs``) still accumulated ~4.2 GB of datagen
artifacts under the *worktree-local* ``benchmark_runs/datagen/``. The
output-root propagation fix (PR #780) means external-root runs should never
write into the local ``benchmark_runs/`` again; these helpers detect and
report loudly if that invariant is ever broken.

The guardrails are *report-only*. They snapshot ``cwd/benchmark_runs`` before
a run and assert it did not grow afterwards. They never delete or move
artifacts — surfacing the unexpected local path (and the external root that
should have received the writes) is the entire job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from benchbox.core.runtime_paths import DEFAULT_BENCHMARK_RUNS_ROOT

LOCAL_RUNS_DIRNAME = str(DEFAULT_BENCHMARK_RUNS_ROOT)


class LocalArtifactGrowthError(AssertionError):
    """Raised when ``cwd/benchmark_runs`` grows during an external-root run."""


def dir_size_bytes(path: Path) -> int:
    """Return the total size in bytes of all files under ``path`` (0 if absent)."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            # A file vanishing mid-walk is not a hygiene violation; skip it.
            continue
    return total


def local_runs_root(cwd: Path | str | None = None) -> Path:
    """Return the worktree-local ``benchmark_runs/`` root for ``cwd``."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / LOCAL_RUNS_DIRNAME


def _normalize(path: str | Path) -> Path:
    return Path(path).expanduser()


def configured_external_root(
    env: Mapping[str, str] | None = None,
    *,
    cwd: Path | str | None = None,
    output: str | Path | None = None,
) -> Path | None:
    """Resolve a configured output root iff it points *outside* ``cwd``.

    An external root is "configured" when ``--output`` (``output``) is given
    or ``BENCHBOX_OUTPUT_DIR`` is set to a non-empty value. The guardrail only
    applies when that root resolves to a location outside the current working
    directory — ordinary default local runs (no env/flag, or a root inside the
    worktree) return ``None`` so they are never blocked.
    """
    env_map = os.environ if env is None else env
    base = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()

    candidate: Path | None = None
    if output is not None and str(output).strip():
        candidate = _normalize(output)
    else:
        raw = env_map.get("BENCHBOX_OUTPUT_DIR")
        if raw is not None and raw.strip():
            candidate = _normalize(raw.strip())

    if candidate is None:
        return None

    resolved = candidate if candidate.is_absolute() else (base / candidate)
    resolved = resolved.resolve()
    if resolved == base or resolved.is_relative_to(base):
        # Output root lives inside the worktree — this is a local run.
        return None
    return resolved


@dataclass(frozen=True)
class LocalRunsSnapshot:
    """Pre-run state of the worktree-local ``benchmark_runs/`` tree."""

    root: Path
    total_bytes: int
    file_sizes: dict[str, int]
    # Per-file identity ``(mtime_ns, inode)`` so a same-size rewrite is still detected:
    # a generator that truncates and recreates a deterministic file to the same length,
    # or a stale local leak re-emitted byte-for-byte, leaves the size unchanged but
    # still represents a local write that the external-root run must not perform.
    file_fingerprints: dict[str, tuple[int, int]]


def snapshot_local_runs(cwd: Path | str | None = None) -> LocalRunsSnapshot:
    """Capture per-file size and identity under ``cwd/benchmark_runs`` for later comparison."""
    root = local_runs_root(cwd)
    file_sizes: dict[str, int] = {}
    file_fingerprints: dict[str, tuple[int, int]] = {}
    if root.exists():
        for child in root.rglob("*"):
            try:
                if child.is_file() and not child.is_symlink():
                    stat = child.stat()
                    file_sizes[str(child)] = stat.st_size
                    file_fingerprints[str(child)] = (stat.st_mtime_ns, stat.st_ino)
            except OSError:
                continue
    return LocalRunsSnapshot(
        root=root,
        total_bytes=sum(file_sizes.values()),
        file_sizes=file_sizes,
        file_fingerprints=file_fingerprints,
    )


def _changed_entries(before: LocalRunsSnapshot, after: LocalRunsSnapshot) -> dict[str, int]:
    """Return paths written during the run, mapped to their byte delta.

    A path is reported when it is new, when its size changed (grew or shrank), or when it
    was rewritten at the same size (mtime or inode differs). Same-size rewrites carry a
    delta of 0 but are still violations: any local write under an external-root run is a
    propagation regression, so this no longer reports only files that grew.
    """
    changed: dict[str, int] = {}
    for path, size in after.file_sizes.items():
        before_size = before.file_sizes.get(path)
        if before_size is None:
            changed[path] = size  # new file
        elif size != before_size:
            changed[path] = size - before_size  # grew or shrank
        elif after.file_fingerprints.get(path) != before.file_fingerprints.get(path):
            changed[path] = 0  # same-size rewrite
    return changed


def _format_violation(
    *,
    local_root: Path,
    external_root: Path,
    grew_by: int,
    grown: Mapping[str, int],
) -> str:
    """Build a failure message naming the local path AND the external root."""
    lines = [
        "Local benchmark_runs/ was written during an external-root run (output-root propagation regression — see PR #780).",
        f"  unexpected local path: {local_root}",
        f"  configured external root: {external_root}",
        f"  change: {grew_by} bytes across {len(grown)} file(s) (includes same-size rewrites)",
    ]
    # Surface the largest offenders so the operator can locate the leak fast;
    # datagen is the historical culprit so it tends to dominate this list.
    top = sorted(grown.items(), key=lambda kv: kv[1], reverse=True)[:5]
    for path, delta in top:
        lines.append(f"    + {delta} bytes: {path}")
    lines.append("Guardrail is report-only; no artifacts were moved or deleted.")
    return "\n".join(lines)


def assert_no_local_growth(
    before: LocalRunsSnapshot,
    external_root: Path,
    *,
    cwd: Path | str | None = None,
) -> None:
    """Raise :class:`LocalArtifactGrowthError` if local ``benchmark_runs`` was written.

    Compares ``before`` against a fresh snapshot of the same root. When an
    external root is configured, *any* write under the worktree-local
    ``benchmark_runs/`` is a violation — whether it grows a file, adds one, or
    rewrites one in place at the same size — because the writes should have gone
    to ``external_root`` instead.
    """
    after = snapshot_local_runs(cwd if cwd is not None else before.root.parent)
    changed = _changed_entries(before, after)
    grew_by = after.total_bytes - before.total_bytes
    if changed or grew_by > 0:
        raise LocalArtifactGrowthError(
            _format_violation(
                local_root=before.root,
                external_root=external_root,
                grew_by=max(grew_by, sum(changed.values())),
                grown=changed,
            )
        )


def audit_local_datagen(
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    output: str | Path | None = None,
    threshold_bytes: int = 0,
) -> str | None:
    """Audit the live worktree for the incident shape; return a message or None.

    Used by the preflight/UAT gate. When no external root is configured the
    audit is a no-op (returns ``None``) so default local runs are never
    blocked. When an external root *is* configured, the worktree-local
    ``benchmark_runs/datagen`` is measured: anything above ``threshold_bytes``
    is reported as a violation naming both the local path and the external
    root. This never deletes or moves anything.
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    external_root = configured_external_root(env, cwd=base, output=output)
    if external_root is None:
        return None

    datagen = local_runs_root(base) / "datagen"
    size = dir_size_bytes(datagen)
    if size <= threshold_bytes:
        return None

    lines = [
        "Local benchmark_runs/datagen holds artifacts while an external root is configured.",
        f"  unexpected local path: {datagen}",
        f"  configured external root: {external_root}",
        f"  size: {size} bytes (threshold {threshold_bytes} bytes)",
        "Datagen for external-root runs must land under the external root.",
        "Guardrail is report-only; inspect and relocate manually if intended.",
    ]
    return "\n".join(lines)


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m tests.uat.artifact_hygiene",
        description=(
            "Audit the worktree-local benchmark_runs/datagen for the external-root "
            "artifact-leak incident shape. No-op unless an external root is configured."
        ),
    )
    parser.add_argument("--cwd", default=None, help="Working directory to audit (default: cwd).")
    parser.add_argument("--output", default=None, help="Explicit --output root to treat as external.")
    parser.add_argument(
        "--threshold-bytes",
        type=int,
        default=0,
        help="Local datagen byte budget before the gate fails (default: 0).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the preflight/UAT hygiene gate."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    message = audit_local_datagen(
        cwd=args.cwd,
        output=args.output,
        threshold_bytes=args.threshold_bytes,
    )
    if message is None:
        root = configured_external_root(cwd=args.cwd, output=args.output)
        if root is None:
            print("artifact-hygiene: no external root configured; skipping local datagen audit.")
        else:
            print(f"artifact-hygiene: OK — no local datagen growth (external root {root}).")
        return 0
    print(message)
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised via the make gate
    raise SystemExit(main())
