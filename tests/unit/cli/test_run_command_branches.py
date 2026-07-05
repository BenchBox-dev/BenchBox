"""Coverage tests for benchbox/cli/exceptions.py and benchbox/cli/commands/run.py.

Wave: coverage-per-module-50-remaining (w9)
Target: push benchbox/cli/commands/run.py from 47% to >=50%.
benchbox/cli/exceptions.py is already at 72%.
"""

from __future__ import annotations

import logging
import os
import sys
import sys as _sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ===================================================================
# normalize_benchmark_name
# ===================================================================


class TestNormalizeBenchmarkName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("tpch", "tpch"),
            ("TPC-H", "tpch"),
            ("tpc_h", "tpch"),
            ("TPC-DS", "tpcds"),
            ("tpcds-obt", "tpcds_obt"),
            ("star-schema", "ssb"),
        ],
    )
    def test_aliases(self, raw: str, expected: str):
        from benchbox.cli.commands.run import normalize_benchmark_name

        assert normalize_benchmark_name(raw) == expected

    def test_unknown_name_passthrough(self):
        from benchbox.cli.commands.run import normalize_benchmark_name

        assert normalize_benchmark_name("custom_benchmark") == "custom_benchmark"


# ===================================================================
# PlatformOptionParamType
# ===================================================================


class TestPlatformOptionParamType:
    def test_convert_valid(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        key, val = pt.convert("memory_limit=8GB", None, None)
        assert key == "memory_limit"
        assert val == "8GB"

    def test_convert_equals_in_value(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        key, val = pt.convert("setting=a=b=c", None, None)
        assert key == "setting"
        assert val == "a=b=c"

    def test_convert_no_equals_fails(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        with pytest.raises(Exception):
            pt.convert("no_equals_sign", None, MagicMock())

    def test_convert_empty_key_fails(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        with pytest.raises(Exception):
            pt.convert("=value", None, MagicMock())

    def test_convert_strips_whitespace(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        key, val = pt.convert("  key  =  value  ", None, None)
        assert key == "key"
        assert val == "value"

    def test_name_attribute(self):
        from benchbox.cli.commands.run import PlatformOptionParamType

        pt = PlatformOptionParamType()
        assert pt.name == "key=value"


# ===================================================================
# _build_execution_context
# ===================================================================


class TestBuildExecutionContext:
    def test_basic(self):
        from benchbox.cli.commands.run import _build_execution_context
        from benchbox.cli.composite_params import CompressionConfig, ForceConfig, ValidationConfig

        ctx = _build_execution_context(
            phases_to_run=["load", "power"],
            seed=42,
            compression=CompressionConfig(enabled=True, type="zstd", level=3),
            mode="sql",
            official=False,
            validation=ValidationConfig(mode="exact"),
            force=ForceConfig(datagen=False, upload=False),
            queries_to_run=["Q1", "Q6"],
            capture_plans=True,
            strict_plan_capture=False,
            non_interactive=True,
            tuning="tuned",
        )
        assert ctx.entry_point == "cli"
        assert ctx.phases == ["load", "power"]
        assert ctx.seed == 42
        assert ctx.compression_enabled is True
        assert ctx.compression_type == "zstd"
        assert ctx.compression_level == 3
        assert ctx.mode == "sql"
        assert ctx.official is False
        assert ctx.validation_mode is None  # "exact" produces None
        assert ctx.force_datagen is False
        assert ctx.query_subset == ["Q1", "Q6"]
        assert ctx.capture_plans is True
        assert ctx.non_interactive is True
        assert ctx.tuning_mode == "tuned"

    def test_mode_defaults_to_sql(self):
        from benchbox.cli.commands.run import _build_execution_context
        from benchbox.cli.composite_params import CompressionConfig, ForceConfig, ValidationConfig

        ctx = _build_execution_context(
            phases_to_run=["power"],
            seed=None,
            compression=CompressionConfig(enabled=False, type="none", level=None),
            mode=None,
            official=False,
            validation=ValidationConfig(mode="loose"),
            force=ForceConfig(datagen=True, upload=False),
            queries_to_run=None,
            capture_plans=False,
            strict_plan_capture=False,
            non_interactive=False,
            tuning="notuning",
        )
        assert ctx.mode == "sql"
        assert ctx.seed is None
        assert ctx.query_subset is None
        assert ctx.tuning_mode is None  # "notuning" produces None
        assert ctx.validation_mode == "loose"
        assert ctx.force_datagen is True

    def test_official_mode(self):
        from benchbox.cli.commands.run import _build_execution_context
        from benchbox.cli.composite_params import CompressionConfig, ForceConfig, ValidationConfig

        ctx = _build_execution_context(
            phases_to_run=["power"],
            seed=12345,
            compression=CompressionConfig(enabled=True, type="gzip", level=6),
            mode="dataframe",
            official=True,
            validation=ValidationConfig(mode="full"),
            force=ForceConfig(datagen=False, upload=True),
            queries_to_run=None,
            capture_plans=False,
            strict_plan_capture=True,
            non_interactive=True,
            tuning="auto",
        )
        assert ctx.official is True
        assert ctx.mode == "dataframe"
        assert ctx.strict_plan_capture is True
        assert ctx.force_upload is True
        assert ctx.tuning_mode == "auto"


# ===================================================================
# _apply_platform_optimization_overrides
# ===================================================================


class TestApplyPlatformOptimizationOverrides:
    def test_databricks_platform_options_update_unified_tuning(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        unified = UnifiedTuningConfiguration()

        _apply_platform_optimization_overrides(
            unified,
            sorted_ingestion_mode=None,
            sorted_ingestion_method=None,
            parsed_platform_options={
                "databricks_clustering_strategy": "liquid_clustering",
                "liquid_clustering_columns": "event_time,customer_id",
            },
        )

        assert unified.platform_optimizations.databricks_clustering_strategy == "liquid_clustering"
        assert unified.platform_optimizations.liquid_clustering_enabled is True
        assert unified.platform_optimizations.liquid_clustering_columns == ["event_time", "customer_id"]

    def test_clustering_strategy_via_platform_options(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        unified = UnifiedTuningConfiguration()

        _apply_platform_optimization_overrides(
            unified,
            sorted_ingestion_mode=None,
            sorted_ingestion_method=None,
            parsed_platform_options={"databricks_clustering_strategy": "none"},
        )

        assert unified.platform_optimizations.databricks_clustering_strategy == "none"
        assert unified.platform_optimizations.liquid_clustering_enabled is False

    def test_liquid_auto_strategy_via_platform_options(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        unified = UnifiedTuningConfiguration()

        _apply_platform_optimization_overrides(
            unified,
            sorted_ingestion_mode=None,
            sorted_ingestion_method=None,
            parsed_platform_options={"databricks_clustering_strategy": "liquid_clustering_auto"},
        )

        assert unified.platform_optimizations.databricks_clustering_strategy == "liquid_clustering_auto"
        assert unified.platform_optimizations.liquid_clustering_enabled is True

    def test_liquid_strategy_rejects_legacy_zorder_template_fields(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        unified = UnifiedTuningConfiguration()
        unified.platform_optimizations.z_ordering_enabled = True

        with pytest.raises(ValueError, match="Liquid Clustering cannot be combined"):
            _apply_platform_optimization_overrides(
                unified,
                sorted_ingestion_mode=None,
                sorted_ingestion_method=None,
                parsed_platform_options={"databricks_clustering_strategy": "liquid_clustering_auto"},
            )

    def test_strategy_override_resets_stale_physical_rendering_id(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        # A liquid template carries physical_rendering_id=databricks_liquid_auto; overriding to z_order must drop
        # it so the reported rendering identity follows the authoritative strategy instead of diverging.
        unified = UnifiedTuningConfiguration()
        unified.platform_optimizations.databricks_clustering_strategy = "liquid_clustering_auto"
        unified.platform_optimizations.liquid_clustering_enabled = True
        unified.platform_optimizations.physical_rendering_id = "databricks_liquid_auto"

        _apply_platform_optimization_overrides(
            unified,
            sorted_ingestion_mode=None,
            sorted_ingestion_method=None,
            parsed_platform_options={"databricks_clustering_strategy": "z_order"},
        )

        assert unified.platform_optimizations.databricks_clustering_strategy == "z_order"
        assert unified.platform_optimizations.liquid_clustering_enabled is False
        assert unified.platform_optimizations.physical_rendering_id is None

    def test_sorted_ingestion_validation_is_preserved(self):
        from benchbox.cli.commands.run import _apply_platform_optimization_overrides
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        unified = UnifiedTuningConfiguration()

        with pytest.raises(
            ValueError, match="--sorted-ingestion-method requires --sorted-ingestion-mode auto or force"
        ):
            _apply_platform_optimization_overrides(
                unified,
                sorted_ingestion_mode="off",
                sorted_ingestion_method="ctas",
                parsed_platform_options={},
            )


# ===================================================================
# _render_post_run_charts
# ===================================================================


class TestRenderPostRunCharts:
    def test_quiet_mode_skips(self):
        from benchbox.cli.commands.run import _render_post_run_charts

        mock_result = MagicMock()
        mock_console = MagicMock()
        _render_post_run_charts(mock_result, mock_console, quiet=True)
        mock_console.print.assert_not_called()

    def test_empty_query_results_skips(self):
        from benchbox.cli.commands.run import _render_post_run_charts

        mock_result = MagicMock()
        mock_result.query_results = []
        mock_console = MagicMock()
        _render_post_run_charts(mock_result, mock_console, quiet=False)
        mock_console.print.assert_not_called()

    def test_renders_charts(self):
        from benchbox.cli.commands.run import _render_post_run_charts

        mock_result = MagicMock()
        mock_result.query_results = [MagicMock()]
        mock_console = MagicMock()

        mock_summary = MagicMock()
        mock_summary.charts = ["chart1", "chart2"]

        with patch(
            "benchbox.core.visualization.post_run_summary.generate_post_run_summary",
            return_value=mock_summary,
        ):
            _render_post_run_charts(mock_result, mock_console, quiet=False)
        assert mock_console.print.call_count == 2

    def test_exception_swallowed(self):
        from benchbox.cli.commands.run import _render_post_run_charts

        mock_result = MagicMock()
        mock_result.query_results = [MagicMock()]
        mock_console = MagicMock()

        with patch(
            "benchbox.core.visualization.post_run_summary.generate_post_run_summary",
            side_effect=ImportError("no module"),
        ):
            _render_post_run_charts(mock_result, mock_console, quiet=False)
        # Should not raise


# ===================================================================
# _direct_handle_result
# ===================================================================


class TestDirectHandleResult:
    def test_partial_query_failure_exports_but_exits_and_skips_publish(self):
        from benchbox.cli.commands.run import _direct_handle_result

        ctx = MagicMock()
        ctx.exit.side_effect = SystemExit
        settings = SimpleNamespace(
            ctx=ctx,
            quiet=False,
            benchmark="tpch",
            scale=0.01,
            platform="duckdb",
            resolved_mode="sql",
            publish=True,
            publish_target="benchmark_runs/published",
            publish_label="maintainer-run",
            tuning="notuning",
            phases_to_run=["power"],
            compress_data=False,
            compression_type="none",
            compression_level=None,
            test_execution_type="power",
            seed=None,
            output=None,
            table_mode="standard",
        )
        result = SimpleNamespace(
            validation_status="PARTIAL",
            total_queries=2,
            successful_queries=1,
            failed_queries=1,
        )
        benchmark_config = SimpleNamespace(concurrency=1)

        with (
            patch.object(
                _run_module, "_export_orchestrated_result", return_value={"json": "/tmp/result.json"}
            ) as export,
            patch.object(_run_module, "_render_post_run_charts") as render_charts,
            patch("benchbox.cli.preferences.save_last_run_config") as save_last_run,
            patch("benchbox.cli.commands.publish.publish_bundle") as publish_bundle,
            pytest.raises(SystemExit),
        ):
            _direct_handle_result(settings, result, MagicMock(), benchmark_config)

        export.assert_called_once()
        render_charts.assert_called_once()
        save_last_run.assert_called_once()
        publish_bundle.assert_not_called()
        ctx.exit.assert_called_once_with(1)


# ===================================================================
# _describe_platform_options
# ===================================================================


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestDescribePlatformOptions:
    def test_no_options(self):
        from benchbox.cli.commands.run import _describe_platform_options

        with patch.object(_run_module, "console") as mock_console:
            with patch(
                "benchbox.cli.platform_hooks.PlatformHookRegistry.describe_options",
                return_value=[],
            ):
                _describe_platform_options(["duckdb"])
        # Should print "no platform-specific options registered"
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("no platform-specific options registered" in c for c in calls)

    def test_with_options(self):
        from benchbox.cli.commands.run import _describe_platform_options

        with patch.object(_run_module, "console") as mock_console:
            with patch(
                "benchbox.cli.platform_hooks.PlatformHookRegistry.describe_options",
                return_value=["memory_limit: Set memory limit", "threads: Set thread count"],
            ):
                _describe_platform_options(["duckdb"])
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("memory_limit" in c for c in calls)


# ===================================================================
# setup_verbose_logging
# ===================================================================


class TestSetupVerboseLogging:
    def test_quiet_mode(self):
        from benchbox.cli.commands.run import setup_verbose_logging

        logger_result, settings = setup_verbose_logging(verbose=0, quiet=True)
        assert logger_result is None
        assert settings.quiet is True

    def test_verbose_level_1(self):
        from benchbox.cli.commands.run import setup_verbose_logging

        logger_result, settings = setup_verbose_logging(verbose=1, quiet=False)
        assert logger_result is not None
        assert settings.verbose_enabled is True
        assert settings.very_verbose is False

    def test_verbose_level_2(self):
        from benchbox.cli.commands.run import setup_verbose_logging

        logger_result, settings = setup_verbose_logging(verbose=2, quiet=False)
        assert logger_result is not None
        assert settings.very_verbose is True

    def test_no_verbose_no_quiet(self):
        from benchbox.cli.commands.run import setup_verbose_logging

        logger_result, settings = setup_verbose_logging(verbose=0, quiet=False)
        assert logger_result is None
        assert settings.quiet is False
        assert settings.verbose_enabled is False

    def test_verbosity_settings_passthrough(self):
        from benchbox.cli.commands.run import setup_verbose_logging
        from benchbox.utils.verbosity import VerbositySettings

        vs = VerbositySettings.from_flags(2, False)
        logger_result, settings = setup_verbose_logging(verbose=vs, quiet=False)
        assert settings is vs
        assert logger_result is not None

    def test_verbosity_settings_quiet_override(self):
        from benchbox.cli.commands.run import setup_verbose_logging
        from benchbox.utils.verbosity import VerbositySettings

        vs = VerbositySettings.from_flags(1, False)
        logger_result, settings = setup_verbose_logging(verbose=vs, quiet=True)
        assert settings.quiet is True


# ===================================================================
# CLI exceptions: ErrorHandler branch coverage
# ===================================================================


class TestErrorHandlerBranches:
    def test_handle_database_error(self):
        from benchbox.cli.exceptions import DatabaseError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = DatabaseError("connection refused", include_version=False)
        ctx = ErrorContext(operation="load", stage="connect", database_type="duckdb")
        handler.handle_error(err, ctx)

    def test_handle_database_error_postgresql(self):
        from benchbox.cli.exceptions import DatabaseError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = DatabaseError("connection refused", include_version=False)
        ctx = ErrorContext(operation="load", stage="connect", database_type="postgresql")
        handler.handle_error(err, ctx)

    def test_handle_execution_error_tpch(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler, ExecutionError

        handler = ErrorHandler(console=MagicMock())
        err = ExecutionError("out of memory", include_version=False)
        ctx = ErrorContext(operation="power", stage="query", benchmark_name="tpch")
        handler.handle_error(err, ctx)

    def test_handle_execution_error_no_benchmark(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler, ExecutionError

        handler = ErrorHandler(console=MagicMock())
        err = ExecutionError("timeout", include_version=False)
        ctx = ErrorContext(operation="power", stage="query")
        handler.handle_error(err, ctx)

    def test_handle_validation_error(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler, ValidationError

        handler = ErrorHandler(console=MagicMock())
        err = ValidationError("bad input", include_version=False)
        ctx = ErrorContext(operation="validate", stage="input")
        handler.handle_error(err, ctx)

    def test_handle_cloud_storage_error_s3(self):
        from benchbox.cli.exceptions import CloudStorageError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = CloudStorageError("access denied", details={"provider": "s3"}, include_version=False)
        ctx = ErrorContext(operation="upload", stage="transfer")
        handler.handle_error(err, ctx)

    def test_handle_cloud_storage_error_gcs(self):
        from benchbox.cli.exceptions import CloudStorageError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = CloudStorageError("not found", details={"provider": "gs"}, include_version=False)
        ctx = ErrorContext(operation="upload", stage="transfer")
        handler.handle_error(err, ctx)

    def test_handle_cloud_storage_error_azure(self):
        from benchbox.cli.exceptions import CloudStorageError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = CloudStorageError("forbidden", details={"provider": "azure"}, include_version=False)
        ctx = ErrorContext(operation="upload", stage="transfer")
        handler.handle_error(err, ctx)

    def test_handle_platform_error(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler, PlatformError

        handler = ErrorHandler(console=MagicMock())
        err = PlatformError("driver missing", include_version=False)
        ctx = ErrorContext(operation="connect", stage="init")
        handler.handle_error(err, ctx)

    def test_handle_generic_cli_error(self):
        from benchbox.cli.exceptions import BenchboxCLIError, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = BenchboxCLIError("generic", include_version=False)
        handler.handle_error(err)

    def test_handle_generic_error_with_traceback(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = RuntimeError("unexpected")
        ctx = ErrorContext(operation="run", stage="execute", include_version_info=False)
        handler.handle_error(err, ctx, show_traceback=True)

    def test_handle_cli_error_with_traceback(self):
        from benchbox.cli.exceptions import BenchboxCLIError, ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = BenchboxCLIError("test error", include_version=False)
        ctx = ErrorContext(operation="run", stage="test", include_version_info=False)
        handler.handle_error(err, ctx, show_traceback=True)

    def test_handle_error_with_version_details(self):
        from benchbox.cli.exceptions import BenchboxCLIError, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        err = BenchboxCLIError(
            "test",
            details={"version_warning": "mismatch", "version_info": "1.0"},
            include_version=False,
        )
        handler.handle_error(err)

    def test_show_context_with_source_location(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        ctx = ErrorContext(
            operation="run",
            stage="test",
            source_file="/path/to/benchbox/core/test.py",
            source_line=42,
            source_function="my_function",
            include_version_info=False,
        )
        handler._show_context_info(ctx)

    def test_show_context_non_benchbox_source(self):
        from benchbox.cli.exceptions import ErrorContext, ErrorHandler

        handler = ErrorHandler(console=MagicMock())
        ctx = ErrorContext(
            operation="run",
            stage="test",
            source_file="/some/other/path/module.py",
            source_line=10,
            include_version_info=False,
        )
        handler._show_context_info(ctx)


# ===================================================================
# ValidationRules
# ===================================================================


class TestValidationRules:
    def test_validate_scale_factor_negative(self):
        from benchbox.cli.exceptions import ValidationError, ValidationRules

        with pytest.raises(ValidationError):
            ValidationRules.validate_scale_factor(-1.0)

    def test_validate_scale_factor_zero(self):
        from benchbox.cli.exceptions import ValidationError, ValidationRules

        with pytest.raises(ValidationError):
            ValidationRules.validate_scale_factor(0.0)

    def test_validate_scale_factor_too_large(self):
        from benchbox.cli.exceptions import ValidationError, ValidationRules

        with pytest.raises(ValidationError, match="very large"):
            ValidationRules.validate_scale_factor(200.0)

    def test_validate_scale_factor_valid(self):
        from benchbox.cli.exceptions import ValidationRules

        ValidationRules.validate_scale_factor(1.0)  # should not raise

    def test_validate_benchmark_name_empty(self):
        from benchbox.cli.exceptions import ValidationError, ValidationRules

        with pytest.raises(ValidationError):
            ValidationRules.validate_benchmark_name("", ["tpch", "tpcds"])

    def test_validate_benchmark_name_unknown(self):
        from benchbox.cli.exceptions import ValidationError, ValidationRules

        with pytest.raises(ValidationError, match="Unknown benchmark"):
            ValidationRules.validate_benchmark_name("nonexistent", ["tpch", "tpcds"])

    def test_validate_benchmark_name_case_insensitive(self):
        from benchbox.cli.exceptions import ValidationRules

        ValidationRules.validate_benchmark_name("TPCH", ["tpch", "tpcds"])

    def test_validate_output_directory_local(self, tmp_path):
        from benchbox.cli.exceptions import ValidationRules

        out = str(tmp_path / "new_dir")
        ValidationRules.validate_output_directory(out)
        assert (tmp_path / "new_dir").exists()

    def test_validate_output_directory_cloud(self):
        from benchbox.cli.exceptions import CloudStorageError, ValidationRules

        with patch("benchbox.utils.cloud_storage.is_cloud_path", return_value=True):
            with patch(
                "benchbox.utils.cloud_storage.validate_cloud_credentials",
                return_value={"valid": False, "provider": "s3", "error": "no creds", "env_vars": ["AWS_ACCESS_KEY_ID"]},
            ):
                with pytest.raises(CloudStorageError):
                    ValidationRules.validate_output_directory("s3://bucket/path")


# ===================================================================
# ErrorContext
# ===================================================================


class TestErrorContext:
    def test_basic_creation(self):
        from benchbox.cli.exceptions import ErrorContext

        ctx = ErrorContext(operation="run", stage="init", include_version_info=False)
        assert ctx.operation == "run"
        assert ctx.stage == "init"
        assert ctx.benchmark_name is None

    def test_with_all_fields(self):
        from benchbox.cli.exceptions import ErrorContext

        ctx = ErrorContext(
            operation="run",
            stage="power",
            benchmark_name="tpch",
            database_type="duckdb",
            user_input={"scale": 1.0},
            include_version_info=False,
        )
        assert ctx.benchmark_name == "tpch"
        assert ctx.database_type == "duckdb"


# ===================================================================
# BenchboxCLIError source location
# ===================================================================


class TestBenchboxCLIErrorSourceLocation:
    def test_captures_source_location(self):
        from benchbox.cli.exceptions import BenchboxCLIError

        err = BenchboxCLIError("test", include_version=False)
        assert err.source_file is not None
        assert err.source_line is not None
        assert os.path.basename(err.source_file) == "test_run_command_branches.py"

    def test_with_details(self):
        from benchbox.cli.exceptions import BenchboxCLIError

        err = BenchboxCLIError("test", details={"key": "value"}, include_version=False)
        assert err.details["key"] == "value"

    def test_configuration_error(self):
        from benchbox.cli.exceptions import ConfigurationError

        err = ConfigurationError("bad config", include_version=False)
        assert err.message == "bad config"
        assert err.source_file is not None


# ===================================================================
# create_error_handler
# ===================================================================


class TestCreateErrorHandler:
    def test_default(self):
        from benchbox.cli.exceptions import ErrorHandler, create_error_handler

        handler = create_error_handler()
        assert isinstance(handler, ErrorHandler)

    def test_with_console(self):
        from benchbox.cli.exceptions import ErrorHandler, create_error_handler

        mock = MagicMock()
        handler = create_error_handler(mock)
        assert isinstance(handler, ErrorHandler)
        assert handler.console is mock


# ===================================================================
# run command branch coverage
# ===================================================================


class TestRunCommandBranchCoverage:
    def setup_method(self):
        self.runner = CliRunner()
        self._orig_non_interactive = os.environ.get("BENCHBOX_NON_INTERACTIVE")

    def teardown_method(self):
        if self._orig_non_interactive is None:
            os.environ.pop("BENCHBOX_NON_INTERACTIVE", None)
        else:
            os.environ["BENCHBOX_NON_INTERACTIVE"] = self._orig_non_interactive

    def test_official_with_seed_and_platform_option_without_platform(self):
        from benchbox.cli.commands.run import run

        result = self.runner.invoke(
            run,
            [
                "--official",
                "--scale",
                "1",
                "--seed",
                "7",
                "--benchmark",
                "tpch",
                "--phases",
                "generate",
                "--platform-option",
                "threads=4",
            ],
            obj={},
        )

        assert result.exit_code == 1
        assert "Platform options require a --platform selection" in result.output

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    def test_platform_option_parse_error_logs_and_exits(self):
        from benchbox.cli.commands.run import PlatformOptionError, run

        with patch.object(_run_module.PlatformHookRegistry, "parse_options") as parse_options:
            parse_options.side_effect = PlatformOptionError("invalid option")
            result = self.runner.invoke(
                run,
                [
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--phases",
                    "generate",
                    "--platform-option",
                    "threads=4",
                    "--verbose",
                ],
                obj={},
            )

        assert result.exit_code == 1
        assert "invalid option" in result.output

    def test_non_interactive_missing_required_args(self):
        from benchbox.cli.commands.run import run

        result = self.runner.invoke(
            run,
            [
                "--non-interactive",
                "--verbose",
                "--phases",
                "load",
            ],
            obj={},
        )

        assert result.exit_code == 2
        assert "Non-interactive mode requires all parameters" in result.output


# ===================================================================
# _derive_execution_type  (regression tests for operator-precedence fix)
# ===================================================================


class TestDeriveExecutionType:
    """Unit tests for _derive_execution_type.

    These cover the operator-precedence bug that was fixed in the
    load_only and data_only branches (previously `not set(phases) & X`
    parsed as `not ((set(phases) & X[0]) | X[1])`, always returning False
    for non-empty sets).
    """

    @pytest.fixture(autouse=True)
    def _import(self):
        from benchbox.cli.commands.run import _derive_execution_type

        self.fn = _derive_execution_type

    # --- query-phase branch ---
    @pytest.mark.parametrize(
        ("phases", "expected"),
        [
            (["power"], "power"),
            (["throughput"], "throughput"),
            (["maintenance"], "maintenance"),
            (["power", "throughput"], "combined"),
            (["power", "maintenance"], "combined"),
        ],
    )
    def test_query_phases(self, phases, expected):
        assert self.fn(phases) == expected

    # --- load_only branch (was affected by precedence bug) ---
    @pytest.mark.parametrize(
        "phases",
        [
            ["load"],
            ["generate", "load"],  # generate present but load present → not data_only
            ["load", "warmup"],
            ["load", "statistics"],  # statistics is not a query phase → still load_only
            ["generate", "load", "statistics"],
        ],
    )
    def test_load_only(self, phases):
        assert self.fn(phases) == "load_only"

    # --- data_only branch (was affected by precedence bug) ---
    @pytest.mark.parametrize(
        "phases",
        [
            ["generate"],
            ["generate", "warmup"],  # previously misclassified as "standard"
        ],
    )
    def test_data_only(self, phases):
        assert self.fn(phases) == "data_only"

    # --- generate with load or query phases → not data_only ---
    @pytest.mark.parametrize(
        "phases",
        [
            ["generate", "load"],
            ["generate", "power"],
            ["generate", "throughput"],
            ["generate", "maintenance"],
        ],
    )
    def test_generate_with_load_or_query_not_data_only(self, phases):
        assert self.fn(phases) != "data_only"

    # --- fallback ---
    def test_standard_fallback(self):
        assert self.fn(["warmup"]) == "standard"
        assert self.fn(["load", "power"]) == "power"
