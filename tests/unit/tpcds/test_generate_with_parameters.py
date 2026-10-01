"""Tests for ``DSQGenBinary.generate_with_parameters``: rendering a query with explicit values.

Values are keyed by the names dsqgen's ``-LOG`` writes (``YEAR.01``). The round-trip test renders
a seed, reads its ``-LOG`` values, renders again from those values with a different seed, and
requires the same SQL, so it pins that the explicit values fully determine the substitutions.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.tpcds,
]


@pytest.fixture(scope="module")
def dsqgen():
    from benchbox.core.tpcds.c_tools import DSQGenBinary, TPCDSError

    try:
        return DSQGenBinary()
    except (TPCDSError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"dsqgen binary or templates unavailable: {exc}")


def _squash(sql):
    return " ".join(sql.split())


def _logged_values(dsqgen, query_id, seed):
    """The values dsqgen draws for ``seed``, read from its -LOG file, without the bookkeeping names."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        env = dsqgen._stage_dsqgen_workdir(temp_path)
        log = temp_path / "parameters.log"
        cmd, opt = dsqgen._build_dsqgen_cmd(query_id, None, seed, 1.0, "netezza", False)
        cmd.extend([f"{opt}INPUT", "q/templates.lst", f"{opt}DIRECTORY", "q", f"{opt}LOG", str(log)])
        subprocess.run(cmd, cwd=temp_dir, env=env, capture_output=True, text=True, timeout=30, check=True)
        values = {}
        for line in log.read_text().splitlines():
            match = re.match(r"\s+(\S+)\s*=\s?(.*)$", line)
            if match and not match.group(1).startswith("_"):
                values[match.group(1)] = match.group(2).strip()
        return values


def test_explicit_values_win_over_the_seed(dsqgen):
    for seed in (1, 77):
        sql = _squash(dsqgen.generate_with_parameters(39, {"YEAR.01": 2001, "MONTH.01": 1}, seed=seed))

        assert "d_year =2001" in sql
        assert "inv1.d_moy=1" in sql
        assert "inv2.d_moy=1+1" in sql  # the template's [MONTH]+1 keeps its expression


def test_text_values_and_dependent_defines(dsqgen):
    q93 = _squash(dsqgen.generate_with_parameters(93, {"REASON.01": "reason 28"}))
    q44 = _squash(dsqgen.generate_with_parameters(44, {"STORE.01": 4, "NULLCOLSS.01": "ss_addr_sk"}))

    assert "r_reason_desc = 'reason 28'" in q93
    assert "ss_store_sk = 4" in q44
    assert "ss_addr_sk is null" in q44


def test_a_list_of_four_hundred_values(dsqgen):
    zips = {f"ZIP.{index:03d}": str(10000 + index) for index in range(1, 401)}

    sql = _squash(dsqgen.generate_with_parameters(8, {**zips, "YEAR.01": 2001, "QOY.01": 2}))

    assert all(f"'{10000 + index}'" in sql for index in (1, 200, 400))
    assert "d_year = 2001" in sql


def test_multi_part_variant_selects_its_part(dsqgen):
    sql = dsqgen.generate_with_parameters("39a", {"YEAR.01": 2001, "MONTH.01": 1})

    assert "d_year =2001" in _squash(sql)
    assert sql != dsqgen.generate_with_parameters("39b", {"YEAR.01": 2001, "MONTH.01": 1})


@pytest.mark.parametrize("query_id", [8, 10, 39, 44, 73, 88, 89, 93, 98])
def test_values_from_a_seed_reproduce_that_seed(dsqgen, query_id):
    values = _logged_values(dsqgen, query_id, seed=7)
    reference = dsqgen.generate(query_id, seed=7)

    rendered = dsqgen.generate_with_parameters(query_id, values, seed=99)

    assert _squash(rendered) == _squash(reference)


@pytest.mark.parametrize("name", ["YEAR", "YEAR.", "YEAR.x", ".01"])
def test_malformed_names_are_rejected(dsqgen, name):
    with pytest.raises(ValueError, match="Parameter name"):
        dsqgen.generate_with_parameters(39, {name: 1})


@pytest.mark.parametrize("name", ["NOPE.01", "year.01"])
def test_a_name_the_template_does_not_define_is_rejected(dsqgen, name):
    # Names are case-sensitive.
    with pytest.raises(ValueError, match=f"no substitution for parameter '{name}'"):
        dsqgen.generate_with_parameters(39, {name: 1})


def test_a_defined_value_the_template_does_not_use_is_accepted(dsqgen):
    # Q10 defines ten COUNTY values (and dsqgen -LOG reports ten) but its SQL uses only five.
    used = _squash(dsqgen.generate_with_parameters(10, {"COUNTY.01": "Aa County"}))
    with_unused = _squash(dsqgen.generate_with_parameters(10, {"COUNTY.01": "Aa County", "COUNTY.10": "Zz County"}))

    assert "Aa County" in used
    assert with_unused == used


def test_invalid_query_id_is_rejected(dsqgen):
    with pytest.raises(ValueError):
        dsqgen.generate_with_parameters(100, {"YEAR.01": 2001})
