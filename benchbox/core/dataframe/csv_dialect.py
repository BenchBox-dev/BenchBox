"""Core CSV-dialect predicates shared by the SQL and DataFrame surfaces.

This module lives in core (not platforms) so ``benchbox.core`` readers such
as ``data_loader`` can apply dialect rules without importing from
``benchbox.platforms``, which the ``utils < core < platforms < cli``
layering contract forbids. Platform adapters re-export these helpers from
``benchbox.platforms.dataframe.shared_loading``.
"""


def dialect_preserves_empty_strings(null_marker: str | None) -> bool:
    """True when the SQL dialect loads empty CSV fields as ``""``, not NULL.

    Only ``""`` maps empty fields to NULL (TPC ``.tbl``/``.dat``, JoinOrder,
    ...). Both ``None`` (no NULL conversion) and a non-empty sentinel (only
    that literal maps to NULL, e.g. ClickBench's ``__NULL__``) preserve empty
    strings, so DataFrame readers - which surface an empty text field as
    null/NaN regardless of dialect - must restore ``""`` post-read to match
    the SQL reference.
    """
    return null_marker != ""
