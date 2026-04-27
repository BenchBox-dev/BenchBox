import importlib
import importlib.machinery
import logging
import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

from benchbox.utils import runtime_env
from benchbox.utils.runtime_env import (
    DriverResolution,
    DriverRuntimeStrategy,
    _validate_runtime_abi,
    discover_isolated_runtime,
    ensure_driver_version,
    load_driver_module,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_ensure_driver_version_matches(monkeypatch):
    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda pkg: "1.2.3")
    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.2.3",
        auto_install=False,
    )
    assert resolution.package == "duckdb"
    assert resolution.requested == "1.2.3"
    assert resolution.resolved == "1.2.3"
    assert resolution.actual == "1.2.3"
    assert resolution.auto_install_used is False
    assert resolution.runtime_strategy == DriverRuntimeStrategy.CURRENT_PROCESS.value
    assert resolution.runtime_path is None
    assert resolution.runtime_python_executable


def test_ensure_driver_version_mismatch_without_auto_install(monkeypatch):
    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda pkg: "1.2.3")
    with pytest.raises(RuntimeError) as excinfo:
        ensure_driver_version(
            package_name="duckdb",
            requested_version="2.0.0",
            auto_install=False,
        )
    assert "duckdb" in str(excinfo.value)
    assert "2.0.0" in str(excinfo.value)


def test_ensure_driver_version_autoinstall(monkeypatch):
    installed_version = {"value": None}

    def fake_get_version(_):
        return installed_version["value"]

    def fake_install(_command):
        installed_version["value"] = "2.0.0"

    monkeypatch.setattr(runtime_env, "_get_installed_version", fake_get_version)
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda flag: True)

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="2.0.0",
        auto_install=False,
    )
    assert resolution.package == "duckdb"
    assert resolution.requested == "2.0.0"
    assert resolution.resolved == "2.0.0"
    assert resolution.actual == "2.0.0"
    assert resolution.auto_install_used is True
    assert resolution.runtime_strategy == DriverRuntimeStrategy.CURRENT_PROCESS.value


def test_discover_isolated_runtime_finds_matching_version(tmp_path, monkeypatch):
    root = tmp_path / "envs"
    site_packages = root / "duckdb-0.9.2" / "lib" / "python3.11" / "site-packages"
    site_packages.mkdir(parents=True)
    dist_info = site_packages / "duckdb-0.9.2.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Name: duckdb\nVersion: 0.9.2\n")
    python_bin = root / "duckdb-0.9.2" / "bin"
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text("")

    monkeypatch.setenv("BENCHBOX_DRIVER_RUNTIME_ROOTS", str(root))

    runtime = discover_isolated_runtime(package_name="duckdb", requested_version="0.9.2")

    assert runtime is not None
    assert runtime.package == "duckdb"
    assert runtime.version == "0.9.2"
    assert runtime.strategy == DriverRuntimeStrategy.ISOLATED_SITE_PACKAGES.value
    assert runtime.runtime_path == str(site_packages)
    assert runtime.python_executable == str(python_bin / "python")


def test_ensure_driver_version_prefers_isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda pkg: "1.4.3")
    root = tmp_path / "envs"
    site_packages = root / "duckdb-1.2.2" / "lib" / "python3.11" / "site-packages"
    site_packages.mkdir(parents=True)
    dist_info = site_packages / "duckdb-1.2.2.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Name: duckdb\nVersion: 1.2.2\n")
    monkeypatch.setenv("BENCHBOX_DRIVER_RUNTIME_ROOTS", str(root))

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.2.2",
        auto_install=False,
    )

    assert resolution == DriverResolution(
        package="duckdb",
        requested="1.2.2",
        resolved="1.2.2",
        actual="1.2.2",
        auto_install_used=False,
        runtime_strategy=DriverRuntimeStrategy.ISOLATED_SITE_PACKAGES.value,
        runtime_path=str(site_packages),
        runtime_python_executable=None,
    )


def test_load_driver_module_from_isolated_runtime(tmp_path):
    site_packages = tmp_path / "env" / "lib" / "python3.11" / "site-packages"
    package_dir = site_packages / "duckdb"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("__version__ = '0.9.2'\n")

    resolution = DriverResolution(
        package="duckdb",
        requested="0.9.2",
        resolved="0.9.2",
        actual="0.9.2",
        auto_install_used=False,
        runtime_strategy=DriverRuntimeStrategy.ISOLATED_SITE_PACKAGES.value,
        runtime_path=str(site_packages),
        runtime_python_executable=None,
    )

    try:
        module = load_driver_module(import_name="duckdb", resolution=resolution)
        assert getattr(module, "__version__", None) == "0.9.2"
        assert str(Path(module.__file__).resolve()).startswith(str(site_packages.resolve()))
    finally:
        sys.modules.pop("duckdb", None)


def test_load_driver_module_strict_version_mismatch_raises(tmp_path):
    site_packages = tmp_path / "env" / "lib" / "python3.11" / "site-packages"
    package_dir = site_packages / "duckdb"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("__version__ = '0.9.1'\n")

    resolution = DriverResolution(
        package="duckdb",
        requested="0.9.2",
        resolved="0.9.2",
        actual="0.9.2",
        auto_install_used=False,
        runtime_strategy=DriverRuntimeStrategy.ISOLATED_SITE_PACKAGES.value,
        runtime_path=str(site_packages),
        runtime_python_executable=None,
    )

    try:
        with pytest.raises(RuntimeError, match="requested version is 0.9.2"):
            load_driver_module(import_name="duckdb", resolution=resolution)
    finally:
        sys.modules.pop("duckdb", None)


def test_autoinstall_invalidates_import_caches(monkeypatch):
    """Fix A: importlib.invalidate_caches() is called after subprocess install."""
    installed_version = {"value": "1.0.0"}

    def fake_get_version(_):
        return installed_version["value"]

    def fake_install(_command):
        installed_version["value"] = "2.0.0"

    monkeypatch.setattr(runtime_env, "_get_installed_version", fake_get_version)
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda flag: True)

    with patch.object(importlib, "invalidate_caches") as mock_invalidate:
        resolution = ensure_driver_version(
            package_name="duckdb",
            requested_version="2.0.0",
            auto_install=True,
        )

    assert resolution.auto_install_used is True
    assert resolution.resolved == "2.0.0"
    mock_invalidate.assert_called()


def test_load_driver_module_purges_modules_after_autoinstall(tmp_path):
    """Fix B: load_driver_module purges sys.modules for CURRENT_PROCESS when auto_install_used."""
    # Create a fake package that load_driver_module will import
    package_dir = tmp_path / "fake_driver"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("__version__ = '2.0.0'\n")

    # Pre-populate sys.modules with a stale "old" module
    old_module = type(sys)("fake_driver")
    old_module.__version__ = "1.0.0"
    old_module.__file__ = str(package_dir / "__init__.py")
    sys.modules["fake_driver"] = old_module

    # Add the tmp_path to sys.path so the new version can be imported
    sys.path.insert(0, str(tmp_path))

    resolution = DriverResolution(
        package="fake_driver",
        requested="2.0.0",
        resolved="2.0.0",
        actual="2.0.0",
        auto_install_used=True,
        runtime_strategy=DriverRuntimeStrategy.CURRENT_PROCESS.value,
        runtime_path=None,
        runtime_python_executable=sys.executable,
    )

    try:
        module = load_driver_module(import_name="fake_driver", resolution=resolution)
        # Should have purged the old 1.0.0 module and loaded 2.0.0 from disk
        assert getattr(module, "__version__", None) == "2.0.0"
    finally:
        sys.modules.pop("fake_driver", None)
        sys.path.remove(str(tmp_path))


def test_load_driver_module_no_purge_without_autoinstall(tmp_path):
    """Without auto_install_used, load_driver_module uses cached sys.modules entry."""
    # Pre-populate sys.modules with a module
    cached_module = type(sys)("fake_driver_cached")
    cached_module.__version__ = "1.0.0"
    cached_module.__file__ = "/some/path/__init__.py"
    sys.modules["fake_driver_cached"] = cached_module

    resolution = DriverResolution(
        package="fake_driver_cached",
        requested="1.0.0",
        resolved="1.0.0",
        actual="1.0.0",
        auto_install_used=False,
        runtime_strategy=DriverRuntimeStrategy.CURRENT_PROCESS.value,
        runtime_path=None,
        runtime_python_executable=sys.executable,
    )

    try:
        module = load_driver_module(import_name="fake_driver_cached", resolution=resolution)
        # Should return the cached module without purging
        assert module is cached_module
        assert getattr(module, "__version__", None) == "1.0.0"
    finally:
        sys.modules.pop("fake_driver_cached", None)


# ---------------------------------------------------------------------------
# Tests for driver_auto_install in pip-absent environments (e.g. uv tool envs)
# ---------------------------------------------------------------------------


def test_autoinstall_first_command_targets_current_interpreter(monkeypatch):
    """The uv auto-install command must include --python sys.executable.

    Regression test for the case where benchbox is installed as a uv tool:
    the tool's venv has no pip, so `uv pip install` without --python installs
    into whatever venv uv resolves by default (not the tool venv), causing the
    post-install version check to fail and the fallback pip command to error
    with "No module named pip".
    """
    captured_commands: list[list[str]] = []
    installed_version = {"value": None}

    def fake_install(command: list[str]) -> None:
        captured_commands.append(command)
        # Simulate a successful install only when the command correctly targets
        # sys.executable (i.e. includes --python <path>).
        if "--python" in command and sys.executable in command:
            installed_version["value"] = "1.0.0"
        # Without --python, uv installs to the wrong env; version stays None.

    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: installed_version["value"])
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda _: True)
    # Prevent discover_isolated_runtime from finding a real local env and short-circuiting.
    monkeypatch.setattr(runtime_env, "discover_isolated_runtime", lambda **_: None)

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.0.0",
        auto_install=True,
    )

    assert resolution.auto_install_used is True
    assert resolution.resolved == "1.0.0"

    # The first (and in the happy path, only) command must target sys.executable.
    assert len(captured_commands) >= 1
    first_cmd = captured_commands[0]
    assert "--python" in first_cmd, "uv command must include --python to target the running venv"
    assert sys.executable in first_cmd, "uv command must pass sys.executable as the --python value"
    assert first_cmd[0] == "uv"


def test_autoinstall_succeeds_without_pip_when_uv_available(monkeypatch):
    """Auto-install works in pip-absent environments (uv tool venvs) using uv.

    In a uv tool environment, `python -m pip` raises 'No module named pip'.
    The first command (uv pip install --python ...) must succeed standalone.
    """
    installed_version = {"value": None}
    pip_was_called = {"value": False}

    def fake_install(command: list[str]) -> None:
        if command[0] == "uv":
            installed_version["value"] = "1.0.0"
        elif sys.executable in command and "-m" in command and "pip" in command:
            pip_was_called["value"] = True
            raise RuntimeError("No module named pip")

    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: installed_version["value"])
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda _: True)
    monkeypatch.setattr(runtime_env, "discover_isolated_runtime", lambda **_: None)

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.0.0",
        auto_install=True,
    )

    assert resolution.auto_install_used is True
    assert resolution.resolved == "1.0.0"
    # pip should never have been reached because uv succeeded first.
    assert not pip_was_called["value"], "pip fallback should not be reached when uv succeeds"


def test_autoinstall_falls_back_to_pip_when_uv_absent(monkeypatch):
    """When uv is not on PATH, auto-install falls back to python -m pip."""
    installed_version = {"value": None}

    def fake_install(command: list[str]) -> None:
        if command[0] == "uv":
            raise RuntimeError("uv: command not found")
        # pip fallback succeeds
        installed_version["value"] = "1.0.0"

    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: installed_version["value"])
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda _: True)
    monkeypatch.setattr(runtime_env, "discover_isolated_runtime", lambda **_: None)

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.0.0",
        auto_install=True,
    )

    assert resolution.auto_install_used is True
    assert resolution.resolved == "1.0.0"


def test_autoinstall_raises_when_both_installers_fail(monkeypatch):
    """When all install commands fail, a clear RuntimeError is raised."""

    def fake_install(command: list[str]) -> None:
        if command[0] == "uv":
            raise RuntimeError("uv: command not found")
        raise RuntimeError("No module named pip")

    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: None)
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda _: True)
    monkeypatch.setattr(runtime_env, "discover_isolated_runtime", lambda **_: None)

    with pytest.raises(RuntimeError) as excinfo:
        ensure_driver_version(
            package_name="duckdb",
            requested_version="1.0.0",
            auto_install=True,
        )

    error_text = str(excinfo.value)
    assert "duckdb" in error_text
    assert "1.0.0" in error_text
    # The error should surface the last failure reason so the user can diagnose it.
    assert "No module named pip" in error_text


# ---------------------------------------------------------------------------
# Tests for ABI validation in isolated runtime discovery
# ---------------------------------------------------------------------------


def _make_isolated_env(root: Path, name: str, pkg: str, version: str, ext_files: list[str] | None = None) -> Path:
    """Helper to create a fake isolated runtime environment for testing.

    Returns the site-packages path.
    """
    site_packages = root / name / "lib" / "python3.11" / "site-packages"
    site_packages.mkdir(parents=True)
    dist_info = site_packages / f"{pkg}-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(f"Name: {pkg}\nVersion: {version}\n")
    if ext_files is not None:
        pkg_dir = site_packages / pkg
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / "__init__.py").write_text(f"__version__ = '{version}'\n")
        for fname in ext_files:
            (pkg_dir / fname).write_bytes(b"")
    return site_packages


def _wrong_abi_filename() -> str:
    """Return a filename with a cpython ABI tag that does NOT match the running Python."""
    major, minor = sys.version_info.major, sys.version_info.minor
    wrong_minor = minor + 1  # guaranteed to differ
    ext = ".pyd" if sys.platform == "win32" else ".so"
    return f"duckdb.cpython-{major}{wrong_minor}-platform{ext}"


def _correct_abi_filename() -> str:
    """Return a filename with a cpython ABI tag that matches the running Python."""
    major, minor = sys.version_info.major, sys.version_info.minor
    ext = ".pyd" if sys.platform == "win32" else ".so"
    return f"duckdb.cpython-{major}{minor}-platform{ext}"


def test_validate_runtime_abi_wrong_suffix(tmp_path):
    """Extension files with wrong ABI tag are rejected."""
    site_packages = _make_isolated_env(
        tmp_path,
        "env",
        "duckdb",
        "1.2.2",
        ext_files=[_wrong_abi_filename()],
    )
    assert not _validate_runtime_abi(site_packages, "duckdb")


def test_validate_runtime_abi_correct_suffix(tmp_path):
    """Extension files matching the current interpreter's ABI tag are accepted."""
    site_packages = _make_isolated_env(
        tmp_path,
        "env",
        "duckdb",
        "1.2.2",
        ext_files=[_correct_abi_filename()],
    )
    assert _validate_runtime_abi(site_packages, "duckdb")


def test_validate_runtime_abi_pure_python(tmp_path):
    """Packages with no extension files (pure Python) are accepted."""
    site_packages = _make_isolated_env(
        tmp_path,
        "env",
        "sqlglot",
        "20.0.0",
        ext_files=[],  # creates pkg dir but no .so files
    )
    assert _validate_runtime_abi(site_packages, "sqlglot")


def test_validate_runtime_abi_stable_abi(tmp_path):
    """Stable ABI extensions (.abi3.so) are accepted across Python versions."""
    site_packages = _make_isolated_env(
        tmp_path,
        "env",
        "mypackage",
        "1.0.0",
        ext_files=["_core.abi3.so"],
    )
    assert _validate_runtime_abi(site_packages, "mypackage")


def test_validate_runtime_abi_mixed_tags_accepts_if_any_match(tmp_path):
    """Package with both wrong-ABI and correct-ABI extensions is accepted."""
    site_packages = _make_isolated_env(
        tmp_path,
        "env",
        "duckdb",
        "1.2.2",
        ext_files=[_wrong_abi_filename(), _correct_abi_filename()],
    )
    assert _validate_runtime_abi(site_packages, "duckdb")


def test_validate_runtime_abi_no_package_dir(tmp_path):
    """When no package directory exists (single-file module), accepted."""
    site_packages = _make_isolated_env(tmp_path, "env", "duckdb", "1.2.2")
    # No ext_files means no package dir created
    assert _validate_runtime_abi(site_packages, "duckdb")


def test_discover_skips_abi_mismatch_candidate(tmp_path, monkeypatch, caplog):
    """Discovery skips a candidate with wrong ABI and returns None."""
    _make_isolated_env(
        tmp_path / "envs",
        "duckdb-1.2.2",
        "duckdb",
        "1.2.2",
        ext_files=[_wrong_abi_filename()],
    )
    monkeypatch.setenv("BENCHBOX_DRIVER_RUNTIME_ROOTS", str(tmp_path / "envs"))

    with caplog.at_level(logging.WARNING, logger="benchbox.utils.runtime_env"):
        runtime = discover_isolated_runtime(package_name="duckdb", requested_version="1.2.2")

    assert runtime is None
    assert "ABI mismatch" in caplog.text
    assert "Skipping isolated runtime" in caplog.text


def test_discover_skips_bad_candidate_returns_good_one(tmp_path, monkeypatch):
    """When first candidate has wrong ABI, discovery falls through to the second."""
    envs = tmp_path / "envs"

    # Bad candidate (wrong ABI)
    _make_isolated_env(
        envs,
        "bad-env",
        "duckdb",
        "1.2.2",
        ext_files=[_wrong_abi_filename()],
    )
    # Good candidate (correct ABI)
    good_sp = _make_isolated_env(
        envs,
        "good-env",
        "duckdb",
        "1.2.2",
        ext_files=[_correct_abi_filename()],
    )
    monkeypatch.setenv("BENCHBOX_DRIVER_RUNTIME_ROOTS", str(envs))

    runtime = discover_isolated_runtime(package_name="duckdb", requested_version="1.2.2")

    assert runtime is not None
    assert runtime.runtime_path == str(good_sp)


def test_corrupted_runtime_fallthrough_to_autoinstall(tmp_path, monkeypatch):
    """ensure_driver_version() falls through to auto-install when isolated runtime has wrong ABI."""
    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: "1.4.3")

    envs = tmp_path / "envs"
    _make_isolated_env(
        envs,
        "duckdb-1.2.2",
        "duckdb",
        "1.2.2",
        ext_files=[_wrong_abi_filename()],
    )
    monkeypatch.setenv("BENCHBOX_DRIVER_RUNTIME_ROOTS", str(envs))

    installed_version = {"value": "1.4.3"}

    def fake_install(_command):
        installed_version["value"] = "1.2.2"

    monkeypatch.setattr(runtime_env, "_get_installed_version", lambda _: installed_version["value"])
    monkeypatch.setattr(runtime_env, "_run_install_command", fake_install)
    monkeypatch.setattr(runtime_env, "_should_auto_install", lambda _: True)

    resolution = ensure_driver_version(
        package_name="duckdb",
        requested_version="1.2.2",
        auto_install=True,
    )

    assert resolution.auto_install_used is True
    assert resolution.resolved == "1.2.2"
    assert resolution.runtime_strategy == DriverRuntimeStrategy.CURRENT_PROCESS.value


# ---------------------------------------------------------------------------
# Windows site-packages path resolution
# ---------------------------------------------------------------------------
from benchbox.utils.runtime_env import _iter_site_packages  # noqa: E402


class TestIterSitePackages:
    """_iter_site_packages() must yield both Unix lib/pythonX.Y/site-packages
    and the Windows Lib/site-packages layout when present.
    """

    def test_yields_unix_site_packages(self, tmp_path):
        sp = tmp_path / "lib" / "python3.11" / "site-packages"
        sp.mkdir(parents=True)
        result = list(_iter_site_packages(tmp_path))
        assert sp in result

    def test_yields_windows_site_packages_when_present(self, tmp_path):
        """Windows venvs use Lib/site-packages (capital L, no python version)."""
        win_sp = tmp_path / "Lib" / "site-packages"
        win_sp.mkdir(parents=True)
        result = list(_iter_site_packages(tmp_path))
        assert win_sp in result

    def test_does_not_yield_missing_windows_path(self, tmp_path):
        """If Lib/site-packages doesn't exist, it must not appear in results."""
        result = list(_iter_site_packages(tmp_path))
        win_sp = tmp_path / "Lib" / "site-packages"
        assert win_sp not in result

    def test_yields_both_when_both_exist(self, tmp_path):
        """Environments that have both layouts (unusual but possible) surface both."""
        unix_sp = tmp_path / "lib" / "python3.12" / "site-packages"
        unix_sp.mkdir(parents=True)
        win_sp = tmp_path / "Lib" / "site-packages"
        win_sp.mkdir(parents=True)
        result = list(_iter_site_packages(tmp_path))
        assert unix_sp in result
        assert win_sp in result
