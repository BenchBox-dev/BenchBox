from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.platforms.dataframe import modin_df as mod
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _FakeRay:
    def __init__(self, initialized=False):
        self._initialized = initialized
        self.init_kwargs = None

    def is_initialized(self):
        return self._initialized

    def init(self, **kwargs):
        self.init_kwargs = kwargs
        self._initialized = True


class _FakeDF:
    def __init__(self, rows):
        self._rows = rows
        self.columns = ["id", TRAILING_DUMMY_COLUMN]
        self.iloc = {0: (rows[0] if rows else None)}

    def drop(self, columns):
        self.columns = [c for c in self.columns if c not in columns]
        return self

    def head(self, n):
        return _FakeDF(self._rows[:n])

    def __len__(self):
        return len(self._rows)


class _GroupBy:
    def __init__(self):
        self.called = None

    def agg(self, *args, **kwargs):
        self.called = (args, kwargs)
        return {"args": args, "kwargs": kwargs}


class _GroupableDF:
    def groupby(self, by, as_index=False):
        return _GroupBy()


class TestModinCoverage:
    def test_initialize_ray_helper_paths(self, monkeypatch):
        fake_ray = _FakeRay(initialized=True)
        monkeypatch.setitem(__import__("sys").modules, "ray", fake_ray)
        assert mod._initialize_ray_for_local_execution() is False

        fake_ray = _FakeRay(initialized=False)
        monkeypatch.setitem(__import__("sys").modules, "ray", fake_ray)
        assert mod._initialize_ray_for_local_execution(num_cpus=2) is True
        assert fake_ray.init_kwargs["num_cpus"] == 2

    def test_configure_engine_and_close_and_del(self, monkeypatch):
        adapter = mod.ModinDataFrameAdapter.__new__(mod.ModinDataFrameAdapter)
        adapter.engine = "ray"
        adapter.verbose = False
        adapter.very_verbose = False
        adapter.working_dir = Path.cwd()

        monkeypatch.setenv("MODIN_ENGINE", "")
        adapter._configure_engine()
        assert "MODIN_ENGINE" in __import__("os").environ

        fake_ray = _FakeRay(initialized=True)
        monkeypatch.setitem(__import__("sys").modules, "ray", fake_ray)
        adapter.close()

        adapter.__del__()  # no exception

    def test_read_csv_parquet_and_concat_and_counts(self, monkeypatch, tmp_path):
        fake_mpd = SimpleNamespace()
        fake_mpd.read_csv = lambda path, **kwargs: _FakeDF([(1, "x")])
        fake_mpd.read_parquet = lambda path: {"parquet": str(path)}
        fake_mpd.concat = lambda dfs, ignore_index=True: {"concat": len(dfs), "ignore_index": ignore_index}
        fake_mpd.merge = lambda *args, **kwargs: {"merged": True, **kwargs}

        monkeypatch.setattr(mod, "mpd", fake_mpd)

        adapter = mod.ModinDataFrameAdapter.__new__(mod.ModinDataFrameAdapter)
        adapter.engine = "ray"
        adapter.verbose = False
        adapter.very_verbose = False
        adapter.working_dir = Path.cwd()

        tbl_path = tmp_path / "lineitem.tbl"
        tbl_path.write_text("1|x|\n")

        df = adapter.read_csv(tbl_path, names=["id", "name"], header=None)
        assert TRAILING_DUMMY_COLUMN not in df.columns

        pq = adapter.read_parquet(tmp_path / "x.parquet")
        assert "parquet" in pq

        one = adapter.concat([{"a": 1}])
        assert one == {"a": 1}
        many = adapter.concat([{"a": 1}, {"a": 2}])
        assert many["concat"] == 2

        assert adapter.get_row_count(_FakeDF([(1,), (2,)])) == 2
        assert adapter._get_first_row(_FakeDF([(1, "a")])) == (1, "a")
        assert adapter._get_first_row(_FakeDF([])) is None

    def test_datetime_groupby_merge_to_pandas_and_info(self, monkeypatch):
        fake_pd = SimpleNamespace(
            __version__="2.0",
            Timedelta=lambda days: timedelta(days=days),
            to_datetime=lambda s: f"dt:{s}",
        )
        monkeypatch.setattr(mod, "pd", fake_pd)
        monkeypatch.setattr(mod, "PANDAS_AVAILABLE", True)

        fake_modin = SimpleNamespace(__version__="0.30")
        monkeypatch.setitem(__import__("sys").modules, "modin", fake_modin)
        monkeypatch.setattr(mod, "MODIN_AVAILABLE", True)

        fake_mpd = SimpleNamespace(merge=lambda *args, **kwargs: {"ok": kwargs})
        monkeypatch.setattr(mod, "mpd", fake_mpd)

        adapter = mod.ModinDataFrameAdapter.__new__(mod.ModinDataFrameAdapter)
        adapter.engine = "ray"
        adapter.verbose = False
        adapter.very_verbose = False
        adapter.working_dir = Path.cwd()

        assert adapter.to_datetime("x") == "dt:x"
        assert adapter.timedelta_days(3) == timedelta(days=3)

        merged = adapter.merge({"l": 1}, {"r": 2}, on="id", how="left")
        assert merged["ok"]["on"] == "id"
        assert merged["ok"]["how"] == "left"

        group_df = _GroupableDF()
        named = adapter.groupby_agg(group_df, by="k", agg_spec={"sum_qty": ("qty", "sum")})
        assert "kwargs" in named
        direct = adapter.groupby_agg(group_df, by="k", agg_spec={"qty": "sum"})
        assert "args" in direct

        class DFWithToPandas:
            def _to_pandas(self):
                return {"pd": True}

        assert adapter.to_pandas(DFWithToPandas()) == {"pd": True}

        class BrokenToPandas:
            def _to_pandas(self):
                raise RuntimeError("nope")

        broken = BrokenToPandas()
        assert adapter.to_pandas(broken) is broken

        info = adapter.get_platform_info()
        assert info["platform"] == "Modin"
        assert info["engine"] == "ray"
        assert info["version"] == "0.30"


class TestSupportedEngineIsFailClosed:
    """An accepted-but-unsupported backend is an unreliable public contract."""

    def test_pandas_is_rejected_rather_than_resembling_a_valid_engine(self):
        with pytest.raises(ValueError, match="Unsupported Modin engine 'pandas'"):
            mod.ModinDataFrameAdapter._validate_engine("pandas")

    @pytest.mark.parametrize("engine", ["python", "unidist", "native", "", "ray;dask"])
    def test_unreviewed_backends_are_rejected(self, engine):
        with pytest.raises(ValueError, match="Unsupported Modin engine"):
            mod.ModinDataFrameAdapter._validate_engine(engine)

    @pytest.mark.parametrize(
        ("engine", "expected"), [("ray", "ray"), ("dask", "dask"), ("RAY", "ray"), (" dask ", "dask")]
    )
    def test_reviewed_backends_are_accepted_and_normalized(self, engine, expected):
        assert mod.ModinDataFrameAdapter._validate_engine(engine) == expected

    def test_the_reviewed_set_matches_the_mcp_contract(self):
        """The adapter and the MCP allow-list must not drift apart."""
        from benchbox.mcp.schemas import MCP_PLATFORM_OPTION_ALLOWLIST

        assert set(MCP_PLATFORM_OPTION_ALLOWLIST["modin"]["engine"].choices) == set(mod.SUPPORTED_MODIN_ENGINES)

    def test_constructor_rejects_before_touching_the_modin_environment(self, monkeypatch):
        """Validation must run before MODIN_ENGINE is written."""
        monkeypatch.delenv("MODIN_ENGINE", raising=False)
        monkeypatch.setattr(mod, "MODIN_AVAILABLE", True)
        monkeypatch.setattr(mod, "PANDAS_AVAILABLE", True)

        with pytest.raises(ValueError, match="Unsupported Modin engine 'pandas'"):
            mod.ModinDataFrameAdapter(engine="pandas")

        assert "MODIN_ENGINE" not in os.environ

    def test_tuning_engine_affinity_shares_the_reviewed_set(self):
        """engine_affinity must not become a second, drifting allow-list."""
        import inspect

        source = inspect.getsource(mod.ModinDataFrameAdapter._apply_tuning)
        assert "SUPPORTED_MODIN_ENGINES" in source
