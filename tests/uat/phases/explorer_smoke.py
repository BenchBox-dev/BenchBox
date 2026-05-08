"""Explorer-smoke phase: build Explorer data + run Playwright directly.

Mirrors the Results Explorer browser workflow entrypoint: install the
Explorer npm dependencies, build the static app, then invoke Playwright
with explicit projects. The UAT phase owns only the BenchBox data build;
Playwright remains the single browser-test runner.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXPLORER_DIR = REPO_ROOT / "results-explorer"


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


def build_argv(
    *,
    data_dir: Path | str = Path("results-data"),
    output_dir: Path | str = EXPLORER_DIR / "public" / "data",
    build_extra_args: tuple[str, ...] = (),
) -> list[str]:
    """Return the current `benchbox explorer build` argv."""
    return [
        "benchbox",
        "explorer",
        "build",
        "--data-dir",
        str(data_dir),
        "--output",
        str(output_dir),
        *build_extra_args,
    ]


def playwright_argv(playwright_browsers: tuple[str, ...] = ("chromium",)) -> list[str]:
    """Return the direct Playwright smoke argv for the requested browser projects."""
    argv = ["npx", "playwright", "test", "--grep", "@smoke"]
    for browser in playwright_browsers:
        argv.extend(["--project", browser])
    return argv


def run_explorer_smoke(
    *,
    bundles_dir: Path,
    output_dir: Path,
    log_dir: Path,
    build_extra_args: tuple[str, ...] = (),
    playwright_browsers: tuple[str, ...] = ("chromium",),
    playwright_fixture_dir: Path | None = None,
    runner=subprocess.run,
) -> ExplorerSmokeResult:
    """Build the explorer and run a browser smoke against the bundles in bundles_dir.

    Returns a skipped result if `node` is not on PATH (CI environments
    without browser tooling installed). Requested Playwright projects are
    passed through explicitly; if a project/browser is unavailable, the
    Playwright command fails loudly.
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

    build_log = log_dir / "explorer_build.log"
    smoke_log = log_dir / "playwright_smoke.log"
    data_dir = _prepare_data_dir(bundles_dir=bundles_dir, log_dir=log_dir)
    explorer_build_argv = build_argv(data_dir=data_dir, output_dir=output_dir, build_extra_args=build_extra_args)

    with build_log.open("w", encoding="utf-8") as fh:
        fh.write(f"# {' '.join(explorer_build_argv)}\n")
        build = runner(explorer_build_argv, stdout=fh, stderr=fh, check=False)
    if getattr(build, "returncode", 0) != 0:
        return ExplorerSmokeResult(
            build_returncode=build.returncode,
            smoke_returncode=0,
            build_log=build_log,
            smoke_log=None,
            skipped=False,
            skip_reason=None,
        )

    fixture_dir = playwright_fixture_dir or _default_playwright_fixture_dir(log_dir=log_dir)
    _stage_playwright_fixture_dir(source_dir=output_dir, fixture_dir=fixture_dir)
    smoke_returncode = _run_browser_smoke(
        smoke_log=smoke_log,
        data_dir=output_dir,
        fixture_dir=fixture_dir,
        playwright_browsers=playwright_browsers,
        runner=runner,
    )
    return ExplorerSmokeResult(
        build_returncode=build.returncode,
        smoke_returncode=smoke_returncode,
        build_log=build_log,
        smoke_log=smoke_log,
        skipped=False,
        skip_reason=None,
    )


def _prepare_data_dir(*, bundles_dir: Path, log_dir: Path) -> Path:
    if bundles_dir.name == "bundles":
        return bundles_dir.parent
    data_dir = log_dir / "explorer_input"
    data_dir.mkdir(parents=True, exist_ok=True)
    linked_bundles = data_dir / "bundles"
    if linked_bundles.exists() or linked_bundles.is_symlink():
        linked_bundles.unlink()
    linked_bundles.symlink_to(bundles_dir, target_is_directory=True)
    return data_dir


def _default_playwright_fixture_dir(*, log_dir: Path) -> Path:
    """Return the per-run fixture mount used by the UAT Playwright smoke."""
    return log_dir / "playwright-fixtures" / "data"


def _stage_playwright_fixture_dir(*, source_dir: Path, fixture_dir: Path) -> None:
    """Point Playwright's fixture mount at the UAT-built Explorer data.

    UAT builds a fresh data directory per run, so stage that directory into a
    per-run fixture mount and pass it to `serve-browser-tests.mjs` via
    `E2E_FIXTURE_DIR`.
    """
    source = source_dir.expanduser().resolve()
    fixture = fixture_dir.expanduser()
    if fixture.exists() or fixture.is_symlink():
        try:
            if fixture.resolve() == source:
                return
        except OSError:
            pass
        if fixture.is_symlink() or fixture.is_file():
            fixture.unlink()
        else:
            shutil.rmtree(fixture)
    fixture.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, fixture)


def _run_browser_smoke(
    *,
    smoke_log: Path,
    data_dir: Path,
    fixture_dir: Path,
    playwright_browsers: tuple[str, ...],
    runner,
) -> int:
    env = os.environ.copy()
    env["BENCHBOX_DATA_DIR"] = str(data_dir)
    env["E2E_FIXTURE_DIR"] = str(_absolute_path(fixture_dir))
    env.setdefault("E2E_PORT", str(_find_free_local_port()))
    commands = (
        ["npm", "ci"],
        ["npm", "run", "test:e2e:fixtures"],
        ["npm", "run", "build"],
        playwright_argv(playwright_browsers),
    )
    with smoke_log.open("w", encoding="utf-8") as fh:
        for argv in commands:
            fh.write(f"# (cd {EXPLORER_DIR} && {' '.join(argv)})\n")
            completed = runner(argv, cwd=EXPLORER_DIR, env=env, stdout=fh, stderr=fh, check=False)
            returncode = int(getattr(completed, "returncode", 0))
            if returncode != 0:
                return returncode
    return 0


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
