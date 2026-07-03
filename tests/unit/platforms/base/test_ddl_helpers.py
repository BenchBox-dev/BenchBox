"""Unit tests for benchbox/platforms/base/ddl_helpers.py."""

from __future__ import annotations

import pytest

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys, strip_primary_keys, strip_with_properties

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# ---------------------------------------------------------------------------
# strip_with_properties
# ---------------------------------------------------------------------------


class TestStripWithProperties:
    def test_simple_with_clause(self):
        sql = "CREATE TABLE t (a INT) WITH (format = 'PARQUET')"
        assert strip_with_properties(sql) == "CREATE TABLE t (a INT)"

    def test_nested_function_in_with(self):
        """bucket(x, 16) contains a ) that a naive [^)]* regex would stop at."""
        sql = "CREATE TABLE t (a INT) WITH (partitioning = ARRAY['bucket(x, 16)'])"
        assert strip_with_properties(sql) == "CREATE TABLE t (a INT)"

    def test_nested_date_trunc_in_with(self):
        sql = "CREATE TABLE t (a INT) WITH (sorted_by = ARRAY[date_trunc('day', ts)])"
        assert strip_with_properties(sql) == "CREATE TABLE t (a INT)"

    def test_multiple_properties_with_nested(self):
        sql = "CREATE TABLE t (a INT) WITH (format = 'PARQUET', partitioning = ARRAY['bucket(ws_sold_date_sk, 16)'])"
        assert strip_with_properties(sql) == "CREATE TABLE t (a INT)"

    def test_no_with_clause_passthrough(self):
        sql = "CREATE TABLE t (a INT, b TEXT)"
        assert strip_with_properties(sql) == sql

    def test_with_inside_column_default_untouched(self):
        """WITH appearing inside the column list (e.g. DEFAULT) must not be stripped."""
        sql = "CREATE TABLE t (a INT DEFAULT (now()), b TEXT) ENGINE = MergeTree()"
        assert strip_with_properties(sql) == sql

    def test_empty_with_clause(self):
        sql = "CREATE TABLE t (a INT) WITH ()"
        assert strip_with_properties(sql) == "CREATE TABLE t (a INT)"

    def test_whitespace_preserved_around_removal(self):
        sql = "CREATE TABLE t (a INT)\nWITH (format = 'ORC')"
        result = strip_with_properties(sql)
        assert "WITH" not in result.upper()
        assert "CREATE TABLE t (a INT)" in result

    def test_no_with_keyword_no_scan(self):
        sql = "SELECT a FROM t"
        assert strip_with_properties(sql) == sql

    def test_iceberg_complex_partitioning(self):
        sql = (
            "CREATE TABLE orders (o_id BIGINT, o_date DATE) "
            "WITH (partitioning = ARRAY['month(o_date)', 'bucket(o_id, 8)'])"
        )
        assert strip_with_properties(sql) == "CREATE TABLE orders (o_id BIGINT, o_date DATE)"


# ---------------------------------------------------------------------------
# strip_primary_keys
# ---------------------------------------------------------------------------


class TestStripPrimaryKeys:
    def test_simple_table_level_pk(self):
        sql = "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a))"
        result = strip_primary_keys(sql)
        assert "PRIMARY KEY" not in result.upper()
        assert "a INT" in result

    def test_composite_pk_with_expression(self):
        """PRIMARY KEY ("a", coalesce(b, 0)) — [^)]* stops at first ) in coalesce."""
        sql = 'CREATE TABLE t (a TEXT, b INT, PRIMARY KEY ("a", coalesce(b, 0)))'
        result = strip_primary_keys(sql)
        assert "PRIMARY KEY" not in result.upper()
        assert "a TEXT" in result

    @pytest.mark.parametrize("constraint_name", ["pk_t", '"pk_t"', "`pk_t`"])
    def test_named_table_level_pk(self, constraint_name):
        sql = f"CREATE TABLE t (a INT, CONSTRAINT {constraint_name} PRIMARY KEY (a))"
        result = strip_primary_keys(sql)
        result_upper = result.upper()
        assert "PRIMARY KEY" not in result_upper
        assert "CONSTRAINT" not in result_upper
        assert "a INT" in result
        assert ",)" not in result

    def test_composite_pk_multiple_columns(self):
        sql = "CREATE TABLE t (a INT, b INT, c INT, PRIMARY KEY (a, b, c))"
        result = strip_primary_keys(sql)
        assert "PRIMARY KEY" not in result.upper()

    def test_inline_pk(self):
        sql = "CREATE TABLE t (a INT PRIMARY KEY, b TEXT)"
        result = strip_primary_keys(sql)
        assert "PRIMARY KEY" not in result.upper()
        assert "a INT" in result

    def test_named_inline_pk(self):
        sql = "CREATE TABLE t (a INT CONSTRAINT pk_t PRIMARY KEY, b TEXT)"
        result = strip_primary_keys(sql)
        result_upper = result.upper()
        assert "PRIMARY KEY" not in result_upper
        assert "CONSTRAINT" not in result_upper
        assert "a INT" in result
        assert "b TEXT" in result

    def test_no_pk_passthrough(self):
        sql = "CREATE TABLE t (a INT, b TEXT)"
        assert strip_primary_keys(sql) == sql

    def test_trailing_comma_cleaned(self):
        sql = "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a))"
        result = strip_primary_keys(sql)
        assert ",)" not in result

    def test_pk_with_leading_comma_cleaned(self):
        """Leading comma from the preceding column should also be stripped."""
        sql = "CREATE TABLE t (a INT, PRIMARY KEY (a))"
        result = strip_primary_keys(sql)
        assert "PRIMARY KEY" not in result.upper()
        assert ",)" not in result

    def test_table_level_pk_first_does_not_leave_leading_comma(self):
        sql = "CREATE TABLE t (PRIMARY KEY (a), a INT)"
        result = strip_primary_keys(sql)
        assert result == "CREATE TABLE t (a INT)"

    def test_comment_literal_primary_key_limitation_is_documented(self):
        assert "string-literal false positive" in (strip_primary_keys.__doc__ or "")


# ---------------------------------------------------------------------------
# strip_foreign_keys (regression — ensure w4 fix still holds)
# ---------------------------------------------------------------------------


class TestStripForeignKeys:
    def test_table_level_fk(self):
        sql = "CREATE TABLE orders (  o_id INT,  c_id INT,  FOREIGN KEY (c_id) REFERENCES customer(c_id))"
        result = strip_foreign_keys(sql)
        assert "FOREIGN KEY" not in result.upper()
        assert "REFERENCES" not in result.upper()

    def test_inline_references(self):
        sql = "CREATE TABLE foo (a INT, customer_id INT REFERENCES customer(c_id))"
        result = strip_foreign_keys(sql)
        assert "REFERENCES" not in result.upper()

    def test_fk_with_on_delete_cascade(self):
        sql = "CREATE TABLE t (a INT, b INT, FOREIGN KEY (b) REFERENCES other(b) ON DELETE CASCADE)"
        result = strip_foreign_keys(sql)
        assert "FOREIGN KEY" not in result.upper()

    def test_no_fk_passthrough(self):
        sql = "CREATE TABLE t (a INT, b TEXT)"
        assert strip_foreign_keys(sql) == sql

    def test_trailing_comma_cleaned(self):
        sql = "CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES r(a))"
        result = strip_foreign_keys(sql)
        assert ",)" not in result
