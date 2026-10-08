from __future__ import annotations

import re
from dataclasses import dataclass

PRERELEASE_RE = re.compile(r"\.(?:dev\d+|rc\d+|a\d+|b\d+)$", re.IGNORECASE)


def is_prerelease(version: str) -> bool:
    return bool(PRERELEASE_RE.search(version))


def scale_token(scale: float) -> str:
    return str(int(scale)) if scale == int(scale) else str(scale).replace(".", "")


def scale_argument(scale: float) -> str:
    return str(int(scale) if scale == int(scale) else scale)


def version_token(version: str) -> str:
    return version.replace(".", "_")


@dataclass(frozen=True)
class MatrixSpec:
    engine: str
    display_name: str
    platform: str
    driver_package: str
    versions: tuple[str, ...]
    benchmarks: tuple[tuple[str, float], ...]
    repetitions: int
    compression: str
    required_validation: str
    cleared_database_suffixes: tuple[str, ...] = ()
    driver_option_for_prereleases: bool = False

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
    def analysis_stem(self) -> str:
        return f"{self.engine}-version-matrix"

    @property
    def speedup_field(self) -> str:
        return f"speedup_vs_{self.baseline_version}"

    @property
    def expected_benchmark_runs(self) -> int:
        return len(self.benchmarks) + len(self.versions) * len(self.benchmarks) * (1 + self.repetitions)

    def driver_platform_options(self, version: str | None) -> list[str]:
        if version is None or (is_prerelease(version) and not self.driver_option_for_prereleases):
            return []
        return ["--platform-option", f"driver_version={version}"]

    def bundle_filename(self, benchmark: str, version: str) -> str:
        scale = scale_token(self.scales[benchmark])
        return f"{benchmark}_sf{scale}_{self.engine}_v{version_token(version)}_median.json"


DUCKDB = MatrixSpec(
    engine="duckdb",
    display_name="DuckDB",
    platform="duckdb",
    driver_package="duckdb",
    versions=("1.0.0", "1.1.3", "1.2.2", "1.3.2", "1.4.4", "1.5.5", "1.6.0.dev365"),
    benchmarks=(("tpch", 10.0), ("tpcds", 10.0), ("clickbench", 10.0), ("ssb", 10.0)),
    repetitions=3,
    compression="zstd:3",
    required_validation="passed",
    cleared_database_suffixes=(".duckdb", ".wal"),
)

SPECS: dict[str, MatrixSpec] = {spec.engine: spec for spec in (DUCKDB,)}
