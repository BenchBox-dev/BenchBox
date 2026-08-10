"""Unit tests for _project/scripts/fast_lane_ratchet_check.py's pure logic.

The GitHub-API I/O (issue upsert) is exercised by the nightly workflow
itself and mirrors green_unmerged_sweep.py's pattern (see
test_green_unmerged_sweep.py); here we pin the headroom/quantum math and
digest formatting with no network, plus the script's own fixture-driven
`--self-test`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# medium, not fast: see test_timing_policy_modes.py's pytestmark comment --
# this batch reforms the fast lane's own contention problem and must not add
# to the fast lane it is in the middle of decoupling.
pytestmark = [pytest.mark.unit, pytest.mark.medium]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "fast_lane_ratchet_check.py"
_FIXTURE = _ROOT / "_project" / "scripts" / "fixtures" / "fast_lane_ratchet_fixture.json"


def _load():
    spec = importlib.util.spec_from_file_location("_fast_lane_ratchet_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# ------------------------------------------------------------------ #
# headroom_status                                                      #
# ------------------------------------------------------------------ #
def test_headroom_status_healthy() -> None:
    headroom, needs_ratchet = mod.headroom_status(25000, 26050)
    assert headroom == 1050
    assert needs_ratchet is False


def test_headroom_status_below_warn_threshold() -> None:
    headroom, needs_ratchet = mod.headroom_status(25960, 26050)
    assert headroom == 90
    assert needs_ratchet is True


def test_headroom_status_boundary_exactly_at_threshold_is_not_ratchet() -> None:
    # headroom == warn_threshold must NOT trigger (strict "<" per the spec).
    headroom, needs_ratchet = mod.headroom_status(25950, 26050)
    assert headroom == 100
    assert needs_ratchet is False


def test_headroom_status_over_ceiling() -> None:
    headroom, needs_ratchet = mod.headroom_status(26100, 26050)
    assert headroom == -50
    assert needs_ratchet is True


# ------------------------------------------------------------------ #
# suggested_next_ceiling: +500 quantum, >=250 headroom convention       #
# ------------------------------------------------------------------ #
def test_suggested_next_ceiling_single_quantum() -> None:
    next_ceiling = mod.suggested_next_ceiling(25960, 26050)
    assert next_ceiling == 26550
    assert next_ceiling - 25960 >= 250


def test_suggested_next_ceiling_multiple_quanta_when_far_over() -> None:
    next_ceiling = mod.suggested_next_ceiling(26800, 26050)
    # 26050 + 500 = 26550 (headroom -250, still short); +500 again = 27050
    # (headroom 250, clears the floor).
    assert next_ceiling == 27050
    assert next_ceiling - 26800 >= 250
    assert (next_ceiling - 26050) % 500 == 0


def test_load_reservation_accepts_named_headroom_floor(tmp_path: Path) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps({"max_fast_tests": 28050, "reservation": {"program": "one-engine", "headroom_floor": 500}})
    )

    assert mod.load_reservation(policy) == ("one-engine", 500)


@pytest.mark.parametrize(
    "reservation",
    [
        "one-engine",
        {},
        {"program": "", "headroom_floor": 500},
        {"program": "one-engine", "headroom_floor": 99},
        {"program": "one-engine", "headroom_floor": True},
    ],
)
def test_load_reservation_rejects_malformed_policy(tmp_path: Path, reservation) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"max_fast_tests": 28050, "reservation": reservation}))

    with pytest.raises(ValueError, match="reservation"):
        mod.load_reservation(policy)


# ------------------------------------------------------------------ #
# Digest formatting                                                    #
# ------------------------------------------------------------------ #
def test_build_digest_contains_marker_and_exact_edit() -> None:
    import datetime as dt

    now = dt.datetime(2026, 7, 24, 6, 0, tzinfo=dt.timezone.utc)
    digest = mod.build_digest(collected=25960, ceiling=26050, headroom=90, repo="joeharris76/BenchBox", now=now)
    assert mod.DIGEST_BODY_MARKER in digest
    assert "26550" in digest
    assert "fast_lane_ceiling_log.md" in digest
    assert "never opens or pushes a PR itself" in digest


def test_build_digest_names_eroded_reservation() -> None:
    import datetime as dt

    now = dt.datetime(2026, 8, 10, 6, 0, tzinfo=dt.timezone.utc)
    digest = mod.build_digest(
        collected=27772,
        ceiling=28050,
        headroom=278,
        repo="joeharris76/BenchBox",
        now=now,
        reservation=("one-engine", 500),
    )

    assert "Active reservation: **one-engine**" in digest
    assert "at least **500** tests of headroom" in digest
    assert "explicitly clear" in digest
    assert '"max_fast_tests": 28550' in digest
    assert "+500 from the current ceiling" in digest


def test_build_clear_digest_contains_marker_and_clear_line() -> None:
    import datetime as dt

    now = dt.datetime(2026, 7, 24, 6, 0, tzinfo=dt.timezone.utc)
    digest = mod.build_clear_digest(collected=25000, ceiling=26050, headroom=1050, repo="joeharris76/BenchBox", now=now)
    assert mod.DIGEST_BODY_MARKER in digest
    assert "No ratchet needed" in digest


# ------------------------------------------------------------------ #
# Fixture / self-test consistency                                      #
# ------------------------------------------------------------------ #
def test_bundled_fixture_is_valid_json_with_scenarios() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert "as_of" in fixture
    assert "scenarios" in fixture and len(fixture["scenarios"]) >= 4
    names = {s["name"] for s in fixture["scenarios"]}
    assert "healthy_headroom" in names
    assert "low_headroom" in names


def test_run_self_test_passes() -> None:
    assert mod.run_self_test() == 0
