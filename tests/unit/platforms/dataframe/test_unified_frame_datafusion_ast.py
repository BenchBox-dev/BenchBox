from __future__ import annotations

import pytest

from benchbox.platforms.dataframe import unified_frame as uf

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _RaisingExpr:
    def __init__(self, message: str) -> None:
        self._message = message

    def rex_call_operator(self) -> None:
        raise RuntimeError(self._message)


class _NonRaisingExpr:
    def rex_call_operator(self) -> str:
        return "some_operator_name"


def test_changed_error_format_raises_attributable_error():
    import datafusion

    changed_format_expr = _RaisingExpr("Unexpected internal error: Alias(BinaryExpr(AggregateFunction(...)))")

    with pytest.raises(uf.DataFusionASTFormatError) as excinfo:
        uf._get_datafusion_ast_string(changed_format_expr)

    message = str(excinfo.value)
    assert datafusion.__version__ in message
    assert "Unexpected internal error" in message
    assert uf._DATAFUSION_AST_ERROR_PREFIX in message


def test_missing_wrapper_text_entirely_raises():
    unrelated_expr = _RaisingExpr("SchemaError: no field named 'x'")

    with pytest.raises(uf.DataFusionASTFormatError):
        uf._get_datafusion_ast_string(unrelated_expr)


def test_genuinely_different_expression_shape_returns_none_not_raises():
    plain_column_expr = _RaisingExpr(f'{uf._DATAFUSION_AST_ERROR_PREFIX}: Column {{ relation: None, name: "x" }}')

    assert uf._get_datafusion_ast_string(plain_column_expr) is None


def test_non_raising_expression_returns_none():
    assert uf._get_datafusion_ast_string(_NonRaisingExpr()) is None


def test_non_expr_object_returns_none_without_raising():
    assert uf._get_datafusion_ast_string("id") is None


def test_recognized_format_still_extracts_ast_string():
    valid_expr = _RaisingExpr(
        f"{uf._DATAFUSION_AST_ERROR_PREFIX}: Alias(BinaryExpr {{ left: AggregateFunction(...), "
        'op: Multiply, right: Literal(Float64(0.2), None) }, name: "avg_qty")'
    )

    result = uf._get_datafusion_ast_string(valid_expr)

    assert result is not None
    assert "Alias" in result
    assert "BinaryExpr" in result
