"""Tests for BenchBox MCP schemas module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json

import pytest
from pydantic import ValidationError as PydanticValidationError

from benchbox.mcp.schemas import (
    MAX_QUERY_ID_LENGTH,
    MAX_QUERY_IDS,
    MCP_CLICKHOUSE_PROFILE_ENV,
    MCP_PLATFORM_OPTION_ALLOWLIST,
    MCP_PLATFORM_OPTION_CONTRACT,
    CompareResultsInput,
    DryRunInput,
    ExportSummaryInput,
    GetBenchmarkInfoInput,
    GetResultsInput,
    ListRecentRunsInput,
    MCPValidationError,
    RunBenchmarkInput,
    ValidateConfigInput,
    resolve_clickhouse_connection_profile,
    validate_benchmark_name,
    validate_filename,
    validate_platform_name,
    validate_platform_options,
    validate_query_id,
    validate_query_list,
    validate_scale_factor,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestValidateQueryId:
    """Tests for validate_query_id function."""

    def test_valid_query_ids(self):
        """Test valid query IDs are accepted."""
        assert validate_query_id("1") == "1"
        assert validate_query_id("Q1") == "Q1"
        assert validate_query_id("query-1") == "query-1"
        assert validate_query_id("query_1") == "query_1"
        assert validate_query_id("  Q1  ") == "Q1"  # Strips whitespace

    def test_empty_query_id_rejected(self):
        """Test empty query ID is rejected."""
        with pytest.raises(MCPValidationError, match="cannot be empty"):
            validate_query_id("")
        with pytest.raises(MCPValidationError, match="cannot be empty"):
            validate_query_id("   ")

    def test_too_long_query_id_rejected(self):
        """Test query ID exceeding max length is rejected."""
        long_id = "a" * (MAX_QUERY_ID_LENGTH + 1)
        with pytest.raises(MCPValidationError, match="too long"):
            validate_query_id(long_id)

    def test_invalid_characters_rejected(self):
        """Test query IDs with invalid characters are rejected."""
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_query_id("query@1")
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_query_id("query 1")
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_query_id("../query")


class TestValidateQueryList:
    """Tests for validate_query_list function."""

    def test_valid_query_list(self):
        """Test valid query lists are accepted."""
        assert validate_query_list("1,2,3") == ["1", "2", "3"]
        assert validate_query_list("Q1, Q2, Q3") == ["Q1", "Q2", "Q3"]
        assert validate_query_list("1") == ["1"]

    def test_none_and_empty(self):
        """Test None and empty strings return None."""
        assert validate_query_list(None) is None
        assert validate_query_list("") is None
        assert validate_query_list("   ") is None

    def test_too_many_queries_rejected(self):
        """Test query list exceeding max count is rejected."""
        query_list = ",".join([str(i) for i in range(MAX_QUERY_IDS + 1)])
        with pytest.raises(MCPValidationError, match="Too many query IDs"):
            validate_query_list(query_list)

    def test_invalid_query_in_list_rejected(self):
        """Test invalid query ID in list is rejected."""
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_query_list("1,2,query@3")


class TestValidatePlatformName:
    """Tests for validate_platform_name function."""

    def test_valid_platform_names(self):
        """Test valid platform names are accepted."""
        assert validate_platform_name("duckdb") == "duckdb"
        assert validate_platform_name("DuckDB") == "duckdb"  # Lowercased
        assert validate_platform_name("polars-df") == "polars-df"
        assert validate_platform_name("  snowflake  ") == "snowflake"  # Stripped

    def test_empty_platform_rejected(self):
        """Test empty platform name is rejected."""
        with pytest.raises(MCPValidationError, match="cannot be empty"):
            validate_platform_name("")

    def test_too_long_platform_rejected(self):
        """Test platform name exceeding max length is rejected."""
        long_name = "a" * 51
        with pytest.raises(MCPValidationError, match="too long"):
            validate_platform_name(long_name)

    def test_invalid_characters_rejected(self):
        """Test platform names with invalid characters are rejected."""
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_platform_name("platform@test")
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_platform_name("../platform")


class TestValidateBenchmarkName:
    """Tests for validate_benchmark_name function."""

    def test_valid_benchmark_names(self):
        """Test valid benchmark names are accepted."""
        assert validate_benchmark_name("tpch") == "tpch"
        assert validate_benchmark_name("TPCH") == "tpch"  # Lowercased
        assert validate_benchmark_name("tpc-ds") == "tpc-ds"
        assert validate_benchmark_name("  tpch  ") == "tpch"  # Stripped

    def test_empty_benchmark_rejected(self):
        """Test empty benchmark name is rejected."""
        with pytest.raises(MCPValidationError, match="cannot be empty"):
            validate_benchmark_name("")

    def test_too_long_benchmark_rejected(self):
        """Test benchmark name exceeding max length is rejected."""
        long_name = "a" * 51
        with pytest.raises(MCPValidationError, match="too long"):
            validate_benchmark_name(long_name)


class TestValidateFilename:
    """Tests for validate_filename function."""

    def test_valid_filenames(self):
        """Test valid filenames are accepted."""
        assert validate_filename("results.json") == "results.json"
        assert validate_filename("tpch_sf001_duckdb_20231201.json") == "tpch_sf001_duckdb_20231201.json"
        assert validate_filename("test-file.json") == "test-file.json"

    def test_empty_filename_rejected(self):
        """Test empty filename is rejected."""
        with pytest.raises(MCPValidationError, match="cannot be empty"):
            validate_filename("")

    def test_too_long_filename_rejected(self):
        """Test filename exceeding max length is rejected."""
        long_name = "a" * 256
        with pytest.raises(MCPValidationError, match="too long"):
            validate_filename(long_name)

    def test_path_traversal_rejected(self):
        """Test path traversal attempts are rejected."""
        with pytest.raises(MCPValidationError, match="path components"):
            validate_filename("../secret.json")
        with pytest.raises(MCPValidationError, match="path components"):
            validate_filename("dir/file.json")
        with pytest.raises(MCPValidationError, match="path components"):
            validate_filename("..\\file.json")

    def test_invalid_characters_rejected(self):
        """Test filenames with invalid characters are rejected."""
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_filename("file@name.json")
        with pytest.raises(MCPValidationError, match="invalid characters"):
            validate_filename("file name.json")


class TestValidateScaleFactor:
    """Tests for validate_scale_factor function."""

    def test_valid_scale_factors(self):
        """Test valid scale factors are accepted."""
        assert validate_scale_factor(0.01) == 0.01
        assert validate_scale_factor(1.0) == 1.0
        assert validate_scale_factor(10.0) == 10.0
        assert validate_scale_factor(100.0) == 100.0

    def test_zero_rejected(self):
        """Test zero scale factor is rejected."""
        with pytest.raises(MCPValidationError, match="must be positive"):
            validate_scale_factor(0)

    def test_negative_rejected(self):
        """Test negative scale factor is rejected."""
        with pytest.raises(MCPValidationError, match="must be positive"):
            validate_scale_factor(-1)

    def test_too_small_rejected(self):
        """Test scale factor below minimum is rejected."""
        with pytest.raises(MCPValidationError, match="too small"):
            validate_scale_factor(0.0001)

    def test_too_large_rejected(self):
        """Test scale factor above maximum is rejected."""
        with pytest.raises(MCPValidationError, match="too large"):
            validate_scale_factor(20000)


class TestRunBenchmarkInput:
    """Tests for RunBenchmarkInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = RunBenchmarkInput(platform="duckdb", benchmark="tpch")
        assert inp.platform == "duckdb"
        assert inp.benchmark == "tpch"
        assert inp.scale_factor == 0.01  # Default
        assert inp.queries is None
        assert inp.phases is None

    def test_valid_input_with_all_fields(self):
        """Test valid input with all fields."""
        inp = RunBenchmarkInput(
            platform="DuckDB",
            benchmark="TPCH",
            scale_factor=1.0,
            queries="1,2,3",
            phases="load,power",
        )
        assert inp.platform == "duckdb"  # Lowercased
        assert inp.benchmark == "tpch"  # Lowercased
        assert inp.scale_factor == 1.0
        assert inp.queries == "1,2,3"
        assert inp.phases == "load,power"

    def test_invalid_platform_rejected(self):
        """Test invalid platform is rejected."""
        with pytest.raises(PydanticValidationError):
            RunBenchmarkInput(platform="invalid@platform", benchmark="tpch")

    def test_invalid_scale_factor_rejected(self):
        """Test invalid scale factor is rejected."""
        with pytest.raises(PydanticValidationError):
            RunBenchmarkInput(platform="duckdb", benchmark="tpch", scale_factor=-1)

    def test_platform_options_are_typed_and_normalized(self):
        inp = RunBenchmarkInput(
            platform="duckdb",
            benchmark="tpch",
            platform_options={"threads": 4, "memory_limit": "2GB"},
        )
        assert inp.platform_options == {"threads": 4, "memory_limit": "2GB"}

    def test_every_allowlisted_option_has_an_explicit_contract(self):
        """The value allow-list cannot grow without a reviewed consumer matrix."""
        assert set(MCP_PLATFORM_OPTION_ALLOWLIST) == set(MCP_PLATFORM_OPTION_CONTRACT)
        for platform, specs in MCP_PLATFORM_OPTION_ALLOWLIST.items():
            contracts = MCP_PLATFORM_OPTION_CONTRACT[platform]
            assert set(specs) == set(contracts)
            for option_name, contract in contracts.items():
                assert contract.consumer
                assert contract.security_class in {"execution", "resource", "device", "layout", "connection"}
                assert all(alias != option_name for alias in contract.aliases)

    def test_option_without_contract_is_rejected_fail_closed(self, monkeypatch):
        monkeypatch.delitem(MCP_PLATFORM_OPTION_CONTRACT["duckdb"], "threads")
        with pytest.raises(MCPValidationError, match="not authorized"):
            validate_platform_options("duckdb", {"threads": 2})

    def test_secret_and_unknown_platform_options_are_rejected(self):
        with pytest.raises(PydanticValidationError):
            RunBenchmarkInput(platform="duckdb", benchmark="tpch", platform_options={"password": "secret"})
        with pytest.raises(MCPValidationError):
            validate_platform_options("snowflake", {"warehouse": "secret"})

    def test_platform_option_bounds_and_types_are_rejected(self):
        with pytest.raises(MCPValidationError):
            validate_platform_options("duckdb", {"threads": 0})
        with pytest.raises(MCPValidationError):
            validate_platform_options("duckdb", {"threads": "4"})
        with pytest.raises(MCPValidationError):
            validate_platform_options("duckdb", {"memory_limit": "/tmp/secret"})
        with pytest.raises(MCPValidationError):
            validate_platform_options("sqlite", {"timeout": float("nan")})

    def test_dataframe_aliases_and_identifier_options_are_bounded(self):
        assert validate_platform_options("polars-df", {"streaming": True}) == {"streaming": True}
        assert validate_platform_options("databricks", {"liquid_clustering_columns": "event_time,customer_id"}) == {
            "liquid_clustering_columns": "event_time,customer_id"
        }
        with pytest.raises(MCPValidationError):
            validate_platform_options("databricks", {"liquid_clustering_columns": "event_time;DROP"})

    def test_mcp_platform_choices_match_adapter_contracts(self):
        with pytest.raises(MCPValidationError):
            validate_platform_options("velox", {"deployment": "docker"})
        assert validate_platform_options("velox", {"deployment": "remote"}) == {"deployment": "remote"}
        with pytest.raises(MCPValidationError):
            validate_platform_options("modin", {"engine": "pandas"})


CLICKHOUSE_PLATFORM_SPELLINGS = ("clickhouse", "clickhouse-server")
CLICKHOUSE_UNCONFIGURED_SPELLINGS = ("clickhouse-local", "clickhouse-cloud", "chdb", "clickhouse_server")


class TestClickHouseConnectionBoundary:
    """A caller must never name a ClickHouse destination or transport policy."""

    @pytest.mark.parametrize("platform", CLICKHOUSE_PLATFORM_SPELLINGS)
    @pytest.mark.parametrize("options", [{"port": 9001}, {"secure": False}, {"port": 9001, "secure": True}])
    def test_port_and_tls_overrides_are_rejected(self, platform, options):
        """Port is part of a destination and secure is transport policy."""
        with pytest.raises(MCPValidationError, match="not authorized"):
            validate_platform_options(platform, options)

    @pytest.mark.parametrize("platform", CLICKHOUSE_UNCONFIGURED_SPELLINGS)
    def test_other_clickhouse_spellings_expose_no_options(self, platform):
        with pytest.raises(MCPValidationError, match="not authorized"):
            validate_platform_options(platform, {"port": 9001})

    def test_run_benchmark_input_rejects_port_override(self):
        with pytest.raises(PydanticValidationError):
            RunBenchmarkInput(platform="clickhouse-server", benchmark="tpch", platform_options={"port": 9001})

    def test_unknown_profile_is_rejected_and_is_not_a_probe_oracle(self, monkeypatch):
        """An unconfigured profile fails closed without echoing the request."""
        monkeypatch.delenv(MCP_CLICKHOUSE_PROFILE_ENV, raising=False)
        with pytest.raises(MCPValidationError) as excinfo:
            validate_platform_options("clickhouse-server", {"connection_profile": "analytics"})
        assert "analytics" not in str(excinfo.value)

    def test_configured_profile_admits_only_its_name(self, monkeypatch):
        """The persisted request carries the name, never the resolved tuple."""
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"analytics": {"port": 9440, "secure": True}}))
        normalized = validate_platform_options("clickhouse-server", {"connection_profile": "analytics"})
        assert normalized == {"connection_profile": "analytics"}

    def test_local_deployment_cannot_acquire_a_network_path(self, monkeypatch):
        """chDB local mode is in-process; a profile must not give it a socket."""
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"analytics": {"port": 9440, "secure": True}}))
        with pytest.raises(MCPValidationError, match="deployment_mode='server'"):
            validate_platform_options("clickhouse", {"connection_profile": "analytics"})
        with pytest.raises(MCPValidationError, match="deployment_mode='server'"):
            validate_platform_options("clickhouse", {"connection_profile": "analytics", "deployment_mode": "local"})
        assert validate_platform_options(
            "clickhouse", {"connection_profile": "analytics", "deployment_mode": "server"}
        ) == {"connection_profile": "analytics", "deployment_mode": "server"}

    @pytest.mark.parametrize(
        "registry",
        [
            "not json",
            json.dumps(["analytics"]),
            json.dumps({"Analytics": {"port": 9440}}),
            json.dumps({"analytics": {"port": 0}}),
            json.dumps({"analytics": {"port": 70000}}),
            json.dumps({"analytics": {"port": True}}),
            json.dumps({"analytics": {"port": "9440"}}),
            json.dumps({"analytics": {"port": 9440, "secure": "yes"}}),
            json.dumps({"analytics": {"port": 9440, "host": "10.0.0.5"}}),
            json.dumps({"analytics": {"port": 9440, "password": "hunter2"}}),
        ],
    )
    def test_malformed_server_registry_fails_closed(self, monkeypatch, registry):
        """A malformed or over-broad profile is never partially trusted."""
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, registry)
        with pytest.raises(MCPValidationError, match="not configured"):
            validate_platform_options("clickhouse-server", {"connection_profile": "analytics"})

    def test_profile_name_shape_is_bounded(self, monkeypatch):
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"analytics": {"port": 9440}}))
        for bad_name in ("Analytics", "../etc/passwd", "a" * 65, "9analytics", ""):
            with pytest.raises(MCPValidationError):
                validate_platform_options("clickhouse-server", {"connection_profile": bad_name})

    def test_dataframe_alias_fallback_does_not_bypass_the_policy(self, monkeypatch):
        """A '-df' spelling inherits the base records, so it inherits the rules."""
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"analytics": {"port": 9440, "secure": True}}))
        with pytest.raises(MCPValidationError, match="not authorized"):
            validate_platform_options("clickhouse-df", {"port": 9001})
        with pytest.raises(MCPValidationError, match="deployment_mode='server'"):
            validate_platform_options("clickhouse-df", {"connection_profile": "analytics"})

    def test_resolution_returns_the_server_owned_tuple(self, monkeypatch):
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"analytics": {"port": 9440, "secure": True}}))
        assert resolve_clickhouse_connection_profile("analytics") == {"port": 9440, "secure": True}

    def test_profile_defaults_to_plaintext_only_when_the_operator_says_so(self, monkeypatch):
        monkeypatch.setenv(MCP_CLICKHOUSE_PROFILE_ENV, json.dumps({"plain": {"port": 9000}}))
        assert resolve_clickhouse_connection_profile("plain") == {"port": 9000, "secure": False}


class TestDryRunInput:
    """Tests for DryRunInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = DryRunInput(platform="duckdb", benchmark="tpch")
        assert inp.platform == "duckdb"
        assert inp.benchmark == "tpch"

    def test_with_query_subset(self):
        """Test input with query subset."""
        inp = DryRunInput(platform="duckdb", benchmark="tpch", queries="1,6,17")
        assert inp.queries == "1,6,17"


class TestValidateConfigInput:
    """Tests for ValidateConfigInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = ValidateConfigInput(platform="duckdb", benchmark="tpch")
        assert inp.platform == "duckdb"
        assert inp.benchmark == "tpch"
        assert inp.scale_factor == 1.0  # Different default


class TestGetBenchmarkInfoInput:
    """Tests for GetBenchmarkInfoInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = GetBenchmarkInfoInput(benchmark="tpch")
        assert inp.benchmark == "tpch"

    def test_normalizes_case(self):
        """Test benchmark name is normalized to lowercase."""
        inp = GetBenchmarkInfoInput(benchmark="TPCDS")
        assert inp.benchmark == "tpcds"


class TestListRecentRunsInput:
    """Tests for ListRecentRunsInput Pydantic model."""

    def test_valid_input_with_defaults(self):
        """Test valid input with defaults."""
        inp = ListRecentRunsInput()
        assert inp.limit == 10
        assert inp.platform is None
        assert inp.benchmark is None

    def test_valid_input_with_filters(self):
        """Test valid input with filters."""
        inp = ListRecentRunsInput(limit=5, platform="duckdb", benchmark="tpch")
        assert inp.limit == 5
        assert inp.platform == "duckdb"
        assert inp.benchmark == "tpch"

    def test_limit_bounds(self):
        """Test limit is bounded."""
        with pytest.raises(PydanticValidationError):
            ListRecentRunsInput(limit=0)
        with pytest.raises(PydanticValidationError):
            ListRecentRunsInput(limit=101)


class TestGetResultsInput:
    """Tests for GetResultsInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = GetResultsInput(result_file="test.json")
        assert inp.result_file == "test.json"
        assert inp.include_queries is True  # Default

    def test_path_traversal_rejected(self):
        """Test path traversal is rejected."""
        with pytest.raises(PydanticValidationError):
            GetResultsInput(result_file="../secret.json")


class TestCompareResultsInput:
    """Tests for CompareResultsInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = CompareResultsInput(file1="run1.json", file2="run2.json")
        assert inp.file1 == "run1.json"
        assert inp.file2 == "run2.json"
        assert inp.threshold_percent == 10.0  # Default

    def test_custom_threshold(self):
        """Test custom threshold is accepted."""
        inp = CompareResultsInput(file1="run1.json", file2="run2.json", threshold_percent=5.0)
        assert inp.threshold_percent == 5.0

    def test_threshold_bounds(self):
        """Test threshold is bounded."""
        with pytest.raises(PydanticValidationError):
            CompareResultsInput(file1="a.json", file2="b.json", threshold_percent=-1)
        with pytest.raises(PydanticValidationError):
            CompareResultsInput(file1="a.json", file2="b.json", threshold_percent=101)


class TestExportSummaryInput:
    """Tests for ExportSummaryInput Pydantic model."""

    def test_valid_input(self):
        """Test valid input is accepted."""
        inp = ExportSummaryInput(result_file="test.json")
        assert inp.result_file == "test.json"
        assert inp.format == "text"  # Default

    def test_valid_formats(self):
        """Test valid formats are accepted."""
        inp = ExportSummaryInput(result_file="test.json", format="markdown")
        assert inp.format == "markdown"

        inp = ExportSummaryInput(result_file="test.json", format="json")
        assert inp.format == "json"

    def test_invalid_format_rejected(self):
        """Test invalid format is rejected."""
        with pytest.raises(PydanticValidationError):
            ExportSummaryInput(result_file="test.json", format="xml")
