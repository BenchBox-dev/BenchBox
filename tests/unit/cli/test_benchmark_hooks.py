"""Tests for BenchmarkHookRegistry and benchmark option parsers."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

from benchbox.cli.benchmark_hooks import (
    BenchmarkHookRegistry,
    BenchmarkOptionError,
    BenchmarkOptionSpec,
    parse_bool,
    parse_datetime,
    parse_enum_list,
    parse_int,
    parse_int_list,
    parse_str_list,
)

# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------


class TestParsers:
    def test_parse_int(self):
        assert parse_int("42") == 42
        assert parse_int(" 7 ") == 7
        with pytest.raises(BenchmarkOptionError, match="Invalid integer"):
            parse_int("abc")

    def test_parse_bool(self):
        assert parse_bool("true") is True
        assert parse_bool("False") is False
        assert parse_bool("1") is True
        assert parse_bool("no") is False
        with pytest.raises(BenchmarkOptionError, match="Invalid boolean"):
            parse_bool("maybe")

    def test_parse_int_list(self):
        assert parse_int_list("1,2,3") == [1, 2, 3]
        assert parse_int_list(" 4 , 5 ") == [4, 5]
        with pytest.raises(BenchmarkOptionError, match="Empty list"):
            parse_int_list("")
        with pytest.raises(BenchmarkOptionError, match="Invalid integer list"):
            parse_int_list("1,abc,3")

    def test_parse_str_list(self):
        assert parse_str_list("a,b,c") == ["a", "b", "c"]
        assert parse_str_list(" store , web ") == ["store", "web"]
        with pytest.raises(BenchmarkOptionError, match="Empty list"):
            parse_str_list("")

    def test_parse_enum_list(self):
        from enum import Enum

        class Color(Enum):
            RED = "red"
            BLUE = "blue"

        parser = parse_enum_list(Color)
        assert parser("red,blue") == [Color.RED, Color.BLUE]
        assert parser("red") == [Color.RED]
        with pytest.raises(BenchmarkOptionError, match="Invalid value 'green'"):
            parser("red,green")
        with pytest.raises(BenchmarkOptionError, match="Empty list"):
            parser("")

    def test_parse_enum_list_case_insensitive(self):
        from enum import Enum

        class Fruit(Enum):
            APPLE = "apple"

        parser = parse_enum_list(Fruit)
        assert parser("APPLE") == [Fruit.APPLE]
        assert parser("Apple") == [Fruit.APPLE]

    def test_parse_datetime(self):
        dt = parse_datetime("2019-02-01T00:00:00")
        assert dt.year == 2019
        assert dt.month == 2
        assert dt.day == 1

        dt2 = parse_datetime("2024-12-31")
        assert dt2.year == 2024

        with pytest.raises(BenchmarkOptionError, match="Invalid datetime"):
            parse_datetime("not-a-date")


# ---------------------------------------------------------------------------
# BenchmarkOptionSpec tests
# ---------------------------------------------------------------------------


class TestBenchmarkOptionSpec:
    def test_parse_identity(self):
        spec = BenchmarkOptionSpec(name="foo")
        assert spec.parse("bar") == "bar"

    def test_parse_with_parser(self):
        spec = BenchmarkOptionSpec(name="count", parser=parse_int)
        assert spec.parse("42") == 42

    def test_parse_with_choices_valid(self):
        spec = BenchmarkOptionSpec(name="mode", choices=("full", "minimal"))
        assert spec.parse("full") == "full"

    def test_parse_with_choices_invalid(self):
        spec = BenchmarkOptionSpec(name="mode", choices=("full", "minimal"))
        with pytest.raises(BenchmarkOptionError, match="Invalid value"):
            spec.parse("partial")


# ---------------------------------------------------------------------------
# BenchmarkHookRegistry tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Save and restore registry state around each test."""
    import copy

    saved_specs = copy.deepcopy(BenchmarkHookRegistry._option_specs)
    saved_aliases = copy.deepcopy(BenchmarkHookRegistry._alias_index)
    yield
    BenchmarkHookRegistry._option_specs = saved_specs
    BenchmarkHookRegistry._alias_index = saved_aliases


class TestBenchmarkHookRegistry:
    def test_register_and_list(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="opt_a", parser=parse_int, help="An option"),
        )
        specs = BenchmarkHookRegistry.list_option_specs("test_bench")
        assert "opt_a" in specs
        assert specs["opt_a"].help == "An option"

    def test_register_with_alias(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="my_opt", aliases=("my-opt",)),
        )
        result = BenchmarkHookRegistry.parse_options("test_bench", [("my-opt", "val")])
        assert result == {"my_opt": "val"}

    def test_parse_options_unknown_key_rejected(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="known"),
        )
        with pytest.raises(BenchmarkOptionError, match="Unknown benchmark option 'bad'"):
            BenchmarkHookRegistry.parse_options("test_bench", [("bad", "val")])

    def test_parse_options_duplicate_rejected(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="dupe"),
        )
        with pytest.raises(BenchmarkOptionError, match="Duplicate"):
            BenchmarkHookRegistry.parse_options("test_bench", [("dupe", "a"), ("dupe", "b")])

    def test_parse_options_no_specs_rejected(self):
        with pytest.raises(BenchmarkOptionError, match="does not accept"):
            BenchmarkHookRegistry.parse_options("no_specs_bench", [("key", "val")])

    def test_parse_options_returns_only_provided(self):
        """Ensure defaults are NOT merged - only explicitly provided options returned."""
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="a", default="default_a"),
            BenchmarkOptionSpec(name="b", parser=parse_int),
        )
        result = BenchmarkHookRegistry.parse_options("test_bench", [("b", "5")])
        assert result == {"b": 5}
        assert "a" not in result

    def test_describe_options(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="dim", parser=parse_int, default=128, help="Dimensions"),
        )
        lines = BenchmarkHookRegistry.describe_options("test_bench")
        assert len(lines) == 1
        assert "dim" in lines[0]
        assert "128" in lines[0]
        assert "Dimensions" in lines[0]

    def test_has_specs(self):
        assert not BenchmarkHookRegistry.has_specs("nonexistent")
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="x"),
        )
        assert BenchmarkHookRegistry.has_specs("test_bench")

    def test_re_registration_is_idempotent(self):
        spec = BenchmarkOptionSpec(name="x", help="first")
        BenchmarkHookRegistry.register_option_specs("test_bench", spec)
        # Re-register same name - should silently skip
        spec2 = BenchmarkOptionSpec(name="x", help="second")
        BenchmarkHookRegistry.register_option_specs("test_bench", spec2)
        # First registration wins
        assert BenchmarkHookRegistry.list_option_specs("test_bench")["x"].help == "first"

    def test_duplicate_alias_rejected(self):
        BenchmarkHookRegistry.register_option_specs(
            "test_bench",
            BenchmarkOptionSpec(name="opt_a", aliases=("shared-alias",)),
        )
        with pytest.raises(BenchmarkOptionError, match="Alias 'shared-alias' already used"):
            BenchmarkHookRegistry.register_option_specs(
                "test_bench",
                BenchmarkOptionSpec(name="opt_b", aliases=("shared-alias",)),
            )

    def test_case_insensitive_benchmark_name(self):
        BenchmarkHookRegistry.register_option_specs(
            "TestBench",
            BenchmarkOptionSpec(name="x"),
        )
        assert BenchmarkHookRegistry.has_specs("testbench")
        assert BenchmarkHookRegistry.has_specs("TESTBENCH")


# ---------------------------------------------------------------------------
# Click param type test
# ---------------------------------------------------------------------------


class TestBenchmarkOptionParamType:
    def test_valid_key_value(self):
        from benchbox.cli.commands.run import BenchmarkOptionParamType

        param_type = BenchmarkOptionParamType()
        result = param_type.convert("key=value", None, None)
        assert result == ("key", "value")

    def test_value_with_equals(self):
        from benchbox.cli.commands.run import BenchmarkOptionParamType

        param_type = BenchmarkOptionParamType()
        result = param_type.convert("key=a=b", None, None)
        assert result == ("key", "a=b")

    def test_missing_equals_fails(self):
        from click.exceptions import BadParameter

        from benchbox.cli.commands.run import BenchmarkOptionParamType

        param_type = BenchmarkOptionParamType()
        with pytest.raises(BadParameter):
            param_type.convert("noequals", None, None)


# ---------------------------------------------------------------------------
# Integration: real benchmark specs registered
# ---------------------------------------------------------------------------


class TestRealBenchmarkSpecs:
    """Verify that importing benchmark modules registers option specs."""

    def test_nyctaxi_specs_registered(self):
        from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark  # noqa: F401

        specs = BenchmarkHookRegistry.list_option_specs("nyctaxi")
        assert "taxi_types" in specs
        assert "year" in specs
        assert "months" in specs
        assert "seed" in specs

    def test_nyctaxi_taxi_types_parser(self):
        from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark  # noqa: F401
        from benchbox.core.nyctaxi.schema import TaxiType

        specs = BenchmarkHookRegistry.list_option_specs("nyctaxi")
        result = specs["taxi_types"].parse("yellow,green,hvfhv")
        assert result == [TaxiType.YELLOW, TaxiType.GREEN, TaxiType.HVFHV]

    def test_tsbs_devops_specs_registered(self):
        from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark  # noqa: F401

        specs = BenchmarkHookRegistry.list_option_specs("tsbs_devops")
        assert "num_hosts" in specs
        assert "duration_days" in specs
        assert "interval_seconds" in specs
        assert "start_time" in specs

    def test_tpch_skew_specs_registered(self):
        from benchbox.core.tpch_skew.benchmark import TPCHSkewBenchmark  # noqa: F401

        specs = BenchmarkHookRegistry.list_option_specs("tpch_skew")
        assert "skew_preset" in specs
        assert specs["skew_preset"].default == "moderate"

    def test_vector_search_specs_registered(self):
        from benchbox.core.vector_search.benchmark import VectorSearchBenchmark  # noqa: F401

        specs = BenchmarkHookRegistry.list_option_specs("vector_search")
        assert "dimensions" in specs
        assert specs["dimensions"].default == 128

    def test_joinorder_force_regenerate_documents_download_cost(self):
        from benchbox.core.joinorder.benchmark import JoinOrderBenchmark  # noqa: F401

        specs = BenchmarkHookRegistry.list_option_specs("joinorder")
        help_text = specs["force_regenerate"].help
        assert "re-downloading" in help_text
        assert "~1.2 GB" in help_text

    def test_benchmarks_without_specs_still_work(self):
        """Benchmarks with no registered specs should not raise on empty parse."""
        # tpch has no registered specs - parsing with no options should be fine
        assert not BenchmarkHookRegistry.has_specs("tpch")
