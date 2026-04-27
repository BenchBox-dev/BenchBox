"""Vector search benchmark data generator.

Generates synthetic unit-normalised float32 embeddings using a seeded
NumPy RNG so results are fully reproducible across runs.

Scale factor → vector count:
  SF=0.01  →   10,000 vectors
  SF=0.1   →  100,000 vectors
  SF=1     →1,000,000 vectors
  SF=10    →10,000,000 vectors

The generator also produces a fixed set of 100 pre-generated query
vectors (stored in the vector_queries table) that are used by benchmark
queries. This set is independent of the scale factor so query SQL remains
stable across scales.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Union

import numpy as np

from benchbox.core.manifest_utils import write_generator_manifest
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin

try:
    from cloudpathlib import CloudPath

    PathLike = Union[Path, CloudPath]
except ImportError:
    PathLike = Path  # type: ignore[misc,assignment]

# Number of query vectors pre-generated regardless of scale factor.
NUM_QUERY_VECTORS = 100

# Base corpus size at SF=1.0.
BASE_VECTORS = 1_000_000

# Number of synthetic categories for filtered-search queries.
NUM_CATEGORIES = 10

# Random seed for reproducibility.
_SEED = 42


def _generate_unit_vectors(n: int, dim: int, rng: np.random.Generator) -> np.ndarray:
    """Return *n* unit-normalised float32 vectors of dimension *dim*."""
    vecs = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms


def _array_to_csv(arr: np.ndarray) -> str:
    """Format a 1-D float32 array as a DuckDB list literal ``[v1,v2,…]``."""
    vals = ",".join(f"{v:.6g}" for v in arr)
    return f"[{vals}]"


class VectorSearchDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for vector search benchmark data.

    Attributes:
        scale_factor: Controls corpus size (SF=1 → 1 M vectors).
        output_dir: Directory to write generated CSV files.
        dimensions: Embedding dimensionality (default 128).
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        *,
        dimensions: int = 128,
        verbose: int | bool = 0,
        quiet: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")
        if dimensions < 1:
            raise ValueError(f"dimensions must be >= 1, got {dimensions}")

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()
        self.dimensions = dimensions

        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.quiet = bool(quiet)

        self._manifest_row_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:
        """Generate vector search data files.

        Args:
            tables: Optional subset of tables to generate.  If *None*, all
                    tables are generated (``vectors`` and ``vector_queries``).

        Returns:
            Dict mapping table name to file path string.
        """
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_local(output_dir, tables),
            False,
        )
        self._write_manifest(table_paths)
        return {t: str(p) for t, p in table_paths.items()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_local(
        self,
        output_dir: Path,
        tables: list[str] | None = None,
    ) -> dict[str, str]:
        if tables is None:
            tables = ["vectors", "vector_queries"]

        original_dir = self.output_dir
        self.output_dir = output_dir
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            rng = np.random.default_rng(_SEED)
            file_paths: dict[str, Path] = {}
            self._manifest_row_counts = {}

            if "vectors" in tables:
                file_paths["vectors"] = self._generate_vectors(output_dir, rng)
            if "vector_queries" in tables:
                # Use a separate RNG stream to keep query vectors stable
                # regardless of whether corpus vectors were generated.
                query_rng = np.random.default_rng(_SEED + 1)
                file_paths["vector_queries"] = self._generate_query_vectors(output_dir, query_rng)

            return {t: str(p) for t, p in file_paths.items()}
        finally:
            self.output_dir = original_dir

    def _generate_vectors(self, output_dir: Path, rng: np.random.Generator) -> Path:
        """Write the main corpus vectors CSV."""
        num_vectors = max(1, int(BASE_VECTORS * self.scale_factor))
        filename = self.get_compressed_filename("vectors.csv")
        file_path = output_dir / filename

        categories = [f"category_{i:02d}" for i in range(1, NUM_CATEGORIES + 1)]

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")
            writer.writerow(["id", "embedding", "category", "doc_id"])

            batch = 10_000
            written = 0
            for batch_start in range(0, num_vectors, batch):
                batch_size = min(batch, num_vectors - batch_start)
                vecs = _generate_unit_vectors(batch_size, self.dimensions, rng)
                for i in range(batch_size):
                    row_id = batch_start + i + 1
                    cat = categories[row_id % NUM_CATEGORIES]
                    doc_id = f"doc_{row_id}"
                    writer.writerow([row_id, _array_to_csv(vecs[i]), cat, doc_id])
                    written += 1

        self._manifest_row_counts["vectors"] = written
        return file_path

    def _generate_query_vectors(self, output_dir: Path, rng: np.random.Generator) -> Path:
        """Write the query vectors CSV (always NUM_QUERY_VECTORS rows)."""
        filename = self.get_compressed_filename("vector_queries.csv")
        file_path = output_dir / filename

        vecs = _generate_unit_vectors(NUM_QUERY_VECTORS, self.dimensions, rng)

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")
            writer.writerow(["query_id", "query_vector"])
            for i in range(NUM_QUERY_VECTORS):
                writer.writerow([i + 1, _array_to_csv(vecs[i])])

        self._manifest_row_counts["vector_queries"] = NUM_QUERY_VECTORS
        return file_path

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        write_generator_manifest(
            self, "vector_search", table_paths, self._manifest_row_counts, metadata={"csv_has_header": True}
        )
