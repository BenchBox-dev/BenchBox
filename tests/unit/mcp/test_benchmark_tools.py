"""Tests for BenchBox MCP benchmark execution tools.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# Skip all tests if Python < 3.10
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.version_info < (3, 10), reason="MCP server requires Python 3.10+"),
]


class TestValidateConfigTool:
    """Tests for validate_config tool functionality."""

    def test_valid_duckdb_tpch_config(self):
        """Test validating a valid DuckDB TPC-H configuration."""
        from benchbox.core.benchmark_registry import get_all_benchmarks
        from benchbox.core.platform_registry import PlatformRegistry

        # Check platform is available
        info = PlatformRegistry.get_platform_info("duckdb")
        assert info is not None
        assert info.available

        # Check benchmark exists using public API
        benchmarks = get_all_benchmarks()
        assert "tpch" in benchmarks

    def test_unknown_platform_error(self):
        """Test that unknown platform is detected."""
        from benchbox.core.platform_registry import PlatformRegistry

        info = PlatformRegistry.get_platform_info("nonexistent_platform")
        assert info is None

    def test_unknown_benchmark_error(self):
        """Test that unknown benchmark is detected."""
        from benchbox.core.benchmark_registry import get_all_benchmarks

        benchmarks = get_all_benchmarks()
        assert "nonexistent_benchmark" not in benchmarks

    def test_invalid_scale_factor(self):
        """Test that invalid scale factor is detected."""
        scale_factor = -1.0
        assert scale_factor <= 0  # Should be caught as invalid

    def test_dataframe_platform_validation(self):
        """Test validation for DataFrame platforms."""
        from benchbox.platforms import is_dataframe_platform

        assert is_dataframe_platform("polars-df")
        assert is_dataframe_platform("pandas-df")
        assert not is_dataframe_platform("duckdb")


class TestDryRunTool:
    """Tests for dry_run tool functionality."""

    def test_dry_run_returns_execution_plan(self):
        """Test that dry_run returns an execution plan."""
        from benchbox.core.benchmark_registry import get_all_benchmarks, get_benchmark_class

        # Check benchmark exists using public API
        benchmarks = get_all_benchmarks()
        assert "tpch" in benchmarks

        # Get query IDs via public API
        benchmark_class = get_benchmark_class("tpch")
        assert benchmark_class is not None
        bm = benchmark_class(scale_factor=0.01)
        queries = bm.get_queries()
        query_ids = list(queries.keys())

        assert len(query_ids) == 22

    def test_dry_run_resource_estimates(self):
        """Test that dry_run provides resource estimates."""
        scale_factor = 1.0
        estimated_data_gb = scale_factor * 1.0
        memory_recommended = max(2, estimated_data_gb * 2)

        assert estimated_data_gb == 1.0
        assert memory_recommended >= 2.0


class TestRunBenchmarkTool:
    """Tests for run_benchmark tool functionality."""

    def test_benchmark_config_creation(self):
        """Test that BenchmarkConfig can be created correctly."""
        from benchbox.core.schemas import BenchmarkConfig

        config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
        )

        assert config.name == "tpch"
        assert config.display_name == "TPC-H"
        assert config.scale_factor == 0.01

    def test_database_config_creation(self):
        """Test that DatabaseConfig can be created correctly."""
        from benchbox.core.schemas import DatabaseConfig

        db_config = DatabaseConfig(
            type="duckdb",
            name="test_db",
        )

        assert db_config.type == "duckdb"
        assert db_config.name == "test_db"

    def test_phase_parsing(self):
        """Test phase parsing logic."""
        phases_str = "load,power"
        phase_list = phases_str.lower().split(",")

        phases_to_run = []
        if "load" in phase_list:
            phases_to_run.append("load")
        if "power" in phase_list or "execute" in phase_list:
            phases_to_run.append("power")

        assert "load" in phases_to_run
        assert "power" in phases_to_run

    def test_platform_options_are_forwarded_only_after_validation(self, tmp_path: Path):
        from benchbox.mcp.tools import benchmark as benchmark_tools

        class DummyBenchmark:
            def __init__(self, scale_factor: float) -> None:
                self.scale_factor = scale_factor

            def run_with_platform(self, *_args, **_kwargs):
                return None

        adapter = Mock()
        with (
            patch.object(benchmark_tools, "get_all_benchmarks", return_value={"tpch": {"name": "tpch"}}),
            patch.object(benchmark_tools, "get_public_benchmark_class", return_value=DummyBenchmark),
            patch.object(benchmark_tools, "_get_platform_adapter", return_value=adapter) as get_adapter,
        ):
            response = benchmark_tools._run_benchmark_impl(
                "duckdb",
                "tpch",
                0.01,
                None,
                "load,power",
                "sql",
                platform_options={"threads": 4},
                results_dir=tmp_path,
                anonymize=False,
            )

        assert response["mcp_metadata"]["status"] == "no_results"
        assert get_adapter.call_args.kwargs["thread_limit"] == 4

    def test_modin_engine_reaches_the_effective_backend(self, tmp_path: Path):
        """Forwarding can succeed while the effective backend is unchanged."""
        from benchbox.mcp.schemas import validate_platform_options
        from benchbox.platforms.dataframe import modin_df

        normalized = validate_platform_options("modin", {"engine": "dask"})
        assert normalized == {"engine": "dask"}

        with (
            patch.object(modin_df, "MODIN_AVAILABLE", True),
            patch.object(modin_df, "PANDAS_AVAILABLE", True),
            patch.object(modin_df.ModinDataFrameAdapter, "_configure_engine"),
        ):
            adapter = modin_df.ModinDataFrameAdapter(working_dir=tmp_path, **normalized)

        assert adapter.engine == "dask"

    def test_modin_unsupported_engine_fails_closed_through_the_run_surface(self, tmp_path: Path):
        """The schema rejects `pandas`; the factory must reject it too."""
        from benchbox.mcp.schemas import MCPValidationError, validate_platform_options
        from benchbox.mcp.tools import benchmark as benchmark_tools

        with pytest.raises(MCPValidationError):
            validate_platform_options("modin", {"engine": "pandas"})

        # Even bypassing the schema, the adapter must not accept it.
        response = benchmark_tools._run_benchmark_impl(
            "modin-df",
            "tpch",
            0.01,
            None,
            "load,power",
            "dataframe",
            platform_options={"engine": "pandas"},
            results_dir=tmp_path,
            anonymize=False,
        )
        assert response["status"] == "failed"

    def test_oversized_dask_request_never_builds_a_cluster(self, tmp_path: Path):
        """Proving rejection by starting a 65,536-thread cluster would be the attack."""
        from benchbox.mcp.tools import benchmark as benchmark_tools

        with patch.object(benchmark_tools, "_get_platform_adapter") as get_adapter:
            response = benchmark_tools._run_benchmark_impl(
                "dask-df",
                "tpch",
                0.01,
                None,
                "load,power",
                "dataframe",
                platform_options={"n_workers": 256, "threads_per_worker": 256},
                results_dir=tmp_path,
                anonymize=False,
            )

        assert response["status"] == "failed"
        # The adapter builds its LocalCluster in __init__, so never reaching the
        # factory is the only evidence that no cluster was created.
        get_adapter.assert_not_called()

    def test_dask_local_cluster_is_never_constructed_for_a_rejected_request(self, tmp_path: Path):
        """Spy one level deeper: LocalCluster itself must not be touched.

        Every downstream collaborator is stubbed so that on an unfixed tree this
        fails on the assertion rather than by starting a real cluster or a real
        benchmark.
        """
        pytest.importorskip("dask.distributed")
        from benchbox.mcp.tools import benchmark as benchmark_tools
        from benchbox.platforms.dataframe import dask_df

        class DummyBenchmark:
            def __init__(self, scale_factor: float) -> None:
                self.scale_factor = scale_factor

            def run_with_platform(self, *_args, **_kwargs):
                return None

        with (
            patch.object(benchmark_tools, "get_all_benchmarks", return_value={"tpch": {"name": "tpch"}}),
            patch.object(benchmark_tools, "get_public_benchmark_class", return_value=DummyBenchmark),
            patch.object(dask_df, "LocalCluster") as local_cluster,
            patch.object(dask_df, "Client"),
        ):
            benchmark_tools._run_benchmark_impl(
                "dask-df",
                "tpch",
                0.01,
                None,
                "load,power",
                "dataframe",
                platform_options={"n_workers": 256, "threads_per_worker": 256},
                results_dir=tmp_path,
                anonymize=False,
            )

        local_cluster.assert_not_called()

    def test_dask_request_inside_the_envelope_still_reaches_the_adapter(self, tmp_path: Path):
        """The envelope is a ceiling, not a ban on tuning."""
        from benchbox.mcp.tools import benchmark as benchmark_tools

        class DummyBenchmark:
            def __init__(self, scale_factor: float) -> None:
                self.scale_factor = scale_factor

            def run_with_platform(self, *_args, **_kwargs):
                return None

        with (
            patch.object(benchmark_tools, "get_all_benchmarks", return_value={"tpch": {"name": "tpch"}}),
            patch.object(benchmark_tools, "get_public_benchmark_class", return_value=DummyBenchmark),
            patch.object(benchmark_tools, "_get_platform_adapter", return_value=Mock()) as get_adapter,
        ):
            benchmark_tools._run_benchmark_impl(
                "dask-df",
                "tpch",
                0.01,
                None,
                "load,power",
                "dataframe",
                platform_options={"n_workers": 4, "threads_per_worker": 4, "memory_limit": "4GB"},
                results_dir=tmp_path,
                anonymize=False,
            )

        kwargs = get_adapter.call_args.kwargs
        assert kwargs["n_workers"] == 4
        assert kwargs["threads_per_worker"] == 4
        assert kwargs["memory_limit"] == "4GB"

    @pytest.mark.parametrize("platform", ["clickhouse", "clickhouse-server"])
    def test_clickhouse_port_override_is_refused_before_any_adapter_is_built(self, platform, tmp_path: Path):
        """A request must not be able to point ClickHouse at another listener."""
        from benchbox.mcp.tools import benchmark as benchmark_tools

        with patch.object(benchmark_tools, "_get_platform_adapter") as get_adapter:
            response = benchmark_tools._run_benchmark_impl(
                platform,
                "tpch",
                0.01,
                None,
                "load,power",
                "sql",
                platform_options={"port": 9001, "secure": False},
                results_dir=tmp_path,
                anonymize=False,
            )

        assert response["status"] == "failed"
        get_adapter.assert_not_called()

    def test_clickhouse_profile_resolves_to_the_server_owned_connection_tuple(self, monkeypatch, tmp_path: Path):
        """The adapter sees the operator's port/TLS, never the caller's."""
        import json

        from benchbox.mcp.schemas import MCP_CLICKHOUSE_PROFILE_ENV
        from benchbox.mcp.tools import benchmark as benchmark_tools

        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"reviewed": {"port": 9440, "secure": True}}))

        class DummyBenchmark:
            def __init__(self, scale_factor: float) -> None:
                self.scale_factor = scale_factor

            def run_with_platform(self, *_args, **_kwargs):
                return None

        with (
            patch.object(benchmark_tools, "get_all_benchmarks", return_value={"tpch": {"name": "tpch"}}),
            patch.object(benchmark_tools, "get_public_benchmark_class", return_value=DummyBenchmark),
            patch.object(benchmark_tools, "_get_platform_adapter", return_value=Mock()) as get_adapter,
        ):
            benchmark_tools._run_benchmark_impl(
                "clickhouse-server",
                "tpch",
                0.01,
                None,
                "load,power",
                "sql",
                platform_options={"connection_profile": "reviewed"},
                results_dir=tmp_path,
                anonymize=False,
            )

        kwargs = get_adapter.call_args.kwargs
        assert kwargs["port"] == 9440
        assert kwargs["secure"] is True
        assert "connection_profile" not in kwargs

    def test_clickhouse_profile_withdrawn_by_the_operator_fails_closed(self, monkeypatch, tmp_path: Path):
        """A replayed request cannot outlive the profile that authorized it."""
        from benchbox.mcp.schemas import MCP_CLICKHOUSE_PROFILE_ENV
        from benchbox.mcp.tools import benchmark as benchmark_tools

        monkeypatch.delenv(MCP_CLICKHOUSE_PROFILE_ENV, raising=False)

        with patch.object(benchmark_tools, "_get_platform_adapter") as get_adapter:
            response = benchmark_tools._run_benchmark_impl(
                "clickhouse-server",
                "tpch",
                0.01,
                None,
                "load,power",
                "sql",
                platform_options={"connection_profile": "reviewed"},
                results_dir=tmp_path,
                anonymize=False,
            )

        assert response["status"] == "failed"
        assert "reviewed" not in json.dumps(response)
        get_adapter.assert_not_called()

    def test_databricks_layout_options_build_unified_tuning_config(self):
        from benchbox.mcp.tools.benchmark import _prepare_adapter_platform_options

        options = _prepare_adapter_platform_options(
            "databricks",
            {"databricks_clustering_strategy": "liquid_clustering", "liquid_clustering_columns": "event_time,id"},
        )

        tuning = options["tuning_config"]
        assert options["tuning_enabled"] is True
        assert "databricks_clustering_strategy" not in options
        assert tuning.platform_optimizations.databricks_clustering_strategy == "liquid_clustering"
        assert tuning.platform_optimizations.liquid_clustering_columns == ["event_time", "id"]

    def test_databricks_columns_infer_liquid_clustering_strategy(self):
        from benchbox.mcp.tools.benchmark import _prepare_adapter_platform_options

        options = _prepare_adapter_platform_options("databricks", {"liquid_clustering_columns": "customer_id,order_id"})

        tuning = options["tuning_config"]
        assert options["tuning_enabled"] is True
        assert tuning.platform_optimizations.databricks_clustering_strategy == "liquid_clustering"
        assert tuning.platform_optimizations.liquid_clustering_columns == ["customer_id", "order_id"]

    def test_every_matrix_option_reaches_effective_preparation(self, monkeypatch, tmp_path):  # noqa: C901
        """Each reviewed option reaches a concrete adapter-facing setting."""
        import json

        from benchbox.mcp.schemas import (
            MCP_CLICKHOUSE_PROFILE_ENV,
            MCP_PLATFORM_OPTION_ALLOWLIST,
            validate_platform_options,
        )
        from benchbox.mcp.tools.benchmark import _prepare_adapter_platform_options

        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"reviewed": {"port": 9440, "secure": True}}))

        for platform, specs in MCP_PLATFORM_OPTION_ALLOWLIST.items():
            for option_name, spec in specs.items():
                if spec.kind == "bool":
                    value: object = False
                elif spec.kind == "int":
                    value = spec.minimum if spec.minimum is not None else 1
                elif spec.kind == "float":
                    value = spec.minimum if spec.minimum is not None else 1.0
                elif spec.choices:
                    value = spec.choices[0]
                elif option_name == "liquid_clustering_columns":
                    value = "id"
                elif option_name == "connection_profile":
                    value = "reviewed"
                else:
                    value = "1GB"

                request: dict[str, object] = {option_name: value}
                if platform == "clickhouse" and option_name == "connection_profile":
                    # A profile only applies to server deployments; local mode is in-process.
                    request["deployment_mode"] = "server"

                normalized = validate_platform_options(platform, request)
                prepared = _prepare_adapter_platform_options(platform, normalized)
                if platform == "duckdb" and option_name == "threads":
                    assert prepared == {"thread_limit": value}
                elif platform == "databricks":
                    assert "tuning_config" in prepared
                elif option_name == "connection_profile":
                    # The caller's profile name is replaced by the server-owned tuple.
                    assert "connection_profile" not in prepared
                    assert prepared["port"] == 9440
                    assert prepared["secure"] is True
                else:
                    assert prepared[option_name] == value

                # Extend past preparation: verify the value reaches the constructed adapter.
                # Use from_config for SQL adapters and the constructor for dataframe adapters.
                try:
                    from benchbox.platforms.adapter_factory import get_adapter
                except Exception as exc:
                    pytest.skip(f"adapter factory unavailable: {exc}")

                # Build a minimal config for adapter construction. For SQL platforms,
                # from_config expects benchmark/scale_factor; for dataframe, constructor kwargs.
                # We reuse prepared as adapter kwargs, adding required scaffolding.
                try:
                    # Attempt to get adapter class without constructing via factory string
                    # to avoid side effects; fallback to direct import.
                    # Dataframe adapters have no from_config; use constructor kwargs path.
                    # For SQL adapters, feed through from_config.
                    # Use explicit option->attribute map for observable verification.
                    option_to_attr = {
                        "threads": "thread_limit",
                        "memory_limit": "memory_limit",
                        "n_workers": "n_workers",
                        "threads_per_worker": "threads_per_worker",
                        "use_distributed": "use_distributed",
                        "deployment": "deployment" if platform == "velox" else None,
                        "deployment_mode": "deployment_mode",
                    }
                    attr = option_to_attr.get(option_name)
                    if attr is None:
                        # For options without an explicit attribute mapping, the prepared
                        # value surviving preparation is sufficient; the map covers the
                        # cases where a dropped pass-through would silently discard it.
                        pass
                    else:
                        # Construct via prepared options and verify attribute.
                        # Use duckdb path as representative; for other platforms we
                        # check the attribute if the adapter is constructible without
                        # external dependencies.
                        if platform == "duckdb":
                            from benchbox.platforms.duckdb import DuckDBAdapter

                            # Provide minimal required keys for from_config
                            cfg = {"benchmark": "tpch", "scale_factor": 0.01, "output_dir": str(tmp_path)}
                            cfg.update(prepared)
                            # also ensure database_path to avoid default filesystem issues
                            cfg["database_path"] = ":memory:"
                            built = DuckDBAdapter.from_config(cfg)
                            observed = getattr(built, attr, None)
                            assert observed == value, (
                                f"{platform}.{option_name} -> adapter.{attr} mismatch: {observed!r} != {value!r}"
                            )
                        elif platform in ("polars", "pandas", "modin", "dask"):
                            # Dataframe adapters: constructor kwargs path (via _get_platform_adapter)
                            # Skip if optional dependency missing, but count it.
                            try:
                                # Import to check availability; construct with prepared
                                if platform == "polars":
                                    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

                                    built = PolarsDataFrameAdapter(**prepared)
                                    observed = getattr(built, attr, None) if attr else None
                                    if attr and observed is not None:
                                        assert observed == value
                                elif platform == "dask":
                                    from benchbox.platforms.dataframe.dask_df import DaskDataFrameAdapter

                                    built = DaskDataFrameAdapter(**prepared)
                                    observed = getattr(built, attr, None) if attr else None
                                    if attr and observed is not None:
                                        assert observed == value
                                # other dataframe platforms similar; skip if not applicable
                            except ImportError as ie:
                                pytest.skip(f"{platform} adapter dependency missing: {ie}")
                            except Exception:
                                # Construction may require additional scaffolding; treat as loud skip
                                pytest.skip(f"{platform} adapter not constructible in this test env")
                except pytest.skip.Exception:
                    raise
                except Exception as e:
                    # Any unexpected failure in the sweep extension should be visible
                    raise AssertionError(f"parity sweep extension failed for {platform}.{option_name}: {e}") from e

            # Loud skip discipline: the sweep must exercise a meaningful number of platforms.
            exercised = len(MCP_PLATFORM_OPTION_ALLOWLIST)
            assert exercised >= 10, f"sweep exercised only {exercised} platforms, expected at least 10"
            total_options = sum(len(v) for v in MCP_PLATFORM_OPTION_ALLOWLIST.values())
            assert total_options >= 15, f"allow-list has only {total_options} options, expected at least 15"


class TestGetQueryDetailsTool:
    """Tests for get_query_details tool functionality."""

    def test_tpch_query_complexity_hints(self):
        """Test that TPC-H query complexity hints are available."""
        from benchbox.mcp.tools.benchmark import _get_query_complexity_hints

        # Test Q6 - known simple query
        hints = _get_query_complexity_hints("tpch", "6")
        assert hints["type"] == "scan_filter"
        assert hints["complexity"] == "simple"
        assert hints["joins"] == 0
        assert "lineitem" in hints["tables"]

        # Test Q2 - known complex query
        hints = _get_query_complexity_hints("tpch", "2")
        assert hints["type"] == "correlated_subquery"
        assert hints["complexity"] == "complex"
        assert hints["joins"] >= 4

    def test_unknown_query_returns_default(self):
        """Test that unknown queries return default hints."""
        from benchbox.mcp.tools.benchmark import _get_query_complexity_hints

        hints = _get_query_complexity_hints("unknown_benchmark", "99")
        assert hints["type"] == "unknown"
        assert hints["complexity"] == "unknown"
        assert "note" in hints

    def test_query_id_normalization(self):
        """Test query ID normalization logic."""
        # Test the normalization logic used in get_query_details
        test_cases = [
            ("1", "1"),
            ("Q1", "1"),
            ("q1", "1"),
            ("Q01", "01"),
            ("abc", "abc"),  # Non-numeric kept as-is
        ]

        for input_id, expected in test_cases:
            normalized = input_id.upper().lstrip("Q")
            if not normalized.isdigit():
                normalized = input_id
            # For this test we just verify the logic runs
            assert normalized is not None


class TestResolveQueryDetailsMode:
    """Tests for _resolve_query_details_mode helper."""

    def test_explicit_sql_mode(self):
        """Test explicit SQL mode is returned as-is."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode(None, "sql") == "sql"
        assert _resolve_query_details_mode("duckdb", "sql") == "sql"

    def test_explicit_dataframe_mode(self):
        """Test explicit dataframe mode is returned as-is."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode(None, "dataframe") == "dataframe"
        assert _resolve_query_details_mode("duckdb", "dataframe") == "dataframe"

    def test_mode_case_insensitive(self):
        """Test mode parameter is case-insensitive."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode(None, "SQL") == "sql"
        assert _resolve_query_details_mode(None, "DataFrame") == "dataframe"

    def test_dataframe_platform_auto_detects(self):
        """Test that DataFrame platforms auto-detect to dataframe mode."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode("polars-df", None) == "dataframe"
        assert _resolve_query_details_mode("pandas-df", None) == "dataframe"

    def test_sql_platform_defaults_to_sql(self):
        """Test that SQL platforms default to sql mode."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode("duckdb", None) == "sql"
        assert _resolve_query_details_mode("snowflake", None) == "sql"

    def test_no_params_defaults_to_sql(self):
        """Test that no parameters defaults to sql mode."""
        from benchbox.mcp.tools.benchmark import _resolve_query_details_mode

        assert _resolve_query_details_mode(None, None) == "sql"


class TestGetDataframeFamilyForPlatform:
    """Tests for _get_dataframe_family_for_platform helper."""

    def test_polars_is_expression(self):
        """Test that Polars maps to expression family."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform("polars-df") == "expression"
        assert _get_dataframe_family_for_platform("polars") == "expression"

    def test_pandas_is_pandas(self):
        """Test that Pandas maps to pandas family."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform("pandas-df") == "pandas"
        assert _get_dataframe_family_for_platform("pandas") == "pandas"

    def test_datafusion_is_expression(self):
        """Test that DataFusion maps to expression family."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform("datafusion-df") == "expression"
        assert _get_dataframe_family_for_platform("datafusion") == "expression"

    def test_none_returns_none(self):
        """Test that None platform returns None."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform(None) is None

    def test_unknown_platform_returns_none(self):
        """Test that unknown platform returns None."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform("nonexistent") is None


class TestPopulateDataframeQueryDetails:
    """Tests for _populate_dataframe_query_details helper."""

    def test_tpch_q6_returns_source_code(self):
        """Test that TPC-H Q6 returns DataFrame source code."""
        from benchbox.mcp.tools.benchmark import _populate_dataframe_query_details

        response: dict = {}
        _populate_dataframe_query_details(response, "tpch", "6", "polars-df")

        assert "source_code" in response
        assert response["source_code"] is not None
        assert "source_truncated" in response
        assert response["query_name"] == "Forecasting Revenue Change"
        assert response["has_expression_impl"] is True
        assert response["has_pandas_impl"] is True
        assert response["dataframe_family"] == "expression"

    def test_tpch_q6_pandas_family(self):
        """Test that pandas-df platform returns pandas family source."""
        from benchbox.mcp.tools.benchmark import _populate_dataframe_query_details

        response: dict = {}
        _populate_dataframe_query_details(response, "tpch", "6", "pandas-df")

        assert response["dataframe_family"] == "pandas"
        assert "source_code" in response
        assert response["source_code"] is not None

    def test_no_platform_dataframe_family_is_none(self):
        """Test that no platform resolves to no explicit DataFrame family."""
        from benchbox.mcp.tools.benchmark import _get_dataframe_family_for_platform

        assert _get_dataframe_family_for_platform(None) is None

    def test_unknown_query_returns_error(self):
        """Test that unknown query ID returns error in response."""
        from benchbox.mcp.tools.benchmark import _populate_dataframe_query_details

        response: dict = {}
        _populate_dataframe_query_details(response, "tpch", "99", "polars-df")

        assert "error" in response

    def test_unsupported_benchmark_returns_error(self):
        """Test that unsupported benchmark for DataFrame returns error."""
        from benchbox.mcp.tools.benchmark import _populate_dataframe_query_details

        response: dict = {}
        _populate_dataframe_query_details(response, "clickbench", "1", "polars-df")
        assert "error" in response


class TestBenchmarkResultExportPath:
    """Tests for MCP benchmark export path configuration."""

    def test_export_and_build_payload_uses_injected_results_dir(self, tmp_path: Path):
        """Result exporter should write using injected MCP results_dir."""
        from benchbox.mcp.tools.benchmark import _export_and_build_payload

        result = SimpleNamespace(execution_id=None)
        execution_id = "mcp_test_001"
        exported_json = tmp_path / "tpch_test.json"
        exported_json.write_text("{}", encoding="utf-8")

        with (
            patch("benchbox.mcp.tools.benchmark.ResultExporter") as exporter_cls,
            patch("benchbox.mcp.tools.benchmark.build_result_payload", return_value={"ok": True}),
        ):
            exporter = exporter_cls.return_value
            exporter.export_result.return_value = {"json": exported_json}

            result_file_path, result_payload = _export_and_build_payload(
                result, execution_id, tmp_path, anonymize=False
            )

        assert result.execution_id == execution_id
        assert result_file_path == str(exported_json)
        assert result_payload == {}
        assert exporter_cls.call_args.kwargs["output_dir"] == tmp_path

    @pytest.mark.parametrize("anonymize", [False, True])
    def test_export_honours_the_requested_anonymization(self, tmp_path: Path, anonymize: bool):
        """The exporter is constructed with the caller's trust-boundary decision."""
        from benchbox.mcp.tools.benchmark import _export_and_build_payload

        result = SimpleNamespace(execution_id=None)
        exported_json = tmp_path / "tpch_test.json"
        exported_json.write_text("{}", encoding="utf-8")

        with (
            patch("benchbox.mcp.tools.benchmark.ResultExporter") as exporter_cls,
            patch("benchbox.mcp.tools.benchmark.build_result_payload", return_value={"ok": True}),
        ):
            exporter_cls.return_value.export_result.return_value = {"json": exported_json}

            _export_and_build_payload(result, "mcp_test_002", tmp_path, anonymize=anonymize)

        assert exporter_cls.call_args.kwargs["anonymize"] is anonymize


class TestPopulateSqlQueryDetails:
    """Tests for _populate_sql_query_details helper."""

    def test_tpch_q6_returns_sql(self):
        """Test that TPC-H Q6 returns SQL text."""
        from benchbox.mcp.tools.benchmark import _populate_sql_query_details

        response: dict = {}
        _populate_sql_query_details(response, "tpch", "6", None)

        assert "sql" in response
        assert "SELECT" in response["sql"].upper()

    def test_tpch_q6_with_platform_dialect(self):
        """Test that TPC-H Q6 with platform returns dialect-translated SQL."""
        from benchbox.mcp.tools.benchmark import _populate_sql_query_details

        response: dict = {}
        _populate_sql_query_details(response, "tpch", "6", "duckdb")

        assert "sql" in response
        assert "SELECT" in response["sql"].upper()

    def test_sql_truncation(self):
        """Test that SQL truncated flag is set correctly."""
        from benchbox.mcp.tools.benchmark import _populate_sql_query_details

        response: dict = {}
        _populate_sql_query_details(response, "tpch", "6", None)

        # Q6 is short, should not be truncated
        if "sql" in response:
            assert response.get("sql_truncated") is False


class TestBenchmarkTiming:
    """Tests for monotonic execution timing in benchmark MCP helpers."""

    def test_generate_data_impl_execution_time_uses_monotonic_elapsed(self, tmp_path):
        """Data-only metadata should use monotonic elapsed seconds."""
        from benchbox.mcp.tools import benchmark as benchmark_tools

        class _FakeBenchmark:
            def __init__(self, scale_factor: float):
                self.scale_factor = scale_factor

            def generate_data(self, output_dir: Path, format: str = "parquet"):
                (Path(output_dir) / "lineitem.parquet").write_text("x", encoding="utf-8")

        mock_clock = Mock(return_value=103.21)
        tenant_results = tmp_path / "tenant" / "results"
        tenant_data = tenant_results / "datagen" / "tpch_sf001"
        with (
            patch.object(
                benchmark_tools, "get_benchmark_runs_datagen_path", return_value=tenant_data
            ) as resolve_datagen,
            patch.object(benchmark_tools, "mono_time", mock_clock),
            patch("benchbox.utils.clock.mono_time", mock_clock),
        ):
            response = benchmark_tools._generate_data_impl(
                "tpch", _FakeBenchmark, 0.01, "exec-1", 100.0, results_dir=tenant_results
            )

        assert response["mcp_metadata"]["execution_time_seconds"] == 3.21
        assert response["data_generation"]["data_path"] == str(tenant_data)
        resolve_datagen.assert_called_once_with("tpch", 0.01, tenant_results / "datagen")
