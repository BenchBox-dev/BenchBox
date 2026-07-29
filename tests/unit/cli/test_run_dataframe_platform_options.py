"""Regression tests: DataFrame platform options are reachable from `benchbox run`.

DataFrame platforms are selected on the CLI via a ``-df`` alias
(``--platform datafusion-df``), which ``PLATFORM_ALIASES`` normalizes to the
base platform key (``datafusion``) before any option parsing happens.  The
option specs for those platforms must therefore be registered under the *base*
key, not the ``-df`` alias, or every DataFrame-specific option
(``target_partitions``, ``streaming``, ``dtype_backend``, ...) becomes
unreachable and ``benchbox run`` rejects it as an unknown option.

See benchbox/platforms/__init__.py ``_OPTION_SPEC_ROWS``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys as _sys
from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli
from benchbox.cli.platform import normalize_platform_name
from benchbox.core.hooks.platform_hooks import PlatformHookRegistry
from benchbox.core.schemas import DatabaseConfig

# See test_run_driver_version_announcement.py for why this indirection is needed
# to patch DatabaseManager on the run submodule across Python versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

# Import for its spec-registration side effects so the registry is populated
# regardless of test collection order.
import benchbox.cli.platform_defaults  # noqa: E402,F401

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# (CLI ``-df`` alias, one representative option, a value, its parsed form).
_DATAFRAME_OPTION_CASES = [
    ("datafusion-df", "target_partitions", "4", 4),
    ("polars-df", "streaming", "true", True),
    ("pandas-df", "dtype_backend", "pyarrow", "pyarrow"),
    ("modin-df", "engine", "dask", "dask"),
    ("cudf-df", "device_id", "1", 1),
    ("dask-df", "n_workers", "8", 8),
]


class TestDataFrameOptionSpecKeying:
    """Option specs live under the normalized base key, not the -df alias."""

    @pytest.mark.parametrize("df_alias,option,raw,expected", _DATAFRAME_OPTION_CASES)
    def test_option_reachable_under_normalized_key(self, df_alias, option, raw, expected):
        base_key = normalize_platform_name(df_alias)
        # The alias must actually normalize to a distinct base key, otherwise
        # this regression would be vacuous.
        assert base_key != df_alias

        # Parsing with the key the run CLI actually uses must succeed...
        parsed = PlatformHookRegistry.parse_options(base_key, [(option, raw)])
        assert parsed[option] == expected

        # ...and the spec must be registered under the base key.
        assert option in PlatformHookRegistry.list_option_specs(base_key)

    @pytest.mark.parametrize("df_alias,option,raw,expected", _DATAFRAME_OPTION_CASES)
    def test_option_not_orphaned_under_df_alias(self, df_alias, option, raw, expected):
        # The -df alias key must NOT carry the specs; if it did, the run CLI —
        # which only ever sees the normalized base key — could never reach them.
        assert option not in PlatformHookRegistry.list_option_specs(df_alias)


def _datafusion_df_available() -> bool:
    try:
        from benchbox.platforms import list_available_dataframe_platforms

        avail = list_available_dataframe_platforms()
    except Exception:
        return False
    return bool(avail.get("datafusion-df") or avail.get("datafusion"))


@pytest.mark.skipif(not _datafusion_df_available(), reason="DataFusion DataFrame backend not installed")
class TestDataFrameOptionReachesConfig:
    """`benchbox run --platform <x>-df --platform-option ...` reaches create_config."""

    def _invoke_run(self, platform, option_pairs):
        """Drive `benchbox run` through the non-interactive power path.

        Managers/orchestration are mocked so no benchmark actually executes; we
        only care that _run_direct hands the parsed platform options to
        DatabaseManager.create_config under the normalized base platform key.
        """
        mock_db_manager = MagicMock()
        mock_db_manager.create_config.return_value = DatabaseConfig(type="datafusion", name="DataFusion")

        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test-exec-id"

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute_benchmark.return_value = mock_result
        mock_orchestrator.directory_manager.get_result_path.return_value = "/tmp/test.json"
        mock_orchestrator.directory_manager.results_dir = "/tmp"

        mock_bench_manager = MagicMock()
        mock_bench_manager.benchmarks = {
            "tpch": {
                "display_name": "TPC-H",
                "class": Mock(),
                "description": "TPC-H",
                "estimated_time_range": (2, 10),
            }
        }
        mock_bench_manager.validate_scale_factor = Mock()

        args = [
            "run",
            "--platform",
            platform,
            "--benchmark",
            "tpch",
            "--scale",
            "0.01",
            "--non-interactive",
            "--phases",
            "power",
        ]
        for name, value in option_pairs:
            args += ["--platform-option", f"{name}={value}"]

        runner = CliRunner()
        with (
            patch.object(_run_module, "DatabaseManager", return_value=mock_db_manager),
            patch.object(_run_module, "BenchmarkManager", return_value=mock_bench_manager),
            patch.object(_run_module, "BenchmarkOrchestrator", return_value=mock_orchestrator),
            patch.object(_run_module, "SystemProfiler") as mock_profiler_cls,
            patch("benchbox.cli.main.get_config_manager") as mock_cfg,
            patch.object(_run_module, "_execute_orchestrated_run", return_value=mock_result),
            patch.object(_run_module, "_export_orchestrated_result", return_value={"json": "/tmp/t.json"}),
            patch.object(_run_module, "_render_post_run_charts"),
            patch("benchbox.cli.preferences.save_last_run_config"),
        ):
            mock_profiler_cls.return_value.get_system_profile.return_value = Mock()
            # Behave like an empty config manager: return the caller's default
            # rather than None, so downstream config.get(key, default) lookups
            # (e.g. compression settings) resolve to their real defaults.
            mock_cfg.return_value.get.side_effect = lambda *a, **k: a[1] if len(a) > 1 else k.get("default")
            result = runner.invoke(cli, args)
        return result, mock_db_manager

    def test_datafusion_df_target_partitions_reaches_create_config(self):
        result, mock_db_manager = self._invoke_run("datafusion-df", [("target_partitions", "4")])

        # The bug manifested as a non-zero exit with "Unknown platform option".
        assert "Unknown platform option" not in result.output
        assert result.exit_code == 0, result.output

        # create_config is called with the normalized base key and the parsed
        # option threaded into the options dict.
        assert mock_db_manager.create_config.called
        call = mock_db_manager.create_config.call_args
        platform_key = call.args[0]
        options = call.args[1]
        assert platform_key == "datafusion"
        assert options.get("target_partitions") == 4
