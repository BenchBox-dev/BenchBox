"""TPC-H query management using qgen

Provides TPC-H query generation interface using the compiled qgen binary.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import atexit
import subprocess
import threading
from pathlib import Path
from typing import Optional, Union

from benchbox.utils.tpc_compilation import CompilationStatus, ensure_tpc_binaries


class QGenBinary:
    """Direct interface to qgen binary with hard dependency."""

    def __init__(self) -> None:
        """Find qgen or fail immediately."""
        self.qgen_path = self._find_qgen_or_fail()
        self.templates_dir = self._find_templates_dir()
        # Lazily-created, reused working directory for qgen invocations (see
        # _ensure_work_dir). Guards concurrent first-creation from multiple
        # threads (e.g. throughput-test pre-generation, which fans out
        # per-stream generation across a ThreadPoolExecutor).
        self._work_dir: Optional[str] = None
        self._work_dir_lock = threading.Lock()

    def _ensure_work_dir(self) -> str:
        """Return a writable working directory for qgen, creating it once.

        qgen only *reads* ``dists.dss`` from its cwd and writes generated SQL
        to stdout (no other files are written into the working directory in
        this mode), so a single directory can safely be shared across every
        ``generate()`` call -- including concurrent calls from multiple
        threads -- instead of paying a fresh ``mkdtemp`` + ``dists.dss`` copy
        on every single query generation. The directory is removed at
        process exit via ``atexit`` since it is no longer a context-managed
        ``TemporaryDirectory``.
        """
        if self._work_dir is not None:
            return self._work_dir

        with self._work_dir_lock:
            if self._work_dir is None:
                import shutil
                import tempfile

                work_dir = tempfile.mkdtemp(prefix="benchbox_qgen_")
                dists_src = self.templates_dir / "dists.dss"
                if dists_src.exists():
                    shutil.copy2(dists_src, Path(work_dir) / "dists.dss")
                atexit.register(shutil.rmtree, work_dir, ignore_errors=True)
                self._work_dir = work_dir

        return self._work_dir

    def generate(self, query_id: int, *, seed: Optional[int] = None, scale_factor: float = 1.0) -> str:
        """Generate query using qgen. Returns clean SQL.

        Note: Query 15 automatically uses variant 15a (CTE version) instead of the default
        view-based version for better compatibility across database platforms.
        """
        cmd = [self.qgen_path, "-a"]  # ANSI mode for compatibility

        if seed is not None:
            cmd.extend(["-r", str(seed)])
        else:
            cmd.append("-d")  # Use official TPC-H default substitution parameters
        if scale_factor != 1.0:
            cmd.extend(["-s", str(scale_factor)])

        # For query 15, use variant 15a (CTE) instead of default (VIEW)
        # This provides better compatibility - CTEs are more widely supported than views
        # and don't require CREATE VIEW / DROP VIEW permissions
        if query_id == 15:
            cmd.append("15a")
            query_dir = "variants"
        else:
            cmd.append(str(query_id))
            query_dir = "queries"

        # Set up environment for qgen
        import os

        env = os.environ.copy()
        env["DSS_QUERY"] = str(self.templates_dir / query_dir)

        # Run qgen from a writable directory, reused across calls (see
        # _ensure_work_dir), but point to source templates via DSS_QUERY above.
        work_dir = self._ensure_work_dir()

        result = subprocess.run(
            cmd,
            cwd=work_dir,  # Use the shared work dir as writable working directory
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return self._clean_sql(result.stdout)

    def _find_qgen_or_fail(self) -> str:
        """Find qgen executable or attempt compilation if missing."""
        import logging

        import benchbox

        logger = logging.getLogger(__name__)

        # Check if qgen is available and compile if needed
        results = ensure_tpc_binaries(["qgen"], auto_compile=True)
        qgen_result = results.get("qgen")

        if (
            qgen_result
            and qgen_result.status
            in [
                CompilationStatus.SUCCESS,
                CompilationStatus.NOT_NEEDED,
                CompilationStatus.PRECOMPILED,
            ]
            and qgen_result.binary_path
            and qgen_result.binary_path.exists()
        ):
            logger.info(f"Using qgen binary: {qgen_result.binary_path}")
            return str(qgen_result.binary_path)

        # Fallback to traditional path lookup
        qgen_path = Path(benchbox.__file__).parent.parent / "_sources/tpc-h/dbgen/qgen"

        if not qgen_path.exists():
            error_msg = f"qgen binary required but not found at {qgen_path}."
            if qgen_result and qgen_result.error_message:
                error_msg += f" Auto-compilation failed: {qgen_result.error_message}"
            error_msg += " TPC-H requires the compiled qgen tool to function."

            raise RuntimeError(error_msg)

        return str(qgen_path)

    def _find_templates_dir(self) -> Path:
        """Find the TPC-H templates directory (queries, dists.dss, etc.)."""
        from benchbox.utils.tpc_compilation import get_tpc_templates_dir

        templates_dir = get_tpc_templates_dir("tpc-h")

        # Verify required files and directories exist
        queries_dir = templates_dir / "queries"
        variants_dir = templates_dir / "variants"
        dists_file = templates_dir / "dists.dss"

        if not queries_dir.exists():
            raise RuntimeError(f"TPC-H queries directory not found at {queries_dir}")
        if not variants_dir.exists():
            raise RuntimeError(f"TPC-H variants directory not found at {variants_dir}")
        if not dists_file.exists():
            raise RuntimeError(f"TPC-H dists.dss file not found at {dists_file}")

        return templates_dir

    def _extract_rowcount(self, sql: str) -> Optional[int]:
        """Extract rowcount limit from qgen's database-specific syntax.

        qgen outputs row limits using database-specific syntax based on compile-time
        defines in tpcd.h:
        - Oracle: "WHERE ROWNUM <= 20"
        - SQL Server: "SET ROWCOUNT 100\\nGO"
        - Informix: "FIRST 100"

        This method extracts the limit value so it can be translated to modern
        standard SQL LIMIT syntax. SQLGlot will then handle dialect-specific
        translation (e.g., FETCH FIRST for SQL Server) in later stages.

        Args:
            sql: Raw SQL output from qgen

        Returns:
            The row limit if found, None otherwise
        """
        import re

        # Oracle syntax: WHERE ROWNUM <= n
        if match := re.search(r"where\s+rownum\s*<=\s*(\d+)", sql, re.IGNORECASE):
            return int(match.group(1))

        # SQL Server syntax: SET ROWCOUNT n
        if match := re.search(r"set\s+rowcount\s+(\d+)", sql, re.IGNORECASE):
            return int(match.group(1))

        # Informix syntax: FIRST n (rare, but handle for completeness)
        if match := re.search(r"\bFIRST\s+(\d+)\b", sql, re.IGNORECASE):
            return int(match.group(1))

        return None

    def _clean_sql(self, sql: str) -> str:
        """Clean SQL and translate database-specific syntax to standard SQL.

        This method:
        1. Extracts row limits from qgen's database-specific syntax (Oracle ROWNUM, SQL Server SET ROWCOUNT)
        2. Strips database-specific directives and commands
        3. Normalizes qgen-specific syntax patterns
        4. Adds standard LIMIT clause if a row limit was found

        The output uses standard SQL LIMIT syntax, which SQLGlot will later translate
        to dialect-specific syntax (e.g., FETCH FIRST for SQL Server) as needed.
        """
        import re

        # STEP 1: Extract rowcount BEFORE cleaning (from qgen's database-specific syntax)
        rowcount = self._extract_rowcount(sql)

        # STEP 2: Strip database-specific syntax
        lines = []
        for line in sql.split("\n"):
            line = line.strip()
            # Skip comments and SQL Server directives
            if line and not line.startswith("--") and line.lower() not in ("go", ""):
                # Skip SQL Server specific commands and Oracle-style rownum clauses
                if line.lower().startswith("set rowcount") or line.lower().startswith("where rownum"):
                    continue
                lines.append(line)

        cleaned_sql = "\n".join(lines)

        # STEP 3: Transform qgen-specific syntax for compatibility
        # Normalize interval syntax: "interval '91' day (3)" -> "interval '91' day"
        cleaned_sql = re.sub(
            r"interval\s+'([^']+)'\s+(day|month|year)\s*\(\d+\)",
            r"interval '\1' \2",
            cleaned_sql,
        )

        # Standardize date literal syntax
        cleaned_sql = re.sub(r"date\s+'([^']+)'\s*-\s*interval", r"date '\1' - interval", cleaned_sql)

        # Remove trailing semicolons followed by invalid Oracle clauses
        cleaned_sql = re.sub(
            r";\s*where\s+rownum\s*<=\s*-?\d+;?\s*$",
            ";",
            cleaned_sql,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        # STEP 4: Add standard LIMIT clause if rowcount was found
        # This preserves qgen's row limit specification (from :n directives in templates)
        # and translates it to modern standard SQL syntax
        if rowcount and rowcount > 0:
            # Remove trailing semicolon and whitespace
            cleaned_sql = cleaned_sql.rstrip(";").rstrip()
            # Add LIMIT clause (SQLGlot will handle dialect-specific translation later)
            cleaned_sql = f"{cleaned_sql}\nLIMIT {rowcount};"

        return cleaned_sql


class TPCHQueries:
    """Ultra-simplified TPC-H query manager using qgen exclusively.

    Note: Query 15 automatically uses the CTE variant (15a) instead of the default
    view-based version. This ensures better compatibility across database platforms
    as CTEs are more widely supported and don't require CREATE VIEW / DROP VIEW
    permissions.
    """

    def __init__(self) -> None:
        """Initialize with hard qgen requirement."""
        self.qgen = QGenBinary()

    def get_query(self, query_id: int, *, seed: Optional[int] = None, scale_factor: float = 1.0) -> str:
        """Get TPC-H query using qgen. Parameters are qgen-native.

        Args:
            query_id: TPC-H query number (1-22). Query 15 automatically uses variant 15a (CTE).
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations

        Returns:
            Clean SQL query string. Query 15 uses WITH clause (CTE) instead of CREATE VIEW.

        Raises:
            ValueError: If query_id not in range 1-22
            TypeError: If query_id is not an integer
            RuntimeError: If qgen binary not available
            subprocess.CalledProcessError: If qgen execution fails
        """
        # Validate query_id to match TPC-DS patterns
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        # Validate scale_factor if provided
        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        # Validate seed if provided
        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

        return self.qgen.generate(query_id, seed=seed, scale_factor=scale_factor)

    def get_all_queries(self, **kwargs: Union[int, float, str]) -> dict[int, str]:
        """Get all 22 TPC-H queries.

        Args:
            **kwargs: Arguments passed to get_query() for each query

        Returns:
            Dictionary mapping query IDs (1-22) to SQL strings
        """
        return {i: self.get_query(i, **kwargs) for i in range(1, 23)}
