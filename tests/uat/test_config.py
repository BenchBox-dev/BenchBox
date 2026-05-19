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
    assert cfg.output.benchmark_runs_dir_template == "~/Developer/benchmark_runs"
    assert cfg.preflight.free_space_min_gib == 5.0
    assert cfg.cleanup.docker_manage_platforms is False
    assert cfg.cleanup.docker_platform_switch == "off"


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


def test_validate_config_accepts_execute_extra_args():
    cfg = config.validate_config({"name": "smoke", "execute": {"extra_args": ["--tuning", "tuned"]}})
    assert cfg.execute.extra_args == ("--tuning", "tuned")


def test_validate_config_accepts_managed_docker_cleanup_contract():
    cfg = config.validate_config(
        {
            "name": "smoke",
            "cleanup": {
                "docker_manage_platforms": True,
                "docker_platform_switch": "volumes",
                "docker_project_prefix": "benchbox-uat-test",
                "docker_start_timeout_s": 42,
                "docker_fixed_container_name_policy": "fail",
            },
        }
    )
    assert cfg.cleanup.docker_manage_platforms is True
    assert cfg.cleanup.docker_platform_switch == "volumes"
    assert cfg.cleanup.docker_project_prefix == "benchbox-uat-test"
    assert cfg.cleanup.docker_start_timeout_s == 42


@pytest.mark.parametrize(
    ("field", "cleanup"),
    [
        ("preserve_datagen", {"preserve_datagen": "false"}),
        ("prune_databases", {"prune_databases": "false"}),
        (
            "docker_manage_platforms",
            {"docker_manage_platforms": "false", "docker_platform_switch": "volumes"},
        ),
    ],
)
def test_validate_config_rejects_quoted_cleanup_booleans(field: str, cleanup: dict[str, object]):
    with pytest.raises(config.ConfigError, match=rf"cleanup\.{field}` must be a bool"):
        config.validate_config({"name": "smoke", "cleanup": cleanup})


def test_validate_config_rejects_invalid_docker_cleanup_mode():
    with pytest.raises(config.ConfigError, match="docker_platform_switch"):
        config.validate_config({"name": "smoke", "cleanup": {"docker_platform_switch": "everything"}})


def test_validate_config_rejects_docker_cleanup_noop_without_managed_lifecycle():
    with pytest.raises(config.ConfigError, match="docker_manage_platforms"):
        config.validate_config({"name": "smoke", "cleanup": {"docker_platform_switch": "volumes"}})


def test_validate_config_rejects_invalid_fixed_container_name_policy():
    with pytest.raises(config.ConfigError, match="docker_fixed_container_name_policy"):
        config.validate_config(
            {
                "name": "smoke",
                "cleanup": {
                    "docker_manage_platforms": True,
                    "docker_platform_switch": "volumes",
                    "docker_fixed_container_name_policy": "shrug",
                },
            }
        )


def test_validate_config_accepts_benchmark_runs_dir_template(tmp_path: Path):
    root = tmp_path / "runs" / "{name}" / "{date}"
    cfg = config.validate_config({"name": "smoke", "output": {"benchmark_runs_dir_template": str(root)}})
    assert cfg.output.benchmark_runs_dir_template == str(root)


def test_validate_config_rejects_non_string_execute_extra_args():
    with pytest.raises(config.ConfigError, match="extra_args"):
        config.validate_config({"name": "smoke", "execute": {"extra_args": ["--tuning", 1]}})


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
