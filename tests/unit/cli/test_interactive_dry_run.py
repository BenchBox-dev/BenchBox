"""Tests for interactive wizard functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from benchbox.cli.benchmarks import (
    BenchmarkConfig,
    get_platform_format_recommendation,
    prompt_capture_plans,
    prompt_force_regeneration,
    prompt_official_mode,
    prompt_output_location,
    prompt_phases,
    prompt_platform_options,
    prompt_query_subset,
    prompt_seed,
    prompt_table_format,
    prompt_table_mode,
    prompt_validation_mode,
    prompt_verbose_output,
)
from benchbox.cli.dryrun import display_interactive_preview, generate_cli_command

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGenerateCLICommand:
    """Tests for generate_cli_command function."""

    def test_basic_command(self):
        """Test basic command generation with required params only."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.01,  # Default scale - should not appear
        )
        assert "benchbox run" in cmd
        assert "--platform duckdb" in cmd
        assert "--benchmark tpch" in cmd
        assert "--scale" not in cmd  # Default value omitted

    def test_non_default_scale(self):
        """Test that non-default scale factor is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
        )
        assert "--scale 0.1" in cmd

    def test_phases_included(self):
        """Test that phases are included when not default."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=1.0,
            phases=["generate", "load", "power"],
        )
        assert "--phases generate,load,power" in cmd

    def test_default_phases_omitted(self):
        """Test that default phases (power) are omitted."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=1.0,
            phases=["power"],
        )
        assert "--phases" not in cmd

    def test_queries_included(self):
        """Test that query subset is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            queries=["Q1", "Q6", "Q17"],
        )
        assert "--queries Q1,Q6,Q17" in cmd

    def test_tuning_included(self):
        """Test that tuning mode is included when not default."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            tuning="tuned",
        )
        assert "--tuning tuned" in cmd

    def test_default_tuning_omitted(self):
        """Test that default tuning (notuning) is omitted."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            tuning="notuning",
        )
        assert "--tuning" not in cmd

    def test_seed_included(self):
        """Test that seed is included when specified."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            seed=42,
        )
        assert "--seed 42" in cmd

    def test_output_included(self):
        """Test that output directory is included."""
        cmd = generate_cli_command(
            platform="snowflake",
            benchmark="tpch",
            scale=1.0,
            output="s3://bucket/path",
        )
        assert "--output s3://bucket/path" in cmd

    def test_table_format_included(self):
        """Test that table format is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            table_format="iceberg",
        )
        assert "--table-format iceberg" in cmd

    def test_compression_included(self):
        """Test that compression is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            compression="zstd:9",
        )
        assert "--compression zstd:9" in cmd

    def test_mode_included(self):
        """Test that execution mode is included."""
        cmd = generate_cli_command(
            platform="polars",
            benchmark="tpch",
            scale=0.1,
            mode="dataframe",
        )
        assert "--mode dataframe" in cmd

    def test_table_mode_included(self):
        """Test that table mode is included when specified."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            table_mode="external",
        )
        assert "--table-mode external" in cmd

    def test_table_mode_native_omitted(self):
        """Native table mode (default) should be omitted from equivalent command."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            table_mode="native",
        )
        assert "--table-mode" not in cmd

    def test_force_included(self):
        """Test that force mode is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            force="datagen",
        )
        assert "--force datagen" in cmd

    def test_official_flag(self):
        """Test that official flag is included."""
        cmd = generate_cli_command(
            platform="snowflake",
            benchmark="tpch",
            scale=100,
            official=True,
        )
        assert "--official" in cmd

    def test_capture_plans_flag(self):
        """Test that capture-plans flag is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            capture_plans=True,
        )
        assert "--capture-plans" in cmd

    def test_validation_included(self):
        """Test that validation mode is included."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            validation="full",
        )
        assert "--validation full" in cmd

    def test_full_command_with_all_options(self):
        """Test command generation with all options specified."""
        cmd = generate_cli_command(
            platform="snowflake",
            benchmark="tpcds",
            scale=10,
            phases=["generate", "load", "power", "throughput"],
            queries=["Q1", "Q2", "Q3"],
            tuning="tuned",
            seed=12345,
            output="s3://bucket/benchmark-data",
            table_format="iceberg:zstd",
            compression="zstd:9",
            mode="sql",
            force="all",
            official=True,
            capture_plans=True,
            validation="full",
        )
        assert "--platform snowflake" in cmd
        assert "--benchmark tpcds" in cmd
        assert "--scale 10" in cmd
        assert "--phases generate,load,power,throughput" in cmd
        assert "--queries Q1,Q2,Q3" in cmd
        assert "--tuning tuned" in cmd
        assert "--seed 12345" in cmd
        assert "--output s3://bucket/benchmark-data" in cmd
        assert "--table-format iceberg:zstd" in cmd
        assert "--compression zstd:9" in cmd
        assert "--mode sql" in cmd
        assert "--force all" in cmd
        assert "--official" in cmd
        assert "--capture-plans" in cmd
        assert "--validation full" in cmd

    def test_multiline_formatting(self):
        """Test that command uses proper multiline formatting."""
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.1,
            tuning="tuned",
            seed=42,
        )
        # Check for line continuation characters
        assert "\\\n" in cmd


class TestDisplayInteractivePreview:
    """Tests for display_interactive_preview function."""

    def _create_mock_database_config(self, platform_type="duckdb", execution_mode="sql"):
        """Create a mock database config for testing."""

        class MockDatabaseConfig:  # noqa: B903 - test stub, not domain model
            def __init__(self):
                self.type = platform_type
                self.execution_mode = execution_mode

        return MockDatabaseConfig()

    def _create_mock_benchmark_config(
        self,
        name="tpch",
        display_name="TPC-H",
        scale_factor=0.1,
        queries=None,
        compress_data=True,
        compression_type="zstd",
        compression_level=None,
        options=None,
    ):
        """Create a mock benchmark config for testing."""
        config = BenchmarkConfig(
            name=name,
            display_name=display_name,
            scale_factor=scale_factor,
            queries=queries,
            compress_data=compress_data,
            compression_type=compression_type,
            compression_level=compression_level,
            options=options or {},
        )
        return config

    def test_basic_preview_output(self):
        """Test that basic preview shows expected elements."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config()

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = output.getvalue()
        assert "Configuration Preview" in result
        assert "DUCKDB" in result
        assert "TPC-H" in result
        assert "power" in result
        assert "Table Mode:" in result
        assert "native" in result
        assert "benchbox run" in result

    def test_preview_with_all_options(self):
        """Test preview with all options specified."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config(platform_type="snowflake")
        bench_config = self._create_mock_benchmark_config(
            name="tpcds",
            display_name="TPC-DS",
            scale_factor=10,
            options={"estimated_time_range": (30, 60)},
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["generate", "load", "power"],
            output="s3://bucket/path",
            tuning="tuned",
            seed=42,
            console_obj=console,
        )

        result = output.getvalue()
        assert "SNOWFLAKE" in result
        assert "TPC-DS" in result
        assert "10" in result
        assert "generate" in result
        assert "tuned" in result
        assert "42" in result
        assert "s3://bucket/path" in result
        assert "30-60 minutes" in result

    def test_preview_shows_cli_command(self):
        """Test that preview shows equivalent CLI command."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(scale_factor=0.5)

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        # Strip ANSI escape codes for assertions
        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "Equivalent CLI command" in result
        assert "--platform duckdb" in result
        assert "--benchmark tpch" in result
        assert "--scale 0.5" in result
        assert "--table-mode" not in result  # native is default, omitted

    def test_preview_external_table_mode_reflected(self):
        """Preview table and command should reflect external table mode."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(scale_factor=0.5)

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            table_mode="external",
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "Table Mode:" in result
        assert "external" in result
        assert "--table-mode external" in result

    def test_preview_with_query_subset(self):
        """Test preview with query subset specified."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            queries=["Q1", "Q6", "Q17"],
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = output.getvalue()
        assert "3 selected" in result

    def test_preview_with_compression(self):
        """Test preview with compression settings."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            compress_data=True,
            compression_type="zstd",
            compression_level=9,
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = output.getvalue()
        assert "zstd:9" in result

    def test_preview_with_execution_mode(self):
        """Test preview shows execution mode."""
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config(
            platform_type="polars",
            execution_mode="dataframe",
        )
        bench_config = self._create_mock_benchmark_config()

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = output.getvalue()
        assert "POLARS" in result
        assert "dataframe mode" in result

    def test_preview_shows_table_format_in_table(self):
        """Table Format row appears when table_format is in benchmark options."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            options={"table_format": "iceberg", "table_format_compression": "zstd"},
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["generate", "load", "power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "Table Format:" in result
        assert "Iceberg" in result
        assert "zstd" in result

    def test_preview_shows_table_format_in_cli_command(self):
        """Equivalent CLI command includes --table-format when format is set."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            options={"table_format": "parquet", "table_format_compression": "snappy"},
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--table-format parquet" in result

    def test_preview_omits_format_when_not_set(self):
        """No Table Format row when table_format is absent from options."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config()

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "Table Format:" not in result
        assert "--table-format" not in result

    def test_preview_cli_command_includes_tuning_when_set(self):
        """CLI command in preview should include --tuning when tuning is specified."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config()

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["generate", "load", "power"],
            tuning="tuned",
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--tuning tuned" in result

    def test_preview_cli_command_omits_tuning_when_none(self):
        """CLI command should not include --tuning when tuning is None."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config()

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            tuning=None,
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--tuning" not in result

    def test_preview_cli_command_includes_compression(self):
        """CLI command should include --compression when compress_data is set."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            compress_data=True,
            compression_type="zstd",
            compression_level=3,
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--compression zstd:3" in result

    def test_preview_cli_command_includes_all_configured_options(self):
        """CLI command should include tuning, table-mode, table-format, and compression."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        db_config = self._create_mock_database_config()
        bench_config = self._create_mock_benchmark_config(
            scale_factor=1.0,
            compress_data=True,
            compression_type="zstd",
            compression_level=3,
            options={"table_format": "iceberg"},
        )

        display_interactive_preview(
            database_config=db_config,
            benchmark_config=bench_config,
            phases=["generate", "load", "power"],
            table_mode="external",
            tuning="tuned",
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--tuning tuned" in result
        assert "--table-mode external" in result
        assert "--table-format iceberg" in result
        assert "--compression zstd:3" in result


class TestDisplayInteractivePreviewAllParams:
    """Integration test: display_interactive_preview with all params set."""

    def test_preview_cli_command_includes_all_new_params(self):
        """CLI command output should contain every new flag when all params are set."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)

        class MockDB:
            type = "databricks"
            execution_mode = "sql"

        bench_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=1.0,
            compress_data=True,
            compression_type="zstd",
            compression_level=9,
            options={"table_format": "delta", "table_format_compression": "zstd"},
        )

        display_interactive_preview(
            database_config=MockDB(),
            benchmark_config=bench_config,
            phases=["generate", "load", "power"],
            output="s3://bucket/data",
            table_mode="external",
            tuning="tuned",
            seed=42,
            force="all",
            official=True,
            capture_plans=True,
            validation="full",
            verbose=2,
            console_obj=console,
            platform_options={
                "driver_version": "1.2.0",
                "databricks_clustering_strategy": "liquid_clustering",
                "liquid_clustering_columns": "col1,col2",
            },
            plan_config="sample:0.1,first:5",
            presort="delta-sorted",
            sorted_ingestion_mode="force",
            sorted_ingestion_method="z_order",
            global_cache=True,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())

        # All original params
        assert "--platform databricks" in result
        assert "--benchmark tpch" in result
        assert "--scale 1.0" in result
        assert "--phases generate,load,power" in result
        assert "--tuning tuned" in result
        assert "--seed 42" in result
        assert "--table-mode external" in result
        assert "--table-format delta:zstd" in result
        assert "--compression zstd:9" in result
        assert "--force all" in result
        assert "--official" in result
        assert "--capture-plans" in result
        assert "--validation full" in result
        assert "-vv" in result

        # All new params
        assert "--platform-option driver_version=1.2.0" in result
        assert "--plan-config sample:0.1,first:5" in result
        assert "--presort delta-sorted" in result
        assert "--sorted-ingestion-mode force" in result
        assert "--sorted-ingestion-method z_order" in result
        assert "--platform-option databricks_clustering_strategy=liquid_clustering" in result
        assert "--platform-option liquid_clustering_columns=col1,col2" in result
        assert "--global-cache" in result

    def test_preview_compression_zstd_not_dropped(self):
        """Regression: --compression zstd should appear when compress_data=True."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)

        class MockDB:
            type = "duckdb"
            execution_mode = "sql"

        bench_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
            compress_data=True,
            compression_type="zstd",
            compression_level=None,
        )

        display_interactive_preview(
            database_config=MockDB(),
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--compression zstd" in result

    def test_preview_table_format_with_compression_suffix(self):
        """--table-format should include :compression when not snappy."""
        import re

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)

        class MockDB:
            type = "duckdb"
            execution_mode = "sql"

        bench_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
            compress_data=False,
            options={"table_format": "iceberg", "table_format_compression": "zstd"},
        )

        display_interactive_preview(
            database_config=MockDB(),
            benchmark_config=bench_config,
            phases=["power"],
            console_obj=console,
        )

        result = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
        assert "--table-format iceberg:zstd" in result


class TestPromptPhases:
    """Tests for prompt_phases function."""

    @pytest.mark.parametrize(
        ("responses", "expected"),
        [
            (["1"], ["power"]),
            (["2"], ["generate", "load", "power"]),
            (["3"], ["generate"]),
            (["4"], ["load"]),
            (["5"], ["generate", "load", "warmup", "power", "throughput", "maintenance"]),
            # Numeric menu after statistics was inserted at position 3:
            # 1=generate 2=load 3=statistics 4=warmup 5=power.
            (["6", "1,2,5"], ["generate", "load", "power"]),
            (["6", "1,2,3"], ["generate", "load", "statistics"]),
            (["6", "generate,power,throughput"], ["generate", "power", "throughput"]),
            (["6", "power,power,load,power"], ["power", "load"]),
            (["6", ""], ["power"]),
        ],
    )
    def test_prompt_phases_mappings(self, monkeypatch, responses, expected):
        """Test preset and custom phase mappings."""
        response_iter = iter(responses)
        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", lambda *_args, **_kwargs: next(response_iter))
        assert prompt_phases() == expected

    def test_phases_out_of_range_input_explains_and_points_to_query_step(self, monkeypatch):
        """Out-of-range input (e.g. '37') must show typed value and point user to the query step."""
        rendered_lines: list[str] = []
        monkeypatch.setattr(
            "benchbox.cli.benchmarks.console.print",
            lambda *args, **_kwargs: rendered_lines.append(str(args[0]) if args else ""),
        )
        # First answer "6" to enter custom mode, then "37" (intending Query 37)
        response_iter = iter(["6", "37"])
        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", lambda *_args, **_kwargs: next(response_iter))

        result = prompt_phases()

        assert result == ["power"]
        joined = "\n".join(rendered_lines)
        # Up-front guidance distinguishing phase numbers from query numbers
        assert "not query numbers" in joined
        assert "power or standard" in joined.lower()
        # Fallback echoes the typed input
        assert "'37'" in joined
        # Fallback points the user to the query step
        assert "query selection" in joined.lower()


class TestPromptTableMode:
    """Tests for prompt_table_mode function."""

    def test_select_native(self, monkeypatch):
        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", lambda *_args, **_kwargs: "1")
        assert prompt_table_mode() == "native"

    def test_select_external(self, monkeypatch):
        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", lambda *_args, **_kwargs: "2")
        assert prompt_table_mode() == "external"

    def test_default_fallback_for_invalid_default(self, monkeypatch):
        def _ask(*_args, **kwargs):
            assert kwargs.get("default") == "1"
            return "1"

        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", _ask)
        assert prompt_table_mode(default_mode="unknown") == "native"

    def test_external_default_label_rendered(self, monkeypatch):
        rendered_lines = []

        monkeypatch.setattr(
            "benchbox.cli.benchmarks.console.print",
            lambda *args, **_kwargs: rendered_lines.append(str(args[0]) if args else ""),
        )
        monkeypatch.setattr("benchbox.cli.benchmarks.Prompt.ask", lambda *_args, **_kwargs: "2")

        assert prompt_table_mode(default_mode="external") == "external"
        assert any("external (default)" in line for line in rendered_lines)
        assert not any("native (default)" in line for line in rendered_lines)


class TestPromptQuerySubset:
    """Tests for prompt_query_subset function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_run_all_queries(self, mock_confirm):
        """Test running all queries."""
        mock_confirm.return_value = True
        result = prompt_query_subset("tpch", 22)
        assert result is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_query_subset(self, mock_confirm, mock_prompt):
        """Test selecting a query subset."""
        mock_confirm.return_value = False
        mock_prompt.return_value = "Q1,Q6,Q17"
        result = prompt_query_subset("tpch", 22)
        assert result == ["Q1", "Q6", "Q17"]

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_query_subset_with_numbers(self, mock_confirm, mock_prompt):
        """Test selecting queries using numbers."""
        mock_confirm.return_value = False
        mock_prompt.return_value = "1,6,17"
        result = prompt_query_subset("tpch", 22)
        assert result == ["Q1", "Q6", "Q17"]

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_empty_selection_returns_none(self, mock_confirm, mock_prompt):
        """Test that empty selection returns None (all queries)."""
        mock_confirm.return_value = False
        mock_prompt.return_value = ""
        result = prompt_query_subset("tpch", 22)
        assert result is None


class TestPromptOfficialMode:
    """Tests for prompt_official_mode function."""

    def test_non_tpc_benchmark_returns_false(self):
        """Test that non-TPC benchmarks return False."""
        result, adjusted_scale = prompt_official_mode("ssb", 0.1)
        assert result is False
        assert adjusted_scale is None

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_official_mode(self, mock_confirm):
        """Test declining official mode."""
        mock_confirm.return_value = False
        result, adjusted_scale = prompt_official_mode("tpch", 0.1)
        assert result is False
        assert adjusted_scale is None

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_enable_with_compliant_scale(self, mock_confirm):
        """Test enabling official mode with compliant scale factor."""
        mock_confirm.return_value = True
        result, adjusted_scale = prompt_official_mode("tpch", 10.0)
        assert result is True
        assert adjusted_scale is None  # No adjustment needed

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_non_compliant_scale_adjusts_to_nearest(self, mock_confirm):
        """Test non-compliant scale factor is adjusted to nearest."""
        mock_confirm.side_effect = [True, True]  # Enable official, accept nearest
        result, adjusted_scale = prompt_official_mode("tpch", 0.1)
        assert result is True
        assert adjusted_scale == 1.0  # Nearest TPC-allowed scale

    @patch("benchbox.cli.benchmarks.FloatPrompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_non_compliant_scale_custom_entry(self, mock_confirm, mock_float):
        """Test entering custom TPC-compliant scale factor."""
        mock_confirm.side_effect = [True, False]  # Enable official, decline nearest
        mock_float.return_value = 100.0  # Enter TPC-compliant scale
        result, adjusted_scale = prompt_official_mode("tpch", 0.1)
        assert result is True
        assert adjusted_scale == 100.0


class TestPromptSeed:
    """Tests for prompt_seed function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_no_seed_selected(self, mock_confirm):
        """Test declining to set a seed."""
        mock_confirm.return_value = False
        result = prompt_seed()
        assert result is None

    @patch("benchbox.cli.benchmarks.IntPrompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_seed_selected(self, mock_confirm, mock_int_prompt):
        """Test setting a specific seed."""
        mock_confirm.return_value = True
        mock_int_prompt.return_value = 42
        result = prompt_seed()
        assert result == 42

    @patch("benchbox.cli.benchmarks.IntPrompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_custom_seed_value(self, mock_confirm, mock_int_prompt):
        """Test entering a custom seed value."""
        mock_confirm.return_value = True
        mock_int_prompt.return_value = 12345
        result = prompt_seed()
        assert result == 12345


class TestPromptForceRegeneration:
    """Tests for prompt_force_regeneration function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_force_regeneration(self, mock_confirm):
        """Test declining force regeneration returns None."""
        mock_confirm.return_value = False
        result = prompt_force_regeneration()
        assert result is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_force_all(self, mock_confirm, mock_prompt):
        """Test selecting force all option."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "1"
        result = prompt_force_regeneration()
        assert result == "all"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_force_datagen(self, mock_confirm, mock_prompt):
        """Test selecting force datagen option."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "2"
        result = prompt_force_regeneration()
        assert result == "datagen"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_force_upload(self, mock_confirm, mock_prompt):
        """Test selecting force upload option."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "3"
        result = prompt_force_regeneration()
        assert result == "upload"


class TestPromptValidationMode:
    """Tests for prompt_validation_mode function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_validation_config(self, mock_confirm):
        """Test declining validation configuration returns None."""
        mock_confirm.return_value = False
        result = prompt_validation_mode()
        assert result is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_exact_validation(self, mock_confirm, mock_prompt):
        """Test selecting exact validation mode."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "1"
        result = prompt_validation_mode()
        assert result == "exact"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_loose_validation(self, mock_confirm, mock_prompt):
        """Test selecting loose validation mode."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "2"
        result = prompt_validation_mode()
        assert result == "loose"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_range_validation(self, mock_confirm, mock_prompt):
        """Test selecting range validation mode."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "3"
        result = prompt_validation_mode()
        assert result == "range"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_disabled_validation(self, mock_confirm, mock_prompt):
        """Test selecting disabled validation mode."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "4"
        result = prompt_validation_mode()
        assert result == "disabled"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_full_validation(self, mock_confirm, mock_prompt):
        """Test selecting full validation mode."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "5"
        result = prompt_validation_mode()
        assert result == "full"


class TestPromptCapturePlans:
    """Tests for prompt_capture_plans function."""

    def test_unsupported_platform_returns_false(self):
        """Test unsupported platform returns False without prompting."""
        # Snowflake doesn't support plan capture
        result = prompt_capture_plans("snowflake")
        assert result is False

    def test_unsupported_platform_sqlite(self):
        """Test SQLite (unsupported) returns False."""
        result = prompt_capture_plans("sqlite")
        assert result is False

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_supported_platform_decline(self, mock_confirm):
        """Test declining plan capture for supported platform."""
        mock_confirm.return_value = False
        result = prompt_capture_plans("duckdb")
        assert result is False

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_supported_platform_accept(self, mock_confirm):
        """Test accepting plan capture for supported platform."""
        mock_confirm.return_value = True
        result = prompt_capture_plans("duckdb")
        assert result is True

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_postgresql_supported(self, mock_confirm):
        """Test PostgreSQL is supported."""
        mock_confirm.return_value = True
        result = prompt_capture_plans("postgresql")
        assert result is True

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_datafusion_supported(self, mock_confirm):
        """Test DataFusion is supported."""
        mock_confirm.return_value = True
        result = prompt_capture_plans("datafusion")
        assert result is True

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_case_insensitive(self, mock_confirm):
        """Test platform name is case insensitive."""
        mock_confirm.return_value = True
        result = prompt_capture_plans("DuckDB")
        assert result is True


class TestPromptOutputLocation:
    """Tests for prompt_output_location function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_custom_output(self, mock_confirm):
        """Test declining custom output returns None."""
        mock_confirm.return_value = False
        result = prompt_output_location()
        assert result is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_empty_path_returns_none(self, mock_confirm, mock_prompt):
        """Test empty path input returns None."""
        mock_confirm.return_value = True
        mock_prompt.return_value = ""
        result = prompt_output_location()
        assert result is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_valid_existing_path(self, mock_confirm, mock_prompt):
        """Test valid existing path is returned."""
        from pathlib import Path

        mock_confirm.return_value = True
        mock_prompt.return_value = "/tmp"
        result = prompt_output_location()
        # Path resolves symlinks, so /tmp may become /private/tmp on macOS
        expected = str(Path("/tmp").resolve())
        assert result == expected

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_tilde_expansion(self, mock_confirm, mock_prompt):
        """Test tilde (~) is expanded to home directory."""
        import os

        mock_confirm.return_value = True
        mock_prompt.return_value = "~"
        result = prompt_output_location()
        assert result == os.path.expanduser("~")

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_path_with_subdirectory(self, mock_confirm, mock_prompt):
        """Test path with subdirectory under existing parent."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "/tmp/benchbox_test_output"
        result = prompt_output_location()
        # Use Path for cross-platform path comparison
        assert "benchbox_test_output" in result

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_nonexistent_parent_declined(self, mock_confirm, mock_prompt):
        """Test declining to create nonexistent parent returns None."""
        mock_confirm.side_effect = [True, False]  # Yes to custom, No to create
        mock_prompt.return_value = "/nonexistent_parent_xyz/output"
        result = prompt_output_location()
        assert result is None


class TestGetPlatformFormatRecommendation:
    """Tests for get_platform_format_recommendation function."""

    def test_databricks_recommends_delta(self):
        """Test Databricks recommends Delta Lake."""
        fmt, reason = get_platform_format_recommendation("databricks")
        assert fmt == "delta"
        assert "Delta" in reason

    def test_snowflake_recommends_iceberg(self):
        """Test Snowflake recommends Iceberg."""
        fmt, reason = get_platform_format_recommendation("snowflake")
        assert fmt == "iceberg"
        assert "Iceberg" in reason

    def test_duckdb_recommends_parquet(self):
        """Test DuckDB recommends Parquet."""
        fmt, reason = get_platform_format_recommendation("duckdb")
        assert fmt == "parquet"
        assert "Parquet" in reason

    def test_postgresql_no_format_support(self):
        """Test PostgreSQL returns no format recommendation."""
        fmt, reason = get_platform_format_recommendation("postgresql")
        assert fmt is None
        assert "native" in reason.lower()

    def test_sqlite_no_format_support(self):
        """Test SQLite returns no format recommendation."""
        fmt, reason = get_platform_format_recommendation("sqlite")
        assert fmt is None

    def test_case_insensitive(self):
        """Test platform name is case insensitive."""
        fmt1, _ = get_platform_format_recommendation("DuckDB")
        fmt2, _ = get_platform_format_recommendation("duckdb")
        assert fmt1 == fmt2 == "parquet"

    def test_unknown_platform_defaults_to_parquet(self):
        """Test unknown platform defaults to Parquet."""
        fmt, reason = get_platform_format_recommendation("unknown_platform")
        assert fmt == "parquet"
        assert "widely compatible" in reason


class TestPromptTableFormat:
    """Tests for prompt_table_format function."""

    def test_unsupported_platform_returns_none(self):
        """Test unsupported platform returns None without prompting."""
        result = prompt_table_format("postgresql")
        assert result == (None, None)

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_configure_format(self, mock_confirm):
        """Test declining format configuration returns None."""
        mock_confirm.return_value = False
        result = prompt_table_format("duckdb")
        assert result == (None, None)

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_csv(self, mock_confirm, mock_prompt):
        """Test selecting CSV format."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "1"  # CSV
        fmt, compression = prompt_table_format("duckdb")
        assert fmt is None
        assert compression is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_parquet_with_compression(self, mock_confirm, mock_prompt):
        """Test selecting Parquet with compression."""
        mock_confirm.return_value = True
        # Parquet=2, zstd=2 (parquet options: snappy=1, zstd=2, gzip=3, none=4)
        mock_prompt.side_effect = ["2", "2"]
        fmt, compression = prompt_table_format("duckdb")
        assert fmt == "parquet"
        assert compression == "zstd"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_vortex(self, mock_confirm, mock_prompt):
        """Test selecting Vortex."""
        mock_confirm.return_value = True
        # Vortex=3, zstd=1 (vortex options: zstd=1, lz4=2, none=3)
        mock_prompt.side_effect = ["3", "1"]
        fmt, compression = prompt_table_format("duckdb")
        assert fmt == "vortex"
        assert compression == "zstd"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_delta(self, mock_confirm, mock_prompt):
        """Test selecting Delta Lake."""
        mock_confirm.return_value = True
        # Delta=4, snappy=1 (delta options: snappy=1, zstd=2, none=3)
        mock_prompt.side_effect = ["4", "1"]
        fmt, compression = prompt_table_format("databricks")
        assert fmt == "delta"
        assert compression == "snappy"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_select_iceberg(self, mock_confirm, mock_prompt):
        """Test selecting Iceberg."""
        mock_confirm.return_value = True
        # Iceberg=5, zstd=1 (iceberg options: zstd=1, snappy=2, gzip=3, none=4)
        mock_prompt.side_effect = ["5", "1"]
        fmt, compression = prompt_table_format("snowflake")
        assert fmt == "iceberg"
        assert compression == "zstd"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_no_compression(self, mock_confirm, mock_prompt):
        """Test selecting format with no compression."""
        mock_confirm.return_value = True
        # Parquet=2, none=4 (parquet options: snappy=1, zstd=2, gzip=3, none=4)
        mock_prompt.side_effect = ["2", "4"]
        fmt, compression = prompt_table_format("duckdb")
        assert fmt == "parquet"
        assert compression is None

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_format_and_compression_returned_separately(self, mock_confirm, mock_prompt):
        """Format and compression must be separate values, not combined as 'iceberg:zstd'.

        The runner expects table_format='iceberg' and table_format_compression='zstd'
        as separate keys in benchmark_config.options. A combined string would fail
        the allowed_formats validation in _run_format_conversion().
        """
        mock_confirm.return_value = True
        mock_prompt.side_effect = ["5", "1"]  # Iceberg + zstd
        fmt, compression = prompt_table_format("snowflake")

        # Format must be a plain name without colon - runner validates against {"parquet", "vortex", "delta", "iceberg"}
        assert fmt == "iceberg"
        assert ":" not in fmt
        assert compression == "zstd"

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_all_formats_return_valid_runner_names(self, mock_confirm, mock_prompt):
        """Every format returned by prompt_table_format must be in the runner's allowed set."""
        allowed_formats = {"parquet", "vortex", "delta", "iceberg"}
        format_choices = {"2": "parquet", "3": "vortex", "4": "delta", "5": "iceberg"}

        for choice, expected_fmt in format_choices.items():
            mock_confirm.return_value = True
            mock_prompt.side_effect = [choice, "1"]  # format + first compression option
            fmt, _ = prompt_table_format("duckdb")
            assert fmt in allowed_formats, f"Format '{fmt}' from choice {choice} not in runner's allowed set"
            assert fmt == expected_fmt


class TestPromptVerboseOutput:
    """Tests for prompt_verbose_output function."""

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_verbose(self, mock_confirm):
        """Test declining verbose returns 0."""
        mock_confirm.return_value = False
        result = prompt_verbose_output()
        assert result == 0

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_verbose_level_1(self, mock_confirm, mock_prompt):
        """Test selecting verbose level 1."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "1"
        result = prompt_verbose_output()
        assert result == 1

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_verbose_level_2_debug(self, mock_confirm, mock_prompt):
        """Test selecting debug level 2."""
        mock_confirm.return_value = True
        mock_prompt.return_value = "2"
        result = prompt_verbose_output()
        assert result == 2


class TestPromptPlatformOptions:
    """Tests for prompt_platform_options function."""

    def test_unknown_platform_returns_empty(self):
        """Test unknown platform with no registered options returns empty dict."""
        # Use a platform name that definitely has no options
        result = prompt_platform_options("unknown_platform_xyz")
        assert result == {}

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_decline_configure(self, mock_confirm):
        """Test declining configuration returns empty dict."""
        mock_confirm.return_value = False
        result = prompt_platform_options("duckdb")
        assert result == {}

    @patch("benchbox.cli.benchmarks.Prompt.ask")
    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_duckdb_memory_limit(self, mock_confirm, mock_prompt):
        """Test configuring DuckDB memory limit."""
        mock_confirm.return_value = True
        # DuckDB has: memory_limit, temp_directory, threads (sorted alphabetically)
        # Each needs a value; threads uses special handling for None
        mock_prompt.side_effect = [
            "16GB",  # memory_limit
            "",  # temp_directory (empty = default)
            "",  # threads (empty = auto/None)
        ]
        result = prompt_platform_options("duckdb")
        assert "memory_limit" in result
        assert result["memory_limit"] == "16GB"

    @patch("benchbox.cli.benchmarks.Confirm.ask")
    def test_case_insensitive_platform(self, mock_confirm):
        """Test platform name is case insensitive."""
        mock_confirm.return_value = False
        # Should not raise even with mixed case
        result = prompt_platform_options("DuckDB")
        assert isinstance(result, dict)


class TestExecutionModeSelection:
    """Tests for execution mode selection in DatabaseManager."""

    @patch("benchbox.cli.database.Prompt.ask")
    def test_sql_mode_selection(self, mock_ask):
        """Test selecting SQL mode."""
        from benchbox.cli.database import DatabaseManager

        manager = DatabaseManager()
        mock_ask.return_value = "1"  # Select SQL
        mode = manager._prompt_execution_mode("polars", "sql")
        assert mode == "sql"

    @patch("benchbox.cli.database.Prompt.ask")
    def test_dataframe_mode_selection(self, mock_ask):
        """Test selecting DataFrame mode."""
        from benchbox.cli.database import DatabaseManager

        manager = DatabaseManager()
        mock_ask.return_value = "2"  # Select DataFrame
        mode = manager._prompt_execution_mode("polars", "sql")
        assert mode == "dataframe"

    @patch("benchbox.cli.database.Prompt.ask")
    def test_default_mode_used(self, mock_ask):
        """Test that default mode is correctly passed."""
        from benchbox.cli.database import DatabaseManager

        manager = DatabaseManager()
        # Default for pyspark is dataframe, so choice "2" should be default
        mock_ask.return_value = "2"
        mode = manager._prompt_execution_mode("pyspark", "dataframe")
        assert mode == "dataframe"


class TestRunCommandImportIntegrity:
    """Tests to verify run command imports don't have scoping issues.

    These tests catch bugs like self-referential imports that shadow
    module-level imports (e.g., the ForceConfig bug in commit 8b08b497).
    """

    def test_composite_param_classes_accessible(self):
        """Verify all composite param classes are accessible at module level."""
        from benchbox.cli.commands.run import (
            CompressionConfig,
            ForceConfig,
            PlanCaptureConfig,
            TableFormatConfig,
            ValidationConfig,
        )

        # Instantiate each to verify they're properly imported
        force = ForceConfig()
        assert force.datagen is False
        assert force.upload is False

        compression = CompressionConfig()
        assert compression.enabled is True

        convert = TableFormatConfig()
        assert convert.format == "parquet"

        plan = PlanCaptureConfig()
        assert plan.strict is False

        validation = ValidationConfig()
        assert validation.mode == "exact"

    def test_run_function_importable(self):
        """Verify run function can be imported without errors."""
        from benchbox.cli.commands.run import run

        # Verify it's a click command
        assert hasattr(run, "callback")
        assert callable(run.callback)

    def test_no_self_referential_imports_in_run_module(self):
        """Verify run.py doesn't import from itself (causes UnboundLocalError)."""
        import ast
        from pathlib import Path

        run_path = Path(__file__).parent.parent.parent.parent / "benchbox/cli/commands/run.py"
        source = run_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        self_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "benchbox.cli.commands.run" in node.module:
                    self_imports.append(f"line {node.lineno}: from {node.module} import ...")

        assert not self_imports, f"Self-referential imports found: {self_imports}"
