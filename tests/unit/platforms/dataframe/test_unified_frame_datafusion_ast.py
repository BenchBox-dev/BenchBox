"""Regression coverage for DataFusion AST error-message parsing hardening.

`benchbox.platforms.dataframe.unified_frame._get_datafusion_ast_string()`
extracts AST information by deliberately triggering `Expr.rex_call_operator()`
and parsing the resulting error text. This is inherently coupled to
DataFusion's internal error-message format - see the module docstring and
`_project/TODO/main/planning/unified-frame-error-parsing-hardening.yaml`.

These tests simulate a DataFusion release changing that error-message format
and assert the function now fails loudly and attributably
(`DataFusionASTFormatError`, naming the installed DataFusion version) instead
of silently falling back to unchanged-expression behavior - which is the
actual hardening this TODO introduces. They also confirm the two cases that
must NOT raise: a genuinely different (non-Alias/BinaryExpr/AggregateFunction)
expression shape, and a non-Expr object that doesn't implement
`rex_call_operator()` at all (e.g. a plain column-name string mixed into the
same call).
"""

from __future__ import annotations

import pytest

from benchbox.platforms.dataframe import unified_frame as uf

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _RaisingExpr:
    """Minimal stand-in for a DataFusion Expr whose rex_call_operator() raises."""

    def __init__(self, message: str) -> None:
        self._message = message

    def rex_call_operator(self) -> None:
        raise RuntimeError(self._message)


class _NonRaisingExpr:
    """Stand-in for a DataFusion Expr whose rex_call_operator() succeeds
    (e.g. a plain binary expression that isn't wrapped in an Alias)."""

    def rex_call_operator(self) -> str:
        return "some_operator_name"


def test_changed_error_format_raises_attributable_error():
    """A DataFusion release that changes rex_call_operator()'s wrapper text
    (not just the AST it embeds) must raise DataFusionASTFormatError naming
    the installed DataFusion version and the unrecognized text, instead of
    silently returning None and falling back to unchanged-expression
    behavior.
    """
    import datafusion

    # Simulates a hypothetical future DataFusion release that renames/
    # restructures the catch-all wrapper text this module depends on. Still
    # contains an "Alias(BinaryExpr(...))"-shaped payload to prove the
    # failure is about the *wrapper* format, not the AST content.
    changed_format_expr = _RaisingExpr("Unexpected internal error: Alias(BinaryExpr(AggregateFunction(...)))")

    with pytest.raises(uf.DataFusionASTFormatError) as excinfo:
        uf._get_datafusion_ast_string(changed_format_expr)

    message = str(excinfo.value)
    assert datafusion.__version__ in message
    assert "Unexpected internal error" in message
    assert uf._DATAFUSION_AST_ERROR_PREFIX in message


def test_missing_wrapper_text_entirely_raises():
    """An error message that doesn't even resemble the catch-all wrapper at
    all (e.g. a totally different DataFusion-internal error) must also raise
    loudly rather than being silently treated as "not our pattern"."""
    unrelated_expr = _RaisingExpr("SchemaError: no field named 'x'")

    with pytest.raises(uf.DataFusionASTFormatError):
        uf._get_datafusion_ast_string(unrelated_expr)


def test_genuinely_different_expression_shape_returns_none_not_raises():
    """A real DataFusion expression (e.g. a plain Column/Literal/unaliased
    aggregate) whose error text matches the catch-all wrapper but doesn't
    contain Alias/BinaryExpr/AggregateFunction must still return None - this
    is the "fallback to unchanged expression" behavior the TODO's
    must_preserve requires for genuinely unsupported/inapplicable patterns,
    not a format-parsing failure."""
    plain_column_expr = _RaisingExpr(f'{uf._DATAFUSION_AST_ERROR_PREFIX}: Column {{ relation: None, name: "x" }}')

    assert uf._get_datafusion_ast_string(plain_column_expr) is None


def test_non_raising_expression_returns_none():
    """If rex_call_operator() succeeds without raising (e.g. a plain binary
    expression not wrapped in an Alias), extraction returns None - unrelated
    to error-format hardening entirely."""
    assert uf._get_datafusion_ast_string(_NonRaisingExpr()) is None


def test_non_expr_object_returns_none_without_raising():
    """A plain object without rex_call_operator() at all (e.g. a raw column
    name string mixed into the same select()/agg() call as an aggregate
    expression) is a type mismatch in the caller's input, not a DataFusion
    error-format question - it must return None, not raise
    DataFusionASTFormatError."""
    assert uf._get_datafusion_ast_string("id") is None  # type: ignore[arg-type]


def test_recognized_format_still_extracts_ast_string():
    """Sanity check: the existing, currently-valid format still extracts
    successfully and is unaffected by the hardening."""
    valid_expr = _RaisingExpr(
        f"{uf._DATAFUSION_AST_ERROR_PREFIX}: Alias(BinaryExpr {{ left: AggregateFunction(...), "
        'op: Multiply, right: Literal(Float64(0.2), None) }, name: "avg_qty")'
    )

    result = uf._get_datafusion_ast_string(valid_expr)

    assert result is not None
    assert "Alias" in result
    assert "BinaryExpr" in result
