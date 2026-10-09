from __future__ import annotations

import random
from dataclasses import dataclass

SETUP_ENGINES = {"A": "default", "B": "in-memory", "C": "streaming"}
GIB = 1024**3


@dataclass(frozen=True)
class Cell:
    benchmark: str
    version: str
    setup: str

    @property
    def engine(self) -> str:
        return SETUP_ENGINES[self.setup]

    @property
    def cell_id(self) -> str:
        return f"{self.benchmark}/{self.version}/{self.setup}"


@dataclass(frozen=True)
class PolarsMatrixSpec:
    versions: tuple[str, ...]
    setup_versions: tuple[tuple[str, tuple[str, ...]], ...]
    benchmarks: tuple[tuple[str, float], ...]
    expected_queries: tuple[tuple[str, int], ...]
    rounds: int
    iterations: int
    thread_count: int
    cell_timeout_s: float
    rss_limit_gib: float
    swap_limit_gib: float
    safety_swap_gib: float
    reference_version: str
    mover_effect: float
    qualification_sha256: str
    platform: str = "polars-df"

    @property
    def baseline_version(self) -> str:
        return self.versions[0]

    @property
    def benchmark_ids(self) -> tuple[str, ...]:
        return tuple(benchmark for benchmark, _ in self.benchmarks)

    @property
    def scales(self) -> dict[str, float]:
        return dict(self.benchmarks)

    @property
    def query_counts(self) -> dict[str, int]:
        return dict(self.expected_queries)

    @property
    def setups(self) -> dict[str, tuple[str, ...]]:
        return dict(self.setup_versions)

    def cells(self) -> list[Cell]:
        return [
            Cell(benchmark, version, setup)
            for benchmark in self.benchmark_ids
            for setup, versions in self.setup_versions
            for version in versions
        ]

    @property
    def expected_invocations(self) -> int:
        per_benchmark = sum(len(versions) for _, versions in self.setup_versions)
        return self.rounds * per_benchmark * len(self.benchmarks)

    def snapshot(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "versions": list(self.versions),
            "setups": {setup: list(versions) for setup, versions in self.setup_versions},
            "engines": dict(SETUP_ENGINES),
            "benchmarks": [{"id": name, "scale": scale} for name, scale in self.benchmarks],
            "expected_queries": dict(self.expected_queries),
            "rounds": self.rounds,
            "iterations": self.iterations,
            "thread_count": self.thread_count,
            "cell_timeout_s": self.cell_timeout_s,
            "rss_limit_gib": self.rss_limit_gib,
            "swap_limit_gib": self.swap_limit_gib,
            "safety_swap_gib": self.safety_swap_gib,
            "reference_version": self.reference_version,
            "mover_effect": self.mover_effect,
            "qualification_sha256": self.qualification_sha256,
        }


def round_order(spec: PolarsMatrixSpec, shuffle_seed: int, round_index: int) -> list[Cell]:
    cells = spec.cells()
    random.Random(f"{shuffle_seed}:{round_index}").shuffle(cells)
    return cells


POLARS = PolarsMatrixSpec(
    versions=("1.31.0", "1.35.2", "1.40.1", "1.44.2", "2.0.0"),
    setup_versions=(
        ("A", ("1.31.0", "1.35.2", "1.40.1", "1.44.2", "2.0.0")),
        ("B", ("2.0.0",)),
        ("C", ("1.31.0", "1.40.1", "1.44.2", "2.0.0")),
    ),
    benchmarks=(("tpch", 10.0), ("tpcds", 10.0), ("clickbench", 10.0), ("ssb", 10.0)),
    expected_queries=(("tpch", 22), ("tpcds", 103), ("clickbench", 43), ("ssb", 13)),
    rounds=3,
    iterations=1,
    thread_count=10,
    cell_timeout_s=1800.0,
    rss_limit_gib=14.0,
    swap_limit_gib=1.0,
    safety_swap_gib=6.0,
    reference_version="1.44.2",
    mover_effect=0.10,
    qualification_sha256="da8ea047afdbc880177f6a295dc8d0e9afd1b95a3f044d906e9c6a26b43d2580",
)
