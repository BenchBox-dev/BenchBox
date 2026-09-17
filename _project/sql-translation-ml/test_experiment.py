import pytest
from corpus import cases
from evaluate import bounds
from experiment import apply_edits, edits, wire


def test_edit_contract():
    source, target = "SELECT foo FROM items", "SELECT bar FROM items WHERE id>0"
    assert apply_edits(source, edits(source, target)) == target
    assert apply_edits(source, []) == source
    for invalid in [
        [{"start": -1, "end": 0, "text": "x"}],
        [{"start": 1, "end": 99, "text": "x"}],
        [{"start": 0, "end": 3, "text": "x"}, {"start": 2, "end": 4, "text": "y"}],
        [{"start": True, "end": 3, "text": "x"}],
    ]:
        with pytest.raises(ValueError):
            apply_edits(source, invalid)


def test_family_structure_and_reverse_split_isolation():
    source = cases()
    for field in ("family_id", "group_id", "structure"):
        splits = {}
        for case in source:
            splits.setdefault(case[field], set()).add(case["split"])
        assert all(len(split) == 1 for split in splits.values())
    for dialect in ("duckdb", "sqlite"):
        assert len({c["structure"] for c in source if c["split"] == "test" and c["source"] == dialect}) >= 1000
    assert "candidate" not in wire(source[0], "full", "SECRET SQL")
    assert "SECRET SQL" not in wire(source[0], "full", "SECRET SQL")


def test_related_successes_cannot_claim_high_confidence():
    result = bounds([{"family_id": "one", "success": True}] * 1000)
    assert not result["sufficient_families"]
    assert result["decision_lower"] < 0.99
    result = bounds([{"family_id": str(i), "success": True} for i in range(1000)])
    assert result["decision_lower"] >= 0.99
