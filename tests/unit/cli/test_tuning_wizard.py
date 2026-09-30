"""Coverage tests for CLI tuning wizard module.

The wizard tests run against real ``UnifiedTuningConfiguration`` objects so a
table-layout choice that the config silently drops fails here instead of
passing against a stand-in that accepts every type.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

t = importlib.import_module("benchbox.cli.tuning")
tuning_interface = importlib.import_module("benchbox.core.tuning.interface")
TuningType = tuning_interface.TuningType
UnifiedTuningConfiguration = tuning_interface.UnifiedTuningConfiguration

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _DummyWriteConfig:
    def __init__(self, **kwargs):
        self.sort_by = kwargs.get("sort_by", [])
        self.partition_by = kwargs.get("partition_by", [])
        self.row_group_size = kwargs.get("row_group_size")
        self.repartition_count = kwargs.get("repartition_count")
        self.compression_level = kwargs.get("compression_level")


def _seq(values):
    it = iter(values)
    return lambda *a, **k: next(it)


def _enabled(config: UnifiedTuningConfiguration) -> set:
    return config.get_enabled_tuning_types()


def _table_slots(config: UnifiedTuningConfiguration) -> dict[str, set[str]]:
    """Map table name to the layout slots recorded on it."""
    slots: dict[str, set[str]] = {}
    for name, entry in config.table_tunings.items():
        present = {slot for slot in ("partitioning", "clustering", "distribution", "sorting") if getattr(entry, slot)}
        if present:
            slots[name] = present
    return slots


def test_recommendation_helpers() -> None:
    assert t._get_recommended_threads(8, "duckdb") == 7
    assert t._get_recommended_threads(4, "sqlite") == 1
    assert t._get_recommended_memory_limit(16.0, "duckdb") == pytest.approx(11.2)
    assert t._get_recommended_memory_limit(16.0, "bigquery") is None
    assert t._get_recommended_max_scale(4.0, "tpch") == 0.01
    assert t._get_recommended_max_scale(64.0, "tpcds") == 0.1
    assert t._get_recommended_max_scale(64.0, "clickbench") == 10.0


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
    cfg = UnifiedTuningConfiguration()
    out = t._apply_defaults_to_config(cfg, defaults={}, platform="redshift", benchmark="tpch")
    assert out.primary_keys.enabled is True
    # The DuckDB TPC-H template carries sorting but no distribution slot, so
    # only sorting persists; distribution is declined rather than invented.
    assert TuningType.DISTRIBUTION not in _enabled(out)
    assert TuningType.SORTING in _enabled(out)
    slots = _table_slots(out)
    assert slots, "redshift defaults must persist sort table entries"
    assert all("sorting" in present for present in slots.values())


def test_apply_defaults_to_config_all_platforms() -> None:
    # Only template-backed slots persist: TPC-H carries partitioning on two
    # tables and sorting on six, but no clustering or distribution slot.
    expected = {
        "snowflake": set(),
        "bigquery": {TuningType.PARTITIONING},
        "redshift": {TuningType.SORTING},
    }
    for platform, types in expected.items():
        cfg = UnifiedTuningConfiguration()
        out = t._apply_defaults_to_config(cfg, defaults={}, platform=platform, benchmark="tpch")
        enabled = _enabled(out)
        for tuning_type in types:
            assert tuning_type in enabled, f"{platform} default lost {tuning_type}"
        slots = _table_slots(out)
        if types:
            assert slots, f"{platform} defaults must persist table entries"
        else:
            assert not slots, f"{platform} has no template slot so nothing persists"

    databricks_cfg = UnifiedTuningConfiguration()
    databricks_out = t._apply_defaults_to_config(databricks_cfg, defaults={}, platform="databricks")
    assert TuningType.Z_ORDERING in _enabled(databricks_out)
    assert TuningType.AUTO_OPTIMIZE in _enabled(databricks_out)


def test_enable_layout_applies_every_matching_template_table() -> None:
    """A global layout choice reaches all tuned tables carrying the slot."""
    cfg = UnifiedTuningConfiguration()
    cfg.enable_platform_optimization(TuningType.SORTING, benchmark="tpch")
    slots = _table_slots(cfg)
    assert len(slots) > 1, f"sorting must persist on every tuned table, got {sorted(slots)}"
    assert all("sorting" in present for present in slots.values())


def test_enable_layout_declines_benchmark_without_template() -> None:
    """Benchmarks with no packaged template get no foreign table entry."""
    cfg = UnifiedTuningConfiguration()
    cfg.enable_platform_optimization(TuningType.CLUSTERING, benchmark="nyctaxi")
    assert cfg.table_tunings == {}, "unknown benchmarks must not borrow TPC-H tables"
    assert TuningType.CLUSTERING not in _enabled(cfg)


def test_run_tuning_wizard_non_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    seen: dict = {}

    def _apply(config, defaults, platform, benchmark="tpch"):
        seen.update({"platform": platform, "benchmark": benchmark})
        return ("applied", config, defaults, platform, benchmark)

    monkeypatch.setattr(t, "_apply_defaults_to_config", _apply)
    out = t.run_tuning_wizard("tpch", "redshift", SimpleNamespace(), interactive=False)
    assert out[0] == "applied"
    assert seen == {"platform": "redshift", "benchmark": "tpch"}


def test_run_tuning_wizard_baseline_and_simple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_prompt_save_config", lambda *a, **k: None)

    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    baseline = t.run_tuning_wizard("tpch", "duckdb", SimpleNamespace(), interactive=True)
    assert isinstance(baseline, UnifiedTuningConfiguration)
    assert baseline.primary_keys.enabled is False

    monkeypatch.setattr(t.Prompt, "ask", _seq(["1"]))
    monkeypatch.setattr(t, "_run_simple_wizard", lambda c, *_a, **_k: c)
    simple = t.run_tuning_wizard("tpch", "duckdb", SimpleNamespace(), interactive=True)
    assert isinstance(simple, UnifiedTuningConfiguration)


def test_run_tuning_wizard_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t, "autofill_defaults", lambda *a, **k: {"threads": 4})
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_prompt_save_config", lambda *a, **k: None)
    monkeypatch.setattr(t.Prompt, "ask", _seq(["2"]))
    monkeypatch.setattr(t, "_run_advanced_wizard", lambda c, *_a, **_k: c)
    out = t.run_tuning_wizard("tpch", "snowflake", SimpleNamespace(), interactive=True)
    assert isinstance(out, UnifiedTuningConfiguration)


def test_simple_wizard_objectives_and_platform_feature_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = {"enable_z_ordering": True, "enable_clustering": True}
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_show_simple_summary", lambda *a, **k: None)

    monkeypatch.setattr(t.Prompt, "ask", _seq(["1"]))
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, True]))
    out1 = t._run_simple_wizard(UnifiedTuningConfiguration(), defaults, "databricks", "tpch", SimpleNamespace())
    assert TuningType.Z_ORDERING in _enabled(out1)

    monkeypatch.setattr(t.Prompt, "ask", _seq(["2"]))
    out2 = t._run_simple_wizard(UnifiedTuningConfiguration(), defaults, "duckdb", "tpch", SimpleNamespace())
    assert out2.primary_keys.enabled is True
    assert out2.foreign_keys.enabled is False

    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    out3 = t._run_simple_wizard(UnifiedTuningConfiguration(), defaults, "bigquery", "tpch", SimpleNamespace())
    assert out3.primary_keys.enabled is True


def test_simple_wizard_persists_table_layout_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirmed table-layout choices must survive on the resulting config."""
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t, "_show_simple_summary", lambda *a, **k: None)

    # Snowflake clustering has no TPC-H template slot, so the choice is
    # declined rather than persisted on a foreign table.
    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    monkeypatch.setattr(t.Confirm, "ask", _seq([True]))
    snowflake_out = t._run_simple_wizard(
        UnifiedTuningConfiguration(), {"enable_clustering": True}, "snowflake", "tpch", SimpleNamespace()
    )
    assert TuningType.CLUSTERING not in _enabled(snowflake_out)
    assert not _table_slots(snowflake_out)

    # BigQuery partitioning persists; clustering has no slot and is declined.
    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    monkeypatch.setattr(t.Confirm, "ask", _seq([True]))
    bigquery_out = t._run_simple_wizard(
        UnifiedTuningConfiguration(), {"enable_clustering": True}, "bigquery", "tpch", SimpleNamespace()
    )
    assert TuningType.PARTITIONING in _enabled(bigquery_out)
    assert TuningType.CLUSTERING not in _enabled(bigquery_out)
    bigquery_slots = _table_slots(bigquery_out)
    assert any("partitioning" in present for present in bigquery_slots.values())

    # Redshift sort keys persist on all six tuned tables; distribution is declined.
    monkeypatch.setattr(t.Prompt, "ask", _seq(["3"]))
    monkeypatch.setattr(t.Confirm, "ask", _seq([True]))
    redshift_out = t._run_simple_wizard(UnifiedTuningConfiguration(), {}, "redshift", "tpch", SimpleNamespace())
    assert TuningType.DISTRIBUTION not in _enabled(redshift_out)
    assert TuningType.SORTING in _enabled(redshift_out)
    redshift_slots = _table_slots(redshift_out)
    assert len(redshift_slots) == 6, f"sorting must reach all tuned tables, got {sorted(redshift_slots)}"
    assert all("sorting" in present for present in redshift_slots.values())


def test_advanced_wizard_and_platform_specific_configurators(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = UnifiedTuningConfiguration()
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, False, True, True]))
    monkeypatch.setattr(
        t, "_configure_databricks_optimizations", lambda c: c.enable_platform_optimization(TuningType.Z_ORDERING)
    )
    monkeypatch.setattr(t, "render_tuning_summary", lambda *a, **k: None)
    out = t._run_advanced_wizard(cfg, {}, "databricks", "tpch", SimpleNamespace())
    assert out.primary_keys.enabled is True
    assert out.unique_constraints.enabled is True
    assert TuningType.Z_ORDERING in _enabled(out)

    cfg2 = UnifiedTuningConfiguration()
    monkeypatch.setattr(t.Confirm, "ask", _seq([True, True, False, False]))
    monkeypatch.setattr(
        t,
        "_configure_snowflake_optimizations",
        lambda c, b="tpch": c.enable_platform_optimization(TuningType.CLUSTERING),
    )
    out2 = t._run_advanced_wizard(cfg2, {}, "snowflake", "tpch", SimpleNamespace())
    # Clustering has no TPC-H template slot, so the configurator records
    # nothing instead of inventing a foreign table entry.
    assert TuningType.CLUSTERING not in _enabled(out2)
    assert not _table_slots(out2)


def test_platform_config_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(
        t.Confirm,
        "ask",
        _seq([True, True, True, True, True, True, True, True, True, True, True, True]),
    )
    cfg = UnifiedTuningConfiguration()
    t._configure_databricks_optimizations(cfg)
    t._configure_snowflake_optimizations(cfg)
    t._configure_bigquery_optimizations(cfg)
    t._configure_redshift_optimizations(cfg)
    t._configure_duckdb_optimizations(cfg, {"memory_limit_str": "8GB", "threads": 4})
    t._configure_clickhouse_optimizations(cfg)
    enabled = _enabled(cfg)
    assert TuningType.Z_ORDERING in enabled
    # Only template-backed slots persist: partitioning on two tables and
    # sorting on six; clustering and distribution have no TPC-H slot.
    assert TuningType.PARTITIONING in enabled
    assert TuningType.SORTING in enabled
    assert TuningType.CLUSTERING not in enabled
    assert TuningType.DISTRIBUTION not in enabled
    slots = _table_slots(cfg)
    assert slots, "platform configurators must persist table entries"
    for tuning_type in (
        TuningType.PARTITIONING,
        TuningType.SORTING,
    ):
        assert any(tuning_type.value in present for present in slots.values()), (
            f"{tuning_type} choice was not persisted to table_tunings"
        )


def test_render_summary_and_simple_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = UnifiedTuningConfiguration()
    cfg.enable_all_constraints()
    cfg.enable_platform_optimization(TuningType.CLUSTERING)
    monkeypatch.setattr(t.console, "print", lambda *a, **k: None)
    tbl = t.render_tuning_summary(cfg, "snowflake")
    assert tbl.row_count > 0
    t._show_simple_summary(cfg, {}, "snowflake")


def test_prompt_save_config_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = UnifiedTuningConfiguration()
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
