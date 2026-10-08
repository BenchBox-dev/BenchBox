from __future__ import annotations

import pytest

from benchbox.platforms.clickhouse.workload import ClickHouseWorkloadMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

strip = ClickHouseWorkloadMixin._strip_primary_key_constraints


class TestTableLevelConstraints:
    def test_trailing_table_constraint_is_dropped(self):
        assert (
            strip("CREATE TABLE t (a Int32, PRIMARY KEY (a)) ENGINE = MergeTree()")
            == "CREATE TABLE t (a Int32) ENGINE = MergeTree()"
        )

    def test_leading_table_constraint_is_dropped(self):
        assert strip("CREATE TABLE t (PRIMARY KEY (a), b String)") == "CREATE TABLE t ( b String)"

    def test_middle_table_constraint_is_dropped(self):
        assert strip("CREATE TABLE t (a Int32, PRIMARY KEY (a, b), c String)") == "CREATE TABLE t (a Int32, c String)"

    def test_named_table_constraint_is_dropped_whole(self):
        assert strip("CREATE TABLE t (a Int32, CONSTRAINT pk PRIMARY KEY (a))") == "CREATE TABLE t (a Int32)"

    def test_named_quoted_table_constraint_is_dropped_whole(self):
        assert strip('CREATE TABLE t (a Int32, CONSTRAINT "pk" PRIMARY KEY (a))') == "CREATE TABLE t (a Int32)"

    def test_lowercase_statement_is_stripped(self):
        assert strip("create table t (a int32, primary key (a))") == "create table t (a int32)"

    def test_if_not_exists_is_stripped(self):
        assert (
            strip("CREATE TABLE IF NOT EXISTS t (a Int32, PRIMARY KEY (a));")
            == "CREATE TABLE IF NOT EXISTS t (a Int32);"
        )


class TestQuotedTableNames:
    def test_double_quoted_table_name_is_stripped(self):
        assert strip('CREATE TABLE "my table" (a Int32, PRIMARY KEY (a))') == 'CREATE TABLE "my table" (a Int32)'

    def test_backtick_table_name_is_stripped(self):
        assert strip("CREATE TABLE `t` (a Int32, PRIMARY KEY (a))") == "CREATE TABLE `t` (a Int32)"

    def test_bracket_table_name_is_stripped(self):
        assert strip("CREATE TABLE [t] (a Int32, PRIMARY KEY (a))") == "CREATE TABLE [t] (a Int32)"


class TestInlineConstraints:
    def test_inline_constraint_is_removed(self):
        assert strip("CREATE TABLE t (a Int32 PRIMARY KEY, b String)") == "CREATE TABLE t (a Int32, b String)"

    def test_inline_constraint_on_quoted_column_is_removed(self):
        assert (
            strip('CREATE TABLE t ("my col" Int32 PRIMARY KEY, b String)')
            == 'CREATE TABLE t ("my col" Int32, b String)'
        )

    def test_inline_constraint_after_string_default_is_removed(self):
        assert (
            strip("CREATE TABLE t (n String DEFAULT 'x' PRIMARY KEY, b String)")
            == "CREATE TABLE t (n String DEFAULT 'x', b String)"
        )


class TestLiteralsAndCommentsSurvive:
    def test_string_literal_mentioning_primary_key_survives(self):
        statement = "CREATE TABLE t (a Int32, n String DEFAULT 'a PRIMARY KEY b', PRIMARY KEY (a))"
        assert strip(statement) == "CREATE TABLE t (a Int32, n String DEFAULT 'a PRIMARY KEY b')"

    def test_line_comment_with_comma_survives(self):
        comment = "/" + "* pk, (x) *" + "/"
        statement = f"CREATE TABLE t (a Int32 {comment}, PRIMARY KEY (a))"
        assert strip(statement) == f"CREATE TABLE t (a Int32 {comment})"

    def test_nested_type_commas_do_not_split(self):
        statement = "CREATE TABLE t (d Decimal(10, 2), e Enum8('a', 'b'), PRIMARY KEY (d))"
        assert strip(statement) == "CREATE TABLE t (d Decimal(10, 2), e Enum8('a', 'b'))"


class TestNonTargetsUnchanged:
    def test_statement_without_primary_key_is_unchanged(self):
        statement = "CREATE TABLE t (a Int32, b String)"
        assert strip(statement) == statement

    def test_non_create_statement_is_unchanged(self):
        statement = "SELECT PRIMARY KEY FROM t"
        assert strip(statement) == statement
