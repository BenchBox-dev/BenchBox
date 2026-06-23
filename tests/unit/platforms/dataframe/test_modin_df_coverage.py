from __future__ import annotations

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


class _ContractDF:
    """Records read kwargs and supports the fillna assignment the contract uses."""

    def __init__(self, columns, store):
        self.columns = list(columns)
        self._store = store

    def __getitem__(self, key):
        # df[present] -> a stand-in supporting .fillna(value)
        cols = key if isinstance(key, list) else [key]

        class _Sel:
            def fillna(self, value):
                return ("filled", cols, value)

        return _Sel()

    def __setitem__(self, key, value):
        self._store["fillna"] = (key, value)


def test_read_csv_applies_string_dtype_and_empty_string_contract(monkeypatch, tmp_path):
    """Declared string columns get dtype=object and "" is preserved when null_marker is None (w6)."""
    store: dict = {}

    def _read_csv(path, **kwargs):  # noqa: ARG001
        store["kwargs"] = kwargs
        return _ContractDF(["id", "code", "note"], store)

    monkeypatch.setattr(mod, "mpd", SimpleNamespace(read_csv=_read_csv))

    adapter = mod.ModinDataFrameAdapter.__new__(mod.ModinDataFrameAdapter)
    adapter.verbose = False
    adapter.very_verbose = False

    csv_path = tmp_path / "t.csv"
    csv_path.write_text("id,code,note\n1,007,\n")

    adapter.read_csv(
        csv_path,
        header=0,
        names=["id", "code", "note"],
        null_marker=None,
        column_types=["INTEGER", "VARCHAR(8)", "TEXT"],
    )
    # Declared string columns are read as object so a leading-zero VARCHAR stays text.
    assert store["kwargs"]["dtype"] == {"code": "object", "note": "object"}
    # Empty fields restored to "" on the declared string columns (null_marker is None).
    key, value = store["fillna"]
    assert sorted(key) == ["code", "note"]
    assert value == ("filled", ["code", "note"], "")
