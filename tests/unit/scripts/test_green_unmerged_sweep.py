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


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec: the module uses @dataclass, whose
    # field-type resolution looks the module up by name in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load():
    return _load_module("_green_unmerged_sweep", _SCRIPT)


mod = _load()


def _now() -> dt.datetime:
    return dt.datetime(2026, 7, 23, 12, 0, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------ #
# latest_check_run / is_required_lane_green                           #
# ------------------------------------------------------------------ #
def _run(name: str, conclusion: str, started_at: str = "2026-07-23T08:00:00Z") -> dict[str, str]:
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": started_at,
    }


def _all_required_green() -> list[dict[str, str]]:
    """One passing run per develop-ruleset required context."""
    return [_run(name, "success") for name in mod.REQUIRED_CHECK_NAMES]


def test_required_check_names_match_the_documented_ruleset() -> None:
    # The pin that makes this module's green/not-green verdict trustworthy:
    # it must track the `develop-squash-only` required contexts. Parse them
    # from the same runbook block ruleset_drift_check.py reads, rather than
    # restating the names here -- a second hardcoded copy would drift
    # silently and reintroduce the false-green gap this classifier exists to
    # close. Order is not asserted: every context is required, so the tuple
    # order carries no meaning.
    drift = _load_module("_ruleset_drift_check", _ROOT / "scripts" / "ruleset_drift_check.py")
    runbook = (_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text(encoding="utf-8")
    expected = drift.parse_expected_rulesets(runbook)["develop-squash-only"]
    assert set(mod.REQUIRED_CHECK_NAMES) == set(expected.required_checks)
    assert len(mod.REQUIRED_CHECK_NAMES) == len(set(mod.REQUIRED_CHECK_NAMES)), "duplicate context"


def test_required_lane_green_when_every_context_succeeds() -> None:
    assert mod.is_required_lane_green(_all_required_green()) is True


def test_required_lane_picks_latest_started_run() -> None:
    runs = [
        _run("ci-required-result", "failure", "2026-07-23T07:00:00Z"),
        _run("ci-required-result", "success", "2026-07-23T08:00:00Z"),
        _run("Results Explorer browser gate", "success"),
    ]
    assert mod.is_required_lane_green(runs) is True


def test_required_lane_stale_success_does_not_beat_latest_failure() -> None:
    runs = [
        _run("ci-required-result", "success", "2026-07-23T07:00:00Z"),
        _run("ci-required-result", "failure", "2026-07-23T08:00:00Z"),
        _run("Results Explorer browser gate", "success"),
    ]
    assert mod.is_required_lane_green(runs) is False


def test_required_lane_missing_run_is_not_green() -> None:
    assert mod.is_required_lane_green([]) is False


def test_required_lane_ignores_unrelated_check_names() -> None:
    assert mod.is_required_lane_green([_run("some-other-check", "success")]) is False


@pytest.mark.parametrize("missing", list(mod.REQUIRED_CHECK_NAMES))
def test_required_lane_not_green_when_any_context_never_reported(missing: str) -> None:
    # Fail closed: a required context with no run at all is not green, no
    # matter how many sibling contexts passed.
    runs = [run for run in _all_required_green() if run["name"] != missing]
    assert mod.is_required_lane_green(runs) is False


@pytest.mark.parametrize("failing", list(mod.REQUIRED_CHECK_NAMES))
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", "neutral"])
def test_required_lane_not_green_when_any_context_is_not_success(failing: str, conclusion: str) -> None:
    # Partial green is the exact false-green gap: `ci-required-result` alone
    # passing must not classify the PR as required-lane green.
    runs = [_run(name, conclusion if name == failing else "success") for name in mod.REQUIRED_CHECK_NAMES]
    assert mod.is_required_lane_green(runs) is False


def test_required_lane_not_green_while_a_context_is_still_running() -> None:
    runs = [_run(name, "success") for name in mod.REQUIRED_CHECK_NAMES[1:]]
    runs.append(
        {
            "name": mod.REQUIRED_CHECK_NAMES[0],
            "status": "in_progress",
            "conclusion": None,
            "started_at": "2026-07-23T08:00:00Z",
        }
    )
    assert mod.is_required_lane_green(runs) is False


def test_latest_check_run_returns_none_for_unknown_name() -> None:
    assert mod.latest_check_run(_all_required_green(), "no-such-check") is None


# ------------------------------------------------------------------ #
# is_soundness_gated                                                   #
# ------------------------------------------------------------------ #
def test_soundness_gated_true_for_equivalence_path() -> None:
    assert mod.is_soundness_gated(["benchbox/core/equivalence/compare.py"]) is True


def test_soundness_gated_false_for_ordinary_path() -> None:
    assert mod.is_soundness_gated(["benchbox/platforms/duckdb/adapter.py"]) is False


# ------------------------------------------------------------------ #
# head_age_hours / has_arm_intent / is_stranded                       #
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
    ("events", "expected"),
    [
        ([], False),
        (None, False),
        ([{"event": "committed"}], False),
        ([{"event": "ready_for_review"}], True),
        ([{"event": "auto_squash_enabled"}], True),
        ([{"event": "auto_merge_enabled"}], True),
        ([{"event": "auto_merge_disabled"}], True),
        ([{"event": "committed"}, {"event": "auto_squash_enabled"}, {"event": "auto_merge_disabled"}], True),
    ],
)
def test_has_arm_intent(events, expected) -> None:
    assert mod.has_arm_intent(events) is expected


def test_resolve_had_arm_intent_prefers_explicit_flag() -> None:
    # Explicit false wins even if timeline would say true (fixture override).
    assert (
        mod.resolve_had_arm_intent({"had_arm_intent": False, "timeline_events": [{"event": "ready_for_review"}]})
        is False
    )
    assert mod.resolve_had_arm_intent({"had_arm_intent": True, "timeline_events": []}) is True
    assert mod.resolve_had_arm_intent({"timeline_events": [{"event": "auto_squash_enabled"}]}) is True
    assert mod.resolve_had_arm_intent({}) is False


@pytest.mark.parametrize(
    (
        "draft",
        "required_green",
        "auto_merge_enabled",
        "soundness_gated",
        "age_hours",
        "explicit_hold",
        "had_arm_intent",
        "expected",
    ),
    [
        # True strand: green, auto-merge off, past grace, prior arm intent, no hold label.
        (False, True, False, False, 3.0, False, True, True),
        # Never-armed intentional hold -- NOT stranded.
        (False, True, False, False, 3.0, False, False, False),
        # Explicit hold label excludes even with prior arm intent.
        (False, True, False, False, 3.0, True, True, False),
        (False, True, False, False, 3.0, True, False, False),
        (True, True, False, False, 3.0, False, True, False),  # draft excluded
        (False, False, False, False, 3.0, False, True, False),  # red lane excluded
        (False, True, True, False, 3.0, False, True, False),  # auto-merge already on
        (False, True, False, True, 3.0, False, True, False),  # soundness-gated excluded
        (False, True, False, False, 1.0, False, True, False),  # within grace period
    ],
)
def test_is_stranded_matrix(
    draft,
    required_green,
    auto_merge_enabled,
    soundness_gated,
    age_hours,
    explicit_hold,
    had_arm_intent,
    expected,
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
            had_arm_intent=had_arm_intent,
        )
        is expected
    )


def test_has_auto_merge_hold_label() -> None:
    assert mod.has_auto_merge_hold_label([mod.AUTO_MERGE_HOLD_LABEL]) is True
    assert mod.has_auto_merge_hold_label(["enhancement"]) is False
    assert mod.has_auto_merge_hold_label(None) is False


def test_classify_pr_intentional_hold_not_stranded() -> None:
    pr = {
        "number": 1,
        "title": "hold",
        "html_url": "https://example.invalid/1",
        "draft": False,
        "auto_merge": None,
        "timeline_events": [],
        "changed_files": ["docs/readme.md"],
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "check_runs": _all_required_green(),
    }
    c = mod.classify_pr(pr, _now(), grace_hours=2.0)
    assert c.required_green is True
    assert c.auto_merge_enabled is False
    assert c.had_arm_intent is False
    assert c.explicit_hold is False
    assert c.stranded is False


def test_classify_pr_explicit_hold_label_not_stranded() -> None:
    # Even with prior arm intent, the durable hold label wins.
    pr = {
        "number": 11,
        "title": "labeled hold",
        "html_url": "https://example.invalid/11",
        "draft": False,
        "auto_merge": None,
        "labels": [mod.AUTO_MERGE_HOLD_LABEL],
        "timeline_events": [{"event": "ready_for_review"}, {"event": "auto_squash_enabled"}],
        "changed_files": ["docs/readme.md"],
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "check_runs": _all_required_green(),
    }
    c = mod.classify_pr(pr, _now(), grace_hours=2.0)
    assert c.had_arm_intent is True
    assert c.explicit_hold is True
    assert c.stranded is False


def test_classify_pr_true_strand_ready_for_review() -> None:
    pr = {
        "number": 2,
        "title": "strand",
        "html_url": "https://example.invalid/2",
        "draft": False,
        "auto_merge": None,
        "timeline_events": [{"event": "ready_for_review"}],
        "changed_files": ["docs/readme.md"],
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "check_runs": _all_required_green(),
    }
    c = mod.classify_pr(pr, _now(), grace_hours=2.0)
    assert c.had_arm_intent is True
    assert c.explicit_hold is False
    assert c.stranded is True


def test_classify_pr_true_strand_auto_merge_dropped() -> None:
    pr = {
        "number": 3,
        "title": "dropped",
        "html_url": "https://example.invalid/3",
        "draft": False,
        "auto_merge": None,
        "timeline_events": [
            {"event": "auto_squash_enabled"},
            {"event": "auto_merge_disabled"},
        ],
        "changed_files": ["docs/readme.md"],
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "check_runs": _all_required_green(),
    }
    c = mod.classify_pr(pr, _now(), grace_hours=2.0)
    assert c.had_arm_intent is True
    assert c.stranded is True


@pytest.mark.parametrize(
    ("case", "gate_runs"),
    [
        ("never_reported", []),
        ("red", [_run("Results Explorer browser gate", "failure")]),
    ],
)
def test_classify_pr_partial_green_is_not_stranded(case: str, gate_runs: list[dict[str, str]]) -> None:
    # End-to-end guard on the false-green gap: a PR that would otherwise be a
    # textbook strand (arm intent, auto-merge off, aged, not soundness-gated)
    # must NOT be alerted while a second required context is red or absent --
    # it is genuinely not mergeable yet, so there is nothing stranded about it.
    pr = {
        "number": 4,
        "title": f"partial green: {case}",
        "html_url": "https://example.invalid/4",
        "draft": False,
        "auto_merge": None,
        "timeline_events": [{"event": "ready_for_review"}],
        "changed_files": ["docs/readme.md"],
        "head_pushed_at": "2026-07-23T08:00:00Z",
        "check_runs": [_run("ci-required-result", "success"), *gate_runs],
    }
    c = mod.classify_pr(pr, _now(), grace_hours=2.0)
    assert c.had_arm_intent is True
    assert c.required_green is False
    assert c.stranded is False


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
    assert "Intentional holds" in digest


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


def test_build_digest_lists_stranded_prs_with_safe_remediation() -> None:
    c = mod.ClassifiedPR(
        number=42,
        title="Some PR",
        html_url="https://github.com/joeharris76/BenchBox/pull/42",
        draft=False,
        required_green=True,
        soundness_gated=False,
        auto_merge_enabled=False,
        had_arm_intent=True,
        head_age_hours=5.0,
        stranded=True,
    )
    digest = mod.build_digest([c], now=_now(), repo="joeharris76/BenchBox")
    assert "#42 Some PR" in digest
    assert "never enables auto-merge itself" in digest
    assert "make pr-ready" in digest
    assert "READY=1" in digest
    # Must not claim re-push / synchronize re-enables auto-merge.
    assert "retrigger" not in digest.lower()
    assert "re-push expecting" in digest or "Do **not** re-push" in digest
    assert "synchronize` to re-arm" in digest or "synchronize" in digest


# ------------------------------------------------------------------ #
# Fixture / self-test consistency                                      #
# ------------------------------------------------------------------ #
def test_bundled_fixture_is_valid_json_with_required_keys() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert "as_of" in fixture
    assert "prs" in fixture and len(fixture["prs"]) >= 8
    assert set(fixture["expected_stranded"]) == {2008, 2009, 2010}
    assert fixture["expected_excluded_reasons"]["2001"] == "intentional_hold"
    assert fixture["expected_excluded_reasons"]["2007"] == "no_arm_intent"


def test_fixture_distinguishes_hold_from_true_strand() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    now = mod._parse_iso(fixture["as_of"])
    classified = {c.number: c for c in mod.classify_all(fixture["prs"], now, grace_hours=fixture["grace_hours"])}
    assert classified[2001].stranded is False and classified[2001].had_arm_intent is False
    assert classified[2007].stranded is False and classified[2007].had_arm_intent is False
    assert classified[2008].stranded is True and classified[2008].had_arm_intent is True
    assert classified[2009].stranded is True and classified[2009].had_arm_intent is True
    assert classified[2010].stranded is True and classified[2010].had_arm_intent is True


def test_run_self_test_passes() -> None:
    assert mod.run_self_test() == 0
