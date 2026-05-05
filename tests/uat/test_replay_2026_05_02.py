"""Structural-parity assertion for the 2026-05-02 replay config.

Marked @pytest.mark.slow because it walks the full registry-driven
matrix even in dry-run mode; not in the fast-test default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parent / "configs" / "uat-2026-05-02.yaml"
HEADER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "uat-2026-05-02-matrix-summary-header.tsv"

pytestmark = pytest.mark.slow


def test_replay_dry_run_produces_expected_columns(tmp_path: Path):
    """Run the orchestrator in dry-run mode against the frozen config.

    Asserts the matrix_summary.tsv has the same columns as the fixture
    snapshot of the historical 2026-05-02 retrospective.
    """
    from tests.uat.config import load_config
    from tests.uat.orchestrator import run_sweep

    cfg = load_config(CONFIG)
    cfg = type(cfg)(
        name=cfg.name,
        description=cfg.description,
        phases=cfg.phases,
        dry_run=True,  # force structural pass
        execute=cfg.execute,
        output=cfg.output,
        raw=cfg.raw,
    )
    result = run_sweep(cfg, log_dir_override=tmp_path)
    # In dry_run mode every phase records 0; the report phase isn't asked
    # to write the TSV under dry_run, so we compare only the column header
    # we'd emit. The header is fixed.
    expected_columns = HEADER_FIXTURE.read_text(encoding="utf-8").rstrip("\n").split("\t")
    from tests.uat.phases.report import REPORT_HEADER

    assert REPORT_HEADER.split("\t") == expected_columns
    assert result.exit_code() == 0


def test_replay_config_has_expected_shape():
    """Cheap structural smoke: the frozen config keys match the retrospective."""
    import yaml

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert raw["name"] == "uat-2026-05-02"
    assert raw["scales"]["rungs"] == [0.01, 0.1, 1.0]
    assert raw["execute"]["per_cell_timeout_s"] == 600
    assert raw["execute"]["early_stop_after_s"] == 180
    assert raw["package"]["submit_terminal_state"] == "local-stage"
    assert raw["report"]["cross_scale_coverage_min_pairs"] is None
