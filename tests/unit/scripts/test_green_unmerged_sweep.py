"""Unit tests for _project/scripts/green_unmerged_sweep.py's pure classification logic.

The GitHub-API I/O is exercised by the nightly workflow itself and by the
script's own `--self-test` (fixture-driven, offline); here we pin the
individual classification predicates and digest formatting with no network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# medium, not fast: the fast-lane ceiling had ~4 tests of headroom when this
# landed (see fast_test_lane_policy.json); the sweep still gets pre-merge CI
# coverage via the medium-test job, without contending on the shared budget.
pytestmark = [pytest.mark.unit, pytest.mark.medium]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "green_unmerged_sweep.py"
_FIXTURE = _ROOT / "_project" / "scripts" / "fixtures" / "green_unmerged_fixture.json"


def _load():
    spec = importlib.util.spec_from_file_location("_green_unmerged_sweep", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec: the module uses @dataclass, whose
    # field-type resolution looks the module up by name in sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _now() -> dt.datetime:
    return dt.datetime(2026, 7, 23, 12, 0, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------ #
# required_lane_check_run / is_required_lane_green                    #
# ------------------------------------------------------------------ #
def test_required_lane_picks_latest_started_run() -> None:
    runs = [
        {
            "name": "ci-required-result",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "2026-07-23T07:00:00Z",
        },
        {
            "name": "ci-required-result",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-07-23T08:00:00Z",
        },
    ]
    assert mod.is_required_lane_green(runs) is True


def test_required_lane_missing_run_is_not_green() -> None:
    assert mod.is_required_lane_green([]) is False


def test_required_lane_ignores_unrelated_check_names() -> None:
    runs = [
        {
            "name": "some-other-check",
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-07-23T08:00:00Z",
        }
    ]
    assert mod.is_required_lane_green(runs) is False


# ------------------------------------------------------------------ #
# is_soundness_gated                                                   #
# ------------------------------------------------------------------ #
def test_soundness_gated_true_for_equivalence_path() -> None:
    assert mod.is_soundness_gated(["benchbox/core/equivalence/compare.py"]) is True


def test_soundness_gated_false_for_ordinary_path() -> None:
    assert mod.is_soundness_gated(["benchbox/platforms/duckdb/adapter.py"]) is False


# ------------------------------------------------------------------ #
# head_age_hours / is_stranded                                        #
# ------------------------------------------------------------------ #
def test_head_age_hours_uses_head_pushed_at_over_updated_at() -> None:
    pr = {"head_pushed_at": "2026-07-23T10:00:00Z", "updated_at": "2026-07-23T11:59:00Z"}
    assert mod.head_age_hours(pr, _now()) == pytest.approx(2.0)


def test_head_age_hours_falls_back_to_updated_at() -> None:
    pr = {"updated_at": "2026-07-23T09:00:00Z"}
    assert mod.head_age_hours(pr, _now()) == pytest.approx(3.0)


def test_head_age_hours_unknown_anchor_is_zero() -> None:
    assert mod.head_age_hours({}, _now()) == 0.0


@pytest.mark.parametrize(
    ("draft", "required_green", "auto_merge_enabled", "soundness_gated", "age_hours", "explicit_hold", "expected"),
    [
        (False, True, False, False, 3.0, False, True),  # stranded
        (True, True, False, False, 3.0, False, False),  # draft excluded
        (False, False, False, False, 3.0, False, False),  # red lane excluded
        (False, True, True, False, 3.0, False, False),  # auto-merge already on
        (False, True, False, True, 3.0, False, False),  # soundness-gated excluded
        (False, True, False, False, 1.0, False, False),  # within grace period
        (False, True, False, False, 3.0, True, False),  # explicit hold label excluded
    ],
)
def test_is_stranded_matrix(
    draft, required_green, auto_merge_enabled, soundness_gated, age_hours, explicit_hold, expected
) -> None:
    assert (
        mod.is_stranded(
            draft=draft,
            required_green=required_green,
            auto_merge_enabled=auto_merge_enabled,
            soundness_gated=soundness_gated,
            age_hours=age_hours,
            grace_hours=2.0,
            explicit_hold=explicit_hold,
        )
        is expected
    )


def test_has_auto_merge_hold_label() -> None:
    assert mod.has_auto_merge_hold_label([mod.AUTO_MERGE_HOLD_LABEL]) is True
    assert mod.has_auto_merge_hold_label(["enhancement"]) is False
    assert mod.has_auto_merge_hold_label(None) is False


# ------------------------------------------------------------------ #
# is_post_merge_red                                                    #
# ------------------------------------------------------------------ #
def test_post_merge_red_on_completed_failure() -> None:
    assert mod.is_post_merge_red({"status": "completed", "conclusion": "failure"}) is True


@pytest.mark.parametrize(
    "run",
    [
        None,
        {"status": "completed", "conclusion": "success"},
        {"status": "in_progress", "conclusion": None},
        {"status": "completed", "conclusion": "cancelled"},
    ],
)
def test_post_merge_not_red(run) -> None:
    assert mod.is_post_merge_red(run) is False


# ------------------------------------------------------------------ #
# build_digest                                                         #
# ------------------------------------------------------------------ #
def test_build_digest_always_carries_marker() -> None:
    digest = mod.build_digest([], now=_now(), repo="joeharris76/BenchBox")
    assert mod.DIGEST_BODY_MARKER in digest
    assert "No stranded PRs" in digest


def test_build_digest_post_merge_red_section() -> None:
    digest = mod.build_digest(
        [],
        now=_now(),
        repo="joeharris76/BenchBox",
        post_merge_red=True,
        post_merge_run={"html_url": "https://example.invalid/run/1"},
    )
    assert mod.POST_MERGE_SLA in digest
    assert "develop post-merge is RED" in digest


def test_build_digest_lists_stranded_prs() -> None:
    c = mod.ClassifiedPR(
        number=42,
        title="Some PR",
        html_url="https://github.com/joeharris76/BenchBox/pull/42",
        draft=False,
        required_green=True,
        soundness_gated=False,
        auto_merge_enabled=False,
        head_age_hours=5.0,
        stranded=True,
    )
    digest = mod.build_digest([c], now=_now(), repo="joeharris76/BenchBox")
    assert "#42 Some PR" in digest
    assert "never enables auto-merge itself" in digest


# ------------------------------------------------------------------ #
# Fixture / self-test consistency                                      #
# ------------------------------------------------------------------ #
def test_bundled_fixture_is_valid_json_with_required_keys() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert "as_of" in fixture
    assert "prs" in fixture and len(fixture["prs"]) >= 6
    assert set(fixture["expected_stranded"]) == {2001, 2007}


def test_run_self_test_passes() -> None:
    assert mod.run_self_test() == 0
