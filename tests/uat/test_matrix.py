"""Fast-test coverage for tests/uat/matrix.py.

Includes the structural-parity assertion against
`scripts/local_stress_test.sh` required by the parent TODO's W2: every
key in the bash case statements must appear in the Python dict (and
vice versa) with the same value.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import matrix

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Bash-parity helpers and assertions.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BASH_SCRIPT = REPO_ROOT / "scripts" / "local_stress_test.sh"


def _parse_bash_case(text: str, fn_name: str) -> dict[str, str]:
    """Extract `case "$1" in <key>) echo "...";; ... esac` mapping for fn_name."""
    fn_match = re.search(
        rf"^\s*{fn_name}\s*\(\s*\)\s*\{{\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not fn_match:
        raise AssertionError(f"Did not find function {fn_name} in bash script")
    body_start = fn_match.end()
    case_match = re.search(r'case\s+"\$1"\s+in', text[body_start:])
    assert case_match, f"No case statement in {fn_name}"
    body_after_case = text[body_start + case_match.end() :]
    esac_match = re.search(r"\besac\b", body_after_case)
    assert esac_match, f"No esac in {fn_name}"
    body = body_after_case[: esac_match.start()]
    out: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'([\w-]+(?:\|[\w-]+)*)\)\s*echo\s+"(.*)"\s*;;\s*$', line)
        if not m:
            continue
        keys = m.group(1).split("|")
        value = m.group(2)
        for key in keys:
            if key == "*":
                continue
            out[key] = value
    return out


def _bash_case_keys() -> dict[str, dict[str, str]]:
    text = BASH_SCRIPT.read_text()
    return {
        "get_platform_port": _parse_bash_case(text, "get_platform_port"),
        "get_platform_extra_opts": _parse_bash_case(text, "get_platform_extra_opts"),
        "get_platform_cli_flags": _parse_bash_case(text, "get_platform_cli_flags"),
        "get_platform_uv_extra": _parse_bash_case(text, "get_platform_uv_extra"),
    }


def test_bash_parity_platform_ports():
    bash = _bash_case_keys()["get_platform_port"]
    assert set(bash) == set(matrix.PLATFORM_PORTS)
    for key, value in bash.items():
        assert matrix.PLATFORM_PORTS[key] == value


def test_bash_parity_extra_opts():
    bash = _bash_case_keys()["get_platform_extra_opts"]
    py_keys = set(matrix.PLATFORM_EXTRA_OPTS)
    assert set(bash) == py_keys
    for key, value in bash.items():
        # Bash echoes a single space-separated string; Python stores argv list.
        assert " ".join(matrix.PLATFORM_EXTRA_OPTS[key]) == value


def test_bash_parity_cli_flags():
    bash = _bash_case_keys()["get_platform_cli_flags"]
    py_keys = set(matrix.PLATFORM_CLI_FLAGS)
    assert set(bash) == py_keys
    for key, value in bash.items():
        assert " ".join(matrix.PLATFORM_CLI_FLAGS[key]) == value


def test_bash_parity_uv_extra():
    bash = _bash_case_keys()["get_platform_uv_extra"]
    py_keys = set(matrix.PLATFORM_UV_EXTRA)
    assert set(bash) == py_keys
    for key, value in bash.items():
        assert matrix.PLATFORM_UV_EXTRA[key] == value


# ---------------------------------------------------------------------------
# resolve_platforms / resolve_benchmarks.
# ---------------------------------------------------------------------------


def test_resolve_platforms_groups_dedupe():
    out = matrix.resolve_platforms(groups=["fast", "sql"])
    assert "duckdb" in out
    # `sql` is a superset; make sure dedupe by-first-occurrence held.
    assert out.count("duckdb") == 1


def test_resolve_platforms_include_then_exclude():
    out = matrix.resolve_platforms(
        groups=["fast"],
        include=["sqlite"],
        exclude=["duckdb"],
    )
    assert "duckdb" not in out
    assert "sqlite" in out
    assert "datafusion" in out


def test_resolve_platforms_unknown_group():
    with pytest.raises(ValueError, match="Unknown platform group"):
        matrix.resolve_platforms(groups=["nope"])


def test_resolve_benchmarks_categories():
    out = matrix.resolve_benchmarks(groups=["tpc"])
    assert "tpch" in out
    assert "tpcds" in out


def test_resolve_benchmarks_unknown_group():
    with pytest.raises(ValueError, match="Unknown benchmark group"):
        matrix.resolve_benchmarks(groups=["nope"])


# ---------------------------------------------------------------------------
# Reachability / TCP probe.
# ---------------------------------------------------------------------------


def test_platform_is_reachable_no_port_assumes_reachable():
    matrix.reset_reachability_cache()
    assert matrix.platform_is_reachable("duckdb") is True


def test_platform_is_reachable_uses_cache():
    matrix.reset_reachability_cache()
    with patch.object(matrix, "tcp_probe", return_value=False) as probe:
        assert matrix.platform_is_reachable("postgresql") is False
        assert matrix.platform_is_reachable("postgresql") is False
    assert probe.call_count == 1


def test_tcp_probe_unreachable():
    # Reserved-style high port that should be closed locally.
    assert matrix.tcp_probe("127.0.0.1", 1, timeout_s=0.5) is False


# ---------------------------------------------------------------------------
# Scale resolution.
# ---------------------------------------------------------------------------


def test_smoke_scale_for_tpch_uses_min():
    assert matrix.smoke_scale_for("tpch") == 0.01


def test_smoke_scale_for_tpcds_overrides_to_subscale():
    assert matrix.smoke_scale_for("tpcds") == 0.01


def test_filter_scales_by_registry_drops_above_max():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=0.01,
        scale_options=(0.01, 0.1, 1.0),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.01, 0.1, 1.0, 10.0], info=info)
    assert out == [0.01, 0.1, 1.0]


def test_filter_scales_by_registry_drops_below_min():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=1.0,
        scale_options=(1.0,),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.01, 0.1, 1.0], info=info)
    assert out == [1.0]


def test_filter_scales_by_registry_empty_options_passes_through():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=None,
        scale_options=(),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.5, 2.0], info=info)
    assert out == [0.5, 2.0]


# ---------------------------------------------------------------------------
# argv builders.
# ---------------------------------------------------------------------------


def test_uv_run_argv_native_uses_no_sync():
    assert matrix.uv_run_argv("duckdb") == ["uv", "run", "--no-sync", "--"]


def test_uv_run_argv_extra_uses_extra_flag():
    assert matrix.uv_run_argv("singlestore") == [
        "uv",
        "run",
        "--extra",
        "singlestore",
        "--",
    ]


def test_benchbox_run_argv_includes_platform_extras():
    argv = matrix.benchbox_run_argv("starrocks", "tpch", 0.01)
    assert "--quiet" in argv
    assert "--platform" in argv and "starrocks" in argv
    assert "--platform-option" in argv
    # The starrocks-specific port=19030 must be there.
    assert "port=19030" in argv


@pytest.mark.parametrize(
    "platform",
    ["pg-duckdb", "pg-mooncake", "timescaledb", "postgresql"],
)
def test_benchbox_run_argv_defaults_to_external_postgres_credentials(platform):
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01)
    assert "password=benchbox" not in argv


@pytest.mark.parametrize(
    "platform",
    ["pg-duckdb", "pg-mooncake", "timescaledb", "postgresql"],
)
def test_benchbox_run_argv_includes_local_managed_postgres_password_when_requested(platform):
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01, local_managed_platform=True)
    assert "--platform-option" in argv
    assert "password=benchbox" in argv


def test_benchbox_run_argv_appends_extra_args():
    argv = matrix.benchbox_run_argv("duckdb", "tpch", 0.01, extra_args=["--tuning", "tuned"])
    assert argv[-2:] == ["--tuning", "tuned"]


def test_benchbox_run_argv_velox_iterations_one():
    argv = matrix.benchbox_run_argv("velox", "tpch", 0.01)
    # CLI flags before --platform-option per the bash ordering.
    iter_idx = argv.index("--iterations")
    opt_idx = argv.index("--platform-option")
    assert iter_idx < opt_idx
