"""Coverage tests for CLI tuning wizard module."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

t = importlib.import_module("benchbox.cli.tuning")
TuningType = importlib.import_module("benchbox.core.tuning.interface").TuningType

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _DummyConfig:
    def __init__(self):
        self.primary_keys = SimpleNamespace(enabled=False)
        self.foreign_keys = SimpleNamespace(enabled=False)
        self.unique_constraints = SimpleNamespace(enabled=False)
        self.check_constraints = SimpleNamespace(enabled=False)
        self.enabled = set()
        self.disabled = False

    def enable_all_constraints(self):
        self.primary_keys.enabled = True
        self.foreign_keys.enabled = True
        self.unique_constraints.enabled = True
        self.check_constraints.enabled = True

    def disable_all_constraints(self):
        self.primary_keys.enabled = False
        self.foreign_keys.enabled = False
        self.unique_constraints.enabled = False
        self.check_constraints.enabled = False
        self.disabled = True

    def enable_primary_keys(self):
        self.primary_keys.enabled = True

    def enable_foreign_keys(self):
        self.foreign_keys.enabled = True

    def disable_foreign_keys(self):
        self.foreign_keys.enabled = False

    def enable_platform_optimization(self, tuning_type):
        self.enabled.add(tuning_type)

    def get_enabled_tuning_types(self):
        return self.enabled

    def to_dict(self):
        return {"enabled": [e.value for e in self.enabled]}


class _DummyWriteConfig:
    def __init__(self, **kwargs):
        self.sort_by = kwargs.get("sort_by", [])
        self.partition_by = kwargs.get("partition_by", [])
        self.row_group_size = kwargs.get("row_group_size")
        self.repartition_count = kwargs.get("repartition_count")
        self.compression_level = kwargs.get("compression_level")


def _patch_unified_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t, "UnifiedTuningConfiguration", _DummyConfig)


def _seq(values):
    it = iter(values)
    return lambda *a, **k: next(it)


def test_recommendation_helpers() -> None:
    assert t._get_recommended_threads(8, "duckdb") == 7
    assert t._get_recommended_threads(4, "sqlite") == 1
    assert t._get_recommended_memory_limit(16.0, "duckdb") == pytest.approx(11.2)
    assert t._get_recommended_memory_limit(16.0, "bigquery") is None
    assert t._get_recommended_max_scale(4.0, "tpch") == 0.01
    assert t._get_recommended_max_scale(64.0, "tpcds") == 0.1
    assert t._get_recommended_max_scale(64.0, "clickbench") == 1.0


def test_autofill_defaults_cloud_and_local() -> None:
    profile = SimpleNamespace(cpu_cores_logical=8, memory_total_gb=32.0)
    cloud = t.autofill_defaults(profile, "databricks", benchmark="tpch")
    local = t.autofill_defaults(profile, "duckdb", benchmark="tpcds")

    assert cloud["tuning_mode"] == "tuned"
    assert cloud["enable_photon"] is True
    assert local["tuning_mode"] == "balanced"
    assert local["memory_limit_str"].endswith("GB")
    assert local["max_recommended_sf"] <= 1.0


def test_apply_defaults_to_config() -> None:
    cfg = _DummyConfig()
    out = t._apply_defaults_to_config(cfg, defaults={}, platform="redshift")
    assert out.primary_keys.enabled is True
    assert TuningType.DISTRIBUTION in out.enabled
    assert TuningType.SORTING in out.enabled


def test_run_tuning_wizard_non_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_unified_config(monkeypatch)
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    monkeypatch.setattr(t, "_apply_defaults_to_config", lambda c, d, p: ("applied", c, d, p))
    out = t.run_tuning_wizard("tpch", "duckdb", SimpleNamespace(), interactive=False)
    assert out[0] == "applied"


def test_run_tuning_wizard_baseline_and_simple(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_unified_config(monkeypatch)
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_prompt_save_config", lambda *a, **k: None)

    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    baseline = t.run_tuning_wizard("tpch", "duckdb", SimpleNamespace(), interactive=True)
    assert isinstance(baseline, _DummyConfig)
    assert baseline.disabled is True

    monkeypatch.setattr(t.Prompt, "ask", _seq(["1"]))
    monkeypatch.setattr(t, "_run_simple_wizard", lambda c, *_a, **_k: c)
    simple = t.run_tuning_wizard("tpch", "duckdb", SimpleNamespace(), interactive=True)
    assert isinstance(simple, _DummyConfig)


def test_run_tuning_wizard_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_unified_config(monkeypatch)
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_prompt_save_config", lambda *a, **k: None)
    monkeypatch.setattr(t.Prompt, "ask", _seq(["2"]))
    monkeypatch.setattr(t, "_run_advanced_wizard", lambda c, *_a, **_k: c)
    out = t.run_tuning_wizard("tpch", "snowflake", SimpleNamespace(), interactive=True)
    assert isinstance(out, _DummyConfig)


def test_simple_wizard_objectives_and_platform_feature_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _DummyConfig()
    defaults = {"enable_z_ordering": True, "enable_clustering": True}
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_show_simple_summary", lambda *a, **k: None)

    monkeypatch.setattr(t.Prompt, "ask", _seq(["1"]))
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, True]))
    out1 = t._run_simple_wizard(cfg, defaults, "databricks", "tpch", SimpleNamespace())
    assert TuningType.Z_ORDERING in out1.enabled

    cfg2 = _DummyConfig()
    monkeypatch.setattr(t.Prompt, "ask", _seq(["2"]))
    out2 = t._run_simple_wizard(cfg2, defaults, "duckdb", "tpch", SimpleNamespace())
    assert out2.primary_keys.enabled is True
    assert out2.foreign_keys.enabled is False

    cfg3 = _DummyConfig()
    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    out3 = t._run_simple_wizard(cfg3, defaults, "bigquery", "tpch", SimpleNamespace())
    assert out3.primary_keys.enabled is True


def test_advanced_wizard_and_platform_specific_configurators(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _DummyConfig()
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, False, True, True]))
    monkeypatch.setattr(
        t, "_configure_databricks_optimizations", lambda c: c.enable_platform_optimization(TuningType.Z_ORDERING)
    )
    monkeypatch.setattr(t, "render_tuning_summary", lambda *a, **k: None)
    out = t._run_advanced_wizard(cfg, {}, "databricks", "tpch", SimpleNamespace())
    assert out.primary_keys.enabled is True
    assert out.unique_constraints.enabled is True
    assert TuningType.Z_ORDERING in out.enabled

    cfg2 = _DummyConfig()
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, True, False, False]))
    monkeypatch.setattr(
        t, "_configure_snowflake_optimizations", lambda c: c.enable_platform_optimization(TuningType.CLUSTERING)
    )
    out2 = t._run_advanced_wizard(cfg2, {}, "snowflake", "tpch", SimpleNamespace())
    assert TuningType.CLUSTERING in out2.enabled


def test_platform_config_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(
        t.Confirm,
        "ask",
        _seq([True, True, True, True, True, True, True, True, True, True, True, True]),
    )
    cfg = _DummyConfig()
    t._configure_databricks_optimizations(cfg)
    t._configure_snowflake_optimizations(cfg)
    t._configure_bigquery_optimizations(cfg)
    t._configure_redshift_optimizations(cfg)
    t._configure_duckdb_optimizations(cfg, {"memory_limit_str": "8GB", "threads": 4})
    t._configure_clickhouse_optimizations(cfg)
    assert len(cfg.enabled) > 0


def test_render_summary_and_simple_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _DummyConfig()
    cfg.enable_all_constraints()
    cfg.enable_platform_optimization(TuningType.CLUSTERING)
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    tbl = t.render_tuning_summary(cfg, "snowflake")
    assert tbl.row_count > 0
    t._show_simple_summary(cfg, {}, "snowflake")


def test_prompt_save_config_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = _DummyConfig()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)

    monkeypatch.setattr(t.Confirm, "ask", _seq([False]))
    t._prompt_save_config(cfg, "duckdb", "tpch")

    monkeypatch.setattr(t.Confirm, "ask", _seq([True]))
    monkeypatch.setattr(t.Prompt, "ask", _seq([str(tmp_path / "x.yaml")]))
    monkeypatch.setattr(
        "benchbox.core.config_utils.save_config_file", lambda d, p, f: p.write_text("ok\n", encoding="utf-8")
    )
    t._prompt_save_config(cfg, "duckdb", "tpch")
    assert (tmp_path / "x.yaml").exists()

    monkeypatch.setattr(t.Confirm, "ask", _seq([True]))
    monkeypatch.setattr(t.Prompt, "ask", _seq([str(tmp_path / "y.yaml")]))
    monkeypatch.setattr(
        "benchbox.core.config_utils.save_config_file", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    t._prompt_save_config(cfg, "duckdb", "tpch")


def test_run_dataframe_write_wizard_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tuning = SimpleNamespace(
        DataFrameWriteConfiguration=_DummyWriteConfig,
        PartitionColumn=lambda name, strategy: SimpleNamespace(name=name, strategy=strategy),
        PartitionStrategy=lambda v: SimpleNamespace(value=v),
        SortColumn=lambda name, order: SimpleNamespace(name=name, order=order),
        get_platform_write_capabilities=lambda _p: {
            "sort_by": True,
            "partition_by": True,
            "repartition_count": True,
            "row_group_size": True,
        },
    )
    monkeypatch.setitem(sys.modules, "benchbox.core.dataframe.tuning", fake_tuning)
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)

    out_non_interactive = t.run_dataframe_write_wizard("duckdb", interactive=False)
    assert out_non_interactive is None

    monkeypatch.setattr(t.Confirm, "ask", _seq([False]))
    out_skip = t.run_dataframe_write_wizard("duckdb", interactive=True)
    assert out_skip is None

    monkeypatch.setattr(t.Confirm, "ask", _seq([True, True, True, True, True, True]))
    monkeypatch.setattr(
        t.Prompt,
        "ask",
        _seq(["l_shipdate", "asc", "day", "date_day"]),
    )
    monkeypatch.setattr(t.IntPrompt, "ask", _seq([1000, 8, 3]))
    cfg = t.run_dataframe_write_wizard("duckdb", benchmark="tpch", interactive=True)
    assert cfg is not None
    assert cfg.row_group_size == 1000

    t._show_dataframe_write_summary(cfg, "duckdb")
