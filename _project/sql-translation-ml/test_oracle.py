import pytest
from oracle import equivalent, safe_query, validate


def test_values_are_not_silently_normalized():
    assert not equivalent((1, [("a ",)]), (1, [("a",)]), False)
    assert not equivalent((1, [("1",)]), (1, [(1,)]), False)
    assert not equivalent((1, [(1,), (1,)]), (1, [(1,)]), False)
    assert not equivalent((2, []), (1, []), False)
    with pytest.raises(ValueError, match="nonfinite"):
        equivalent((1, [(float("nan"),)]), (1, [(None,)]), False)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DELETE FROM items",
        "DROP TABLE items",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT load_extension('x')",
        "SELECT * FROM sqlite_master",
        "SELECT random()",
        "SELECT APPROX_COUNT_DISTINCT(id) FROM items",
    ],
)
def test_candidate_safety(sql):
    with pytest.raises(ValueError):
        safe_query(sql, "sqlite")


@pytest.mark.parametrize(
    "source,target",
    [
        ("SELECT DISTINCT amount FROM items", "SELECT amount FROM items"),
        (
            "SELECT a.id,b.id FROM items a LEFT JOIN other b ON a.id=b.id",
            "SELECT a.id,b.id FROM items a JOIN other b ON a.id=b.id",
        ),
        ("SELECT id FROM items WHERE amount > 0", "SELECT id FROM items"),
        ("SELECT amount / 2 FROM items", "SELECT amount / 2 FROM items"),
        (
            "SELECT amount FROM items ORDER BY amount NULLS FIRST, id NULLS FIRST",
            "SELECT amount FROM items ORDER BY amount NULLS LAST, id NULLS FIRST",
        ),
        ("SELECT AVG(amount) FROM items", "SELECT round(AVG(amount)) FROM items"),
    ],
)
def test_wrong_translations_are_rejected(source, target):
    assert not validate(source, target, "duckdb", [101, 202, 303, 404, 505])["equivalent"]


def test_valid_translation_on_five_fixtures():
    sql = "SELECT grp,COUNT(*),SUM(amount) FROM items GROUP BY grp"
    assert validate(sql, sql, "duckdb", [101, 202, 303, 404, 505])["equivalent"]
