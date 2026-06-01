"""Explorer-smoke phase: validate the packaged corpus, then delegate the browser smoke.

The phase always runs a cheap, no-Node corpus contract over the packaged
bundles. The heavy path only runs when the explorer build inputs are present on
the branch (they live on `develop`, not `main`): UAT builds the BenchBox data,
installs npm dependencies, then hands off to the Results Explorer's
`uat-external-corpus-smoke` script, which owns the static build and the
external-corpus Playwright run. UAT no longer issues `npm run build` /
`npx playwright` itself.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tests.uat.phases import PhaseResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXPLORER_DIR = REPO_ROOT / "results-explorer"
EXPLORER_PUBLISH_SCRIPT = REPO_ROOT / "_project" / "scripts" / "explorer_publish.py"
EXTERNAL_CORPUS_SMOKE_TAG = "@uat-external-corpus"
# Single delegated entrypoint owned by the Results Explorer: it builds the
# static app and runs the external-corpus Playwright grep. UAT forwards browser
# `--project` flags via `npm run <script> -- ...` rather than re-issuing
# npm/build/playwright itself (see results-explorer/package.json).
EXPLORER_SMOKE_NPM_SCRIPT = "uat-external-corpus-smoke"
EXPLORER_BUILD_ARGV = (
    "uv",
    "run",
    "--",
    "python",
    "_project/scripts/explorer_publish.py",
    "build",
)


@dataclass(frozen=True)
class ExplorerSmokeResult(PhaseResult):
    build_returncode: int
    smoke_returncode: int
    build_log: Path | None
    smoke_log: Path | None
    skipped: bool
    skip_reason: str | None

    def exit_code(self) -> int:
        if self.aborted:
            return 2
        if self.skipped:
            return 0
        if self.build_returncode != 0:
            return self.build_returncode
        return self.smoke_returncode


def has_node() -> bool:
    return shutil.which("node") is not None


def explorer_present() -> bool:
    """Return True only when both explorer build inputs exist on this branch.

    The phase ships on `main`, but `_project/scripts/explorer_publish.py` and
    `results-explorer/` live only on `develop`. Without this guard a clean
    `main` checkout false-gates: the heavy build shells out to files that are
    not there. When absent we skip-with-reason instead of hard-failing.
    """
    return EXPLORER_PUBLISH_SCRIPT.is_file() and (EXPLORER_DIR / "package.json").is_file()


def _explorer_absent_reason() -> str:
    missing = [
        str(path)
        for path, present in (
            (EXPLORER_PUBLISH_SCRIPT, EXPLORER_PUBLISH_SCRIPT.is_file()),
            (EXPLORER_DIR / "package.json", (EXPLORER_DIR / "package.json").is_file()),
        )
        if not present
    ]
    return "explorer assets absent on this branch: " + ", ".join(missing)


def build_argv(
    *,
    data_dir: Path | str = Path("results-data"),
    output_dir: Path | str = EXPLORER_DIR / "public" / "data",
    build_extra_args: tuple[str, ...] = (),
) -> list[str]:
    """Return the current Explorer publisher argv."""
    return [
        *EXPLORER_BUILD_ARGV,
        "--data-dir",
        str(data_dir),
        "--output",
        str(output_dir),
        *build_extra_args,
    ]


def smoke_npm_argv(playwright_browsers: tuple[str, ...] = ("chromium",)) -> list[str]:
    """Return the delegated Results Explorer smoke command for the requested projects.

    UAT does not own build/playwright mechanics: it calls the explorer's
    `uat-external-corpus-smoke` script (which builds and runs the
    external-corpus grep) and forwards browser `--project` flags through npm's
    `--` argument passthrough.
    """
    argv = ["npm", "run", EXPLORER_SMOKE_NPM_SCRIPT, "--"]
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

    Always runs the cheap, no-Node corpus contract on the packaged bundles.
    Returns a skipped result (never a hard failure) when the explorer build
    inputs are absent on this branch, or when `node` is not on PATH. Requested
    Playwright projects are passed through explicitly; if a project/browser is
    unavailable, the Playwright command fails loudly.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    # Minimal always-on gate: validate the packaged corpus regardless of
    # explorer presence or Node availability. This is the check that has value
    # on a clean `main` checkout where the heavy browser path cannot run.
    resolved_bundles_dir = _resolve_bundles_dir(bundles_dir)
    contract = _validate_external_corpus(bundles_dir=resolved_bundles_dir)
    (log_dir / "explorer_corpus_contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not explorer_present():
        return ExplorerSmokeResult(
            phase="explorer_smoke",
            build_returncode=0,
            smoke_returncode=0,
            build_log=None,
            smoke_log=None,
            skipped=True,
            skip_reason=_explorer_absent_reason(),
        )
    if not has_node():
        return ExplorerSmokeResult(
            phase="explorer_smoke",
            build_returncode=0,
            smoke_returncode=0,
            build_log=None,
            smoke_log=None,
            skipped=True,
            skip_reason="node not on PATH",
        )

    build_log = log_dir / "explorer_build.log"
    smoke_log = log_dir / "playwright_smoke.log"
    data_dir = _prepare_data_dir(bundles_dir=resolved_bundles_dir, log_dir=log_dir)
    explorer_build_argv = build_argv(data_dir=data_dir, output_dir=output_dir, build_extra_args=build_extra_args)

    with build_log.open("w", encoding="utf-8") as fh:
        fh.write(f"# {' '.join(explorer_build_argv)}\n")
        build = runner(explorer_build_argv, stdout=fh, stderr=fh, check=False)
    if getattr(build, "returncode", 0) != 0:
        return ExplorerSmokeResult(
            phase="explorer_smoke",
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
        phase="explorer_smoke",
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


def _resolve_bundles_dir(path: Path) -> Path:
    """Accept either DATA_DIR/bundles, a bare bundles dir, or a package root."""
    if path.name == "bundles":
        return path
    if (path / "bundle").is_dir():
        return path / "bundle"
    if (path / "bundles").is_dir():
        return path / "bundles"
    return path


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
        smoke_npm_argv(playwright_browsers),
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


def _validate_external_corpus(*, bundles_dir: Path) -> dict[str, object]:
    """Fail early when UAT hands Explorer smoke an empty or malformed corpus."""
    bundle_files = sorted(
        path
        for path in bundles_dir.rglob("*.json")
        if not path.name.endswith((".manifest.json", ".plans.json", ".tuning.json"))
    )
    if not bundle_files:
        raise RuntimeError(f"Explorer smoke corpus has no result bundles: {bundles_dir}")

    benchmarks: set[str] = set()
    platforms: set[str] = set()
    query_count = 0
    checked = 0
    errors: list[str] = []
    for path in bundle_files:
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON ({exc})")
            continue
        checked += 1
        benchmark = bundle.get("benchmark") if isinstance(bundle, dict) else None
        platform = bundle.get("platform") if isinstance(bundle, dict) else None
        run = bundle.get("run") if isinstance(bundle, dict) else None
        benchmark_id = benchmark.get("id") if isinstance(benchmark, dict) else None
        scale_factor = benchmark.get("scale_factor") if isinstance(benchmark, dict) else None
        platform_name = platform.get("name") if isinstance(platform, dict) else None
        run_id = run.get("id") if isinstance(run, dict) else None
        if not benchmark_id:
            errors.append(f"{path}: missing benchmark.id")
        else:
            benchmarks.add(str(benchmark_id))
        if scale_factor is None:
            errors.append(f"{path}: missing benchmark.scale_factor")
        if not platform_name:
            errors.append(f"{path}: missing platform.name")
        else:
            platforms.add(str(platform_name))
        if not run_id:
            errors.append(f"{path}: missing run.id")
        queries = bundle.get("queries") if isinstance(bundle, dict) else None
        if isinstance(queries, list):
            query_count += len(queries)

    if errors:
        raise RuntimeError("Explorer smoke corpus contract failed:\n  - " + "\n  - ".join(errors[:20]))
    return {
        "bundles": len(bundle_files),
        "checked_bundles": checked,
        "benchmarks": sorted(benchmarks),
        "platforms": sorted(platforms),
        "queries": query_count,
    }


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
