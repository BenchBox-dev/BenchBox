from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class QueryManager(Protocol):
    def get_all_queries(self) -> dict[str, str]: ...


def get_queries_with_translation(
    query_manager: QueryManager,
    dialect: str | None,
    translate_query_text: Callable[[str, str], str],
) -> dict[str, str]:
    queries = query_manager.get_all_queries()
    if not dialect:
        return queries

    return {query_id: translate_query_text(query_text, dialect) for query_id, query_text in queries.items()}
