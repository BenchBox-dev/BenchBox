"""Ultra-simplified TPC-DS query generation using templates with comprehensive SQL cleaning.

Provides minimum TPC-DS query interface by processing template files with parameter substitution. Uses the same approach as the queries.py module for consistency.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Optional, Union

from benchbox.utils.tpc_compilation import (
    CompilationStatus,
    ensure_tpc_binaries,
    get_tpc_compiler,
)


def _resolve_tpcds_tool_and_template_paths() -> tuple[Path, Path]:
    """Determine the preferred tool and template directories.

    Returns:
        Tuple of (tools_path, templates_path) where:
        - tools_path: Directory containing platform-specific binaries (dsdgen, dsqgen)
          and data files (tpcds.idx, tpcds.dst)
        - templates_path: Directory containing SQL query templates (.tpl files)

    Architecture Note:
        TPC-DS binaries are platform-specific (ARM64, x86-64, Windows) and must be
        compiled for each architecture. However, query templates are plain text files
        that are identical across all platforms.

        To eliminate maintenance burden and prevent template divergence, we:
        1. Use platform-specific binaries from _binaries/tpc-ds/{platform}/
        2. Use centralized templates from _binaries/tpc-ds/templates/query_templates/
           (bundled inside the package for wheel installs)

        This approach is safe because:
        - dsqgen uses the DSS_QUERY environment variable to locate templates
        - Templates and binaries don't need to be co-located
        - Data files (tpcds.idx, tpcds.dst) are copied from binary location at runtime
    """
    from benchbox.utils.tpc_compilation import get_tpc_templates_dir

    compiler = get_tpc_compiler(auto_compile=False)

    # Resolve templates: bundled package first, then _sources/ fallback
    templates_root = get_tpc_templates_dir("tpc-ds")
    templates_path = templates_root / "query_templates"

    # Use platform-specific binaries from precompiled bundle when available
    if compiler.precompiled_base:
        platform_str = compiler._get_platform_string()
        bundle_root = compiler.precompiled_base / "tpc-ds" / platform_str
        if bundle_root.exists():
            return bundle_root, templates_path

    # Fallback to source tools if no precompiled binaries
    import benchbox

    repo_root = Path(benchbox.__file__).parent.parent
    tools_path = repo_root / "_sources/tpc-ds/tools"
    return tools_path, templates_path


class TPCDSError(Exception):
    """Exception for TPC-DS operations."""


class TPCDSCTools:
    """Coordinator class for TPC-DS C tools (dsqgen, dsdgen, etc.)."""

    def __init__(self) -> None:
        """Initialize TPC-DS C tools."""
        self.tools_path, self.templates_path = _resolve_tpcds_tool_and_template_paths()

        # Individual tool binaries
        self.dsdgen_path = self.tools_path / "dsdgen"  # Data generation
        self.dsqgen_path = self.tools_path / "dsqgen"  # Query generation

        # Initialize query generator
        self.query_generator = DSQGenBinary()

    def is_available(self) -> bool:
        """Check if TPC-DS C tools are available."""
        return self.tools_path.exists() and self.templates_path.exists() and self.dsqgen_path.exists()

    def generate_query(self, query_id: int, **kwargs: Union[str, int, float]) -> str:
        """Generate a query using dsqgen."""
        return self.query_generator.generate(query_id, **kwargs)

    def get_tools_info(self) -> dict[str, Any]:
        """Get information about available TPC-DS tools."""
        # Check actual binary availability through the compilation system
        dsdgen_results = ensure_tpc_binaries(["dsdgen"])
        dsqgen_results = ensure_tpc_binaries(["dsqgen"])

        dsdgen_status = dsdgen_results.get("dsdgen")
        dsqgen_status = dsqgen_results.get("dsqgen")

        dsdgen_available = dsdgen_status and dsdgen_status.status in [
            CompilationStatus.PRECOMPILED,
            CompilationStatus.SUCCESS,
        ]
        dsqgen_available = dsqgen_status and dsqgen_status.status in [
            CompilationStatus.PRECOMPILED,
            CompilationStatus.SUCCESS,
        ]

        return {
            "tools_path": str(self.tools_path),
            "templates_path": str(self.templates_path),
            "available_tools": [
                {
                    "name": "dsdgen",
                    "path": str(dsdgen_status.binary_path) if dsdgen_available else str(self.dsdgen_path),
                    "exists": dsdgen_available,
                },
                {
                    "name": "dsqgen",
                    "path": str(dsqgen_status.binary_path) if dsqgen_available else str(self.dsqgen_path),
                    "exists": dsqgen_available,
                },
            ],
            "dsqgen_available": dsqgen_available,
            "templates_available": self.templates_path.exists(),
        }

    def get_available_tables(self) -> list[str]:
        """Get list of available TPC-DS tables.

        Returns:
            List of TPC-DS table names
        """
        from benchbox.core.tpcds.constants import TPCDS_TABLE_NAMES

        return list(TPCDS_TABLE_NAMES)


class DSQGenBinary:
    """Direct interface to dsqgen binary with proper parameter generation."""

    def __init__(self) -> None:
        """Find dsqgen binary or templates, failing if neither available."""
        tools_path, templates_path = _resolve_tpcds_tool_and_template_paths()
        self.templates_dir = self._find_templates_or_fail(templates_path)
        self.tools_dir = tools_path
        self.dsqgen_path = self._find_dsqgen_or_fail()  # Required binary
        self._parameter_cache = {}  # Cache for parameter generation
        self._query_cache = {}  # Cache for generated queries
        self._supported_dialects = self._detect_supported_dialects()

    def generate(
        self,
        query_id: Union[int, str],
        *,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        stream_id: Optional[int] = None,
        dialect: str = "netezza",
    ) -> str:
        """Generate query using dsqgen binary with proper parameter generation.

        Args:
            query_id: TPC-DS query number (1-99, or string like '14a', '23b')
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations (GB)
            stream_id: Stream identifier for multi-stream execution
            dialect: SQL dialect for output (netezza, ansi, sqlserver, etc.)

        Returns:
            Clean SQL query string

        Raises:
            TPCDSError: If dsqgen binary execution fails
            ValueError: If query_id is invalid
            TypeError: If types are incorrect
        """
        # Parse query ID to handle variants like '14a', '23b'
        try:
            base_query_id, variant = self._parse_query_id(query_id)
        except (ValueError, TypeError) as e:
            # Convert to ValueError to match TPC-H patterns
            raise ValueError(f"Invalid query_id: {e}") from e

        if not (1 <= base_query_id <= 99):
            raise ValueError(f"Query ID must be 1-99, got {base_query_id}")

        # Validate and normalize dialect
        dialect = self._validate_dialect(dialect)

        # Check cache first
        cache_key = self._get_cache_key(base_query_id, variant, seed, scale_factor, stream_id, dialect)
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        # Generate parameter variations for this query
        param_variations = self._generate_parameter_variations(seed, stream_id, scale_factor)
        self._parameter_cache[cache_key] = param_variations

        result = self._generate_with_binary(
            base_query_id,
            variant=variant,
            seed=seed,
            scale_factor=scale_factor,
            stream_id=stream_id,
            dialect=dialect,
        )

        # Cache the result
        self._query_cache[cache_key] = result
        return result

    def _resolve_template_arg(self, query_id: int, variant: Optional[str], is_multi_part: bool) -> str:
        """Pick the template path argument dsqgen should use."""
        template_name = f"query{query_id}.tpl" if is_multi_part else f"query{query_id}{variant or ''}.tpl"
        template_rel = f"query_templates/{template_name}"
        try:
            variants_dir = self.templates_dir.parent / "query_variants"
            main_path = self.templates_dir / template_name
            alt_path = variants_dir / template_name
            if alt_path.exists() and (variant and not is_multi_part) or (not main_path.exists()):
                template_rel = f"query_variants/{template_name}"
        except Exception:
            template_rel = f"query_templates/{template_name}"

        if "query_variants/" in template_rel:
            return f"../{template_rel}"
        return template_rel.replace("query_templates/", "")

    def _build_dsqgen_cmd(
        self,
        query_id: int,
        variant: Optional[str],
        seed: Optional[int],
        scale_factor: float,
        dialect: str,
        is_multi_part: bool,
    ) -> tuple[list[str], str]:
        """Build the dsqgen command and return (cmd, opt_prefix)."""
        _opt = "/" if sys.platform == "win32" else "-"
        template_arg = self._resolve_template_arg(query_id, variant, is_multi_part)

        cmd = [str(self.dsqgen_path)]
        cmd.extend([f"{_opt}TEMPLATE", template_arg])
        cmd.extend([f"{_opt}DIALECT", dialect])
        cmd.extend([f"{_opt}SCALE", str(scale_factor)])
        if seed is not None:
            cmd.extend([f"{_opt}RNGSEED", str(seed)])
        cmd.extend([f"{_opt}FILTER", "Y"])
        cmd.extend([f"{_opt}VERBOSE", "N"])
        return cmd, _opt

    def _stage_dsqgen_workdir(self, temp_path: Path) -> dict[str, str]:
        """Stage templates + variants + distribution files into temp_path. Returns env."""
        import os
        import shutil as _shutil

        _shutil.copytree(self.templates_dir, temp_path / "q")
        var_src = self.templates_dir.parent / "query_variants"
        if var_src.exists():
            _shutil.copytree(var_src, temp_path / "query_variants")

        env = os.environ.copy()
        env["DSS_QUERY"] = str(temp_path)

        dsqgen_dir = Path(self.dsqgen_path).parent
        for dist_file in ("tpcds.dst", "tpcds.idx"):
            dist_src = dsqgen_dir / dist_file
            if dist_src.exists():
                _shutil.copy2(dist_src, temp_path / dist_file)
            dist_src_alt = self.tools_dir / dist_file
            if not (temp_path / dist_file).exists() and dist_src_alt.exists():
                _shutil.copy2(dist_src_alt, temp_path / dist_file)
        return env

    def _run_dsqgen(
        self, cmd: list[str], opt: str, query_id: int, variant: Optional[str]
    ) -> subprocess.CompletedProcess:
        """Run dsqgen in a staged temporary workdir and return the completed process."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env = self._stage_dsqgen_workdir(temp_path)

            cmd.extend([f"{opt}INPUT", "q/templates.lst"])
            cmd.extend([f"{opt}DIRECTORY", "q"])

            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

        if result.returncode != 0:
            error_output = result.stderr.strip() if result.stderr else "Unknown error"
            stdout_output = result.stdout.strip() if result.stdout else ""
            cmd_str = " ".join(cmd)
            raise TPCDSError(
                f"dsqgen failed for query {query_id}{variant or ''} (exit code {result.returncode}): "
                f"Command: {cmd_str}\n"
                f"Stderr: {error_output}\n"
                f"Stdout: {stdout_output}"
            )
        return result

    def _extract_sql_from_output(self, stdout: str, query_id: int, variant: Optional[str]) -> str:
        sql_output = stdout.strip()
        if not sql_output:
            raise TPCDSError(f"dsqgen returned empty output for query {query_id}{variant or ''}")

        sql_lines: list[str] = []
        for line in sql_output.split("\n"):
            if "qgen2 Query Generator" in line or "Copyright Transaction" in line:
                break
            sql_lines.append(line)

        sql_query = "\n".join(sql_lines).strip()
        if not sql_query:
            raise TPCDSError(f"No SQL query found in dsqgen output for query {query_id}{variant or ''}")
        return sql_query

    def _select_multi_part(self, sql_query: str, query_id: int, variant: Optional[str]) -> str:
        parts = [p.strip() for p in sql_query.split(";") if p.strip()]
        if len(parts) < 2:
            raise TPCDSError(f"Expected 2 queries for multi-part query {query_id}, but found {len(parts)}")

        part_index = 0 if variant == "a" else 1
        if part_index >= len(parts):
            raise TPCDSError(f"Query {query_id}{variant} not found - only {len(parts)} parts available")
        return parts[part_index]

    def _wrap_dsqgen_called_process_error(
        self, exc: subprocess.CalledProcessError, query_id: int, variant: Optional[str]
    ) -> TPCDSError:
        error_msg = exc.stderr.strip() if exc.stderr else "Unknown error"
        error_lower = error_msg.lower()
        q = f"{query_id}{variant or ''}"

        if "File '" in error_msg and "not found" in error_msg:
            return TPCDSError(f"Template not found for query {q}: {error_msg}")
        if "Substitution" in error_msg and "is used before being initialized" in error_msg:
            return TPCDSError(
                f"Template substitution error for query {q}: {error_msg}. "
                "This indicates an issue with the TPC-DS template or dsqgen configuration that needs to be fixed."
            )
        if "template" in error_lower:
            return TPCDSError(f"Template error for query {q}: {error_msg}")
        if "parameter" in error_lower:
            return TPCDSError(f"Parameter generation failed for query {q}: {error_msg}")
        return TPCDSError(f"dsqgen failed for query {q}: {error_msg}")

    def _generate_with_binary(
        self,
        query_id: int,
        *,
        variant: Optional[str] = None,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        stream_id: Optional[int] = None,
        dialect: str = "netezza",
    ) -> str:
        """Generate query using dsqgen binary with minimal wrapper."""
        is_multi_part = query_id in (14, 23, 24, 39) and variant in ("a", "b")
        cmd, opt = self._build_dsqgen_cmd(query_id, variant, seed, scale_factor, dialect, is_multi_part)

        try:
            result = self._run_dsqgen(cmd, opt, query_id, variant)
            sql_query = self._extract_sql_from_output(result.stdout, query_id, variant)
            if is_multi_part:
                return self._select_multi_part(sql_query, query_id, variant)
            return sql_query
        except subprocess.CalledProcessError as e:
            raise self._wrap_dsqgen_called_process_error(e, query_id, variant) from e
        except subprocess.TimeoutExpired:
            raise TPCDSError(f"dsqgen timed out for query {query_id}{variant or ''} (60s limit exceeded)") from None
        except FileNotFoundError:
            raise TPCDSError(f"dsqgen binary not found at {self.dsqgen_path}") from None

    def _detect_supported_dialects(self) -> set[str]:
        """Detect available SQL dialect templates.

        Dialect templates are special .tpl files that define SQL syntax variations
        (netezza.tpl, oracle.tpl, db2.tpl, sqlserver.tpl, ansi.tpl).
        Query templates (query1.tpl, query2.tpl, etc.) are NOT dialects.
        """
        # Known TPC-DS dialect templates
        known_dialects = {"ansi", "netezza", "oracle", "db2", "sqlserver"}
        dialects = set()

        for dialect_file in self.templates_dir.glob("*.tpl"):
            dialect_name = dialect_file.stem
            # Only include known dialect files, not query templates
            if dialect_name in known_dialects:
                dialects.add(dialect_name)

        # ANSI is always supported (fallback)
        dialects.add("ansi")

        return dialects

    def _get_cache_key(
        self,
        query_id: int,
        variant: Optional[str],
        seed: Optional[int],
        scale_factor: float,
        stream_id: Optional[int],
        dialect: str,
    ) -> str:
        """Generate cache key for parameter and query caching."""
        return f"{query_id}{variant or ''}_{seed}_{scale_factor}_{stream_id}_{dialect}"

    def _validate_dialect(self, dialect: str) -> str:
        """Validate and normalize dialect name."""
        dialect_lower = dialect.lower()

        if dialect_lower not in self._supported_dialects:
            # Fall back to Netezza if unsupported dialect requested
            warnings.warn(f"Dialect '{dialect}' not supported, falling back to 'netezza'", stacklevel=2)
            return "netezza"

        return dialect_lower

    def _generate_parameter_variations(
        self, base_seed: Optional[int], stream_id: Optional[int], scale_factor: float
    ) -> dict[str, Union[int, str, float, tuple[float, float]]]:
        """Generate parameter variations for TPC-DS query customization.

        This creates seed-based parameter variations that are reproducible but diverse
        across different streams and scale factors.
        """
        if base_seed is None:
            import random
            import time

            # Use time-based seed if none provided, but make it deterministic per session
            base_seed = int(time.time()) % 100000

        # Create stream-specific seed variation
        effective_seed = base_seed
        if stream_id is not None:
            effective_seed = (base_seed * 7919 + stream_id * 3037) % 2147483647  # Large primes for distribution

        import random

        random.seed(effective_seed)

        # Generate parameter variations based on scale factor and seed
        params = {
            "year": random.choice(range(1998, 2003)),
            "quarter": random.randint(1, 4),
            "month": random.randint(1, 12),
            "day": random.randint(1, 28),
            "state_count": max(1, int(random.randint(1, 10) * (scale_factor**0.5))),
            "brand_count": max(1, int(random.randint(5, 50) * (scale_factor**0.3))),
            "category_count": max(1, int(random.randint(1, 20) * (scale_factor**0.2))),
            "dms_base": random.randint(1176, 1224),  # Date month sequence
            "price_range": (10.0 * scale_factor, 1000.0 * scale_factor),
            "effective_seed": effective_seed,
        }

        return params

    def _parse_query_id(self, query_id: Union[int, str]) -> tuple[int, Optional[str]]:
        """Parse query ID to extract base query number and variant.

        Args:
            query_id: Query identifier (int, string like '14a', '23b')

        Returns:
            Tuple of (base_query_id, variant) where variant is 'a', 'b', or None
        """
        if isinstance(query_id, int):
            return query_id, None

        query_str = str(query_id).strip().lower()

        # Handle variants like '14a', '23b'
        if query_str[-1] in ("a", "b"):
            try:
                base_id = int(query_str[:-1])
                variant = query_str[-1]
                return base_id, variant
            except ValueError:
                pass

        # Handle plain number strings
        try:
            return int(query_str), None
        except ValueError:
            raise ValueError(f"Invalid query ID format: {query_id}. Expected int or string like '14a'") from None

    def clear_cache(self) -> None:
        """Clear parameter and query caches."""
        self._parameter_cache.clear()
        self._query_cache.clear()

    def get_parameter_variations(
        self,
        query_id: Union[int, str],
        *,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        stream_id: Optional[int] = None,
    ) -> dict[str, Union[int, str, float]]:
        """Get parameter variations for a query without generating the SQL.

        This is useful for understanding what parameter values will be used
        for a particular query generation request.
        """
        base_query_id, variant = self._parse_query_id(query_id)
        cache_key = self._get_cache_key(base_query_id, variant, seed, scale_factor, stream_id, "netezza")

        if cache_key not in self._parameter_cache:
            param_variations = self._generate_parameter_variations(seed, stream_id, scale_factor)
            self._parameter_cache[cache_key] = param_variations

        return self._parameter_cache[cache_key].copy()

    def get_supported_dialects(self) -> set[str]:
        """Return set of supported SQL dialects."""
        return self._supported_dialects.copy()

    def get_available_queries(self) -> list[str]:
        """Get list of all available query templates."""
        queries = []
        for template_file in sorted(self.templates_dir.glob("query*.tpl")):
            query_name = template_file.stem
            if query_name.startswith("query"):
                query_id = query_name[5:]  # Remove "query" prefix
                if query_id.isdigit() or (len(query_id) > 1 and query_id[:-1].isdigit() and query_id[-1] in "ab"):
                    queries.append(query_id)
        return queries

    def _find_templates_or_fail(self, templates_path: Optional[Path] = None) -> Path:
        """Find TPC-DS templates directory or fail immediately."""
        if templates_path is None:
            _, templates_path = _resolve_tpcds_tool_and_template_paths()

        if not templates_path.exists():
            raise RuntimeError(
                f"TPC-DS query templates required but not found at {templates_path}. "
                "TPC-DS requires the query template files to function. "
                "Please ensure the TPC-DS templates are properly installed."
            )
        return templates_path

    def _clean_sql(self, sql: str) -> str:
        """Comprehensive SQL cleaning for TPC-DS queries to work with modern databases.

        This method handles TPC-DS specific syntax issues including:
        - Complex window functions and CTEs
        - Database-specific syntax (DB2, SQL Server, Oracle)
        - Date arithmetic and interval syntax
        - ROLLUP, CUBE, and grouping set syntax
        - Template parameter cleanup
        """
        # Step 1: Basic line filtering and comment removal
        lines = []
        for line in sql.split("\n"):
            line = line.strip()
            # Skip comments, empty lines, and database-specific directives
            if line and not line.startswith("--") and line.lower() not in ("go", ""):
                # Skip database-specific commands
                if any(
                    line.lower().startswith(cmd)
                    for cmd in [
                        "set rowcount",
                        "set ansi_nulls",
                        "set quoted_identifier",
                        "set arithabort",
                        "set concat_null_yields_null",
                        "set numeric_roundabort",
                        "set ansi_padding",
                        "use ",
                        "\\timing",
                    ]
                ):
                    continue
                lines.append(line)

        cleaned_sql = "\n".join(lines)

        # Step 2: TPC-DS template parameter cleanup
        # Remove limit template parameters
        cleaned_sql = re.sub(r"\[_LIMIT[ABC]\]", "", cleaned_sql, flags=re.IGNORECASE)

        # Remove any unprocessed template parameters
        cleaned_sql = re.sub(r"\[\w+(?:\.\w+)?\]", "", cleaned_sql)

        # Step: Database-specific syntax normalization

        # Remove SQL Server TOP syntax (it's handled by limit templates)
        cleaned_sql = re.sub(r"\bselect\s+top\s+\d+\b", "select", cleaned_sql, flags=re.IGNORECASE)

        # Normalize Oracle/DB2 date literal syntax
        cleaned_sql = re.sub(r"\bdate\s*'\s*([^']+)\s*'", r"date '\1'", cleaned_sql, flags=re.IGNORECASE)

        # Transform DB2-style date arithmetic to standard interval syntax
        cleaned_sql = re.sub(
            r"\bdate\s*\(\s*([^)]+)\s*\)\s*\+\s*(\d+)\s+days?\b",
            r"\1 + interval '\2' day",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Step 4: Date and interval syntax standardization

        # Convert "date + N days/months/years" to standard interval syntax
        cleaned_sql = re.sub(
            r"\+\s*(\d+)\s+days?\b",
            r"+ interval '\1' day",
            cleaned_sql,
            flags=re.IGNORECASE,
        )
        cleaned_sql = re.sub(
            r"\+\s*(\d+)\s+months?\b",
            r"+ interval '\1' month",
            cleaned_sql,
            flags=re.IGNORECASE,
        )
        cleaned_sql = re.sub(
            r"\+\s*(\d+)\s+years?\b",
            r"+ interval '\1' year",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Strip precision specifiers from interval syntax
        cleaned_sql = re.sub(
            r"interval\s+'([^']+)'\s+(day|month|year)\s*\(\d+\)",
            r"interval '\1' \2",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Step 5: Window function and analytic syntax normalization

        # Ensure proper OVER clause formatting
        cleaned_sql = re.sub(
            r"\bover\s*\(\s*partition\s+by\b",
            "over (partition by",
            cleaned_sql,
            flags=re.IGNORECASE,
        )
        cleaned_sql = re.sub(
            r"\bover\s*\(\s*order\s+by\b",
            "over (order by",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Normalize window frame syntax
        cleaned_sql = re.sub(
            r"\brows?\s+between\s+unbounded\s+preceding\s+and\s+current\s+row\b",
            "rows between unbounded preceding and current row",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Normalize rank() and dense_rank() function syntax
        cleaned_sql = re.sub(
            r"\brank\s*\(\s*\)\s+over\s*\(",
            "rank() over (",
            cleaned_sql,
            flags=re.IGNORECASE,
        )
        cleaned_sql = re.sub(
            r"\bdense_rank\s*\(\s*\)\s+over\s*\(",
            "dense_rank() over (",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Step 6: Grouping and aggregation syntax normalization

        # Normalize ROLLUP syntax
        cleaned_sql = re.sub(
            r"\bgroup\s+by\s+rollup\s*\(",
            "group by rollup(",
            cleaned_sql,
            flags=re.IGNORECASE,
        )
        cleaned_sql = re.sub(
            r"\bgroup\s+by\s+cube\s*\(",
            "group by cube(",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Normalize GROUPING SETS syntax
        cleaned_sql = re.sub(
            r"\bgroup\s+by\s+grouping\s+sets\s*\(",
            "group by grouping sets(",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Step 7: CTE (Common Table Expression) syntax normalization

        # Ensure proper CTE formatting
        cleaned_sql = re.sub(
            r"\bwith\s+(\w+)\s+as\s*\(",
            r"with \1 as (",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Step 8: JOIN syntax standardization

        # Transform implicit joins to explicit joins where possible (basic cases)
        # This is conservative to avoid breaking complex logic

        # Step 9: Function call standardization

        # Normalize COALESCE function calls
        cleaned_sql = re.sub(
            r"\bcoalesce\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)",
            r"coalesce(\1, \2)",
            cleaned_sql,
            flags=re.IGNORECASE,
        )

        # Normalize CASE expression formatting
        cleaned_sql = re.sub(r"\bcase\s+when\b", "case when", cleaned_sql, flags=re.IGNORECASE)
        cleaned_sql = re.sub(r"\belse\s+case\b", "else case", cleaned_sql, flags=re.IGNORECASE)
        cleaned_sql = re.sub(r"\bend\s+case\b", "end case", cleaned_sql, flags=re.IGNORECASE)

        # Step 10: String and numeric literal normalization

        # Convert double-quoted strings to single quotes for SQL standard compliance
        cleaned_sql = re.sub(r'"([^"]*)"', r"'\1'", cleaned_sql)

        # Normalize escaped quotes
        cleaned_sql = re.sub(r"''([^']*?)''", r"'\1'", cleaned_sql)

        # Step 11: LIMIT clause standardization

        # Remove trailing semicolons that might cause issues
        cleaned_sql = cleaned_sql.rstrip(";")

        # Step 12: Whitespace normalization

        # Clean up extra whitespace
        cleaned_sql = re.sub(r"\n\s*\n", "\n", cleaned_sql)  # Remove multiple empty lines
        cleaned_sql = re.sub(r"[ \t]+", " ", cleaned_sql)  # Normalize horizontal whitespace
        cleaned_sql = re.sub(r"\n\s+", "\n", cleaned_sql)  # Remove leading whitespace on lines

        # Step 13: SQL dialect translation (optional)

        # Attempt SQL dialect translation for better compatibility
        # This is done last to preserve our manual fixes
        try:
            import sqlglot  # type: ignore[import-untyped]

            # Parse with multiple dialect attempts for better compatibility
            for source_dialect in ["postgres", "mysql", "sqlite", None]:
                try:
                    parsed = sqlglot.parse_one(cleaned_sql, dialect=source_dialect)  # type: ignore[attr-defined]
                    if parsed:
                        # Transpile to PostgreSQL dialect for maximum compatibility
                        transpiled = parsed.sql(dialect="postgres", pretty=True)  # type: ignore[attr-defined]
                        if transpiled and len(transpiled.strip()) > 0:
                            cleaned_sql = transpiled
                            break
                except Exception:
                    continue
        except ImportError:
            # sqlglot not available, continue with manual cleaning
            pass
        except Exception:
            # If all sqlglot attempts fail, continue with our manual cleaning
            pass

        # Step 14: Final cleanup

        # Ensure the query ends properly
        cleaned_sql = cleaned_sql.strip()

        # Add semicolon if it's a complete query and doesn't already have one
        if cleaned_sql and not cleaned_sql.endswith(";") and not cleaned_sql.endswith(")"):
            # Only add semicolon for complete SELECT statements
            if re.match(r"^\s*(with\s+|select\s+)", cleaned_sql, re.IGNORECASE):
                cleaned_sql += ";"

        return cleaned_sql

    def _find_dsqgen_or_fail(self) -> Path:
        """Find dsqgen binary, attempt compilation if missing, fail if unavailable."""
        import logging

        logger = logging.getLogger(__name__)

        # Use auto-compilation utility
        results = ensure_tpc_binaries(["dsqgen"], auto_compile=True)
        dsqgen_result = results.get("dsqgen")

        if (
            dsqgen_result
            and dsqgen_result.status
            in [
                CompilationStatus.SUCCESS,
                CompilationStatus.NOT_NEEDED,
                CompilationStatus.PRECOMPILED,
            ]
            and dsqgen_result.binary_path
            and dsqgen_result.binary_path.exists()
        ):
            logger.info(f"Using dsqgen binary: {dsqgen_result.binary_path}")
            return dsqgen_result.binary_path

        # Fallback to traditional path lookup
        dsqgen_path = self.tools_dir / "dsqgen"

        if dsqgen_path.exists():
            return dsqgen_path

        # If auto-compilation failed, provide detailed error
        error_msg = f"dsqgen binary required but not found at {dsqgen_path}."
        if dsqgen_result and dsqgen_result.error_message:
            error_msg += f" Auto-compilation failed: {dsqgen_result.error_message}"
        error_msg += " TPC-DS requires the compiled dsqgen tool to function."

        raise RuntimeError(error_msg)

    def get_query_variations(self, query_id: int) -> list[str]:
        """Get all available variations for a query ID.

        Args:
            query_id: Base query number (1-99)

        Returns:
            List of query variations (e.g., ['14', '14a', '14b'] for query 14)
        """
        variations = [str(query_id)]

        # Check for query variants in the query_variants directory
        variants_dir = self.templates_dir.parent / "query_variants"
        if variants_dir.exists():
            for variant_suffix in ["a", "b", "c", "d"]:
                variant_file = variants_dir / f"query{query_id}{variant_suffix}.tpl"
                if variant_file.exists():
                    variations.append(f"{query_id}{variant_suffix}")

        return variations

    def validate_query_id(self, query_id: Union[int, str]) -> bool:
        """Validate if a query ID is supported.

        Args:
            query_id: Query identifier to validate

        Returns:
            True if query ID is valid for TPC-DS
        """
        try:
            base_query_id, variant = self._parse_query_id(query_id)
            if not (1 <= base_query_id <= 99):
                return False

            # Check if the base query template exists
            query_template = self.templates_dir / f"query{base_query_id}.tpl"
            if not query_template.exists():
                return False

            # Check if variant exists (if specified)
            if variant:
                variants_dir = self.templates_dir.parent / "query_variants"
                variant_template = variants_dir / f"query{base_query_id}{variant}.tpl"
                if not variant_template.exists():
                    return False

            return True
        except (ValueError, TypeError):
            return False

    def generate_with_parameters(
        self,
        query_id: int,
        parameters: dict[str, Any],
        *,
        scale_factor: float = 1.0,
        dialect: str = "netezza",
    ) -> str:
        """Generate query with specific parameter values.

        Args:
            query_id: Query number (1-99)
            parameters: Dictionary of parameter names to values
            scale_factor: Scale factor for calculations
            dialect: SQL dialect

        Returns:
            SQL query string with parameters substituted
        """
        # For TPC-DS, we'll need to use template processing with custom parameters
        # This is a simplified implementation that uses dsqgen with a fixed seed
        # and then post-processes the result with custom parameters

        # Generate base query first
        base_sql = self.generate(query_id, seed=1, scale_factor=scale_factor, dialect=dialect)

        # Apply custom parameter substitutions
        for param_name, param_value in parameters.items():
            # Convert parameter name to template format
            template_param = f"[{param_name.upper()}]"
            if template_param in base_sql:
                base_sql = base_sql.replace(template_param, str(param_value))

        return self._clean_sql(base_sql)


class TPCDSQueries:
    """Ultra-simplified TPC-DS query manager using dsqgen exclusively."""

    def __init__(self) -> None:
        """Initialize with hard dsqgen requirement."""
        self.dsqgen = DSQGenBinary()

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        seed: Optional[int] = None,
        scale_factor: float = 1.0,
        stream_id: Optional[int] = None,
        dialect: str = "netezza",
    ) -> str:
        """Get TPC-DS query using dsqgen. Parameters are dsqgen-native.

        Args:
            query_id: TPC-DS query number (1-99, or string like '14a', '23b')
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations (GB)
            stream_id: Stream identifier for multi-stream execution
            dialect: SQL dialect for output (netezza, ansi, sqlserver, oracle, db2)

        Returns:
            Clean SQL query string

        Raises:
            ValueError: If query_id not in range 1-99
            TPCDSError: If dsqgen binary execution fails
        """
        if isinstance(query_id, int) and not (1 <= query_id <= 99):
            raise ValueError(f"Query ID must be 1-99, got {query_id}")
        return self.dsqgen.generate(
            query_id,
            seed=seed,
            scale_factor=scale_factor,
            stream_id=stream_id,
            dialect=dialect,
        )

    def get_all_queries(self, **kwargs: Union[str, int, float]) -> dict[Union[int, str], str]:
        """Get all 99 TPC-DS queries.

        Args:
            **kwargs: Arguments passed to get_query() for each query

        Returns:
            Dictionary mapping query IDs (1-99) to SQL strings
        """
        results = {}

        # Handle standard queries 1-99
        for i in range(1, 100):
            try:
                results[i] = self.get_query(i, **kwargs)
            except (ValueError, TPCDSError):
                # Some queries might have variants or might fail for certain parameters
                # Continue with other queries but log the failure
                continue

        # Handle query variants that actually exist in the templates
        for query_id in self.dsqgen.get_available_queries():
            if not query_id.isdigit():  # This catches variants like '14a', '23b'
                try:
                    results[query_id] = self.get_query(query_id, **kwargs)
                except (ValueError, TPCDSError):
                    # Variants might not exist for all configurations
                    continue

        return results

    def get_stream_queries(self, stream_count: int = 1, **kwargs) -> dict[int, dict[Union[int, str], str]]:
        """Get multiple streams of TPC-DS queries for parallel execution.

        Args:
            stream_count: Number of query streams to generate
            **kwargs: Arguments passed to get_query() for each query

        Returns:
            Dictionary mapping stream IDs to query dictionaries
        """
        streams = {}

        for stream_id in range(1, stream_count + 1):
            # Each stream gets different parameter values
            stream_kwargs = kwargs.copy()
            stream_kwargs["stream_id"] = stream_id

            # Vary seed per stream for parameter diversity
            if "seed" in stream_kwargs and stream_kwargs["seed"] is not None:
                stream_kwargs["seed"] = stream_kwargs["seed"] + stream_id

            streams[stream_id] = self.get_all_queries(**stream_kwargs)

        return streams

    def get_supported_dialects(self) -> set[str]:
        """Get set of supported SQL dialects."""
        return self.dsqgen.get_supported_dialects()

    def get_available_queries(self) -> list[str]:
        """Get list of all available query templates."""
        return self.dsqgen.get_available_queries()

    def validate_query_id(self, query_id: Union[int, str]) -> bool:
        """Validate if a query ID is supported."""
        return self.dsqgen.validate_query_id(query_id)

    def clear_cache(self) -> None:
        """Clear parameter and query caches."""
        self.dsqgen.clear_cache()
