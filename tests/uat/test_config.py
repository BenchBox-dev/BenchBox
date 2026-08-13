"""Fast-test coverage for tests/uat/config.py.

Covers W3-relevant fields only. W4 expands.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.uat import config, matrix

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
    assert cfg.preflight.free_memory_min_gib == 2.0
    assert cfg.preflight.clickhouse_memory_limit == "8g"
    assert cfg.preflight.docker_memory_reserve_gib == 2.0
    assert cfg.memory_gate_enabled is True
    assert cfg.cleanup.docker_manage_platforms is False
    assert cfg.cleanup.docker_platform_switch == "off"
    assert cfg.cleanup.docker_settle_s == 10
    assert cfg.execute.liveness_probe_timeout_s == 2.0
    assert cfg.platforms.groups is None
    assert cfg.benchmarks.groups is None
    assert cfg.scales.rungs == (0.01,)
    assert cfg.validate.validator_clean_rate_floor == 0.80
    assert cfg.package.submit_terminal_state is None
    assert cfg.explorer_smoke.playwright_browsers == ("chromium",)
    assert cfg.report.matrix_summary_tsv == "matrix_summary.tsv"
    assert cfg.compatibility.release_gate_runtime_envelopes is False


def test_validate_matrix_filter_tracks_explicit_empty_include():
    cfg = config.validate_config(
        {
            "name": "smoke",
            "platforms": {"include": []},
            "benchmarks": {"include": []},
        }
    )
    omitted = config.validate_config({"name": "smoke"})

    assert cfg.platforms.include == ()
    assert cfg.platforms.include_was_specified is True
    assert cfg.platforms.uses_implicit_group_default is False
    assert cfg.benchmarks.include_was_specified is True
    assert cfg.benchmarks.uses_implicit_group_default is False
    assert omitted.platforms.include_was_specified is False
    assert omitted.platforms.uses_implicit_group_default is True


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


def test_validate_config_accepts_liveness_probe_timeout_s():
    cfg = config.validate_config({"name": "smoke", "execute": {"liveness_probe_timeout_s": 0.5}})
    assert cfg.execute.liveness_probe_timeout_s == 0.5


def test_validate_config_liveness_probe_timeout_zero_disables_probe():
    """0-disables, same convention as the two *_min_gib floors."""
    cfg = config.validate_config({"name": "smoke", "execute": {"liveness_probe_timeout_s": 0}})
    assert cfg.execute.liveness_probe_timeout_s == 0.0


def test_validate_config_rejects_negative_liveness_probe_timeout_s():
    with pytest.raises(config.ConfigError, match="liveness_probe_timeout_s"):
        config.validate_config({"name": "smoke", "execute": {"liveness_probe_timeout_s": -1}})


def test_validate_config_accepts_docker_settle_s():
    cfg = config.validate_config({"name": "smoke", "cleanup": {"docker_settle_s": 5}})
    assert cfg.cleanup.docker_settle_s == 5


def test_validate_config_rejects_zero_docker_settle_s():
    with pytest.raises(config.ConfigError, match="docker_settle_s"):
        config.validate_config({"name": "smoke", "cleanup": {"docker_settle_s": 0}})


def test_validate_config_accepts_free_memory_min_gib():
    cfg = config.validate_config({"name": "smoke", "preflight": {"free_memory_min_gib": 4.5}})
    assert cfg.preflight.free_memory_min_gib == 4.5
    assert cfg.memory_gate_enabled is True


def test_validate_config_free_memory_min_gib_zero_disables_gate():
    """Mirrors free_space_min_gib: 0 -- the same 0-disables convention (must_preserve)."""
    cfg = config.validate_config({"name": "smoke", "preflight": {"free_memory_min_gib": 0}})
    assert cfg.preflight.free_memory_min_gib == 0.0
    assert cfg.memory_gate_enabled is False
    warning = config.memory_gate_disabled_warning(cfg)
    assert warning is not None
    assert warning.startswith(config.MEMORY_GATE_DISABLED_WARNING_PREFIX)
    assert "free_memory_min_gib=0" in warning


def test_validate_config_memory_gate_disabled_warning_is_none_when_enabled():
    cfg = config.validate_config({"name": "smoke"})
    assert config.memory_gate_disabled_warning(cfg) is None


def test_validate_config_rejects_negative_free_memory_min_gib():
    with pytest.raises(config.ConfigError, match="free_memory_min_gib"):
        config.validate_config({"name": "smoke", "preflight": {"free_memory_min_gib": -1}})


def test_validate_config_accepts_clickhouse_memory_admission_settings():
    cfg = config.validate_config(
        {
            "name": "smoke",
            "preflight": {"clickhouse_memory_limit": "8g", "docker_memory_reserve_gib": 3.5},
        }
    )
    assert cfg.preflight.clickhouse_memory_limit == "8g"
    assert cfg.preflight.docker_memory_reserve_gib == 3.5


@pytest.mark.parametrize("value", ["", None, 4])
def test_validate_config_rejects_invalid_clickhouse_memory_limit(value):
    with pytest.raises(config.ConfigError, match="clickhouse_memory_limit"):
        config.validate_config({"name": "smoke", "preflight": {"clickhouse_memory_limit": value}})


def test_validate_config_rejects_negative_docker_memory_reserve():
    with pytest.raises(config.ConfigError, match="docker_memory_reserve_gib"):
        config.validate_config({"name": "smoke", "preflight": {"docker_memory_reserve_gib": -0.1}})


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
            "tests/uat/phases/execute.py",
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
    assert overridden.scales.requested_rungs == (0.1,)


# ---------------------------------------------------------------------------
# Release-gate re-run configs (uat-certification-rerun-ordering-and-gate).
# ---------------------------------------------------------------------------

_RELEASE_GATE_CONFIGS_DIR = Path(__file__).parent / "configs"


def test_release_gate_configs_load_and_encode_stage_ordering():
    """The three release-gate configs validate and encode the four-stage order."""
    stage1 = config.load_config(_RELEASE_GATE_CONFIGS_DIR / "release-gate-01-native-dataframe.yaml")
    stage2 = config.load_config(_RELEASE_GATE_CONFIGS_DIR / "release-gate-02-docker-nonoltp.yaml")
    stage3 = config.load_config(_RELEASE_GATE_CONFIGS_DIR / "release-gate-03-docker-oltp.yaml")

    # Stage 1 is native + dataframe only — no Docker management, so no `action=up`
    # events can precede the Docker stages.
    assert stage1.platforms.groups == ("native-sql", "dataframe")
    stage1_platforms = matrix.resolve_platforms(groups=stage1.platforms.groups or ())
    assert set(stage1_platforms).isdisjoint(matrix.DOCKER_PLATFORMS)
    assert stage1.cleanup.docker_manage_platforms is False
    assert stage1.scales.rungs == (0.01, 0.1, 1.0)

    # Stages 2 and 3 are the Docker tiers, managed lifecycle, serialized.
    assert stage2.platforms.groups == ("docker-fast",)
    assert stage3.platforms.groups == ("docker-slow",)
    for stage in (stage2, stage3):
        assert stage.cleanup.docker_manage_platforms is True
        assert stage.execute.parallel_platforms is False
    assert stage3.scales.rungs == (0.01,)  # OLTP at 0.01 only

    # Every stage reaches the report phase and arms the cross-scale gate teeth.
    for stage in (stage1, stage2, stage3):
        assert "report" in stage.phases
        assert stage.report.cross_scale_coverage_min_pairs is not None
        assert stage.execute.parallel_platforms is False


def test_release_gate_cross_scale_floors_are_tuned_and_achievable():
    """uat-release-gate-enforcement w4: floors derived from enumeration, never placeholder, never exact.

    Recomputes each stage's cross-scale-eligible pair count (pairs whose
    every configured rung is enumerable) from registry truth and asserts the
    checked-in floor sits in the sound band: above the stage's absolute
    minimum, at most floor(0.8 * eligible), and strictly below the eligible
    count (the anti-pattern: an exact floor lets one flaky docker stack
    block every release). Registry growth can raise `eligible` without
    breaking this test; shrinkage that invalidates a floor fails it, which
    is the prompt to re-run the w4 derivation.
    """
    import math

    from tests.uat.phases.enumerate import enumerate_cells_with_pruning

    minimums = {
        "release-gate-01-native-dataframe.yaml": 8,
        "release-gate-02-docker-nonoltp.yaml": 4,
        "release-gate-03-docker-oltp.yaml": 2,
    }
    for config_name, minimum in minimums.items():
        stage = config.load_config(_RELEASE_GATE_CONFIGS_DIR / config_name)
        floor_value = stage.report.cross_scale_coverage_min_pairs
        assert floor_value is not None and floor_value > 1, f"{config_name}: placeholder floor"

        rungs = set(stage.scales.rungs)
        by_pair: dict[tuple[str, str], set[float]] = {}
        for cell in enumerate_cells_with_pruning(stage).cells:
            by_pair.setdefault((cell.platform, cell.benchmark), set()).add(cell.scale)
        eligible = sum(1 for scales in by_pair.values() if rungs.issubset(scales))

        assert floor_value >= minimum, f"{config_name}: floor {floor_value} below absolute minimum {minimum}"
        assert floor_value <= math.floor(0.8 * eligible), (
            f"{config_name}: floor {floor_value} exceeds 0.8 * eligible ({eligible}); re-run the w4 derivation"
        )
        assert floor_value < eligible, f"{config_name}: floor must never equal the eligible count"


# ---------------------------------------------------------------------------
# w1 load-time enforcement (uat-config-schema-spec-realignment): rules that
# were previously either unvalidated or only enforced at runtime.
# ---------------------------------------------------------------------------


def test_validate_config_rejects_duplicate_phases():
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.validate_config({"name": "smoke", "phases": ["preflight", "execute", "execute"]})


def test_validate_config_rejects_out_of_order_phases():
    """`report` before `execute` used to load fine and silently produce an
    empty report (the orchestrator walks `phases:` literally)."""
    with pytest.raises(config.ConfigError, match="canonical order"):
        config.validate_config({"name": "smoke", "phases": ["report", "execute"]})


def test_validate_config_accepts_canonical_phase_subsequence():
    cfg = config.validate_config({"name": "smoke", "phases": ["preflight", "execute", "validate", "report"]})
    assert cfg.phases == ("preflight", "execute", "validate", "report")


def test_validate_config_rejects_rungs_and_override_together():
    with pytest.raises(config.ConfigError, match="mutually exclusive"):
        config.validate_config({"name": "smoke", "phases": ["execute"], "scales": {"rungs": [0.1], "override": 1.0}})


def test_validate_config_uses_override_as_report_rung():
    cfg = config.validate_config({"name": "official", "scales": {"override": 1.0}})

    assert cfg.scales.override == 1.0
    assert cfg.scales.rungs == (1.0,)


def test_validate_config_rejects_bool_rung():
    with pytest.raises(config.ConfigError, match="scales.rungs"):
        config.validate_config({"name": "smoke", "scales": {"rungs": [True]}})


def test_validate_config_rejects_bool_override():
    with pytest.raises(config.ConfigError, match="scales.override"):
        config.validate_config({"name": "smoke", "scales": {"override": True}})


def test_validate_config_rejects_validator_clean_rate_floor_above_one():
    with pytest.raises(config.ConfigError, match=r"\[0\.0, 1\.0\]"):
        config.validate_config(
            {"name": "smoke", "phases": ["execute", "validate"], "validate": {"validator_clean_rate_floor": 1.5}}
        )


def test_validate_config_accepts_validator_clean_rate_floor_boundaries():
    lo = config.validate_config({"name": "smoke", "validate": {"validator_clean_rate_floor": 0.0}})
    hi = config.validate_config({"name": "smoke", "validate": {"validator_clean_rate_floor": 1.0}})
    assert lo.validate.validator_clean_rate_floor == 0.0
    assert hi.validate.validator_clean_rate_floor == 1.0


def test_validate_config_rejects_non_string_phases_arg():
    with pytest.raises(config.ConfigError, match="phases_arg"):
        config.validate_config({"name": "smoke", "execute": {"phases_arg": ["load"]}})


@pytest.mark.parametrize(
    "field",
    ["benchmark_runs_dir_template", "logs_dir_template", "submissions_dir_template"],
)
def test_validate_config_rejects_non_string_output_template(field: str):
    with pytest.raises(config.ConfigError, match=rf"output\.{field}` must be a string"):
        config.validate_config({"name": "smoke", "output": {field: {"nested": "mapping"}}})


def test_validate_config_rejects_package_phase_without_terminal_state():
    with pytest.raises(config.ConfigError, match="submit_terminal_state.*required"):
        config.validate_config({"name": "smoke", "phases": ["preflight", "execute", "package", "report"]})


def test_validate_config_rejects_package_phase_with_invalid_vocab():
    with pytest.raises(config.ConfigError, match="not in"):
        config.validate_config(
            {
                "name": "smoke",
                "phases": ["execute", "package"],
                "package": {"submit_terminal_state": "merged-mainline"},
            }
        )


def test_validate_config_rejects_package_phase_cloud_uploaded_without_service():
    with pytest.raises(config.ConfigError, match="package.service"):
        config.validate_config(
            {
                "name": "smoke",
                "phases": ["execute", "package"],
                "package": {"submit_terminal_state": "cloud-uploaded"},
            }
        )


def test_validate_config_accepts_package_phase_cloud_uploaded_with_service():
    cfg = config.validate_config(
        {
            "name": "smoke",
            "phases": ["execute", "package"],
            "package": {"submit_terminal_state": "cloud-uploaded", "service": "https://results.example.com"},
        }
    )
    assert cfg.package.service == "https://results.example.com"


def test_validate_config_package_checks_are_inert_when_package_phase_not_enabled():
    """A stale/invalid `package:` section is only enforced once `package` is
    actually in `phases:` -- mirrors the framework's existing leniency for
    unused-phase config (e.g. `preflight.free_space_min_gib` when
    `preflight` is absent from `phases:`). This keeps
    `tests/uat/phases/package.py`'s own runtime guard (package.py:55-68)
    independently testable via `validate_config` payloads that never enable
    the package phase."""
    cfg = config.validate_config(
        {
            "name": "smoke",
            "phases": ["preflight", "execute", "report"],
            "package": {"submit_terminal_state": "merged-mainline"},
        }
    )
    assert cfg.package.submit_terminal_state == "merged-mainline"


# ---------------------------------------------------------------------------
# w3 corpus runnability guard (uat-config-schema-spec-realignment): every
# checked-in config (*.yaml or *.yml) under tests/uat/configs/ -- including
# generated-rerun-shards/, which no test referenced before this guard --
# must load, resolve with zero unknown platform/benchmark includes, and
# enumerate to a non-empty cell set. Parametrized by discovered path so a
# failing config is named in the test id; each assertion also names the
# specific field that broke.
# ---------------------------------------------------------------------------

_CORPUS_CONFIGS_ROOT = Path(__file__).parent / "configs"
# Both extensions: a future `.yml` config must not silently escape the corpus
# and lifecycle-header guards below.
_CONFIG_GLOB_EXTS = ("*.yaml", "*.yml")


def _glob_configs(directory: Path, *, recursive: bool) -> set[Path]:
    glob = directory.rglob if recursive else directory.glob
    return {path for ext in _CONFIG_GLOB_EXTS for path in glob(ext)}


def _corpus_config_paths() -> tuple[Path, ...]:
    return tuple(sorted(_glob_configs(_CORPUS_CONFIGS_ROOT, recursive=True)))


@pytest.mark.parametrize(
    "config_path",
    _corpus_config_paths(),
    ids=lambda p: str(p.relative_to(_CORPUS_CONFIGS_ROOT)),
)
def test_every_corpus_config_loads_and_enumerates_nonempty(config_path: Path):
    from tests.uat.matrix import load_benchmarks, missing_benchmarks_from_include, missing_platforms_from_include
    from tests.uat.phases.enumerate import enumerate_cells_with_pruning

    try:
        cfg = config.load_config(config_path)
    except config.ConfigError as exc:
        pytest.fail(f"{config_path}: `load_config` raised: {exc}")

    benchmarks = load_benchmarks()

    missing_platforms = missing_platforms_from_include(cfg.platforms.include)
    assert not missing_platforms, f"{config_path}: `platforms.include` has unknown platform id(s): {missing_platforms}"

    missing_benchmarks = missing_benchmarks_from_include(cfg.benchmarks.include, benchmarks)
    assert not missing_benchmarks, (
        f"{config_path}: `benchmarks.include` has unknown benchmark id(s): {missing_benchmarks}"
    )

    result = enumerate_cells_with_pruning(cfg, benchmarks=benchmarks)
    assert result.cells, f"{config_path}: `enumerate_cells_with_pruning` produced zero cells (empty matrix)"


def test_corpus_config_paths_cover_generated_rerun_shards():
    """Guard the guard: fail loudly if the corpus discovery glob stops
    reaching `generated-rerun-shards/` (e.g. a rename), rather than silently
    shrinking the parametrized set above."""
    shard_dir = _CORPUS_CONFIGS_ROOT / "generated-rerun-shards"
    discovered = set(_corpus_config_paths())
    shards = {p for p in discovered if shard_dir in p.parents}
    assert shards, "corpus discovery found zero generated-rerun-shards/ config files"
    assert shards == _glob_configs(shard_dir, recursive=False)


# ---------------------------------------------------------------------------
# w4 lifecycle headers (uat-config-schema-spec-realignment): every top-level
# config under tests/uat/configs/ (excluding generated-rerun-shards/, which
# carries its own generated/frozen-header convention per Section 9.3) must
# declare its lifecycle class as the first line -- `# TEMPLATE` or
# `# HISTORICAL` -- per _project/specs/uat-framework.md Section 9.
# ---------------------------------------------------------------------------

_RECOGNIZED_CONFIG_HEADERS = ("# TEMPLATE", "# HISTORICAL")


def _top_level_config_paths() -> tuple[Path, ...]:
    return tuple(sorted(_glob_configs(_CORPUS_CONFIGS_ROOT, recursive=False)))


@pytest.mark.parametrize("config_path", _top_level_config_paths(), ids=lambda p: p.name)
def test_top_level_config_carries_recognized_lifecycle_header(config_path: Path):
    first_line = config_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith(_RECOGNIZED_CONFIG_HEADERS), (
        f"{config_path.name}: first line {first_line!r} does not start with one of "
        f"{_RECOGNIZED_CONFIG_HEADERS} (see _project/specs/uat-framework.md Section 9)"
    )


def test_top_level_config_paths_exclude_generated_rerun_shards():
    """Guard the guard: the top-level glob must stay non-recursive so
    generated-rerun-shards/ (a different header convention) never enters
    this parametrized set."""
    shard_dir = _CORPUS_CONFIGS_ROOT / "generated-rerun-shards"
    assert all(shard_dir not in p.parents for p in _top_level_config_paths())
    assert len(_top_level_config_paths()) == 16
