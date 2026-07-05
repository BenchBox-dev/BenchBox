"""Common test fixtures for BenchBox.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

# ── Limit library-internal parallelism ────────────────────────────────────
# Must be set BEFORE importing any native library (polars, numpy, etc.).
# With pytest-xdist each worker is a separate process; libraries that default
# to using all CPU cores (polars, DuckDB, BLAS, OpenMP) multiply effective
# parallelism by the worker count, causing CPU oversubscription and machine
# lock-ups on developer workstations.
import os
import shutil
from types import FrameType

os.environ.setdefault("POLARS_MAX_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
# DuckDB ignores env vars; patched in pytest_configure below.

import sys
import time
import warnings
from pathlib import Path
from typing import Any

import pytest

from benchbox.utils.printing import set_quiet

# Sphinx 11 deprecations in third-party extensions (sphinx_tags, myst_parser, ablog, napoleon).
# Guarded because older Sphinx versions (e.g. on Python 3.10) lack this class,
# and --strict-config in pytest.ini would abort on an unresolvable category.
try:
    from sphinx.deprecation import RemovedInSphinx11Warning

    warnings.filterwarnings("ignore", category=RemovedInSphinx11Warning)
except (ImportError, AttributeError):
    pass

# Register fixture plugins - this must come before any imports from those modules
# to allow pytest to rewrite assertions in the fixture modules
pytest_plugins = [
    "tests.fixtures.database_fixtures",
    "tests.fixtures.test_data_fixtures",
    "tests.fixtures.result_dict_fixtures",
    "tests.fixtures.platform_fixtures",
    "tests.fixtures.utility_fixtures",
]


@pytest.fixture
def joinorder_canonical_tiny(tmp_path: Path) -> Path:
    """Copy the canonical tiny JOB fixture and return its isolated path.

    Predicate oracle: every non-known-zero embedded canonical query has at
    least one underlying row; 2c, 5a, 5b, 10b, and 32a intentionally preserve
    zero-underlying-row aggregate semantics.
    """
    source = Path(__file__).parent / "fixtures" / "joinorder_canonical_tiny"
    target = tmp_path / "joinorder_canonical_tiny"
    shutil.copytree(source, target)
    return target


# ── Parallel test run mutual exclusion ──────────────────────────────────────
_test_lock_fd: int | None = None  # Kept open to hold the flock for the session lifetime.
_test_databases_created = False


def _get_test_lock_path() -> Path:
    """Return the inter-process lock path used by parallel pytest runs."""
    lock_dir = os.environ.get("BENCHBOX_TEST_LOCK_DIR")
    base_dir = Path(lock_dir).expanduser() if lock_dir else Path.home() / ".benchbox"
    return base_dir / "test.lock"


def _should_acquire_test_lock(config: pytest.Config) -> bool:
    """Return True when this process should compete for the parallel run lock.

    Skips lock acquisition for xdist worker subprocesses (only the controller
    process locks), when parallelism is disabled (-n 0 / no numprocesses), or
    when BENCHBOX_SKIP_TEST_LOCK is set in the environment.
    """
    if hasattr(config, "workerinput"):
        return False  # xdist worker - the controller holds the lock on our behalf
    if os.environ.get("BENCHBOX_SKIP_TEST_LOCK"):
        return False  # explicit opt-out (e.g. intentional concurrent debug runs)
    try:
        n = config.option.numprocesses
    except AttributeError:
        return False  # xdist not installed or numprocesses not yet registered
    # Lock for '-n auto' (string) or any explicit positive worker count.
    # bool(0) is False so n != 0 would be redundant - bool(n) is sufficient.
    # Assumes numprocesses is None, 0, "auto", or a positive int (pytest-xdist contract).
    return bool(n)


def _is_xdist_remote_exec_namespace(globals_dict: dict[str, Any]) -> bool:
    """Return True for the live xdist remote.py ``__channelexec__`` globals."""
    return globals_dict.get("__name__") == "__channelexec__" and callable(globals_dict.get("worker_title"))


def _suppress_xdist_worker_title(start_frame: FrameType | None = None) -> bool:
    """Replace xdist's live ``worker_title`` when its exec frame is on the stack."""
    import inspect

    frame = start_frame or inspect.currentframe()
    if frame is None:
        return False
    if start_frame is None:
        frame = frame.f_back

    try:
        while frame is not None:
            if _is_xdist_remote_exec_namespace(frame.f_globals):
                frame.f_globals["worker_title"] = lambda title: None
                return True
            frame = frame.f_back
    finally:
        del frame  # avoid reference cycle

    return False


def pytest_configure(config) -> None:
    """Configure pytest with enhanced test organization and optimization settings."""
    global _test_lock_fd

    # Suppress setproctitle on macOS to prevent launchservicesd CPU storm.
    #
    # Root cause: xdist calls setproctitle() twice per test (running/idle)
    # via xdist.remote.worker_title().  At ~200 calls/second this triggers
    # macOS launchservicesd to rebuild its process registry continuously,
    # consuming 200%+ CPU and ~900 MB RSS - the actual root cause of
    # the macOS beachball during parallel test runs.
    #
    # In xdist workers, remote.py runs in an execnet __channelexec__
    # namespace, so `import xdist.remote` loads a different module object
    # than the one executing.  We walk the call stack to find the real
    # xdist exec namespace and patch its worker_title there.
    if sys.platform == "darwin" and hasattr(config, "workerinput"):
        _suppress_xdist_worker_title()

    # Acquire exclusive lock to prevent concurrent parallel test runs from
    # competing for CPU. Only the controller process (not xdist workers) locks.
    if _should_acquire_test_lock(config):
        test_lock_path = _get_test_lock_path()
        test_lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(test_lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            # Another parallel run holds the lock - fail fast with a clear message.
            try:
                holder_info = test_lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                holder_info = "(could not read lock file)"
            os.close(fd)
            # Use os._exit() rather than sys.exit(): pytest_configure is called
            # before the session loop so SystemExit bubbles up as INTERNALERROR.
            # os._exit() terminates the process immediately with the given code.
            sys.stderr.write(
                f"\n\033[91m[benchbox] BLOCKED: A parallel test run is already active.\033[0m\n"
                f"  Lock file : {test_lock_path}\n"
                f"  Holder    : {holder_info}\n\n"
                f"  Options:\n"
                f"    \u2022 Wait for the other run to finish and retry.\n"
                f"    \u2022 Kill the other run, then retry.\n"
                f"    \u2022 Run single-threaded (no lock):  pytest -n 0 ...\n"
                f"    \u2022 Bypass lock (dangerous):         BENCHBOX_SKIP_TEST_LOCK=1 pytest ...\n\n"
            )
            sys.stderr.flush()
            os._exit(1)
        # Write diagnostic info so other processes can identify the lock holder.
        # ftruncate is safe here: O_RDWR opens at position 0, so the subsequent
        # write lands at offset 0 without needing an explicit seek.
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        cmd = " ".join(sys.argv[:4])
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid:{os.getpid()} started:{started} cmd:{cmd}\n".encode())
        except OSError:
            pass
        _test_lock_fd = fd  # Keep fd open to maintain the lock for the whole session.

    # Limit DuckDB internal threads.  DuckDB ignores environment variables;
    # the only reliable method is passing config={'threads': N} to connect().
    # Monkey-patch duckdb.connect so ALL connections created during tests
    # default to 2 threads (preserving explicit overrides).
    try:
        import duckdb as _duckdb_mod

        _original_duckdb_connect = _duckdb_mod.connect

        def _limited_duckdb_connect(*args, **kwargs):
            cfg = kwargs.get("config") or {}
            if isinstance(cfg, dict) and "threads" not in cfg:
                cfg["threads"] = "2"
                kwargs["config"] = cfg
            return _original_duckdb_connect(*args, **kwargs)

        _duckdb_mod.connect = _limited_duckdb_connect
    except ImportError:
        pass


def pytest_unconfigure(config) -> None:
    """Release the parallel run lock when the session ends."""
    global _test_lock_fd
    if _test_lock_fd is not None:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(_test_lock_fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(_test_lock_fd, fcntl.LOCK_UN)
            os.close(_test_lock_fd)
        except OSError:
            pass
        _test_lock_fd = None


def _warn_on_unreasoned_skip_markers(items) -> None:
    """Warn (don't fail) on skip/skipif/xfail markers missing a ``reason=``.

    Every suppressed test should explain WHY in writing so it can be
    triaged later. Called from ``pytest_collection_finish`` (read-only -
    does NOT rewrite items; that would violate the no-collection-time-
    marker-rewrite policy in tests/unit/test_marker_strategy.py). Set
    ``BENCHBOX_SKIP_REASON_CHECK=1`` to bypass.
    """
    if os.environ.get("BENCHBOX_SKIP_REASON_CHECK"):
        return
    offenders: list[str] = []
    for item in items:
        for marker in item.iter_markers():
            if marker.name not in {"skip", "skipif", "xfail"}:
                continue
            # pytest stores reason as kwarg OR (for skip/xfail) as first positional
            if marker.kwargs.get("reason"):
                continue
            if marker.name in {"skip", "xfail"} and marker.args and isinstance(marker.args[0], str):
                continue
            offenders.append(f"{item.nodeid}: @pytest.mark.{marker.name} without reason=")
    if offenders:
        import warnings

        for line in offenders[:20]:  # cap to keep output readable
            warnings.warn(line, UserWarning, stacklevel=0)
        if len(offenders) > 20:
            warnings.warn(
                f"... and {len(offenders) - 20} more skip/xfail markers without reason=",
                UserWarning,
                stacklevel=0,
            )


def _items_require_test_databases(items) -> bool:
    """Return True when the selected test set includes database/integration coverage."""
    return any(item.get_closest_marker("integration") or item.get_closest_marker("database") for item in items)


def _create_test_databases() -> None:
    """Create shared test databases for tests that use persistent DB fixtures."""
    global _test_databases_created
    if _test_databases_created:
        return

    import subprocess
    import sys

    test_db_dir = Path(__file__).parent / "databases"
    test_db_dir.mkdir(exist_ok=True)

    create_script = test_db_dir / "create_test_databases.py"
    if create_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(create_script)],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent),
            )
            if result.returncode != 0:
                print(f"Warning: Failed to create test databases: {result.stderr}")
        except Exception as e:
            print(f"Warning: Error creating test databases: {e}")

    _test_databases_created = True


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items) -> None:
    """Create shared test databases only when the selected test set needs them."""
    if _items_require_test_databases(items):
        _create_test_databases()


def pytest_collection_finish(session) -> None:
    """Run read-only marker hygiene checks after collection completes."""
    _warn_on_unreasoned_skip_markers(session.items)


@pytest.fixture(autouse=True)
def _reset_global_quiet_state():
    """Never let benchbox's global quiet flag leak across tests.

    benchbox.utils.printing keeps module-global output state (_QUIET) that
    tests toggle via set_quiet(True). A test that fails, times out, or forgets
    its reset between set_quiet(True) and its cleanup poisons every later
    test in the same xdist worker: emit() routes to the sink console and
    capsys sees ''. Observed live on develop-post-merge run 28706929881,
    where test_display_results failed with CaptureResult(out='') under -n 5
    while passing in isolation (medium-tier-red-disposition-and-promotion).
    Resetting AFTER each test (post-yield) contains the blast radius to the
    leaking test itself.

    ``set_quiet`` is imported at module scope (not lazily here in the
    teardown body): this fixture is autouse, so its teardown runs after
    EVERY test, including one that monkeypatches ``builtins.__import__``
    for the duration of its own test body (e.g. the vortex-converter
    "missing module" test). A lazy import here would route through that
    patched ``__import__`` and raise the OTHER test's synthetic
    ImportError, misattributed to this fixture's teardown, whenever pytest's
    fixture-teardown ordering runs this after monkeypatch's own finalizer
    (order is topology-dependent, hence intermittent). Importing once at
    module load time, before any test's monkeypatch is active, avoids the
    race entirely.
    """
    yield
    set_quiet(False)


def pytest_runtest_setup(item) -> None:
    """Set up test-specific configurations based on markers."""
    # Set timeouts based on speed markers
    if item.get_closest_marker("fast"):
        item.config.option.timeout = 30
    elif item.get_closest_marker("medium"):
        item.config.option.timeout = 120
    elif item.get_closest_marker("slow"):
        item.config.option.timeout = 600

    # Skip tests based on environment
    if item.get_closest_marker("skip_ci") and os.environ.get("CI"):
        pytest.skip("Skipped in CI environment")

    if item.get_closest_marker("local_only") and os.environ.get("CI"):
        pytest.skip("Local-only test skipped in CI")


def pytest_sessionfinish(session, exitstatus) -> None:
    """Clean up test databases after the test session ends."""
    from pathlib import Path

    # the test databases directory
    test_db_dir = Path(__file__).parent / "databases"

    # Strip all .duckdb files
    if test_db_dir.exists():
        for db_file in test_db_dir.glob("*.duckdb"):
            try:
                db_file.unlink()
            except Exception as e:
                print(f"Warning: Could not remove {db_file}: {e}")


def pytest_terminal_summary(terminalreporter, config, exitstatus) -> None:
    """Emit a WARN (non-failing) when total coverage is below 80%.

    This reads the `.coverage` data file and computes overall coverage using
    the coverage.py API to avoid relying on pytest-cov's fail-under behavior.
    It does not fail the test run; it only prints a prominent warning line.
    CI remains the blocking gate at 70% via the workflow `--cov-fail-under`
    flag; this 80% threshold is intentionally advisory.

    Only runs when pytest-cov is active (i.e. --cov was passed), so stale
    .coverage files from prior runs don't produce misleading warnings.
    """
    # Skip when pytest-cov wasn't active in this session
    if not config.pluginmanager.hasplugin("_cov"):
        return

    try:
        import io

        import coverage

        threshold = 80.0

        # Load existing coverage data written by pytest-cov
        cov = coverage.Coverage(data_file=".coverage", config_file=".coveragerc_core")
        cov.load()

        buf = io.StringIO()
        total = cov.report(ignore_errors=True, file=buf)  # returns float percent

        if total < threshold:
            terminalreporter.write_sep(
                "-",
                f"WARNING: Test coverage {total:.2f}% is below threshold {threshold:.0f}%",
            )
    except Exception as e:  # pragma: no cover - best-effort warning path
        # If coverage data/lib isn't available, don't break the test run.
        terminalreporter.write_line(f"Note: Coverage warning check skipped: {e}")
