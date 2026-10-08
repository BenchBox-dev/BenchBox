# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
import os
import re
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

try:
    import sqlglot
    from sqlglot import parse_one, transpile
    from sqlglot.errors import ParseError

    SQLGLOT_AVAILABLE = True
except ImportError:
    sqlglot = None
    parse_one = None
    transpile = None
    ParseError = Exception
    SQLGLOT_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QgenError(Exception):
    pass


class QgenCompilationError(QgenError):
    pass


class QgenExecutionError(QgenError):
    pass


class QgenParsingError(QgenError):
    pass


class QueryComparisonError(QgenError):
    pass


@dataclass
class QgenQuery:
    query_id: int
    raw_query: str
    normalized_query: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    generation_time: float = 0.0
    parse_tree: Optional[Any] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryComparisonResult:
    query_id: int
    python_query: str
    c_query: str
    similarity_score: float = 0.0
    structure_match: bool = False
    parameter_match: bool = False
    semantic_match: bool = False
    differences: list[str] = field(default_factory=list)
    python_errors: list[str] = field(default_factory=list)
    c_errors: list[str] = field(default_factory=list)
    comparison_metadata: dict[str, Any] = field(default_factory=dict)


class ComparisonLevel(Enum):
    BASIC = "basic"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    PARAMETER = "parameter"


class QGenWrapper:
    def __init__(
        self,
        tpch_tools_path: Optional[Path] = None,
        force_compile: bool = False,
        verbose: bool = False,
        timeout: int = 60,
    ):
        self.verbose = verbose
        self.timeout = timeout
        self.force_compile = force_compile

        if tpch_tools_path is None:
            project_root = Path(__file__).parent.parent.parent
            tpch_tools_path = project_root / "_sources" / "tpc-h" / "dbgen"

        self.tools_path = Path(tpch_tools_path)
        self.qgen_binary = self.tools_path / "qgen"
        self.dbgen_binary = self.tools_path / "dbgen"

        self._is_available = None
        self._last_check_time = 0

        if self.check_availability():
            self._ensure_tools_ready()

    def check_availability(self, force_check: bool = False) -> bool:
        current_time = time.time()

        if not force_check and self._is_available is not None and current_time - self._last_check_time < 30:
            return self._is_available

        self._last_check_time = current_time

        try:
            if not self.tools_path.exists():
                if self.verbose:
                    logger.warning(f"TPC-H tools directory not found: {self.tools_path}")
                self._is_available = False
                return False

            required_files = [
                "qgen.c",
                "makefile",
                "tpcd.h",
                "dss.h",
                "varsub.c",
                "rnd.c",
            ]

            missing_files = []
            for file in required_files:
                if not (self.tools_path / file).exists():
                    missing_files.append(file)

            if missing_files:
                if self.verbose:
                    logger.warning(f"Missing TPC-H source files: {missing_files}")
                self._is_available = False
                return False

            if not self.qgen_binary.exists() or self.force_compile:
                try:
                    self._compile_tools()
                except QgenCompilationError:
                    self._is_available = False
                    return False

            test_result = self._test_qgen_functionality()
            self._is_available = test_result
            return test_result

        except Exception as e:
            if self.verbose:
                logger.error(f"Error checking TPC-H tools availability: {e}")
            self._is_available = False
            return False

    def _ensure_tools_ready(self) -> None:
        if not self.qgen_binary.exists() or self.force_compile:
            self._compile_tools()

    def _compile_tools(self) -> None:
        if self.verbose:
            logger.info(f"Compiling TPC-H tools in {self.tools_path}")

        try:
            with self._change_directory(self.tools_path):
                self._run_make_command("clean", check=False)

                self._run_make_command("qgen")

                if not self.qgen_binary.exists():
                    raise QgenCompilationError("qgen binary not found after compilation")

                os.chmod(self.qgen_binary, 0o755)

                if self.verbose:
                    logger.info("TPC-H tools compiled successfully")

        except subprocess.CalledProcessError as e:
            error_msg = f"TPC-H compilation failed: {e}"
            if hasattr(e, "stderr") and e.stderr:
                error_msg += f"\nSTDERR: {e.stderr}"
            raise QgenCompilationError(error_msg) from e
        except Exception as e:
            raise QgenCompilationError(f"Unexpected compilation error: {e}") from e

    def _run_make_command(self, target: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["make", target]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)

        if check and result.returncode != 0:
            error_msg = f"Make {target} failed (return code {result.returncode})"
            if result.stderr:
                error_msg += f"\nSTDERR: {result.stderr}"
            if result.stdout:
                error_msg += f"\nSTDOUT: {result.stdout}"
            raise subprocess.CalledProcessError(result.returncode, cmd, error_msg)

        return result

    @contextmanager
    def _change_directory(self, path: Path) -> Generator[None, None, None]:
        old_cwd = os.getcwd()
        try:
            os.chdir(path)
            yield
        finally:
            os.chdir(old_cwd)

    def _test_qgen_functionality(self) -> bool:
        try:
            result = subprocess.run(
                [str(self.qgen_binary), "-h"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            return bool(result.stdout or result.stderr)

        except Exception as e:
            if self.verbose:
                logger.error(f"qgen functionality test failed: {e}")
            return False

    def generate_query(
        self,
        query_id: int,
        seed: Optional[int] = None,
        dialect: str = "ansi",
        scale_factor: float = 1.0,
    ) -> QgenQuery:
        if not self.check_availability():
            raise QgenExecutionError("TPC-H qgen tools not available")

        if not 1 <= query_id <= 22:
            raise ValueError(f"Invalid query ID: {query_id}. Must be between 1 and 22.")

        start_time = time.time()

        try:
            cmd = [str(self.qgen_binary), "-s", str(query_id)]
            if seed is not None:
                cmd.extend(["-r", str(seed)])

            with self._change_directory(self.tools_path):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)

            generation_time = time.time() - start_time

            if result.returncode != 0:
                error_msg = f"qgen execution failed for query {query_id}"
                if result.stderr:
                    error_msg += f": {result.stderr}"
                raise QgenExecutionError(error_msg)

            query = self._parse_qgen_output(result.stdout, query_id)
            query.generation_time = generation_time

            if self.verbose:
                logger.info(f"Generated query {query_id} in {generation_time:.3f}s")

            return query

        except subprocess.TimeoutExpired:
            raise QgenExecutionError(f"qgen timed out for query {query_id}") from None
        except Exception as e:
            raise QgenExecutionError(f"Failed to generate query {query_id}: {e}") from e

    def _parse_qgen_output(self, output: str, query_id: int) -> QgenQuery:
        lines = output.strip().split("\n")

        query_lines = []
        parameters = {}
        errors = []
        warnings = []
        metadata = {}

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if line.startswith("--"):
                param_match = re.match(r"--\s*(\w+)\s*[:=]\s*(.+)", line)
                if param_match:
                    param_name, param_value = param_match.groups()
                    parameters[param_name] = param_value.strip()
                continue

            if any(keyword in line.lower() for keyword in ["error", "fail", "exception"]):
                errors.append(line)
                continue

            if any(keyword in line.lower() for keyword in ["warning", "warn"]):
                warnings.append(line)
                continue

            query_lines.append(line)

        raw_query = "\n".join(query_lines)

        query = QgenQuery(
            query_id=query_id,
            raw_query=raw_query,
            parameters=parameters,
            errors=errors,
            warnings=warnings,
            metadata=metadata,
        )

        try:
            query.normalized_query = self._normalize_query(raw_query)
        except Exception as e:
            errors.append(f"Query normalization failed: {e}")
            query.normalized_query = raw_query

        if SQLGLOT_AVAILABLE:
            try:
                query.parse_tree = parse_one(raw_query, dialect="postgres")
            except Exception as e:
                warnings.append(f"Query parsing failed: {e}")

        return query

    def _normalize_query(self, query: str) -> str:
        if SQLGLOT_AVAILABLE:
            try:
                parsed = parse_one(query, dialect="postgres")
                return parsed.sql(dialect="postgres", pretty=True)
            except Exception:
                pass

        query = re.sub(r"\s+", " ", query)
        query = query.strip()

        keywords = [
            "SELECT",
            "FROM",
            "WHERE",
            "GROUP BY",
            "ORDER BY",
            "HAVING",
            "LIMIT",
            "OFFSET",
            "JOIN",
            "INNER JOIN",
            "LEFT JOIN",
            "RIGHT JOIN",
            "FULL JOIN",
            "UNION",
            "INTERSECT",
            "EXCEPT",
            "WITH",
            "AS",
        ]

        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            query = re.sub(pattern, keyword, query, flags=re.IGNORECASE)

        return query

    def generate_all_queries(self, seed: Optional[int] = None, dialect: str = "ansi") -> list[QgenQuery]:
        if not self.check_availability():
            raise QgenExecutionError("TPC-H qgen tools not available")

        queries = []

        for query_id in range(1, 23):
            try:
                query = self.generate_query(query_id, seed, dialect)
                queries.append(query)
            except Exception as e:
                logger.warning(f"Failed to generate query {query_id}: {e}")
                error_query = QgenQuery(query_id=query_id, raw_query="", errors=[str(e)])
                queries.append(error_query)

        return queries

    def compare_with_python_query(
        self,
        query_id: int,
        python_query: str,
        seed: Optional[int] = None,
        comparison_level: ComparisonLevel = ComparisonLevel.STRUCTURAL,
    ) -> QueryComparisonResult:
        try:
            c_query_obj = self.generate_query(query_id, seed)
            c_query = c_query_obj.raw_query
            c_errors = c_query_obj.errors
        except Exception as e:
            c_query = ""
            c_errors = [str(e)]

        result = QueryComparisonResult(
            query_id=query_id,
            python_query=python_query,
            c_query=c_query,
            c_errors=c_errors,
        )

        if python_query and c_query:
            try:
                self._perform_comparison(result, comparison_level)
            except Exception as e:
                result.python_errors.append(f"Comparison failed: {e}")

        return result

    def _perform_comparison(self, result: QueryComparisonResult, comparison_level: ComparisonLevel) -> None:
        norm_python = self._normalize_query(result.python_query)
        norm_c = self._normalize_query(result.c_query)

        result.similarity_score = self._calculate_similarity(norm_python, norm_c)

        result.differences = self._identify_differences(norm_python, norm_c)

        if comparison_level in [ComparisonLevel.STRUCTURAL, ComparisonLevel.SEMANTIC]:
            result.structure_match = self._compare_structure(norm_python, norm_c)

        if comparison_level == ComparisonLevel.SEMANTIC:
            result.semantic_match = self._compare_semantics(norm_python, norm_c)

        if comparison_level == ComparisonLevel.PARAMETER:
            result.parameter_match = self._compare_parameters(norm_python, norm_c)

    def _calculate_similarity(self, query1: str, query2: str) -> float:
        import difflib

        return difflib.SequenceMatcher(None, query1, query2).ratio()

    def _identify_differences(self, query1: str, query2: str) -> list[str]:
        import difflib

        differences = []
        diff = difflib.unified_diff(
            query1.splitlines(),
            query2.splitlines(),
            fromfile="python",
            tofile="c",
            lineterm="",
        )

        for line in diff:
            if line.startswith(("+", "-")):
                differences.append(line)

        return differences

    def _compare_structure(self, query1: str, query2: str) -> bool:
        if SQLGLOT_AVAILABLE:
            try:
                parsed1 = parse_one(query1, dialect="postgres")
                parsed2 = parse_one(query2, dialect="postgres")

                return type(parsed1) == type(parsed2)

            except Exception:
                pass

        return self._compare_text_structure(query1, query2)

    def _compare_text_structure(self, query1: str, query2: str) -> bool:
        clauses1 = self._extract_sql_clauses(query1)
        clauses2 = self._extract_sql_clauses(query2)

        return set(clauses1.keys()) == set(clauses2.keys())

    def _extract_sql_clauses(self, query: str) -> dict[str, str]:
        clauses = {}

        clause_patterns = {
            "SELECT": r"SELECT\s+(.+?)(?=\s+FROM|\s*$)",
            "FROM": r"FROM\s+(.+?)(?=\s+WHERE|\s+GROUP\s+BY|\s+ORDER\s+BY|\s+LIMIT|\s*$)",
            "WHERE": r"WHERE\s+(.+?)(?=\s+GROUP\s+BY|\s+ORDER\s+BY|\s+LIMIT|\s*$)",
            "GROUP_BY": r"GROUP\s+BY\s+(.+?)(?=\s+HAVING|\s+ORDER\s+BY|\s+LIMIT|\s*$)",
            "HAVING": r"HAVING\s+(.+?)(?=\s+ORDER\s+BY|\s+LIMIT|\s*$)",
            "ORDER_BY": r"ORDER\s+BY\s+(.+?)(?=\s+LIMIT|\s*$)",
            "LIMIT": r"LIMIT\s+(.+?)(?=\s*$)",
        }

        for clause_name, pattern in clause_patterns.items():
            match = re.search(pattern, query, re.IGNORECASE | re.DOTALL)
            if match:
                clauses[clause_name] = match.group(1).strip()

        return clauses

    def _compare_semantics(self, query1: str, query2: str) -> bool:

        return self._compare_structure(query1, query2)

    def _compare_parameters(self, query1: str, query2: str) -> bool:
        param_pattern = r":\w+|\$\d+|\?\d*"

        params1 = set(re.findall(param_pattern, query1))
        params2 = set(re.findall(param_pattern, query2))

        return params1 == params2

    def generate_comparison_report(
        self,
        comparisons: list[QueryComparisonResult],
        output_file: Optional[Path] = None,
    ) -> str:
        report_lines = []

        report_lines.append("TPC-H Query Comparison Report")
        report_lines.append("=" * 50)
        report_lines.append("")

        total_queries = len(comparisons)
        successful_comparisons = sum(1 for c in comparisons if c.c_query and c.python_query)
        structure_matches = sum(1 for c in comparisons if c.structure_match)
        semantic_matches = sum(1 for c in comparisons if c.semantic_match)

        if successful_comparisons > 0:
            avg_similarity = (
                sum(c.similarity_score for c in comparisons if c.similarity_score > 0) / successful_comparisons
            )
        else:
            avg_similarity = 0

        report_lines.append(f"Total Queries: {total_queries}")
        report_lines.append(f"Successful Comparisons: {successful_comparisons}")
        report_lines.append(f"Structure Matches: {structure_matches} ({structure_matches / total_queries * 100:.1f}%)")
        report_lines.append(f"Semantic Matches: {semantic_matches} ({semantic_matches / total_queries * 100:.1f}%)")
        report_lines.append(f"Average Similarity: {avg_similarity:.3f}")
        report_lines.append("")

        report_lines.append("Detailed Results:")
        report_lines.append("-" * 20)

        for comp in comparisons:
            report_lines.append(f"Query {comp.query_id}:")
            report_lines.append(f"  Similarity Score: {comp.similarity_score:.3f}")
            report_lines.append(f"  Structure Match: {comp.structure_match}")
            report_lines.append(f"  Semantic Match: {comp.semantic_match}")
            report_lines.append(f"  Parameter Match: {comp.parameter_match}")

            if comp.differences:
                report_lines.append(f"  Differences: {len(comp.differences)}")
                for diff in comp.differences[:3]:
                    report_lines.append(f"    {diff}")
                if len(comp.differences) > 3:
                    report_lines.append(f"    ... and {len(comp.differences) - 3} more")

            if comp.python_errors or comp.c_errors:
                report_lines.append(f"  Errors: Python({len(comp.python_errors)}), C({len(comp.c_errors)})")
                for error in comp.python_errors[:2]:
                    report_lines.append(f"    Python: {error}")
                for error in comp.c_errors[:2]:
                    report_lines.append(f"    C: {error}")

            report_lines.append("")

        report = "\n".join(report_lines)

        if output_file:
            output_file.write_text(report)
            logger.info(f"Comparison report written to {output_file}")

        return report

    def cleanup(self) -> None:
        try:
            temp_files = self.tools_path.glob("*.tmp")
            for temp_file in temp_files:
                temp_file.unlink()

            if self.force_compile:
                with self._change_directory(self.tools_path):
                    self._run_make_command("clean", check=False)

        except Exception as e:
            if self.verbose:
                logger.warning(f"Cleanup failed: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


def create_qgen_wrapper(tpch_tools_path: Optional[Path] = None, verbose: bool = False) -> QGenWrapper:
    try:
        wrapper = QGenWrapper(tpch_tools_path=tpch_tools_path, verbose=verbose)

        if not wrapper.check_availability():
            raise QgenError("TPC-H C tools not available")

        return wrapper

    except Exception as e:
        raise QgenError(f"Failed to create qgen wrapper: {e}") from e


def compare_query_implementations(
    python_query: str,
    query_id: int,
    tpch_tools_path: Optional[Path] = None,
    seed: Optional[int] = None,
) -> QueryComparisonResult:
    with create_qgen_wrapper(tpch_tools_path) as wrapper:
        return wrapper.compare_with_python_query(query_id=query_id, python_query=python_query, seed=seed)


def batch_compare_queries(
    python_queries: dict[int, str],
    tpch_tools_path: Optional[Path] = None,
    seed: Optional[int] = None,
) -> list[QueryComparisonResult]:
    results = []

    with create_qgen_wrapper(tpch_tools_path) as wrapper:
        for query_id, python_query in python_queries.items():
            try:
                result = wrapper.compare_with_python_query(query_id=query_id, python_query=python_query, seed=seed)
                results.append(result)
            except Exception as e:
                error_result = QueryComparisonResult(
                    query_id=query_id,
                    python_query=python_query,
                    c_query="",
                    python_errors=[str(e)],
                )
                results.append(error_result)

    return results
