from __future__ import annotations

from threading import Lock
from typing import Callable, Generic, NamedTuple, TypeVar, cast

T = TypeVar("T")
_UNSET = object()


class CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int


class SingleFlightValueCache(Generic[T]):
    def __init__(self, loader: Callable[[], T]) -> None:
        self._loader = loader
        self._lock = Lock()
        self._value: T | object = _UNSET
        self._hits = 0
        self._misses = 0

    def __call__(self) -> T:
        with self._lock:
            if self._value is not _UNSET:
                self._hits += 1
                return cast(T, self._value)
            self._misses += 1
            self._value = self._loader()
            return cast(T, self._value)

    def cache_clear(self) -> None:
        with self._lock:
            self._value = _UNSET
            self._hits = 0
            self._misses = 0

    def cache_info(self) -> CacheInfo:
        with self._lock:
            return CacheInfo(
                hits=self._hits,
                misses=self._misses,
                maxsize=1,
                currsize=0 if self._value is _UNSET else 1,
            )
