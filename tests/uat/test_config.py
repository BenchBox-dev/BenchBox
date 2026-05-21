"""Fast-test coverage for tests/uat/config.py.

Covers W3-relevant fields only. W4 expands.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.uat import config

pytestmark = pytest.mark.fast


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "uat.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


def _leaf_field_paths(payload: Any, *, prefix: str = "") -> set[str]:
    if not isinstance(payload, dict):
        return {prefix}
    paths: set[str] = set()
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            paths.update(_leaf_field_paths(value, prefix=path))
        else:
            paths.add(path)
    return paths


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
    assert cfg.platforms.groups is None
    assert cfg.benchmarks.groups is None
    assert cfg.scales.rungs == (0.01,)
    assert cfg.validate.validator_clean_rate_floor == 0.80
    assert cfg.package.submit_terminal_state is None
    assert cfg.explorer_smoke.playwright_browsers == ("chromium",)
    assert cfg.report.matrix_summary_tsv == "matrix_summary.tsv"
    assert cfg.compatibility.release_gate_runtime_envelopes is False


def test_validate_config_rejects_parallel_platforms():
    with pytest.raises(config.ConfigError, match="parallel_platforms"):
        config.validate_config({"name": "smoke", "execute": {"parallel_platforms": True}})


def test_validate_config_rejects_unknown_phase():
    with pytest.raises(config.ConfigError, match="Unknown phase"):
        config.validate_config({"name": "smoke", "phases": ["preflight", "moonshot"]})


def test_validate_config_rejects_missing_name():
    with pytest.raises(config.ConfigError, match="`name:`"):
        config.validate_config({})


def test_validate_config_rejects_unknown_root_field():
    with pytest.raises(config.ConfigError, match="Unknown field\\(s\\) in `root`: moonshot"):
        config.validate_config({"name": "smoke", "moonshot": True})


def test_validate_config_rejects_unknown_section_field():
    with pytest.raises(config.ConfigError, match="Unknown field\\(s\\) in `platforms`: moonshot"):
        config.validate_config({"name": "smoke", "platforms": {"moonshot": True}})


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


@pytest.mark.parametrize(
    ("section", "payload", "field"),
    [
        ("root", {"dry_run": "false"}, "dry_run"),
        ("execute", {"execute": {"early_stop_on_failure": "false"}}, "early_stop_on_failure"),
        ("execute", {"execute": {"skip_unreachable": "false"}}, "skip_unreachable"),
        ("preflight", {"preflight": {"docker_required": "false"}}, "docker_required"),
        ("preflight", {"preflight": {"local_platforms_check": "false"}}, "local_platforms_check"),
    ],
)
def test_validate_config_rejects_quoted_booleans(section: str, payload: dict[str, object], field: str):
    with pytest.raises(config.ConfigError, match=rf"{section}\.{field}` must be a bool"):
        config.validate_config({"name": "smoke", **payload})


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


def test_stress_default_fields_have_reader_or_reserved_contract():
    payload = yaml.safe_load(Path("tests/uat/configs/stress-default.yaml").read_text(encoding="utf-8"))
    evidence = {
        "name": ("tests/uat/config.py", 'name = payload.get("name")'),
        "description": ("tests/uat/config.py", 'description=str(payload.get("description", ""))'),
        "phases": ("tests/uat/config.py", '_validate_phases(payload.get("phases")'),
        "platforms.groups": ("tests/uat/phases/enumerate.py", "config.platforms.groups"),
        "benchmarks.groups": ("tests/uat/phases/enumerate.py", "config.benchmarks.groups"),
        "scales.rungs": ("tests/uat/phases/enumerate.py", "config.scales.rungs"),
        "execute.per_cell_timeout_s": ("tests/uat/phases/execute.py", "config.execute.per_cell_timeout_s"),
        "execute.early_stop_after_s": ("tests/uat/phases/execute.py", "config.execute.early_stop_after_s"),
        "execute.early_stop_on_failure": ("tests/uat/phases/execute.py", "config.execute.early_stop_on_failure"),
        "execute.phases_arg": ("tests/uat/phases/execute.py", "config.execute.phases_arg"),
        "execute.skip_unreachable": ("tests/uat/phases/execute.py", "config.execute.skip_unreachable"),
        "preflight.free_space_min_gib": ("tests/uat/phases/preflight.py", "config.preflight.free_space_min_gib"),
        "preflight.free_space_path": ("tests/uat/phases/preflight.py", "config.preflight.free_space_path"),
        "cleanup.preserve_datagen": ("tests/uat/config.py", "preserve_datagen: false` is not supported"),
        "cleanup.prune_databases": ("tests/uat/orchestrator.py", "config.cleanup.prune_databases"),
        "cleanup.docker_manage_platforms": ("tests/uat/phases/execute.py", "config.cleanup.docker_manage_platforms"),
        "cleanup.docker_platform_switch": ("tests/uat/phases/execute.py", "config.cleanup.docker_platform_switch"),
        "cleanup.docker_project_prefix": ("tests/uat/phases/execute.py", "config.cleanup.docker_project_prefix"),
        "cleanup.docker_start_timeout_s": ("tests/uat/phases/execute.py", "config.cleanup.docker_start_timeout_s"),
        "cleanup.docker_fixed_container_name_policy": (
            "tests/uat/phases/execute.py",
            "config.cleanup.docker_fixed_container_name_policy",
        ),
        "report.matrix_summary_tsv": ("tests/uat/orchestrator.py", "config.report.matrix_summary_tsv"),
        "output.logs_dir_template": ("tests/uat/phases/execute.py", "config.output.logs_dir_template"),
        "output.submissions_dir_template": (
            "tests/uat/orchestrator.py",
            "config.output.submissions_dir_template",
        ),
    }

    fields = _leaf_field_paths(payload)
    assert fields == set(evidence)
    for field, (path, snippet) in evidence.items():
        text = Path(path).read_text(encoding="utf-8")
        assert snippet in text, f"{field} lost its reader/reserved-field evidence in {path}"


def test_stress_override_uses_dataclass_replace_for_platform_and_benchmark():
    cfg = config.validate_config(
        {
            "name": "stress",
            "platforms": {"groups": ["all"]},
            "benchmarks": {"groups": ["all"]},
        }
    )
    overridden = replace(
        cfg,
        platforms=replace(cfg.platforms, groups=(), include=("duckdb",)),
        benchmarks=replace(cfg.benchmarks, groups=(), include=("tpch",)),
    )
    assert overridden.platforms.groups == ()
    assert overridden.platforms.include == ("duckdb",)
    assert overridden.benchmarks.include == ("tpch",)
    # Original config not mutated
    assert cfg.platforms.groups == ("all",)


def test_stress_override_scale_sets_override_without_mutating_rungs():
    cfg = config.validate_config({"name": "stress", "scales": {"rungs": [0.01, 0.1, 1.0]}})
    overridden = replace(cfg, scales=replace(cfg.scales, override=0.1))
    assert overridden.scales.rungs == (0.01, 0.1, 1.0)
    assert overridden.scales.override == 0.1
