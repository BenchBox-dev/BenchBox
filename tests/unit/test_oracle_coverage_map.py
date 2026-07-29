"""Guards for the benchmark correctness-oracle coverage map (w0/w3).

These keep the generated map (``_project/analysis/oracle-coverage-map.{md,json}``)
honest and current:

  - drift: the checked-in artifacts must match a fresh regeneration, so the map
    cannot silently fall behind the registry / gates;
  - completeness: every shipped benchmark is classified;
  - exemplars: the known oracles (tpch/tpcds expected-results, tpchavoc variant
    gate, ssb cross-surface) stay classified as such (locks in must_preserve);
  - new-benchmark visibility: a newly added benchmark with no oracle changes the
    generated map, which trips the drift check — forcing the author to regenerate
    and consciously record it as UNGUARDED rather than discovering it later.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The generator lives in _project/scripts (a project tool, not shipped in the
# package); ensure the repo root is importable so `_project.scripts` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _project.scripts.generate_oracle_coverage_map import (  # noqa: E402
    INDEPENDENCE_NONE,
    INDEPENDENCE_SELF,
    INDEPENDENCE_SEMI,
    ORACLE_CROSS_SURFACE,
    ORACLE_CROSS_SURFACE_VARIANT,
    ORACLE_EXPECTED_RESULTS,
    ORACLE_NONE,
    ORACLE_VARIANT_EQUIVALENCE,
    PROVENANCE_MIXED,
    PROVENANCE_NONE,
    PROVENANCE_SEPARATE,
    PROVENANCE_SHARED_SPEC,
    STRENGTH_CARDINALITY,
    STRENGTH_NONE,
    STRENGTH_VALUE,
    STRENGTH_VALUE_AND_CARDINALITY,
    build_coverage_map,
    check_artifacts,
    oracle_reference_independence,
    oracle_strength_and_scale,
    oracle_surface_provenance,
    render_markdown,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return build_coverage_map()


def test_checked_in_artifacts_are_current(rows):
    """The committed map must match a fresh regeneration (run the generator + commit)."""
    problems = check_artifacts(rows)
    assert not problems, "oracle coverage map is stale:\n" + "\n".join(problems)


def test_check_artifacts_fix_hint_names_exact_regen_command(rows, monkeypatch):
    """guards-fix-regen-target-2: a stale/missing artifact must name the exact
    regen command (`make oracle-coverage-map`) and point at `make guards-fix`
    as the one-command alternative -- not just say "stale, go figure it out"."""
    from _project.scripts import generate_oracle_coverage_map as gocm

    # Must resolve under _REPO_ROOT: check_artifacts() calls path.relative_to(_REPO_ROOT).
    missing_path = gocm.ARTIFACT_DIR / "does-not-exist-guard-messages-test.md"
    monkeypatch.setattr(gocm, "MARKDOWN_ARTIFACT", missing_path)

    problems = check_artifacts(rows)
    assert problems, "expected a missing-artifact problem to be reported"
    hint_problems = [p for p in problems if "does-not-exist-guard-messages-test.md" in p]
    assert hint_problems, problems
    assert any("make oracle-coverage-map" in p and "make guards-fix" in p for p in hint_problems)


def test_every_shipped_benchmark_is_classified(rows):
    """Every registry benchmark appears exactly once with a primary oracle."""
    from benchbox.core.benchmark_registry import list_benchmark_ids

    mapped = {r["benchmark"] for r in rows}
    assert mapped == set(list_benchmark_ids()), "coverage map and registry disagree on benchmark set"
    assert len(rows) == len(mapped), "duplicate benchmark rows in coverage map"
    for r in rows:
        assert r["primary_oracle"], f"{r['benchmark']} has no primary_oracle classification"
        assert (r["primary_oracle"] == ORACLE_NONE) == (not r["guarded"]), (
            f"{r['benchmark']} guarded/primary_oracle disagree"
        )


def test_known_oracles_stay_classified(rows):
    """The existing oracles must remain recognized (must_preserve)."""
    by_id = {r["benchmark"]: r for r in rows}
    assert ORACLE_EXPECTED_RESULTS in by_id["tpch"]["oracles"]
    assert ORACLE_EXPECTED_RESULTS in by_id["tpcds"]["oracles"]
    assert ORACLE_VARIANT_EQUIVALENCE in by_id["tpchavoc"]["oracles"]
    assert ORACLE_CROSS_SURFACE in by_id["ssb"]["oracles"]


def test_cross_surface_applicable_implies_dual_surface_and_unguarded(rows):
    """The w1 dispatch flag must be self-consistent."""
    for r in rows:
        if r["cross_surface_applicable"]:
            assert r["dual_surface"], f"{r['benchmark']} flagged cross-surface but is single-surface"
            assert not r["guarded"], f"{r['benchmark']} flagged cross-surface but already guarded"


# --- Strength + scale disclosure (oracle-coverage-map-strength-disclosure) ---


def test_strength_and_scale_columns_present(rows):
    """Every row carries a strength + scale field (the new disclosure axes)."""
    for r in rows:
        assert "strength" in r and r["strength"], f"{r['benchmark']} missing strength"
        assert "scale" in r and r["scale"], f"{r['benchmark']} missing scale"
        # Unguarded rows disclose no guarantee on either axis.
        if not r["guarded"]:
            assert r["strength"] == STRENGTH_NONE, f"{r['benchmark']} unguarded but strength={r['strength']}"


def test_known_oracle_strength_and_scale_truth(rows):
    """Pin the TRUTH of strength + scale for known oracles (classifier-truth, w4).

    The drift test only proves committed == regenerated (consistency). This pins
    what each known oracle ACTUALLY proves, so a future change that mislabels an
    oracle's strength/scale fails here even if the artifact is internally consistent.
    """
    by_id = {r["benchmark"]: r for r in rows}

    # expected-results: cardinality-only by default; TPC-H carries stored VALUE
    # digests (bounded-correctness-gate value oracle), so it reads value+cardinality.
    # Both hold only at SF=1 (the loader raises for other scales).
    assert by_id["tpch"]["strength"] == STRENGTH_VALUE_AND_CARDINALITY
    assert by_id["tpch"]["scale"] == "SF=1"
    assert by_id["tpcds"]["strength"] == STRENGTH_CARDINALITY
    assert by_id["tpcds"]["scale"] == "SF=1"

    # cross-surface / variant gates compare full result VALUES at the bounded scale.
    for benchmark in ("ssb", "amplab", "coffeeshop", "tpchavoc"):
        assert by_id[benchmark]["strength"] == STRENGTH_VALUE, f"{benchmark} should be value-level"
        assert by_id[benchmark]["scale"].startswith("SF="), f"{benchmark} missing bounded scale"


def test_expected_results_strength_is_derived_not_hardcoded(monkeypatch):
    """The expected-results strength must track the provider's real digest capability.

    Flipping the live signal (stored value digests present/absent) must flip the
    label, proving it is derived rather than a hand-maintained constant.
    """
    import _project.scripts.generate_oracle_coverage_map as gen

    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: True)
    strength, scale = oracle_strength_and_scale(ORACLE_EXPECTED_RESULTS, "tpch")
    assert strength == STRENGTH_VALUE_AND_CARDINALITY
    assert scale == "SF=1"

    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: False)
    strength, _ = oracle_strength_and_scale(ORACLE_EXPECTED_RESULTS, "tpch")
    assert strength == STRENGTH_CARDINALITY


def test_value_level_oracle_scale_is_read_live(rows):
    """Value-level gate scale must equal the equivalence module's bounded scale."""
    from benchbox.core.equivalence.cross_surface import EQUIVALENCE_SCALE

    by_id = {r["benchmark"]: r for r in rows}
    assert by_id["ssb"]["scale"] == f"SF={EQUIVALENCE_SCALE}"


# --- Reference-independence axis (oracle-coverage-map-reference-independence) ---


def test_independence_column_present(rows):
    """Every row carries independence fields; unguarded rows disclose no axis."""
    for r in rows:
        assert "independence" in r and r["independence"], f"{r['benchmark']} missing independence"
        assert "independence_rationale" in r and r["independence_rationale"], (
            f"{r['benchmark']} missing independence rationale"
        )
        if not r["guarded"]:
            assert r["independence"] == INDEPENDENCE_NONE, (
                f"{r['benchmark']} unguarded but independence={r['independence']}"
            )
            assert r["independence_rationale"] == INDEPENDENCE_NONE, (
                f"{r['benchmark']} unguarded but rationale={r['independence_rationale']}"
            )


def test_known_oracle_independence_truth(rows):
    """Pin the TRUTH of reference-independence for known oracles (classifier-truth, w4).

    Orthogonal to Strength AND to Surface-provenance: this column answers only "is the
    reference an authority OUTSIDE benchbox?". This pins what each known oracle's
    reference ACTUALLY is, so a future change that mislabels independence fails here
    even if the artifact is internally consistent.
    """
    by_id = {r["benchmark"]: r for r in rows}

    # tpch's VALUE digest is a frozen benchbox-on-DuckDB snapshot -> self-referential
    # on the value axis (a regression snapshot, not an authority).
    assert by_id["tpch"]["independence"] == INDEPENDENCE_SELF
    # tpcds is cardinality-only: row counts come from the published TPC answer sets
    # (an authority on cardinality), values unchecked -> semi-independent.
    assert by_id["tpcds"]["independence"] == INDEPENDENCE_SEMI

    # Every cross-surface gate compares benchbox SQL against benchbox DataFrame code,
    # so NO authoring provenance -- not even `separate-handwritten` -- makes the
    # reference external. This is the conflation the split exists to prevent.
    for benchmark in ("ssb", "joinorder_synthetic", "clickbench", "read_primitives", "amplab", "coffeeshop", "h2odb"):
        assert by_id[benchmark]["independence"] == INDEPENDENCE_SELF, (
            f"{benchmark} cross-surface reference is benchbox's own DataFrame code, not an external authority"
        )

    # TPC-Havoc variant gates still compare against their own canonical/variant
    # surfaces rather than an external authority.
    assert by_id["tpchavoc"]["independence"] == INDEPENDENCE_SELF

    # No provenance label may leak into the Independence column (the pre-split bug).
    provenance_labels = {PROVENANCE_SHARED_SPEC, PROVENANCE_MIXED, PROVENANCE_SEPARATE}
    leaked = {r["benchmark"] for r in rows if r["independence"] in provenance_labels}
    assert not leaked, f"surface-provenance labels leaked into the Independence column: {sorted(leaked)}"


# --- Surface-provenance axis (oracle-coverage-map-independence-provenance-split) ---


def test_surface_provenance_column_present(rows):
    """Every row carries the provenance fields; only cross-surface rows disclose a label."""
    for r in rows:
        assert "surface_provenance" in r and r["surface_provenance"], f"{r['benchmark']} missing surface_provenance"
        assert "surface_provenance_rationale" in r and r["surface_provenance_rationale"], (
            f"{r['benchmark']} missing surface_provenance_rationale"
        )
        # The axis only applies to cross-surface gates; everything else reports `—`.
        if r["primary_oracle"] != ORACLE_CROSS_SURFACE:
            assert r["surface_provenance"] == PROVENANCE_NONE, (
                f"{r['benchmark']} is not cross-surface but discloses provenance={r['surface_provenance']}"
            )
            assert r["surface_provenance_rationale"] == PROVENANCE_NONE, (
                f"{r['benchmark']} is not cross-surface but carries a provenance rationale"
            )


def test_known_surface_provenance_truth(rows):
    """Pin the TRUTH of surface provenance per gate (classifier-truth, w4).

    The labels that used to sit in the Independence column now live here, and this
    pins which gate has which, so a mislabel fails even when the artifact is
    internally consistent.
    """
    by_id = {r["benchmark"]: r for r in rows}

    for benchmark in ("ssb", "joinorder_synthetic"):
        assert by_id[benchmark]["surface_provenance"] == PROVENANCE_SHARED_SPEC
    for benchmark in ("clickbench", "read_primitives"):
        assert by_id[benchmark]["surface_provenance"] == PROVENANCE_MIXED
    for benchmark in ("amplab", "coffeeshop", "h2odb"):
        assert by_id[benchmark]["surface_provenance"] == PROVENANCE_SEPARATE
    assert "separately handwritten" in by_id["coffeeshop"]["surface_provenance_rationale"]


def test_surface_provenance_is_read_live_from_gate_metadata(rows):
    """Provenance must equal the live per-gate metadata, never a hand-kept table.

    Re-registering a gate with different provenance must reclassify the row, so assert
    against ``CrossSurfaceGate.surface_independence`` itself rather than a copy, and
    pin the generator's label vocabulary to the live constants so the two cannot drift.
    """
    from benchbox.core.equivalence.cross_surface import (
        GATES,
        STAGED_GATES,
        SURFACE_INDEPENDENCE_MIXED,
        SURFACE_INDEPENDENCE_SEPARATE,
        SURFACE_INDEPENDENCE_SHARED_SPEC,
    )

    assert PROVENANCE_SHARED_SPEC == SURFACE_INDEPENDENCE_SHARED_SPEC
    assert PROVENANCE_MIXED == SURFACE_INDEPENDENCE_MIXED
    assert PROVENANCE_SEPARATE == SURFACE_INDEPENDENCE_SEPARATE

    by_id = {r["benchmark"]: r for r in rows}
    for benchmark_id, gate in {**GATES, **STAGED_GATES}.items():
        assert by_id[benchmark_id]["surface_provenance"] == gate.surface_independence, (
            f"{benchmark_id} provenance is not read live from CrossSurfaceGate metadata"
        )
        assert by_id[benchmark_id]["surface_provenance_rationale"] == gate.surface_independence_rationale


def test_provenance_never_changes_independence(rows):
    """The two axes are INDEPENDENT columns: provenance must not move independence.

    Gates that span the whole provenance range (`shared-spec` through
    `separate-handwritten`) must all read `self-referential`, and the pure classifiers
    must agree -- `oracle_reference_independence` takes no benchmark id at all, so a
    per-gate provenance value has no path back into the independence label.
    """
    by_id = {r["benchmark"]: r for r in rows}
    spread = {by_id[b]["surface_provenance"] for b in ("ssb", "clickbench", "coffeeshop")}
    assert spread == {PROVENANCE_SHARED_SPEC, PROVENANCE_MIXED, PROVENANCE_SEPARATE}
    assert {by_id[b]["independence"] for b in ("ssb", "clickbench", "coffeeshop")} == {INDEPENDENCE_SELF}

    assert oracle_reference_independence(ORACLE_CROSS_SURFACE, STRENGTH_VALUE) == INDEPENDENCE_SELF
    assert oracle_reference_independence(ORACLE_VARIANT_EQUIVALENCE, STRENGTH_VALUE) == INDEPENDENCE_SELF
    assert oracle_reference_independence(ORACLE_CROSS_SURFACE_VARIANT, STRENGTH_VALUE) == INDEPENDENCE_SELF
    # A variant gate has no cross-surface gate entry, so it discloses no provenance.
    assert oracle_surface_provenance(ORACLE_VARIANT_EQUIVALENCE, "tpchavoc") == (PROVENANCE_NONE, PROVENANCE_NONE)
    assert oracle_surface_provenance(ORACLE_CROSS_SURFACE, "coffeeshop")[0] == PROVENANCE_SEPARATE


def test_markdown_renders_independence_and_provenance_as_distinct_columns(rows):
    """The map must show two separate columns, and the prose must keep them apart."""
    markdown = render_markdown(rows)
    header = next(line for line in markdown.splitlines() if line.startswith("| Benchmark |"))
    columns = [c.strip() for c in header.strip().strip("|").split("|")]
    assert "Independence" in columns
    assert "Surface provenance" in columns
    assert columns.index("Independence") != columns.index("Surface provenance")

    # A separately-handwritten gate: provenance in its own cell, independence still self.
    coffeeshop = next(line for line in markdown.splitlines() if line.startswith("| coffeeshop |"))
    cells = [c.strip() for c in coffeeshop.strip().strip("|").split("|")]
    assert cells[columns.index("Independence")] == INDEPENDENCE_SELF
    assert cells[columns.index("Surface provenance")] == PROVENANCE_SEPARATE

    # The prose must explicitly warn that provenance is not independence, or the
    # reader re-makes exactly the conflation this split removed.
    assert "Surface-provenance disclosure:" in markdown
    assert "not** as independence" in markdown


def test_independence_is_derived_from_value_digest_signal(monkeypatch):
    """Independence must track the live digest signal: flip it -> the label flips.

    The expected-results independence label is DERIVED, not hand-set: when stored
    value digests are present the value axis is a frozen self-snapshot
    (self-referential); drop them and only the answer-set cardinality is checked
    (semi-independent). Proving the flip end-to-end is the truth check the drift check
    lacks for the new axis.
    """
    import _project.scripts.generate_oracle_coverage_map as gen

    # With value digests present (tpch today): value+cardinality -> self-referential.
    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: True)
    flipped_on = {r["benchmark"]: r for r in gen.build_coverage_map()}
    assert flipped_on["tpch"]["strength"] == STRENGTH_VALUE_AND_CARDINALITY
    assert flipped_on["tpch"]["independence"] == INDEPENDENCE_SELF

    # Drop the digests: cardinality-only -> the label flips to semi-independent.
    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: False)
    flipped_off = {r["benchmark"]: r for r in gen.build_coverage_map()}
    assert flipped_off["tpch"]["strength"] == STRENGTH_CARDINALITY
    assert flipped_off["tpch"]["independence"] == INDEPENDENCE_SEMI

    # And the pure classifier agrees (orthogonal to the cross-surface KIND): both gate
    # kinds compare benchbox against benchbox, so both stay self-referential.
    assert oracle_reference_independence(ORACLE_CROSS_SURFACE, STRENGTH_VALUE) == INDEPENDENCE_SELF
    assert oracle_reference_independence(ORACLE_VARIANT_EQUIVALENCE, STRENGTH_VALUE) == INDEPENDENCE_SELF


def test_tpch_row_discloses_sf1_value_blindness(rows):
    """The tpch row ALONE (not the Scale cell / prose) must show values are SF=1-only.

    w2: a skimmer reading only the Strength column must not conclude tpch values are
    guarded generally. The SF>1 value-blindness is rendered INTO the tpch Strength
    cell, derived from the live strength signal.
    """
    markdown = render_markdown(rows)
    tpch_line = next(line for line in markdown.splitlines() if line.startswith("| tpch |"))
    # The disclosure rides in the Strength cell (column 4), so it is visible without
    # reading the Scale column (column 5) or the prose.
    cells = [c.strip() for c in tpch_line.strip().strip("|").split("|")]
    strength_cell = cells[3]
    assert "UNGUARDED above SF=1" in strength_cell, (
        f"tpch Strength cell must disclose SF>1 value-blindness; got {strength_cell!r}"
    )
    # A cardinality-only expected-results row (tpcds) has no VALUE claim, so it carries
    # no value-blindness disclosure (the marker is value-specific, not blanket).
    tpcds_line = next(line for line in markdown.splitlines() if line.startswith("| tpcds |"))
    assert "UNGUARDED above SF=1" not in tpcds_line


def test_independence_does_not_overload_strength(rows):
    """The independence axis is a SEPARATE column, never folded into Strength.

    A `value-level` variant cell and the `value+cardinality` tpch cell share an
    independence label but keep distinct Strength labels -- proving the axes are
    orthogonal columns, not one merged signal.
    """
    by_id = {r["benchmark"]: r for r in rows}
    assert by_id["tpchavoc"]["strength"] == STRENGTH_VALUE
    assert by_id["tpch"]["strength"] == STRENGTH_VALUE_AND_CARDINALITY
    assert by_id["tpchavoc"]["independence"] == by_id["tpch"]["independence"] == INDEPENDENCE_SELF


def test_cross_surface_enforced_distinguishes_registered_from_verified_green(rows):
    """A cross-surface gate's CI-enforcement (M1 honesty) is recorded and accurate.

    ``cross_surface_enforced`` separates a CI-enforced (blocking, hence green-or-
    CI-fails) gate from one merely registered: it is ``True`` for gates in the
    enforced ``GATES`` registry, ``False`` for ``STAGED_GATES`` (registered but not
    run in CI), and ``None`` for benchmarks with no cross-surface gate. Mere
    registration must never be reported as enforced coverage.
    """
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES

    by_id = {r["benchmark"]: r for r in rows}
    for benchmark_id in GATES:
        assert by_id[benchmark_id]["cross_surface_enforced"] is True, (
            f"{benchmark_id} is in enforced GATES but not reported as CI-enforced"
        )
    for benchmark_id in STAGED_GATES:
        assert by_id[benchmark_id]["cross_surface_enforced"] is False, (
            f"{benchmark_id} is STAGED (not CI-enforced) but reported as enforced"
        )
    # The currently-enforced cross-surface gates must be reported as such.
    assert {"ssb", "coffeeshop", "amplab", "clickbench", "joinorder_synthetic"} <= set(GATES), (
        "expected enforced cross-surface gate set changed; update the coverage-map honesty test"
    )
    for r in rows:
        # A non-cross-surface benchmark carries no enforcement signal.
        if ORACLE_CROSS_SURFACE not in r["oracles"]:
            assert r["cross_surface_enforced"] is None, (
                f"{r['benchmark']} has no cross-surface gate but carries an enforcement flag"
            )
