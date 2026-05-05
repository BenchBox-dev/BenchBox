"""Explorer-smoke phase: build the explorer + run Playwright.

Mirrors the W6 step of the 2026-05-02 retrospective. Reuses
`benchbox explorer build` and
`results-explorer/scripts/serve-browser-tests.mjs` exactly — the
parent TODO's anti_pattern forbids reimplementing the explorer build.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PLAYWRIGHT_ENTRY = REPO_ROOT / "results-explorer" / "scripts" / "serve-browser-tests.mjs"


@dataclass(frozen=True)
class ExplorerSmokeResult:
    build_returncode: int
    smoke_returncode: int
    build_log: Path | None
    smoke_log: Path | None
    skipped: bool
    skip_reason: str | None

    def exit_code(self) -> int:
        if self.skipped:
            return 0
        if self.build_returncode != 0:
            return self.build_returncode
        return self.smoke_returncode


def has_node() -> bool:
    return shutil.which("node") is not None


def playwright_entry_exists() -> bool:
    return PLAYWRIGHT_ENTRY.exists()


def run_explorer_smoke(
    *,
    bundles_dir: Path,
    output_dir: Path,
    log_dir: Path,
    build_extra_args: tuple[str, ...] = (),
    playwright_browsers: tuple[str, ...] = ("chromium",),
    runner=subprocess.run,
) -> ExplorerSmokeResult:
    """Build the explorer and run a browser smoke against the bundles in bundles_dir.

    Returns a skipped result if `node` is not on PATH (CI environments
    without browser tooling installed). The 2026-05-02 sweep ran this
    locally only; the framework matches that scope.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    if not has_node():
        return ExplorerSmokeResult(
            build_returncode=0,
            smoke_returncode=0,
            build_log=None,
            smoke_log=None,
            skipped=True,
            skip_reason="node not on PATH",
        )
    if not playwright_entry_exists():
        return ExplorerSmokeResult(
            build_returncode=0,
            smoke_returncode=0,
            build_log=None,
            smoke_log=None,
            skipped=True,
            skip_reason=f"playwright entry not found at {PLAYWRIGHT_ENTRY}",
        )

    build_log = log_dir / "explorer_build.log"
    smoke_log = log_dir / "playwright_smoke.log"
    build_argv = [
        sys.executable,
        "-m",
        "benchbox.cli",
        "explorer",
        "build",
        "--bundles-dir",
        str(bundles_dir),
        "--output",
        str(output_dir),
        *build_extra_args,
    ]
    smoke_argv = [
        "node",
        str(PLAYWRIGHT_ENTRY),
        "--data-dir",
        str(output_dir),
        "--browsers",
        ",".join(playwright_browsers),
    ]

    with build_log.open("w") as fh:
        build = runner(build_argv, stdout=fh, stderr=fh, check=False)
    if getattr(build, "returncode", 0) != 0:
        return ExplorerSmokeResult(
            build_returncode=build.returncode,
            smoke_returncode=0,
            build_log=build_log,
            smoke_log=None,
            skipped=False,
            skip_reason=None,
        )

    with smoke_log.open("w") as fh:
        smoke = runner(smoke_argv, stdout=fh, stderr=fh, check=False)
    return ExplorerSmokeResult(
        build_returncode=build.returncode,
        smoke_returncode=smoke.returncode,
        build_log=build_log,
        smoke_log=smoke_log,
        skipped=False,
        skip_reason=None,
    )
