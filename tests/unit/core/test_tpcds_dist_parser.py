import tempfile
from pathlib import Path

import pytest

from benchbox.core.tpcds.dist_parser import (
    TPCDSDistribution,
    TPCDSDistributionParser,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_dist_parser_parses_minimal_dst_file():
    sample_dst_content = """
-- comment line
create cities;
set types = (varchar);
set weights = 4;
set names = (name:usgs, uniform, large);
add ("Midway":212, 1, 0.5, 0);
add ("Fairview":199, 0.5, 0.25, 0);
add ("Oak Grove":160, 0, 0.25, 1);
""".strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".dst", delete=False, encoding="utf-8") as f:
        f.write(sample_dst_content)
        temp_file = f.name

    try:
        parser = TPCDSDistributionParser()
        dists = parser.parse_file(Path(temp_file))

        assert "cities" in dists
        dist = dists["cities"]
        assert dist.types == ["varchar"]
        assert dist.weights == 4
        # names should strip suffix after ':'
        assert dist.weight_names[0] == "name"
        assert len(dist.entries) == 3

        # weight set 0,1,2 should be accessible
        w0 = dist.get_weighted_entries(0)
        w1 = dist.get_weighted_entries(1)
        w2 = dist.get_weighted_entries(2)
        assert any(v == "Midway" for v, _ in w0)
        assert any(v == "Fairview" for v, _ in w1)
        assert any(v == "Oak Grove" for v, _ in w2)
    finally:
        Path(temp_file).unlink(missing_ok=True)


def test_distribution_add_entry_mismatch_raises():
    d = TPCDSDistribution("example")
    d.weights = 2
    # only one weight provided should raise
    try:
        d.add_entry("X", [0.1])
        raised = False
    except ValueError as e:
        raised = True
        assert "Weight count mismatch" in str(e)
    assert raised


def test_dist_parser_edge_cases_and_helpers(tmp_path):
    parser = TPCDSDistributionParser()

    # _extract_parentheses_content with no closing paren
    assert parser._extract_parentheses_content("add (no close") is None

    # _parse_add_statement invalid formats
    assert parser._parse_add_statement('"') is None

    # simple value format without quotes
    result = parser._parse_add_statement("Midway, 1, 2, 3")
    assert result is not None, "Expected parse result"
    value, weights = result
    assert value == "Midway" and weights == [1.0, 2.0, 3.0]

    # get_weighted_entries invalid index
    d = TPCDSDistribution("x")
    d.weights = 2
    d.add_entry("A", [0.1, 0.9])
    try:
        d.get_weighted_entries(5)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # parse_directory with a valid and an invalid file
    good = tmp_path / "cities.dst"
    bad = tmp_path / "bad.dst"
    good.write_text(
        """
create cities;
set types = (varchar);
set weights = 2;
set names = (n1, n2);
add ("X":1, 1);
""".strip()
    )
    bad.write_text("add invalid")
    dists = parser.parse_directory(tmp_path)
    assert "cities" in dists
    assert repr(dists["cities"]).startswith("TPCDSDistribution(")
