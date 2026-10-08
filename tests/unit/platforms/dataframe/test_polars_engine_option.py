from __future__ import annotations

import ast
import functools
import sys
import types
from datetime import date
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError
from benchbox.core.results.platform_info import build_platform_info
from benchbox.platforms import get_dataframe_adapter, polars_compat
from benchbox.platforms.dataframe import expression_family, polars_df, unified_frame
from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter
from benchbox.platforms.dataframe.unified_frame import UnifiedLazyFrame
from benchbox.platforms.polars_compat import PolarsEngineUnsupportedError

pytestmark = [pytest.mark.unit, pytest.mark.fast]

TPCH_TABLES = {
    "partsupp": {
        "ps_partkey": [1, 2],
        "ps_suppkey": [1, 1],
        "ps_supplycost": [1.0, 2.0],
        "ps_availqty": [10, 20],
    },
    "supplier": {
        "s_suppkey": [1],
        "s_nationkey": [1],
        "s_name": ["supplier"],
        "s_address": ["address"],
        "s_phone": ["phone"],
    },
    "nation": {"n_nationkey": [1], "n_name": ["GERMANY"]},
    "lineitem": {
        "l_suppkey": [1],
        "l_shipdate": [date(1996, 2, 1)],
        "l_extendedprice": [100.0],
        "l_discount": [0.1],
    },
    "customer": {
        "c_custkey": [1, 2],
        "c_phone": ["13-555-0100", "31-555-0101"],
        "c_acctbal": [100.0, 200.0],
    },
    "orders": {"o_custkey": [1]},
}


CAPABILITY_CACHES = (polars_compat.collect_accepts_engine, polars_compat.collect_engine_supported)


@pytest.fixture(autouse=True)
def clear_capability_caches():
    for cached in CAPABILITY_CACHES:
        cached.cache_clear()
    yield
    for cached in CAPABILITY_CACHES:
        cached.cache_clear()


@pytest.fixture
def collect_calls(monkeypatch):
    calls: list[dict] = []
    real_collect = pl.LazyFrame.collect

    @functools.wraps(real_collect)
    def recording_collect(self, *args, **kwargs):
        calls.append(dict(kwargs))
        return real_collect(self, *args, **kwargs)

    monkeypatch.setattr(pl.LazyFrame, "collect", recording_collect)
    return calls


def _parse(module) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _collect_calls_in(node: ast.AST) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "collect"
    ]


def _is_self_call(call: ast.Call) -> bool:
    receiver = call.func.value
    return isinstance(receiver, ast.Name) and receiver.id == "self"


def _polars_branches(tree: ast.Module) -> list[ast.If]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_is_polars_df"
            for child in ast.walk(node.test)
        )
    ]


def _context_for(adapter: PolarsDataFrameAdapter):
    ctx = adapter.create_context()
    for name, data in TPCH_TABLES.items():
        ctx.register_table(name, pl.DataFrame(data).lazy())
    return ctx


class TestCollectGuard:
    def test_polars_adapter_never_calls_collect_directly(self):
        assert _collect_calls_in(_parse(polars_df)) == []

    def test_expression_family_only_delegates_to_the_adapter(self):
        calls = _collect_calls_in(_parse(expression_family))

        assert calls
        assert all(_is_self_call(call) for call in calls)

    def test_unified_frame_polars_branches_never_call_collect_directly(self):
        branches = _polars_branches(_parse(unified_frame))

        assert branches
        violations = [call for branch in branches for stmt in branch.body for call in _collect_calls_in(stmt)]
        assert violations == []


class TestEngineReachesEveryCollect:
    @pytest.mark.parametrize(
        ("engine", "expected"), [("default", None), ("in-memory", "in-memory"), ("streaming", "streaming")]
    )
    @pytest.mark.parametrize("query_id", [11, 15, 22])
    def test_tpch_scalar_queries(self, collect_calls, query_id, engine, expected):
        from benchbox.core.tpch import dataframe_queries

        adapter = PolarsDataFrameAdapter(engine=engine)
        ctx = _context_for(adapter)
        collect_calls.clear()

        result = getattr(dataframe_queries, f"q{query_id}_expression_impl")(ctx)
        frame = getattr(result, "native", result)
        adapter.get_row_count(frame)
        adapter._get_first_row(frame)
        adapter.collect(frame)

        assert len(collect_calls) >= 4
        assert all(call == ({} if expected is None else {"engine": expected}) for call in collect_calls)

    def test_scalar_and_row_count_use_the_requested_engine(self, collect_calls):
        adapter = PolarsDataFrameAdapter(engine="in-memory")
        frame = pl.LazyFrame({"a": [1, 2, 3]})
        collect_calls.clear()

        assert adapter.scalar(frame.select(pl.col("a").sum())) == 6
        assert adapter.get_row_count(frame) == 3
        assert adapter._get_first_row(frame) == (1,)

        assert collect_calls == [{"engine": "in-memory"}] * 3

    def test_unified_frame_collects_use_the_adapter_engine(self, collect_calls):
        adapter = PolarsDataFrameAdapter(engine="in-memory")
        unified = UnifiedLazyFrame(pl.LazyFrame({"a": [1, 2]}), adapter)
        collect_calls.clear()

        unified.collect()
        assert unified.collect_column_as_list("a") == [1, 2]
        assert unified.scalar() == 1

        assert collect_calls == [{"engine": "in-memory"}] * 3

    def test_unified_frame_without_a_polars_adapter_uses_the_default_engine(self, collect_calls):
        unified = UnifiedLazyFrame(pl.LazyFrame({"a": [1]}), object())
        collect_calls.clear()

        assert unified.scalar() == 1

        assert collect_calls == [{}]

    def test_streaming_flag_selects_the_streaming_engine(self, collect_calls):
        adapter = PolarsDataFrameAdapter(streaming=True)
        collect_calls.clear()

        adapter.collect(pl.LazyFrame({"a": [1]}))

        assert adapter.collect_engine == "streaming"
        assert collect_calls == [{"engine": "streaming"}]

    def test_default_engine_passes_no_engine_argument(self, collect_calls):
        adapter = PolarsDataFrameAdapter()
        collect_calls.clear()

        adapter.collect(pl.LazyFrame({"a": [1]}))
        adapter.get_row_count(pl.LazyFrame({"a": [1]}))

        assert adapter.collect_engine == "default"
        assert collect_calls == [{}, {}]


class TestEngineValidation:
    def test_simulated_version_without_an_engine_parameter_fails_the_run(self, monkeypatch):
        monkeypatch.setattr(polars_compat, "collect_accepts_engine", lambda: False)

        for engine in ("in-memory", "streaming"):
            with pytest.raises(PolarsEngineUnsupportedError, match=rf"Polars {pl.__version__}.*engine='{engine}'"):
                PolarsDataFrameAdapter(engine=engine)

        with pytest.raises(PolarsEngineUnsupportedError, match="engine='streaming'"):
            PolarsDataFrameAdapter(streaming=True)

        assert PolarsDataFrameAdapter().collect_engine == "default"

    def test_value_rejected_by_polars_fails_the_run(self, monkeypatch):
        def rejecting_collect(self, *, engine="auto"):
            raise ValueError(f"unsupported engine {engine}")

        monkeypatch.setattr(pl.LazyFrame, "collect", rejecting_collect)

        with pytest.raises(PolarsEngineUnsupportedError, match=rf"Polars {pl.__version__}.*engine='in-memory'"):
            PolarsDataFrameAdapter(engine="in-memory")

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown Polars engine 'gpu'"):
            PolarsDataFrameAdapter(engine="gpu")

    def test_in_memory_conflicts_with_streaming_mode(self):
        with pytest.raises(ValueError, match="conflicts with streaming"):
            PolarsDataFrameAdapter(engine="in-memory", streaming=True)


class TestEngineMetadata:
    @pytest.mark.parametrize(
        ("module_name", "module_version", "package", "version"),
        [
            ("polars.polars", None, "absent", "absent"),
            ("_polars_runtime_32._polars_runtime", "1.44.2", "polars-runtime-32", "1.44.2"),
            ("_polars_runtime_64._polars_runtime", "1.44.2", "polars-runtime-64", "1.44.2"),
            ("_polars_runtime_compat._polars_runtime", "1.44.2", "polars-runtime-compat", "1.44.2"),
        ],
        ids=["pre-1.35-layout", "rt32", "rt64", "rtcompat"],
    )
    def test_platform_info_records_the_active_runtime_package(
        self, monkeypatch, module_name, module_version, package, version
    ):
        loaded = types.ModuleType(module_name)
        if module_version is not None:
            loaded.__version__ = module_version
        monkeypatch.setitem(sys.modules, "polars._plr", loaded)

        info = PolarsDataFrameAdapter(engine="in-memory").get_platform_info()

        assert info["version"] == pl.__version__
        assert info["polars_runtime_package"] == package
        assert info["polars_runtime_version"] == version
        assert info["engine_requested"] == "in-memory"
        assert info["collect_engine_argument"] == "in-memory"
        assert info["observed_execution"] == "not_captured"

    def test_active_runtime_ignores_other_installed_runtime_distributions(self, monkeypatch):
        loaded = types.ModuleType("_polars_runtime_64._polars_runtime")
        loaded.__version__ = "1.44.2"
        monkeypatch.setitem(sys.modules, "polars._plr", loaded)
        monkeypatch.setattr(polars_compat.metadata, "version", lambda name: "0.0.1")

        assert polars_compat.active_runtime() == ("polars-runtime-64", "1.44.2")

    def test_active_runtime_falls_back_to_distribution_metadata_without_a_module_version(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "polars._plr", types.ModuleType("_polars_runtime_32._polars_runtime"))
        monkeypatch.setattr(polars_compat.metadata, "version", lambda name: f"{name}-metadata")

        assert polars_compat.active_runtime() == ("polars-runtime-32", "polars-runtime-32-metadata")

    def test_active_runtime_matches_the_loaded_module(self):
        package, version = polars_compat.active_runtime()
        loaded = sys.modules["polars._plr"].__name__

        if loaded.startswith("_polars_runtime_"):
            assert package == loaded.split(".", 1)[0].removeprefix("_").replace("_", "-")
            assert version == sys.modules["polars._plr"].__version__
        else:
            assert (package, version) == ("absent", "absent")

    @pytest.mark.parametrize(
        ("kwargs", "requested", "argument"),
        [
            ({}, "default", None),
            ({"streaming": True}, "default", "streaming"),
            ({"engine": "streaming"}, "streaming", "streaming"),
        ],
    )
    def test_requested_engine_is_distinct_from_the_applied_collect_argument(self, kwargs, requested, argument):
        info = PolarsDataFrameAdapter(**kwargs).get_platform_info()

        assert info["engine_requested"] == requested
        assert info["collect_engine_argument"] == argument

    def test_result_bundle_config_carries_the_engine_fields(self):
        platform_info = build_platform_info(PolarsDataFrameAdapter(engine="in-memory"), execution_mode="dataframe")

        assert platform_info.platform_version == pl.__version__
        assert platform_info.config["engine_requested"] == "in-memory"
        assert platform_info.config["collect_engine_argument"] == "in-memory"
        assert platform_info.config["observed_execution"] == "not_captured"
        assert "polars_runtime_version" in platform_info.config
        assert "polars_runtime_package" in platform_info.config


class TestEngineOption:
    def test_option_is_registered_with_a_default(self):
        specs = PlatformHookRegistry.list_option_specs("polars")

        assert "engine" in specs
        assert PlatformHookRegistry.get_default_options("polars")["engine"] == "default"

    @pytest.mark.parametrize("engine", ["default", "in-memory", "streaming"])
    def test_option_parses_each_supported_value(self, engine):
        assert PlatformHookRegistry.parse_options("polars", [("engine", engine)])["engine"] == engine

    def test_option_rejects_other_values(self):
        with pytest.raises(PlatformOptionError):
            PlatformHookRegistry.parse_options("polars", [("engine", "gpu")])

    def test_factory_passes_the_option_to_the_adapter(self):
        assert get_dataframe_adapter("polars-df", engine="in-memory").engine == "in-memory"
