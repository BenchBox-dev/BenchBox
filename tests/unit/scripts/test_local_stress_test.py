"""Behavioral tests for scripts/local_stress_test.sh timeout handling."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.platform == "win32", reason="Shell scripts not supported on Windows"),
]

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "local_stress_test.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _write_uv_stub(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "uv",
        """#!/bin/sh
if [ "$1" = "sync" ]; then
  exit 0
fi

if [ "$1" = "run" ] && [ "$2" = "--no-sync" ] && [ "$3" = "--" ] && [ "$4" = "python" ]; then
  cat <<'EOF'
TPC_BENCHMARKS=( tpch )
PRIMITIVES_BENCHMARKS=( _unused_ )
INDUSTRY_BENCHMARKS=( _unused_ )
ACADEMIC_BENCHMARKS=( _unused_ )
TIMESERIES_BENCHMARKS=( _unused_ )
REALWORLD_BENCHMARKS=( _unused_ )
AIML_BENCHMARKS=( _unused_ )
EXPERIMENTAL_BENCHMARKS=( _unused_ )
SQL_ONLY_BENCHMARKS=( _unused_ )
BENCHMARK_SMOKE_SCALES=()
BENCHMARK_SMOKE_SCALES+=("tpch=0.01")
EOF
  exit 0
fi

if [ "$1" = "run" ] && [ "$2" = "--no-sync" ] && [ "$3" = "--" ] && [ "$4" = "benchbox" ] && [ "$5" = "run" ]; then
  if [ -n "$UV_STUB_SLEEP" ]; then
    sleep "$UV_STUB_SLEEP"
  fi
  if [ -n "$UV_STUB_STDOUT" ]; then
    printf '%s\\n' "$UV_STUB_STDOUT"
  fi
  exit "${UV_STUB_EXIT:-0}"
fi

echo "unexpected uv invocation: $*" >&2
exit 99
""",
    )


def _base_env(bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def _run_script(tmp_path: Path, env: dict[str, str], *extra_args: str) -> subprocess.CompletedProcess[str]:
    log_dir = tmp_path / "logs"
    cmd = [
        "/bin/bash",
        str(SCRIPT),
        "--platform",
        "duckdb",
        "--benchmark",
        "tpch",
        "--log-dir",
        str(log_dir),
        *extra_args,
    ]
    return subprocess.run(
        cmd,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def test_perl_fallback_enforces_timeout_without_ignore_warning(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_uv_stub(bin_dir)
    _write_executable(bin_dir / "timeout", "#!/bin/sh\nexit 1\n")
    _write_executable(bin_dir / "gtimeout", "#!/bin/sh\nexit 1\n")

    env = _base_env(bin_dir)
    env["UV_STUB_SLEEP"] = "2"

    result = _run_script(tmp_path, env, "--per-benchmark-timeout", "1")

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "TIMEOUT after" in combined
    assert "ignoring" not in combined


def test_coreutils_timeout_exit_124_is_reported_as_timeout(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_uv_stub(bin_dir)
    _write_executable(
        bin_dir / "timeout",
        """#!/bin/sh
if [ "$1" = "--help" ]; then
  exit 0
fi
exit 124
""",
    )

    env = _base_env(bin_dir)

    result = _run_script(tmp_path, env, "--per-benchmark-timeout", "1")

    assert result.returncode == 1
    assert "TIMEOUT after" in result.stdout + result.stderr


def test_timeout_request_fails_fast_when_no_backend_is_available(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_uv_stub(bin_dir)
    _write_executable(bin_dir / "timeout", "#!/bin/sh\nexit 1\n")
    _write_executable(bin_dir / "gtimeout", "#!/bin/sh\nexit 1\n")
    _write_executable(bin_dir / "perl", "#!/bin/sh\nexit 1\n")

    env = _base_env(bin_dir)

    result = _run_script(tmp_path, env, "--per-benchmark-timeout", "1")

    assert result.returncode == 2
    assert "requires timeout(1), gtimeout(1), or a working perl(1) interpreter" in result.stderr
