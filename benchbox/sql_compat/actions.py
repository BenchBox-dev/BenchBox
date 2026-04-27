"""CompatAction enum - the eight actions a compatibility rule can produce."""

from __future__ import annotations

from enum import Enum


class CompatAction(str, Enum):
    BLOCK_BENCHMARK = "block_benchmark"
    SKIP_QUERY = "skip_query"
    SELECT_VARIANT = "select_variant"
    REWRITE_QUERY = "rewrite_query"
    REWRITE_DDL = "rewrite_ddl"
    SET_SESSION_POLICY = "set_session_policy"
    POST_TRANSLATE = "post_translate"
    NATIVE = "native"
