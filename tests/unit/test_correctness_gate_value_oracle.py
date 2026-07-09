"""Sensitivity proof for the bounded correctness gate's VALUE oracle.

The gate historically validated only ROW COUNTS, so a wrong-but-same-cardinality
answer shipped GREEN. These tests prove the value-digest oracle closes that gap:

  1. the digest primitive itself flips for cardinality-preserving value mutations
     (a perturbed aggregate, a swapped column, a changed rounding, a permuted
     column) -- so a wrong value cannot hash to the same digest as the right one;
  2. the gate's validation path (``_validate_against_expected_results``) turns RED
     when an emitted digest mismatches the stored reference even though the row
     count is unchanged, and -- under strict arming -- when an emitted digest is
     missing (the value oracle must not silently disarm).

These run in the fast unit lane (no DuckDB / answer files), so the sensitivity
guarantee is always exercised, not only inside the heavy SF=1 gate.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from benchbox.core.expected_results.models import ValidationMode, ValidationResult
from benchbox.core.results.result_digest import compute_result_digest, digests_match

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# A representative correct result set: TPC-H Q1-shaped grouped aggregate rows
# (4 rows, mixed string + numeric columns).
_BASE_ROWS = [
    ("A", "F", 37734107, 56586554400.73, 53758257134.87, 0.05, 25.52),
    ("N", "F", 991417, 1487504710.38, 1413082168.05, 0.05, 25.51),
    ("N", "O", 74476040, 111701729697.74, 106118230307.61, 0.05, 25.50),
    ("R", "F", 37719753, 56568041380.90, 53741292684.60, 0.05, 25.51),
]


def _perturb_aggregate(rows):
    """Cardinality-preserving: change one aggregate value in one row."""
    mutated = [list(r) for r in rows]
    # Shift a revenue sum by ~1e-5 relative -- above the digest's ~1e-6 relative floor
    # at any magnitude (a fixed 2-cent absolute shift is now far below the floor on a
    # ~5.6e10 revenue value, so the perturbation is expressed relatively).
    mutated[0][3] = mutated[0][3] * (1 + 1e-5)
    return [tuple(r) for r in mutated]


def _swap_two_columns(rows):
    """Cardinality-preserving: swap two numeric columns of equal cardinality."""
    return [(a, b, c, e, d, f, g) for (a, b, c, d, e, f, g) in rows]


def _change_rounding(rows):
    """Cardinality-preserving: round a value to whole units."""
    mutated = [list(r) for r in rows]
    mutated[2][4] = round(mutated[2][4])  # 106118230307.61 -> 106118230308
    return [tuple(r) for r in mutated]


def _permute_a_column(rows):
    """Cardinality-preserving: swap two rows' values within one column."""
    mutated = [list(r) for r in rows]
    mutated[0][6], mutated[1][6] = mutated[1][6], mutated[0][6]
    return [tuple(r) for r in mutated]


_MUTATIONS = {
    "perturbed_aggregate": _perturb_aggregate,
    "swapped_columns": _swap_two_columns,
    "changed_rounding": _change_rounding,
    "permuted_column": _permute_a_column,
}


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
def test_digest_flips_on_cardinality_preserving_value_mutation(name):
    """Each cardinality-preserving value mutation changes the digest (>=3 classes)."""
    base_digest = compute_result_digest(_BASE_ROWS)
    mutated_rows = _MUTATIONS[name](_BASE_ROWS)

    # The mutation must preserve cardinality -- that is the whole point (row-count
    # validation cannot catch it).
    assert len(mutated_rows) == len(_BASE_ROWS), f"{name} changed cardinality"

    mutated_digest = compute_result_digest(mutated_rows)
    assert mutated_digest != base_digest, f"{name} was NOT caught by the value digest"


def test_at_least_three_distinct_mutation_classes_are_caught():
    """The sensitivity proof must cover >=3 distinct cardinality-preserving classes."""
    base_digest = compute_result_digest(_BASE_ROWS)
    caught = [
        name
        for name, mutate in _MUTATIONS.items()
        if compute_result_digest(mutate(_BASE_ROWS)) != base_digest and len(mutate(_BASE_ROWS)) == len(_BASE_ROWS)
    ]
    assert len(caught) >= 3, f"expected >=3 caught cardinality-preserving mutations, got {sorted(caught)}"


def test_column_swap_with_identical_columns_is_a_known_blind_spot():
    """Document a value-mutation class the digest cannot catch: swapping equal columns.

    Swapping two columns whose values are pairwise identical is invisible to any
    value comparator (the result is byte-identical). This is the documented
    limitation referenced by the gate TODO (w3 acceptance: any uncatchable class is
    recorded with its reason).
    """
    rows = [("x", 1.0, 1.0), ("y", 2.0, 2.0)]
    swapped = [(a, c, b) for (a, b, c) in rows]
    assert compute_result_digest(rows) == compute_result_digest(swapped)


# --- Precision floor: relative, not absolute (w1) -------------------------------
#
# The digest normalizes real numbers to ``_DIGEST_FLOAT_SIGFIGS`` significant figures,
# so the sensitivity floor is ~1e-6 RELATIVE per cell (half of the last-sig-fig grid),
# uniform across column magnitude. These tests PIN that boundary on a real gate column
# so a future normalization change cannot silently move it without updating the
# recorded decision next to ``_format_real``.

# TPC-H Q1 ``avg_disc`` (result column index 8 in the canonical Q1 projection) is a
# small averaged ratio ~0.05. Under the OLD absolute 4dp floor it had only ~0.1%
# relative sensitivity; the relative floor now gives it the same ~1e-6 relative
# sensitivity as any other column. At ~0.05 the 6-sig-fig grid is 1e-7 absolute, so
# the half-bucket floor is ~5e-8 absolute (~1e-6 relative).
_AVG_DISC = 0.05  # representative TPC-H Q1 avg_disc value (a float, ~0.0500)


def test_precision_floor_is_relative_below_floor_not_caught():
    """A per-cell error BELOW the ~1e-6 relative floor on avg_disc is INVISIBLE.

    At ~0.05 the half-bucket floor is ~5e-8 absolute; 0.05 + 4e-8 rounds to the same
    6-sig-fig token, so the digest is unchanged. This residual blind spot is now
    ~1000x finer than the old absolute 4dp floor (~5e-5 absolute / ~0.1% relative).
    """
    base = compute_result_digest([(_AVG_DISC,)])
    just_below = compute_result_digest([(_AVG_DISC + 4e-8,)])
    assert just_below == base, "an error below the relative floor must NOT change the digest"


def test_precision_floor_is_relative_above_floor_caught():
    """A per-cell error ABOVE the ~1e-6 relative floor on avg_disc IS caught.

    0.05 + 6e-8 crosses into the next 6-sig-fig token, so the digest differs. The
    precise midpoint (~5e-8 absolute here) is round-half-even and float-representation
    dependent, so it is deliberately not asserted.
    """
    base = compute_result_digest([(_AVG_DISC,)])
    just_above = compute_result_digest([(_AVG_DISC + 6e-8,)])
    assert just_above != base, "an error above the relative floor MUST change the digest"


def test_precision_floor_is_uniform_relative_across_magnitudes():
    """The floor is RELATIVE, so a large-magnitude column has the SAME ~1e-6 relative
    sensitivity -- finer than the old absolute floor on small ratios, coarser on big
    ones (the accepted tradeoff of switching to significant-figure rounding).

    On revenue ~5.66e10 a 2-cent (absolute) change is ~3e-13 relative -- far below the
    floor, so it is now INVISIBLE (the old absolute 4dp scheme would have caught it);
    a change above ~1e-6 relative IS caught.
    """
    revenue = 56586554400.73
    base = compute_result_digest([(revenue,)])
    assert compute_result_digest([(revenue + 0.02,)]) == base, "below the relative floor -> invisible"
    assert compute_result_digest([(revenue * (1 + 1e-5),)]) != base, "above the relative floor -> caught"


# --- Value+type coupling: a value+type digest, DuckDB-pinned (w2) ----------------


def test_digest_couples_value_with_numeric_type():
    """The digest is a value+TYPE digest: equal value, different Python type -> differs.

    An ``int`` renders exactly ("37734107") while a ``float``/``Decimal`` of the same
    value renders to fixed significant figures ("377341e2"), so they hash DIFFERENTLY. This
    is acceptable ONLY because the oracle is DuckDB-pinned (DuckDB returns a stable
    column type per query), and it is the documented blocker for cross-engine reuse
    (w5 deferred). If a future change canonicalizes integer-valued numerics to one
    representation, this test flips and the 18 reference digests must be regenerated
    in the same change.
    """
    int_digest = compute_result_digest([(37734107,)])
    float_digest = compute_result_digest([(37734107.0,)])
    decimal_digest = compute_result_digest([(Decimal("37734107"),)])

    # int renders exactly; float/Decimal render at fixed precision -> int differs.
    assert int_digest != float_digest, "int and float of equal value must (today) differ -- value+type coupling"
    assert int_digest != decimal_digest, "int and Decimal of equal value must (today) differ -- value+type coupling"
    # float and Decimal share the fixed-precision rendering, so they DO agree: the
    # coupling is specifically integer-exact-vs-fixed-precision, not arbitrary.
    assert float_digest == compute_result_digest([(Decimal("37734107.00"),)])


# --- Gate validation path: a mismatch / missing digest must turn RED ------------


_GATE_ROWS = {"1": 4, "6": 1, "3": 10}  # query_id -> expected row count


def _make_fake_validator(stored_digests):
    """Build a fake QueryValidator that returns fixed row counts + stored digests.

    Decouples the sensitivity proof from real answer files / DuckDB while exercising
    the exact ``_validate_against_expected_results`` code path the gate uses.
    """

    class _FakeRegistry:
        def get_expected_result(self, benchmark_type, query_id, scale_factor, stream_id):
            if stream_id is not None and int(stream_id) > 0:
                return None
            qid = str(query_id)
            if qid not in stored_digests:
                return None
            # Stored references are SF=1 (the only scale with stored digests).
            return SimpleNamespace(
                value_digest=stored_digests[qid], expected_row_count=_GATE_ROWS.get(qid), scale_factor=1.0
            )

    class _FakeValidator:
        def __init__(self):
            self.registry = _FakeRegistry()

        def validate_query_result(self, benchmark_type, query_id, actual_row_count, scale_factor, stream_id):
            expected = _GATE_ROWS.get(str(query_id))
            if expected is None:
                return ValidationResult(
                    is_valid=True,
                    query_id=str(query_id),
                    expected_row_count=None,
                    actual_row_count=actual_row_count,
                    validation_mode=ValidationMode.SKIP,
                )
            return ValidationResult(
                is_valid=expected == actual_row_count,
                query_id=str(query_id),
                expected_row_count=expected,
                actual_row_count=actual_row_count,
                validation_mode=ValidationMode.EXACT,
            )

    return _FakeValidator


def _gate_payload(digests):
    """Payload whose stream-0 queries carry the given emitted digests + correct rows."""
    return {
        "queries": [
            {"id": qid, "status": "SUCCESS", "rows": rows, "stream": 0, "digest": digests.get(qid)}
            for qid, rows in _GATE_ROWS.items()
        ]
    }


def _stored_digests():
    """Stored reference digests derived from real result sets (one per gate query)."""
    sources = {
        "1": _BASE_ROWS,
        "6": [(123456.789,)],
        "3": [(i, float(i) * 1.5, f"k{i}") for i in range(10)],
    }
    return {qid: compute_result_digest(rows) for qid, rows in sources.items()}, sources


def test_gate_goes_red_on_value_mutation_with_unchanged_cardinality(monkeypatch):
    """A cardinality-preserving value mutation in one query turns the gate RED."""
    import tests.integration.test_local_platform_benchmark_matrix as matrix

    stored, sources = _stored_digests()
    monkeypatch.setattr(matrix, "QueryValidator", _make_fake_validator(stored))
    monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")

    # Correct emitted digests: gate is GREEN (no assertion raised).
    correct_emitted = dict(stored)
    matrix._validate_against_expected_results(
        _gate_payload(correct_emitted), "tpch", 1.0, expected_query_ids=set(_GATE_ROWS)
    )

    # Mutate Q1's VALUES (cardinality unchanged) -> emitted digest diverges -> RED.
    mutated_rows = _perturb_aggregate(sources["1"])
    assert len(mutated_rows) == len(sources["1"])  # cardinality preserved
    mutated_emitted = dict(stored)
    mutated_emitted["1"] = compute_result_digest(mutated_rows)

    with pytest.raises(AssertionError, match="VALUE DIGEST mismatch"):
        matrix._validate_against_expected_results(
            _gate_payload(mutated_emitted), "tpch", 1.0, expected_query_ids=set(_GATE_ROWS)
        )


def test_gate_goes_red_when_digest_missing_under_strict(monkeypatch):
    """A missing emitted digest disarms the value oracle -> RED under strict arming."""
    import tests.integration.test_local_platform_benchmark_matrix as matrix

    stored, _ = _stored_digests()
    monkeypatch.setattr(matrix, "QueryValidator", _make_fake_validator(stored))
    monkeypatch.setenv("BENCHBOX_STRICT_EXPECTED_RESULTS", "1")

    emitted = dict(stored)
    emitted["3"] = None  # value oracle disarmed for Q3 (no digest emitted)

    with pytest.raises(AssertionError, match="strict value-digest"):
        matrix._validate_against_expected_results(
            _gate_payload(emitted), "tpch", 1.0, expected_query_ids=set(_GATE_ROWS)
        )


def test_digests_match_never_silently_matches_missing():
    """A missing emitted digest never equals a stored digest (no silent pass)."""
    assert digests_match("abc", "abc") is True
    assert digests_match("abc", None) is False
    assert digests_match(None, "abc") is False
    assert digests_match(None, None) is False


def test_sf1_value_digest_is_not_reused_at_other_scales():
    """A scale-independent fallback must NOT leak the SF=1 value digest to SF != 1.

    The registry returns the SF=1 ExpectedQueryResult for a scale-independent query
    (e.g. TPC-H Q1) at any scale; its row count is scale-independent but its VALUE
    digest is not. `_stored_value_digest` must therefore decline the digest when the
    stored object's scale does not match the run scale, so digest emission at SF != 1
    cannot produce a spurious RED.
    """
    import tests.integration.test_local_platform_benchmark_matrix as matrix

    class _ScaleIndependentRegistry:
        def get_expected_result(self, benchmark_type, query_id, scale_factor, stream_id):
            # Mirrors the real registry's scale-independent fallback: always returns
            # the SF=1 object regardless of the requested scale.
            return SimpleNamespace(value_digest="sf1digest", expected_row_count=4, scale_factor=1.0)

    validator = SimpleNamespace(registry=_ScaleIndependentRegistry())

    # At the stored scale (SF=1) the digest is honored.
    assert matrix._stored_value_digest(validator, "tpch", "1", 1.0, 0) == "sf1digest"
    # At other scales the SF=1 digest is declined (row-count fallback still applies).
    assert matrix._stored_value_digest(validator, "tpch", "1", 0.01, 0) is None
    assert matrix._stored_value_digest(validator, "tpch", "1", 10.0, 0) is None
