from __future__ import annotations

import inspect
from functools import cache


@cache
def reader_accepts(reader: str, keyword: str) -> bool:
    import polars as pl

    return keyword in inspect.signature(getattr(pl, reader)).parameters


def csv_empty_string_option(preserve_empty_strings: bool) -> dict[str, bool]:
    if reader_accepts("scan_csv", "empty_string_is_null"):
        return {"empty_string_is_null": not preserve_empty_strings}
    return {"missing_utf8_is_empty_string": preserve_empty_strings}


def reader_rechunk_option(reader: str, rechunk: bool) -> dict[str, bool]:
    if reader_accepts(reader, "rechunk"):
        return {"rechunk": rechunk}
    return {}


def reader_rechunk_effective(rechunk: bool) -> bool:
    return rechunk and reader_accepts("scan_parquet", "rechunk")
