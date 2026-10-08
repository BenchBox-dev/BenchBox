from typing import ClassVar


class BenchmarkPhase:
    POWER: ClassVar[str] = "power"
    THROUGHPUT: ClassVar[str] = "throughput"
    MAINTENANCE: ClassVar[str] = "maintenance"


__all__ = ["BenchmarkPhase"]
