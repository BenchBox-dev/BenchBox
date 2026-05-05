"""Fast-test coverage for tests/uat/config.py.

Covers W3-relevant fields only. W4 expands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.uat import config

pytestmark = pytest.mark.fast


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "uat.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


def test_validate_config_minimal():
    cfg = config.validate_config({"name": "smoke"})
    assert cfg.name == "smoke"
    assert "execute" in cfg.phases or cfg.phases  # default phases applied
    assert cfg.execute.per_cell_timeout_s == 600
    assert cfg.execute.parallel_platforms is False


def test_validate_config_rejects_parallel_platforms():
    with pytest.raises(config.ConfigError, match="parallel_platforms"):
        config.validate_config({"name": "smoke", "execute": {"parallel_platforms": True}})


def test_validate_config_rejects_unknown_phase():
    with pytest.raises(config.ConfigError, match="Unknown phase"):
        config.validate_config({"name": "smoke", "phases": ["preflight", "moonshot"]})


def test_validate_config_rejects_missing_name():
    with pytest.raises(config.ConfigError, match="`name:`"):
        config.validate_config({})


def test_validate_config_rejects_zero_timeout():
    with pytest.raises(config.ConfigError, match="per_cell_timeout_s"):
        config.validate_config({"name": "smoke", "execute": {"per_cell_timeout_s": 0}})


def test_validate_config_rejects_float_timeout():
    with pytest.raises(config.ConfigError, match="per_cell_timeout_s"):
        config.validate_config({"name": "smoke", "execute": {"per_cell_timeout_s": 60.5}})


def test_validate_config_accepts_string_int_timeout():
    cfg = config.validate_config({"name": "smoke", "execute": {"per_cell_timeout_s": "120"}})
    assert cfg.execute.per_cell_timeout_s == 120


def test_validate_config_rejects_bool_timeout():
    with pytest.raises(config.ConfigError, match="per_cell_timeout_s"):
        config.validate_config({"name": "smoke", "execute": {"per_cell_timeout_s": True}})


def test_load_config_round_trip(tmp_path: Path):
    p = _write(
        tmp_path,
        {
            "name": "rep",
            "description": "test",
            "phases": ["preflight", "execute", "report"],
            "execute": {
                "per_cell_timeout_s": 60,
                "phases_arg": "load,power",
            },
        },
    )
    cfg = config.load_config(p)
    assert cfg.name == "rep"
    assert cfg.execute.per_cell_timeout_s == 60
    assert cfg.phases == ("preflight", "execute", "report")


def test_load_config_missing_file(tmp_path: Path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load_config(tmp_path / "nope.yaml")


def test_apply_stress_overrides_platform_and_benchmark():
    cfg = config.validate_config(
        {
            "name": "stress",
            "platforms": {"groups": ["all"]},
            "benchmarks": {"groups": ["all"]},
        }
    )
    overridden = config.apply_stress_overrides(cfg, platform="duckdb", benchmark="tpch")
    assert overridden.raw["platforms"]["groups"] == []
    assert overridden.raw["platforms"]["include"] == ["duckdb"]
    assert overridden.raw["benchmarks"]["include"] == ["tpch"]
    # Original config not mutated
    assert cfg.raw["platforms"]["groups"] == ["all"]


def test_apply_stress_overrides_scale_clears_rungs():
    cfg = config.validate_config({"name": "stress", "scales": {"rungs": [0.01, 0.1, 1.0]}})
    overridden = config.apply_stress_overrides(cfg, scale=0.1)
    assert "rungs" not in overridden.raw["scales"]
    assert overridden.raw["scales"]["override"] == 0.1
