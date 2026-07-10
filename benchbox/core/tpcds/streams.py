"""TPC-DS Stream and Permutation Support

This module implements the stream generation and permutation functionality
that matches the original C implementation for concurrent query execution.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Query template IDs that expand to two SQL statements ('a' and 'b' variants).
# Shared by the home-grown permutation path (_get_query_variants) and the
# official dsqgen -STREAMS batch parser (_parse_dsqgen_stream_log) below.
MULTI_PART_QUERY_IDS = frozenset({14, 23, 24, 39})


class PermutationMode(Enum):
    """Permutation modes for query ordering."""

    SEQUENTIAL = "sequential"  # Queries in order 1, 2, 3, ...
    RANDOM = "random"  # Queries in random order
    TPCDS_STANDARD = "tpcds"  # TPC-DS standard permutation algorithm


@dataclass
class QueryStreamConfig:
    """Configuration for a query stream."""

    stream_id: int
    query_ids: list[int]
    permutation_mode: PermutationMode
    seed: Optional[int] = None
    parameter_seed: Optional[int] = None


@dataclass
class StreamQuery:
    """Represents a single query in a stream."""

    stream_id: int
    position: int
    query_id: int
    variant: Optional[str] = None  # 'a' or 'b' for multi-query templates
    parameters: Optional[dict[str, Any]] = None
    sql: Optional[str] = None


class TPCDSPermutationGenerator:
    """Generates permutations using TPC-DS standard algorithms."""

    def __init__(self, seed: Optional[int] = None) -> None:
        """Initialize with optional seed for reproducible permutations."""
        self.seed = seed
        if seed is not None:
            random.seed(seed)

    def generate_permutation(self, items: list[int], mode: PermutationMode) -> list[int]:
        """Generate a permutation of items based on the specified mode."""
        if mode == PermutationMode.SEQUENTIAL:
            return sorted(items)
        elif mode == PermutationMode.RANDOM:
            return self._random_permutation(items)
        elif mode == PermutationMode.TPCDS_STANDARD:
            return self._tpcds_permutation(items)
        else:
            raise ValueError(f"Unknown permutation mode: {mode}")

    def _random_permutation(self, items: list[int]) -> list[int]:
        """Generate a random permutation."""
        permuted = items.copy()
        random.shuffle(permuted)
        return permuted

    def _tpcds_permutation(self, items: list[int]) -> list[int]:
        """Generate permutation using TPC-DS standard algorithm."""
        n = len(items)
        if n <= 1:
            return items.copy()

        # Create a copy to work with
        permuted = items.copy()

        # Use a deterministic but pseudo-random permutation
        for i in range(n - 1, 0, -1):
            # Generate a pseudo-random index based on position and seed
            if self.seed is not None:
                # Use seed to generate deterministic permutation
                j = (self.seed + i * 17 + i * i * 7) % (i + 1)
            else:
                j = random.randint(0, i)

            # Swap elements
            permuted[i], permuted[j] = permuted[j], permuted[i]

        return permuted


class TPCDSStreamManager:
    """Manages multiple query streams with different parameter sets."""

    PERMUTATION_SEED = 19620718

    def __init__(self, query_manager, stream_configs: Optional[list[QueryStreamConfig]] = None) -> None:
        """Initialize stream manager."""
        self.query_manager = query_manager
        self.stream_configs = stream_configs or []
        self.streams: dict[int, list[StreamQuery]] = {}
        self.permutation_generator = TPCDSPermutationGenerator()

    def add_stream(self, config: QueryStreamConfig) -> None:
        """Add a stream configuration."""
        self.stream_configs.append(config)

    def generate_streams(self) -> dict[int, list[StreamQuery]]:
        """Generate all configured streams."""
        self.streams = {}

        for config in self.stream_configs:
            self.streams[config.stream_id] = self._generate_single_stream(config)

        return self.streams

    def _generate_single_stream(self, config: QueryStreamConfig) -> list[StreamQuery]:
        """Generate a single query stream."""
        # Set seeds for reproducible generation
        if config.seed is not None:
            self.permutation_generator.seed = config.seed

        if config.parameter_seed is not None:
            random.seed(config.parameter_seed)

        # Generate permutation of query IDs
        permuted_queries = self.permutation_generator.generate_permutation(config.query_ids, config.permutation_mode)

        # Create stream queries
        stream_queries = []
        for position, query_id in enumerate(permuted_queries):
            # Handle multi-query templates
            variants = self._get_query_variants(query_id)

            for variant in variants:
                stream_query = StreamQuery(
                    stream_id=config.stream_id,
                    position=position,
                    query_id=query_id,
                    variant=variant,
                )

                # Generate parameters for this query instance
                try:
                    if variant:
                        # For multi-query templates like 14a, 14b, use the base query ID
                        # and pass variant information separately if supported
                        if hasattr(self.query_manager, "get_query") and hasattr(
                            self.query_manager.get_query, "__code__"
                        ):
                            # Check if the method supports variant parameter
                            if "variant" in self.query_manager.get_query.__code__.co_varnames:
                                stream_query.sql = self.query_manager.get_query(
                                    query_id,
                                    seed=config.parameter_seed,
                                    variant=variant,
                                )
                            else:
                                # Fallback: try with base query ID and add comment
                                base_query = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                                stream_query.sql = f"-- Query {query_id}{variant}\\n{base_query}"
                        else:
                            # Simple fallback
                            base_query = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                            stream_query.sql = f"-- Query {query_id}{variant}\\n{base_query}"
                    else:
                        # Standard single query
                        stream_query.sql = self.query_manager.get_query(query_id, seed=config.parameter_seed)
                except Exception as e:
                    # Fallback to a simple query comment if generation fails
                    variant_suffix = variant if variant else ""
                    stream_query.sql = (
                        f"-- Query {query_id}{variant_suffix} (generation failed: {e})\\nSELECT 1 AS placeholder_query;"
                    )

                stream_queries.append(stream_query)

        return stream_queries

    def _get_query_variants(self, query_id: int) -> list[Optional[str]]:
        """Get variants for a query (a, b, or None for single queries)."""
        if query_id in MULTI_PART_QUERY_IDS:
            return ["a", "b"]
        else:
            return [None]

    def get_stream(self, stream_id: int) -> Optional[list[StreamQuery]]:
        """Get a specific stream by ID."""
        return self.streams.get(stream_id)

    def get_stream_summary(self, stream_id: int) -> Optional[dict[str, Any]]:
        """Get summary information for a stream."""
        stream = self.get_stream(stream_id)
        if stream is None:
            return None

        unique_queries = set()
        for sq in stream:
            query_key = f"{sq.query_id}{sq.variant or ''}"
            unique_queries.add(query_key)

        return {
            "stream_id": stream_id,
            "total_queries": len(stream),
            "unique_queries": len(unique_queries),
            "query_list": [f"{sq.query_id}{sq.variant or ''}" for sq in stream],
        }


def create_standard_streams(
    query_manager,
    num_streams: int = 2,
    query_range: tuple[int, int] = (1, 99),
    base_seed: int = 42,
    query_ids: Optional[list[int]] = None,
) -> TPCDSStreamManager:
    """Create standard TPC-DS streams with default configuration.

    Args:
        query_manager: The query manager to use for generating queries.
        num_streams: Number of streams to generate.
        query_range: Range of query IDs to include (start, end inclusive).
            Ignored if query_ids is provided.
        base_seed: Base seed for reproducible permutations.
        query_ids: Explicit list of query IDs to use. If provided, query_range is ignored.
            This is useful for benchmarks like TPC-DS OBT that have a subset of queries.

    Returns:
        TPCDSStreamManager configured with the specified streams.
    """
    manager = TPCDSStreamManager(query_manager)

    # Use explicit query_ids if provided, otherwise generate from range
    if query_ids is not None:
        query_ids = sorted(query_ids)
    else:
        query_ids = list(range(query_range[0], query_range[1] + 1))

    # Create stream configurations
    for stream_id in range(num_streams):
        config = QueryStreamConfig(
            stream_id=stream_id,
            query_ids=query_ids,
            permutation_mode=PermutationMode.TPCDS_STANDARD,
            seed=base_seed + stream_id,
            parameter_seed=base_seed + stream_id + 1000,
        )
        manager.add_stream(config)

    return manager


class DSQGenStreamsError(Exception):
    """Raised when the official dsqgen ``-STREAMS`` batch generation fails.

    This is distinct from ``benchbox.core.tpcds.c_tools.TPCDSError`` (the
    single-template dsqgen error type) to keep the batch -STREAMS path fully
    self-contained in this module.
    """


# --- Official dsqgen -STREAMS batch generation ------------------------------
#
# dsqgen (the official TPC-DS query generator binary) has a `-STREAMS N` mode
# that, given `-INPUT templates.lst`, generates ALL N throughput streams in a
# single invocation: one `query_<n>.sql` file per stream containing the
# official per-stream query ORDERING with the official per-stream
# substitution PARAMETERS already applied, plus (with `-LOG <file>`) a
# parameter log that records the `Template: queryNN.tpl` sequence dsqgen used
# for each stream -- the ground truth for ordering, since the SQL output
# itself carries no per-query markers.
#
# This supersedes TPCDSPermutationGenerator/TPCDSStreamManager for the
# throughput-test path: that Python permutation never matched dsqgen's
# per-stream RNG state, and the single-template dsqgen calls used previously
# reset dsqgen's RNG per query, which does not reproduce a real stream's
# sequential RNG consumption. TPCDSPermutationGenerator/create_standard_streams
# remain in place, unchanged, for power/dry-run/OBT/dataframe callers that
# use the single-query get_query() path (see must_preserve in
# tpcds-throughput-permutation-compliance TODO).

_DSQGEN_BEGIN_STREAM_RE = re.compile(r"^BEGIN STREAM\s+(\d+)\s*$", re.IGNORECASE)
_DSQGEN_TEMPLATE_RE = re.compile(r"^Template:\s*query(\d+)([ab]?)\.tpl\s*$", re.IGNORECASE)
_DSQGEN_STATEMENT_SPLIT_RE = re.compile(r"(?<=;)\n+(?=\S)")


def _resolve_dsqgen_binary_and_templates() -> tuple[Path, Path]:
    """Resolve the dsqgen binary directory and templates directory.

    Delegates to the existing TPC-DS path-resolution helper in
    ``benchbox.core.tpcds.c_tools`` (imported, not modified -- that module is
    out of scope for the dsqgen -STREAMS TODO) so the batch path and the
    single-template path always agree on which binary/templates to use.
    """
    from benchbox.core.tpcds.c_tools import _resolve_tpcds_tool_and_template_paths

    return _resolve_tpcds_tool_and_template_paths()


def _stage_dsqgen_streams_workdir(temp_path: Path, templates_dir: Path, tools_dir: Path, dsqgen_path: Path) -> dict:
    """Stage templates + variants + distribution files for a dsqgen -STREAMS run.

    Mirrors the staging performed by DSQGenBinary._stage_dsqgen_workdir for
    the single-template path (c_tools.py), reimplemented here since that
    method lives in a file out of scope for this change.
    """
    shutil.copytree(templates_dir, temp_path / "q")
    variants_src = templates_dir.parent / "query_variants"
    if variants_src.exists():
        shutil.copytree(variants_src, temp_path / "query_variants")

    env = os.environ.copy()
    env["DSS_QUERY"] = str(temp_path)

    dsqgen_dir = Path(dsqgen_path).parent
    for dist_file in ("tpcds.dst", "tpcds.idx"):
        if (temp_path / dist_file).exists():
            continue
        for candidate_dir in (dsqgen_dir, tools_dir):
            dist_src = candidate_dir / dist_file
            if dist_src.exists():
                shutil.copy2(dist_src, temp_path / dist_file)
                break

    return env


def _parse_dsqgen_stream_log(log_text: str) -> dict[int, list[tuple[int, Optional[str]]]]:
    """Parse dsqgen's ``-LOG`` output into official per-stream ordering.

    The log lists ``BEGIN STREAM <n>`` markers followed by one
    ``Template: query<NN>.tpl`` line per query position, in official
    generation order. Multi-part templates (14, 23, 24, 39) appear once here
    but expand to two SQL statements ('a' and 'b') in the corresponding
    ``query_<n>.sql`` output file, so they are expanded to two ordering
    entries here to line up 1:1 with the parsed SQL statements.
    """
    streams: dict[int, list[tuple[int, Optional[str]]]] = {}
    current_stream: Optional[int] = None

    for line in log_text.splitlines():
        stripped = line.strip()

        begin_match = _DSQGEN_BEGIN_STREAM_RE.match(stripped)
        if begin_match:
            current_stream = int(begin_match.group(1))
            streams[current_stream] = []
            continue

        template_match = _DSQGEN_TEMPLATE_RE.match(stripped)
        if template_match and current_stream is not None:
            query_id = int(template_match.group(1))
            if query_id in MULTI_PART_QUERY_IDS:
                streams[current_stream].append((query_id, "a"))
                streams[current_stream].append((query_id, "b"))
            else:
                streams[current_stream].append((query_id, None))

    return streams


def _split_dsqgen_stream_sql(sql_text: str) -> list[str]:
    """Split a dsqgen -STREAMS per-stream SQL file into individual statements.

    Empirically (see docs/benchmarks/tpc-ds.md), dsqgen's -STREAMS output
    contains exactly one semicolon-terminated statement per query position
    (two for multi-part templates 14/23/24/39), with the terminating ``;``
    always the last character of its line and no other statement text
    following on that line. Splitting on ``;`` immediately followed by a
    newline and further non-whitespace therefore reconstructs exact
    per-query boundaries without needing explicit markers (dsqgen emits
    none in -STREAMS mode).
    """
    cleaned = sql_text.strip()
    if not cleaned:
        return []
    return [stmt.strip() for stmt in _DSQGEN_STATEMENT_SPLIT_RE.split(cleaned) if stmt.strip()]


def generate_dsqgen_streams(
    num_streams: int,
    scale_factor: float = 1.0,
    seed: Optional[int] = None,
    dialect: str = "netezza",
    timeout: int = 300,
) -> dict[int, list[StreamQuery]]:
    """Generate all TPC-DS throughput streams via one official dsqgen -STREAMS pass.

    Unlike TPCDSPermutationGenerator/create_standard_streams (a Python
    re-implementation of query ordering) and the single-template
    DSQGenBinary.generate() calls used for get_query() (which reset dsqgen's
    RNG per query and can't reproduce a stream's true sequential RNG
    consumption), this shells out to dsqgen's own `-STREAMS N` mode, which
    produces the official per-stream query ORDERING and per-stream
    substitution PARAMETERS in a single deterministic pass.

    Args:
        num_streams: Number of concurrent throughput streams to generate.
        scale_factor: TPC-DS scale factor (GB) passed to dsqgen -SCALE.
        seed: RNG seed for the whole batch (dsqgen -RNGSEED). Reproducible
            for a fixed (num_streams, seed) pair.
        dialect: dsqgen base template dialect (netezza/ansi/oracle/db2/
            sqlserver). This is NOT the target execution platform -- callers
            translate the returned raw SQL to the target platform dialect
            the same way get_query() does (translate_query_text +
            per-platform overrides), so the actual target platform never
            needs its own dsqgen dialect file.
        timeout: subprocess timeout in seconds.

    Returns:
        Mapping of stream_id (0-indexed) -> ordered list of StreamQuery, each
        with ``.sql`` populated with dsqgen's raw generated SQL text (still
        in ``dialect``, not yet translated to a target platform).

    Reproducibility note:
        Per-stream ORDERING is fully deterministic for a fixed
        (num_streams, seed). Per-query substitution PARAMETERS are
        deterministic for 98 of the 99 templates; query46 is the sole
        exception -- its 5-city IN-list is built by a dsqgen-internal
        ``ulist(random(1, rowcount("active_cities", "store"), uniform), 5)``
        substitution that is not reproducible even with a fixed -RNGSEED.
        This is a property of the bundled reference dsqgen binary (verified
        directly, serially and concurrently), not of this integration, and
        it does not affect query46's stable ordering slot.

    Raises:
        ValueError: If num_streams < 1.
        DSQGenStreamsError: If dsqgen fails, times out, or its output can't
            be parsed into a consistent per-stream ordering.
    """
    if num_streams < 1:
        raise ValueError(f"num_streams must be >= 1, got {num_streams}")

    tools_dir, templates_dir = _resolve_dsqgen_binary_and_templates()
    dsqgen_path = tools_dir / ("dsqgen.exe" if sys.platform == "win32" else "dsqgen")
    if not dsqgen_path.exists():
        raise DSQGenStreamsError(f"dsqgen binary not found at {dsqgen_path}")
    if not templates_dir.exists():
        raise DSQGenStreamsError(f"TPC-DS query templates not found at {templates_dir}")

    opt = "/" if sys.platform == "win32" else "-"
    log_file_name = "stream_params.log"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        env = _stage_dsqgen_streams_workdir(temp_path, templates_dir, tools_dir, dsqgen_path)

        cmd = [
            str(dsqgen_path),
            f"{opt}STREAMS",
            str(num_streams),
            f"{opt}INPUT",
            "q/templates.lst",
            f"{opt}DIRECTORY",
            "q",
            f"{opt}SCALE",
            str(scale_factor),
            f"{opt}DIALECT",
            dialect,
            f"{opt}OUTPUT_DIR",
            ".",
            f"{opt}LOG",
            log_file_name,
            f"{opt}VERBOSE",
            "Y",
        ]
        if seed is not None:
            cmd.extend([f"{opt}RNGSEED", str(seed)])

        try:
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise DSQGenStreamsError(f"dsqgen -STREAMS {num_streams} timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            raise DSQGenStreamsError(f"dsqgen binary not found at {dsqgen_path}") from exc

        if result.returncode != 0:
            raise DSQGenStreamsError(
                f"dsqgen -STREAMS {num_streams} failed (exit {result.returncode}): "
                f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
            )

        log_path = temp_path / log_file_name
        if not log_path.exists():
            raise DSQGenStreamsError(
                f"dsqgen -STREAMS did not produce the expected log file {log_path}; stdout={result.stdout.strip()!r}"
            )
        ordering = _parse_dsqgen_stream_log(log_path.read_text(encoding="utf-8"))

        streams: dict[int, list[StreamQuery]] = {}
        for stream_id in range(num_streams):
            sql_path = temp_path / f"query_{stream_id}.sql"
            if not sql_path.exists():
                raise DSQGenStreamsError(f"dsqgen -STREAMS did not produce the expected stream file {sql_path}")

            statements = _split_dsqgen_stream_sql(sql_path.read_text(encoding="utf-8"))
            stream_order = ordering.get(stream_id, [])

            if len(statements) != len(stream_order):
                raise DSQGenStreamsError(
                    f"dsqgen -STREAMS stream {stream_id}: parsed {len(statements)} SQL statements but "
                    f"{len(stream_order)} query positions from the -LOG ordering -- dsqgen's output format "
                    "may have changed; refusing to guess a mapping."
                )

            stream_queries: list[StreamQuery] = []
            for position, ((query_id, variant), sql_text) in enumerate(zip(stream_order, statements)):
                stream_queries.append(
                    StreamQuery(
                        stream_id=stream_id,
                        position=position,
                        query_id=query_id,
                        variant=variant,
                        sql=sql_text,
                    )
                )
            streams[stream_id] = stream_queries

        return streams


# Keep the original class names for backwards compatibility
TPCDSStreams = TPCDSStreamManager
TPCDSStreamRunner = TPCDSStreamManager
