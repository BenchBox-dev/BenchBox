"""Tests for ExecutionContext model for reproducibility.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.schemas import ExecutionContext

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestExecutionContextDefaults:
    """Test ExecutionContext default values."""

    def test_default_entry_point_is_python_api(self):
        """Default entry point should be python_api."""
        ctx = ExecutionContext()
        assert ctx.entry_point == "python_api"

    def test_default_phases_is_power(self):
        """Default phases should be ['power']."""
        ctx = ExecutionContext()
        assert ctx.phases == ["power"]

    def test_default_mode_is_sql(self):
        """Default mode should be sql."""
        ctx = ExecutionContext()
        assert ctx.mode == "sql"

    def test_default_compression_disabled(self):
        """Compression should be disabled by default."""
        ctx = ExecutionContext()
        assert ctx.compression_enabled is False
        assert ctx.compression_type == "none"

    def test_default_flags_are_false(self):
        """All boolean flags should default to False."""
        ctx = ExecutionContext()
        assert ctx.official is False
        assert ctx.force_datagen is False
        assert ctx.force_upload is False
        assert ctx.capture_plans is False
        assert ctx.strict_plan_capture is False
        assert ctx.non_interactive is False


class TestExecutionContextSerialization:
    """Test ExecutionContext serialization with model_dump()."""

    def test_model_dump_includes_all_fields(self):
        """model_dump() should include all fields."""
        ctx = ExecutionContext(
            entry_point="cli",
            phases=["load", "power"],
            seed=42,
        )
        data = ctx.model_dump()

        assert data["entry_point"] == "cli"
        assert data["phases"] == ["load", "power"]
        assert data["seed"] == 42
        assert "invocation_timestamp" in data

    def test_model_dump_roundtrip(self):
        """Should be able to recreate from model_dump()."""
        original = ExecutionContext(
            entry_point="mcp",
            phases=["generate", "load", "power"],
            seed=123,
            compression_enabled=True,
            compression_type="zstd",
            compression_level=9,
            mode="dataframe",
            official=True,
            validation_mode="full",
            force_datagen=True,
            query_subset=["1", "6", "17"],
            capture_plans=True,
            non_interactive=True,
            tuning_mode="tuned",
        )
        data = original.model_dump()

        # Remove timestamp for cleaner comparison
        data.pop("invocation_timestamp", None)

        recreated = ExecutionContext(**data)

        assert recreated.entry_point == original.entry_point
        assert recreated.phases == original.phases
        assert recreated.seed == original.seed
        assert recreated.compression_enabled == original.compression_enabled
        assert recreated.compression_type == original.compression_type
        assert recreated.compression_level == original.compression_level
        assert recreated.mode == original.mode
        assert recreated.official == original.official
        assert recreated.validation_mode == original.validation_mode
        assert recreated.force_datagen == original.force_datagen
        assert recreated.query_subset == original.query_subset
        assert recreated.capture_plans == original.capture_plans
        assert recreated.non_interactive == original.non_interactive
        assert recreated.tuning_mode == original.tuning_mode


class TestToCliArgs:
    """Test ExecutionContext.to_cli_args() method."""

    def test_default_context_returns_empty_args(self):
        """Default context should return empty args list."""
        ctx = ExecutionContext()
        args = ctx.to_cli_args()
        assert args == []

    def test_phases_non_default(self):
        """Non-default phases should be included."""
        ctx = ExecutionContext(phases=["load", "power"])
        args = ctx.to_cli_args()
        assert "--phases" in args
        assert "load,power" in args

    def test_phases_default_not_included(self):
        """Default phases should not be included."""
        ctx = ExecutionContext(phases=["power"])
        args = ctx.to_cli_args()
        assert "--phases" not in args

    def test_seed_included(self):
        """Seed should be included when set."""
        ctx = ExecutionContext(seed=42)
        args = ctx.to_cli_args()
        assert "--seed" in args
        assert "42" in args

    def test_compression_with_level(self):
        """Compression with level should format correctly."""
        ctx = ExecutionContext(
            compression_enabled=True,
            compression_type="zstd",
            compression_level=9,
        )
        args = ctx.to_cli_args()
        assert "--compression" in args
        assert "zstd:9" in args

    def test_compression_without_level(self):
        """Compression without level should format correctly."""
        ctx = ExecutionContext(
            compression_enabled=True,
            compression_type="gzip",
        )
        args = ctx.to_cli_args()
        assert "--compression" in args
        assert "gzip" in args

    def test_dataframe_mode_included(self):
        """Non-sql mode should be included."""
        ctx = ExecutionContext(mode="dataframe")
        args = ctx.to_cli_args()
        assert "--mode" in args
        assert "dataframe" in args

    def test_sql_mode_not_included(self):
        """Default sql mode should not be included."""
        ctx = ExecutionContext(mode="sql")
        args = ctx.to_cli_args()
        assert "--mode" not in args

    def test_official_flag(self):
        """Official flag should be included."""
        ctx = ExecutionContext(official=True)
        args = ctx.to_cli_args()
        assert "--official" in args

    def test_validation_mode(self):
        """Validation mode should be included."""
        ctx = ExecutionContext(validation_mode="full")
        args = ctx.to_cli_args()
        assert "--validation" in args
        assert "full" in args

    def test_force_datagen_only(self):
        """Force datagen only should format correctly."""
        ctx = ExecutionContext(force_datagen=True)
        args = ctx.to_cli_args()
        assert "--force" in args
        assert "datagen" in args

    def test_force_upload_only(self):
        """Force upload only should format correctly."""
        ctx = ExecutionContext(force_upload=True)
        args = ctx.to_cli_args()
        assert "--force" in args
        assert "upload" in args

    def test_force_both(self):
        """Force both should format correctly."""
        ctx = ExecutionContext(force_datagen=True, force_upload=True)
        args = ctx.to_cli_args()
        assert "--force" in args
        assert "datagen,upload" in args

    def test_query_subset(self):
        """Query subset should be included."""
        ctx = ExecutionContext(query_subset=["1", "6", "17"])
        args = ctx.to_cli_args()
        assert "--queries" in args
        assert "1,6,17" in args

    def test_capture_plans(self):
        """Capture plans flag should be included."""
        ctx = ExecutionContext(capture_plans=True)
        args = ctx.to_cli_args()
        assert "--capture-plans" in args

    def test_strict_plan_capture(self):
        """Strict plan capture should be included in plan config."""
        ctx = ExecutionContext(strict_plan_capture=True)
        args = ctx.to_cli_args()
        assert "--plan-config" in args
        assert "strict:true" in args

    def test_non_interactive(self):
        """Non-interactive flag should be included."""
        ctx = ExecutionContext(non_interactive=True)
        args = ctx.to_cli_args()
        assert "--non-interactive" in args

    def test_tuning_mode(self):
        """Tuning mode should be included when not notuning."""
        ctx = ExecutionContext(tuning_mode="tuned")
        args = ctx.to_cli_args()
        assert "--tuning" in args
        assert "tuned" in args

    def test_tuning_mode_notuning_round_trips_explicit_request(self):
        """Explicit notuning must remain distinct from an absent tuning flag."""
        ctx = ExecutionContext(tuning_mode="notuning")
        args = ctx.to_cli_args()
        assert args[-2:] == ["--tuning", "notuning"]

        absent = ExecutionContext()
        assert "--tuning" not in absent.to_cli_args()

    def test_tuning_path_round_trips_byte_for_byte(self):
        tuning_path = "/tmp/custom tuning/profile.yaml"

        assert ExecutionContext(tuning_mode=tuning_path).to_cli_args()[-2:] == ["--tuning", tuning_path]


class TestToCliString:
    """Test ExecutionContext.to_cli_string() method."""

    def test_basic_command(self):
        """Basic command should include platform, benchmark, scale."""
        ctx = ExecutionContext()
        cmd = ctx.to_cli_string("duckdb", "tpch", 1.0)
        assert cmd == "benchbox run --platform duckdb --benchmark tpch --scale 1.0"

    def test_command_with_options(self):
        """Command with options should include all flags."""
        ctx = ExecutionContext(
            phases=["load", "power"],
            seed=42,
        )
        cmd = ctx.to_cli_string("duckdb", "tpch", 0.01)
        assert "--platform duckdb" in cmd
        assert "--benchmark tpch" in cmd
        assert "--scale 0.01" in cmd
        assert "--phases load,power" in cmd
        assert "--seed 42" in cmd

    def test_full_command(self):
        """Full command with many options should be valid."""
        ctx = ExecutionContext(
            entry_point="cli",
            phases=["generate", "load", "power"],
            seed=123,
            compression_enabled=True,
            compression_type="zstd",
            compression_level=9,
            official=True,
            validation_mode="full",
            force_datagen=True,
            query_subset=["1", "6"],
            capture_plans=True,
            non_interactive=True,
            tuning_mode="tuned",
        )
        cmd = ctx.to_cli_string("snowflake", "tpcds", 100)

        assert "benchbox run" in cmd
        assert "--platform snowflake" in cmd
        assert "--benchmark tpcds" in cmd
        assert "--scale 100" in cmd
        assert "--phases generate,load,power" in cmd
        assert "--seed 123" in cmd
        assert "--compression zstd:9" in cmd
        assert "--official" in cmd
        assert "--validation full" in cmd
        assert "--force datagen" in cmd
        assert "--queries 1,6" in cmd
        assert "--capture-plans" in cmd
        assert "--non-interactive" in cmd
        assert "--tuning tuned" in cmd


class TestExecutionContextEntryPoints:
    """Test different entry point scenarios."""

    def test_cli_entry_point(self):
        """CLI entry point should be accepted."""
        ctx = ExecutionContext(entry_point="cli")
        assert ctx.entry_point == "cli"

    def test_mcp_entry_point(self):
        """MCP entry point should be accepted."""
        ctx = ExecutionContext(entry_point="mcp")
        assert ctx.entry_point == "mcp"

    def test_python_api_entry_point(self):
        """Python API entry point should be accepted."""
        ctx = ExecutionContext(entry_point="python_api")
        assert ctx.entry_point == "python_api"

    def test_invalid_entry_point_rejected(self):
        """Invalid entry point should be rejected."""
        with pytest.raises(ValueError):
            ExecutionContext(entry_point="invalid")


class TestExecutionContextModes:
    """Test execution mode validation."""

    def test_sql_mode(self):
        """SQL mode should be accepted."""
        ctx = ExecutionContext(mode="sql")
        assert ctx.mode == "sql"

    def test_dataframe_mode(self):
        """DataFrame mode should be accepted."""
        ctx = ExecutionContext(mode="dataframe")
        assert ctx.mode == "dataframe"

    def test_invalid_mode_rejected(self):
        """Invalid mode should be rejected."""
        with pytest.raises(ValueError):
            ExecutionContext(mode="invalid")


class TestExecutionContextStrictValidation:
    """Test strict validation (extra='forbid')."""

    def test_unknown_field_rejected(self):
        """Unknown fields should be rejected due to extra='forbid'."""
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ExecutionContext(unknown_field="value")

    def test_unknown_nested_field_rejected(self):
        """Unknown fields should be rejected even with valid fields."""
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ExecutionContext(entry_point="cli", invalid_option=True)
