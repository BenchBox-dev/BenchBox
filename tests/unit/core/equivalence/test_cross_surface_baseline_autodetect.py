"""Tests for the cross-surface baseline auto-detect + prune glue script.

``_project/scripts/cross_surface_baseline_autodetect.py`` (the supporting glue
for ``.github/workflows/cross-surface-baseline-autodetect.yml``) must never
re-derive which known-divergence baseline keys are "resolved" and must never
reimplement pruning: phase 1 (detect) runs
``run_gate(gate, update_baseline=False)`` -- byte-for-byte the SAME call the
blocking CI gate makes -- and reads the resolved-key list out of ITS OWN
printed report; phase 2 (prune) runs ONLY when phase 1 named a resolved key,
by invoking ``run_gate(gate, update_baseline=True)`` -- the existing #935
``--update-baseline`` writer.

These tests exercise that real code path end to end: a real in-memory DuckDB
connection, the real ``ResultValidator``, and the real
``known_divergences_baseline`` writer against a real temp YAML file. Only the
DataFrame "production loader" (heavy production wiring this module does not
own or need to re-test - see ``build_production_contexts``) is swapped for a
deterministic in-process stand-in.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from benchbox.core.equivalence import cross_surface
from benchbox.core.equivalence.builders.base import CrossSurfaceData
from benchbox.core.equivalence.cross_surface import CrossSurfaceGate

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_script():
    name = "cross_surface_baseline_autodetect"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


autodetect = _load_script()


class _FakeFrame:
    """Minimal duck-typed frame: ``materialize_rows`` only needs ``.rows()``."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def rows(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeQuery:
    """One query id's per-backend DataFrame implementation stand-in."""

    def __init__(self, impls: dict[str, list[tuple[Any, ...]]]) -> None:
        self._impls = impls

    def get_impl_for_family(self, backend: str):
        if backend not in self._impls:
            return None
        rows = self._impls[backend]
        return lambda _ctx, _rows=rows: _FakeFrame(_rows)


def _build_gate(name: str, known_divergences: dict, *, q2_pandas_matches: bool) -> CrossSurfaceGate:
    """A tiny two-query, two-backend synthetic gate over an in-memory DuckDB cell.

    Q1 always matches on both backends - a previously-baselined divergence that
    has since been FIXED (the "resolved" case under test). Q2's pandas backend
    is controlled by *q2_pandas_matches*: False keeps it a genuine,
    still-reproducing divergence (the "a live entry is never dropped" control);
    True simulates the fully-clean state used for the idempotence check.
    """

    def build(_scale: float, _tmp: Path) -> CrossSurfaceData:
        connection = duckdb.connect(":memory:")
        queries = {
            "Q1": _FakeQuery({"expression": [(1,)], "pandas": [(1,)]}),
            "Q2": _FakeQuery({"expression": [(2,)], "pandas": [(2,)] if q2_pandas_matches else [(999,)]}),
        }
        return CrossSurfaceData(
            connection=connection,
            query_ids=["Q1", "Q2"],
            reference_sql=lambda qid: {"Q1": "SELECT 1", "Q2": "SELECT 2"}[qid],
            dataframe_query=lambda qid: queries[qid],
            benchmark=None,
            data_dir=Path("/unused"),
        )

    return CrossSurfaceGate(name=name, build=build, known_divergences=dict(known_divergences))


@pytest.fixture(autouse=True)
def _stub_production_contexts(monkeypatch):
    """Bypass the real DataFrame production loader - unowned by this module;
    the fake queries above ignore their context argument entirely."""
    monkeypatch.setattr(
        cross_surface,
        "build_production_contexts",
        lambda *a, **k: {"expression": None, "pandas": None},
    )


@pytest.fixture
def baseline_file(tmp_path, monkeypatch):
    """A real temp baseline YAML with a resolved key, a still-live key, and an
    unrelated gate's section, then point ``cross_surface``'s writer at it."""
    path = tmp_path / "cross_surface_baseline.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "fake": {
                    "Q1_pandas": "documented test baseline (now fixed)",
                    "Q2_pandas": "documented test baseline (still live)",
                },
                "unrelated": {"SomeKey_pandas": "untouched by fake's prune"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cross_surface, "_BASELINE_YAML_PATH", path)
    return path


def test_detect_and_prune_surfaces_exactly_the_resolved_entry_and_prunes_only_it(baseline_file):
    gate = _build_gate(
        "fake",
        {
            "Q1_pandas": "documented test baseline (now fixed)",
            "Q2_pandas": "documented test baseline (still live)",
        },
        q2_pandas_matches=False,
    )

    outcome = autodetect.detect_and_prune(gate)

    # Phase 1 (detect) is exactly the blocking gate's own call: a resolved
    # entry still present makes that call fail, same as CI would show today.
    assert outcome.detect_exit_code == 1
    # (a) the resolved entry is surfaced exactly - nothing more, nothing less.
    assert outcome.resolved_detected == ["Q1_pandas"]
    # (b) the writer's diff drops only it.
    assert outcome.pruned == ["Q1_pandas"]
    assert outcome.code_only == []
    assert outcome.refused is False
    assert outcome.needs_attention is False
    # Phase 2 (prune) leaves a clean gate (Q2_pandas is still classified).
    assert outcome.prune_exit_code == 0

    data = yaml.safe_load(baseline_file.read_text(encoding="utf-8"))
    # (c) no LIVE entry touched: Q2_pandas (still diverging) remains.
    assert data["fake"] == {"Q2_pandas": "documented test baseline (still live)"}
    # An unrelated gate's section is untouched too.
    assert data["unrelated"] == {"SomeKey_pandas": "untouched by fake's prune"}


def test_detect_and_prune_is_a_no_op_once_the_baseline_is_already_clean(baseline_file):
    """(d) no-op when nothing is resolved.

    Simulates the POST-prune state directly (a fresh process re-importing the
    already-pruned baseline would build a gate whose ``known_divergences`` no
    longer carries ``Q1_pandas``); Q2_pandas is still genuinely diverging
    (``q2_pandas_matches=False``), so it stays classified rather than
    "resolved" - there is nothing left for phase 1 to detect. The writer must
    never be invoked and the file must be byte-identical afterward.
    """
    before = baseline_file.read_text(encoding="utf-8")
    gate = _build_gate("fake", {"Q2_pandas": "documented test baseline (still live)"}, q2_pandas_matches=False)

    outcome = autodetect.detect_and_prune(gate)

    assert outcome.detect_exit_code == 0
    assert outcome.resolved_detected == []
    assert outcome.prune_ran is False
    assert outcome.prune_exit_code is None
    assert outcome.pruned == []
    assert outcome.needs_attention is False
    assert baseline_file.read_text(encoding="utf-8") == before


def test_still_reproducing_divergence_alone_is_never_treated_as_resolved(baseline_file):
    """A gate with ONLY a still-live divergence (nothing resolved) reports
    nothing to prune, even though the gate overall is not clean."""
    gate = _build_gate("fake", {"Q2_pandas": "documented test baseline (still live)"}, q2_pandas_matches=False)

    outcome = autodetect.detect_and_prune(gate)

    assert outcome.detect_exit_code == 0  # the one divergence is classified/tolerated
    assert outcome.resolved_detected == []
    assert outcome.prune_ran is False


def test_run_autodetect_processes_every_enforced_gate_in_sorted_order(monkeypatch, baseline_file):
    """``run_autodetect``/``detect_and_prune_gate`` wire to the live ``GATES``
    registry (``sorted(GATES)`` is the default set), never a private list."""
    resolved_gate = _build_gate(
        "fake",
        {"Q1_pandas": "now fixed", "Q2_pandas": "still live"},
        q2_pandas_matches=False,
    )
    clean_gate = _build_gate("zzz-clean", {}, q2_pandas_matches=True)
    monkeypatch.setattr(cross_surface, "GATES", {"fake": resolved_gate, "zzz-clean": clean_gate})

    outcomes = autodetect.run_autodetect()

    assert [outcome.gate for outcome in outcomes] == ["fake", "zzz-clean"]  # sorted(GATES)
    by_name = {outcome.gate: outcome for outcome in outcomes}
    assert by_name["fake"].pruned == ["Q1_pandas"]
    assert by_name["zzz-clean"].resolved_detected == []


def test_run_autodetect_honors_an_explicit_gate_subset(monkeypatch, baseline_file):
    resolved_gate = _build_gate(
        "fake",
        {"Q1_pandas": "now fixed", "Q2_pandas": "still live"},
        q2_pandas_matches=False,
    )
    other_gate = _build_gate("other", {}, q2_pandas_matches=True)
    monkeypatch.setattr(cross_surface, "GATES", {"fake": resolved_gate, "other": other_gate})

    outcomes = autodetect.run_autodetect(["fake"])

    assert [outcome.gate for outcome in outcomes] == ["fake"]


def test_summarize_flags_any_pruned_and_needs_attention(baseline_file):
    resolved_gate = _build_gate(
        "fake",
        {"Q1_pandas": "now fixed", "Q2_pandas": "still live"},
        q2_pandas_matches=False,
    )
    outcome = autodetect.detect_and_prune(resolved_gate)

    summary = autodetect.summarize([outcome])

    assert summary["any_pruned"] is True
    assert summary["needs_attention"] == []
    assert summary["gates"]["fake"]["pruned"] == ["Q1_pandas"]


def test_extract_list_reads_the_resolved_report_line_verbatim():
    """Pins the parsing contract to cross_surface.py's OWN printed wording -
    this glue reads that text, it never recomputes resolved-ness itself."""
    text = (
        "GATE FAILURE - previously-known divergences now equivalent: "
        "['Q1_pandas'] - remove the stale baseline entry in a reviewed change"
    )
    assert autodetect._extract_list(autodetect._RESOLVED_RE, text) == ["Q1_pandas"]


def test_extract_list_reads_the_removed_report_line_verbatim():
    text = "fake: removed resolved known-divergence baseline entries: ['Q1_pandas', 'Q2_pandas']"
    assert autodetect._extract_list(autodetect._REMOVED_RE, text) == ["Q1_pandas", "Q2_pandas"]


def test_extract_list_returns_empty_when_the_marker_is_absent():
    assert autodetect._extract_list(autodetect._RESOLVED_RE, "SQL and DataFrame surfaces are equivalent.") == []


def test_code_only_entry_is_pruned_where_possible_but_flagged_needs_attention(tmp_path, monkeypatch):
    """A resolved key backed by a ``ClassifiedDivergence`` (code, never the
    YAML file) cannot be auto-pruned; this glue must surface it rather than
    silently reporting success (mirrors cross_surface.py's own contract).

    Real ``ClassifiedDivergence`` entries are never written to the YAML
    baseline at all (see ``known_divergences_baseline.py``'s header), so -
    unlike the shared ``baseline_file`` fixture - only the YAML-backed key
    lives on disk here.
    """
    from benchbox.core.equivalence.cross_surface import ClassifiedDivergence

    path = tmp_path / "cross_surface_baseline.yaml"
    path.write_text(
        yaml.safe_dump({"fake": {"Q1_pandas": "documented test baseline (now fixed)"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cross_surface, "_BASELINE_YAML_PATH", path)

    gate = _build_gate(
        "fake",
        {
            "Q1_pandas": "documented test baseline (now fixed)",
            "Q2_pandas": ClassifiedDivergence(reason="code-only", accepts=lambda d: False),
        },
        # Both Q2 backends match live data -> Q2_pandas is ALSO "resolved"
        # (its ClassifiedDivergence predicate is irrelevant once nothing
        # diverges at all - resolved-ness only asks "is the key's cell still
        # in the divergence set", never whether the predicate would accept).
        q2_pandas_matches=True,
    )

    outcome = autodetect.detect_and_prune(gate)

    assert set(outcome.resolved_detected) == {"Q1_pandas", "Q2_pandas"}
    assert outcome.pruned == ["Q1_pandas"]  # the YAML-backed key is still safely pruned
    assert outcome.code_only == ["Q2_pandas"]
    assert outcome.needs_attention is True
    assert outcome.prune_exit_code == 1

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["fake"] == {}


def test_refusal_is_never_masked_when_an_unrelated_divergence_rides_along(tmp_path, monkeypatch):
    """A resolved key alongside an UNRELATED, never-baselined divergence on the
    same gate must refuse the prune entirely - ``_apply_baseline_update``'s own
    documented contract ("an operator hitting an unrelated regression on the
    same run must fix it first, then re-run to prune"). Exercises the REAL
    ``run_gate(gate, update_baseline=True)`` path end to end (never a mock):
    Q1_pandas is genuinely resolved (would be prunable on its own), but
    Q2_pandas is a live, unclassified divergence that was never baselined at
    all, so the run is not "otherwise completely clean" and nothing is
    written.
    """
    path = tmp_path / "cross_surface_baseline.yaml"
    path.write_text(
        yaml.safe_dump({"fake": {"Q1_pandas": "documented test baseline (now fixed)"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cross_surface, "_BASELINE_YAML_PATH", path)
    before = path.read_text(encoding="utf-8")

    gate = _build_gate(
        "fake",
        # Q2_pandas is deliberately absent from known_divergences - it is an
        # unrelated, never-classified divergence, not a stale baseline entry.
        {"Q1_pandas": "documented test baseline (now fixed)"},
        q2_pandas_matches=False,
    )

    outcome = autodetect.detect_and_prune(gate)

    # Phase 1 detects Q1_pandas as resolved, so phase 2 (prune) does run...
    assert outcome.resolved_detected == ["Q1_pandas"]
    assert outcome.prune_ran is True
    # ...but real run_gate(update_baseline=True) refuses to write: Q2_pandas is
    # an unclassified divergence, so the gate is not otherwise clean.
    # (a) the _REFUSED_MARKER coupling is exercised against the REAL printed
    # report from run_gate/_apply_baseline_update, never a mock.
    assert autodetect._REFUSED_MARKER in outcome.report
    assert outcome.refused is True
    assert outcome.pruned == []
    assert outcome.prune_exit_code == 1

    # (b) nothing was written: the baseline file is byte-identical afterward.
    assert path.read_text(encoding="utf-8") == before
