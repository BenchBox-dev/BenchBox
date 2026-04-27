"""Content validation for docs and blog prior to release.

This module checks markdown content for style guide violations that should
be caught before publication. Validates against BenchBox's voice and style
guidelines documented in _blog/BenchBox_Blog_Style_Guide.md.

Rule Categories:
- PUNCTUATION: Prohibited characters (em-dash, en-dash)
- VAGUE_CLAIMS: Unquantified statements that need specific data
- MARKETING: Corporate/marketing language to avoid
- HEDGING: Excessive hedging that undermines confidence
- CLICHE: Overused phrases that weaken writing
- PLATFORM_ADVOCACY: Biased language about specific platforms
- VOICE: First-person singular (use "we" not "I")
- RESTRICTED_VENDOR: Vendors with restrictive benchmark licensing (DeWitt clause)

Exception Mechanisms:
- VALIDATED_EXCEPTIONS: File-level exceptions for known, reviewed content
  (e.g., SQLGlot dialect docs that legitimately mention Oracle)
- Inline directives: Add <!-- content-ok: category --> to suppress warnings
  on that line or the following line (e.g., <!-- content-ok: restricted_vendor -->)

These rules are integrated into the release automation process and can also
be run standalone for pre-commit validation.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from benchbox.utils.printing import emit

# =============================================================================
# Rule Severity Levels
# =============================================================================


class Severity(Enum):
    """Severity level for content violations."""

    ERROR = "error"  # Must fix before release
    WARNING = "warning"  # Should fix, but can proceed
    SUGGESTION = "suggestion"  # Consider fixing


# =============================================================================
# Punctuation Rules (ERROR)
# =============================================================================

# Unicode code points for prohibited dash characters
EM_DASH = "\u2014"  # -
EN_DASH = "\u2013"  # -

PUNCTUATION_RULES: list[tuple[str, str, str]] = [
    (re.escape(EM_DASH), "em-dash (-)", "Use comma, colon, or hyphen instead"),
    (re.escape(EN_DASH), "en-dash (-)", "Use hyphen (-) for ranges"),
]

# =============================================================================
# Vague Claims Rules (WARNING)
# BenchBox principle: "Lead with Data, Not Opinions"
# =============================================================================

VAGUE_CLAIMS_RULES: list[tuple[str, str, str]] = [
    (r"\bmuch faster\b", "much faster", "Add specific numbers: '2.3x faster' or '45% reduction'"),
    (r"\bmuch slower\b", "much slower", "Add specific numbers: '3x slower' or 'added 2.1s overhead'"),
    (r"\bsignificantly better\b", "significantly better", "Quantify the improvement with metrics"),
    (r"\bsignificantly worse\b", "significantly worse", "Quantify the difference with metrics"),
    (r"\bsignificantly faster\b", "significantly faster", "Quantify: '2.3x faster' or 'completed in 45s vs 120s'"),
    (r"\bsignificantly slower\b", "significantly slower", "Quantify: '3x slower' or 'added 75s overhead'"),
    (r"\blarge dataset\b", "large dataset", "Specify size: '1.1B rows, 170GB' or 'TPC-H SF100'"),
    (r"\bsmall dataset\b", "small dataset", "Specify size: '10K rows' or 'TPC-H SF0.01'"),
    (r"\bhuge improvement\b", "huge improvement", "Quantify: '47% reduction' or '3.2x speedup'"),
    (r"\bbetter performance\b", "better performance", "Add metrics: 'completed in 45s' or '2.3x throughput'"),
    (r"\bpoor performance\b", "poor performance", "Add metrics: 'took 3 minutes' or 'only 100 rows/sec'"),
    (r"\bmany users\b", "many users", "Specify: '10,000+ users' or 'majority of respondents'"),
    (r"\bmost databases\b", "most databases", "Specify which ones: 'PostgreSQL, MySQL, and DuckDB'"),
    (r"\brecently\b", "recently", "Specify when: 'in January 2026' or 'in v0.2.0'"),
    (r"\ba lot of\b", "a lot of", "Be specific: use actual numbers or percentages"),
    (r"\bvery fast\b", "very fast", "Quantify: 'completed in 2.3s' or 'processes 1M rows/sec'"),
    (r"\bvery slow\b", "very slow", "Quantify: 'took 45 minutes' or 'only 100 rows/sec'"),
    (r"\bhigh performance\b", "high performance", "Add metrics: 'processes 10M rows/sec'"),
    (r"\blow latency\b", "low latency", "Quantify: 'p99 latency of 12ms'"),
    (r"\bhigh latency\b", "high latency", "Quantify: 'p99 latency exceeded 500ms'"),
]

# =============================================================================
# Marketing/Corporate Language Rules (WARNING)
# BenchBox anti-pattern: "Marketing-Speak"
# =============================================================================

MARKETING_RULES: list[tuple[str, str, str]] = [
    (r"\brevolutionary\b", "revolutionary", "Describe what it actually does instead"),
    (r"\bgame[- ]?changing\b", "game-changing", "Describe the specific improvement"),
    (r"\bworld[- ]?class\b", "world-class", "Use specific metrics or comparisons"),
    (r"\bcutting[- ]?edge\b", "cutting-edge", "Describe the specific innovation"),
    (r"\bnext[- ]?generation\b", "next-generation", "Describe what's different"),
    (r"\bindustry[- ]?leading\b", "industry-leading", "Provide supporting data"),
    (r"\bpassionate about\b", "passionate about", "Show don't tell: describe actions"),
    (r"\bleverage\b", "leverage", "Use 'use' instead"),
    (r"\bsynergy\b", "synergy", "Be specific about the benefit"),
    (r"\bparadigm shift\b", "paradigm shift", "Describe the actual change"),
    (r"\bdisruptive\b", "disruptive", "Describe the specific impact"),
    (r"\binnovative solution\b", "innovative solution", "Describe what it does"),
    (r"\bunlock the power\b", "unlock the power", "Be specific about capabilities"),
    (r"\bseamless integration\b", "seamless integration", "Describe the integration process"),
    (r"\brobust platform\b", "robust platform", "Describe specific reliability features"),
    (r"\bbest[- ]?in[- ]?class\b", "best-in-class", "Provide comparative metrics"),
    (r"\benterprise[- ]?grade\b", "enterprise-grade", "Describe specific features"),
    (r"\bmission[- ]?critical\b", "mission-critical", "Be specific about requirements"),
    (r"\bturnkey solution\b", "turnkey solution", "Describe what's included"),
    (r"\bscalable solution\b", "scalable solution", "Describe scaling characteristics"),
    (r"\bholistic approach\b", "holistic approach", "Be specific about methodology"),
    (r"\baction(able)? insights?\b", "actionable insights", "Describe what users can do"),
    (r"\bdata[- ]?driven\b", "data-driven", "Show the data instead"),
]

# =============================================================================
# Hedging Phrases Rules (SUGGESTION)
# BenchBox anti-pattern: "Hedging Everything"
# =============================================================================

HEDGING_RULES: list[tuple[str, str, str]] = [
    (r"\bit might possibly\b", "it might possibly", "Be more direct about findings"),
    (r"\bperhaps maybe\b", "perhaps maybe", "Choose one or be direct"),
    (r"\bsome might argue\b", "some might argue", "State the argument directly"),
    (r"\bit could potentially\b", "it could potentially", "State what it does or doesn't do"),
    (r"\bseems like it could\b", "seems like it could", "Be direct: 'it does' or 'it doesn't'"),
    (r"\bI think maybe\b", "I think maybe", "State findings directly (also use 'we')"),
    (r"\bpossibly perhaps\b", "possibly perhaps", "Be direct about uncertainty"),
    (r"\bkind of\b", "kind of", "Be precise or remove"),
    (r"\bsort of\b", "sort of", "Be precise or remove"),
    (r"\bmore or less\b", "more or less", "Provide specific numbers"),
    (r"\bto some extent\b", "to some extent", "Quantify the extent"),
    (r"\bin some cases\b", "in some cases", "Specify which cases"),
    (r"\bfor the most part\b", "for the most part", "Quantify or be specific"),
]

# =============================================================================
# Cliché Phrases Rules (SUGGESTION)
# =============================================================================

CLICHE_RULES: list[tuple[str, str, str]] = [
    (r"\bat the end of the day\b", "at the end of the day", "Remove or be direct"),
    (r"\blow[- ]?hanging fruit\b", "low-hanging fruit", "Describe the specific opportunity"),
    (r"\bmove the needle\b", "move the needle", "Describe the specific impact"),
    (r"\bboil the ocean\b", "boil the ocean", "Describe the scope concern"),
    (r"\bdrink the kool[- ]?aid\b", "drink the kool-aid", "Describe the concern directly"),
    (r"\bthink outside the box\b", "think outside the box", "Describe the creative approach"),
    (r"\b10,?000[- ]?foot view\b", "10,000-foot view", "Use 'overview' or 'summary'"),
    (r"\bdeep dive\b", "deep dive", "Use 'detailed analysis' or 'thorough examination'"),
    (r"\bpain point\b", "pain point", "Describe the specific problem"),
    (r"\bsecret sauce\b", "secret sauce", "Describe the specific technique"),
    (r"\bsilver bullet\b", "silver bullet", "Describe limitations directly"),
    (r"\bbandwidth\b", "bandwidth (for capacity)", "Use 'capacity' or 'availability'"),
    (r"\bsync up\b", "sync up", "Use 'meet' or 'discuss'"),
    (r"\bcircle back\b", "circle back", "Use 'follow up' or 'revisit'"),
    (r"\bloop in\b", "loop in", "Use 'include' or 'involve'"),
]

# =============================================================================
# Platform Advocacy Rules (ERROR)
# BenchBox principle: "Neutral on Platforms"
# =============================================================================

PLATFORM_ADVOCACY_RULES: list[tuple[str, str, str]] = [
    (r"\bclearly superior\b", "clearly superior", "Present data neutrally without judgment"),
    (r"\bclearly inferior\b", "clearly inferior", "Present data neutrally without judgment"),
    (r"\bobviously better\b", "obviously better", "Let data speak for itself"),
    (r"\bobviously worse\b", "obviously worse", "Let data speak for itself"),
    (r"\bshould be avoided\b", "should be avoided", "Present trade-offs, not recommendations"),
    (r"\bwaste of time\b", "waste of time", "Present findings without judgment"),
    (r"\bthe best choice\b", "the best choice", "Present options without advocacy"),
    (r"\bthe worst choice\b", "the worst choice", "Present options without advocacy"),
    (r"\bthe only choice\b", "the only choice", "Present as 'one option' with trade-offs"),
    (r"\bneeds to fix\b", "needs to fix", "Report findings, don't prescribe vendor actions"),
    (r"\bfailing to\b", "failing to", "Use neutral language: 'does not currently'"),
    (r"\bwake up\b", "wake up (to vendors)", "Avoid telling vendors what to do"),
    (r"\babsolutely destroyed\b", "absolutely destroyed", "Use neutral comparison language"),
    (r"\bcrushes\b", "crushes", "Use neutral comparison: 'outperformed by X%'"),
    (r"\bwins hands down\b", "wins hands down", "Present data without declaring winners"),
    (r"\bloses badly\b", "loses badly", "Present data without judgment"),
]

# =============================================================================
# Voice Rules (WARNING)
# BenchBox principle: "Community-Inclusive" - use "we" not "I"
# =============================================================================

VOICE_RULES: list[tuple[str, str, str]] = [
    (r"\bI think\b", "I think", "Use 'we found' or 'our testing showed'"),
    (r"\bI believe\b", "I believe", "Use 'we believe' or state findings directly"),
    (r"\bI found\b", "I found", "Use 'we found' or 'our analysis showed'"),
    (r"\bIn my opinion\b", "In my opinion", "Use 'Based on our testing' or remove"),
    (r"\bIn my experience\b", "In my experience", "Use 'In our experience' or 'Our testing showed'"),
    (r"\bI recommend\b", "I recommend", "Use 'we recommend' or present as option"),
    (r"\bI suggest\b", "I suggest", "Use 'we suggest' or 'consider'"),
    (r"\bmy view\b", "my view", "Use 'our view' or 'the data suggests'"),
    (r"\bmy testing\b", "my testing", "Use 'our testing'"),
    (r"\bmy analysis\b", "my analysis", "Use 'our analysis'"),
]

# =============================================================================
# Restricted Vendor Rules (WARNING)
# Vendors with restrictive benchmark licensing (DeWitt clause)
# =============================================================================

RESTRICTED_VENDOR_RULES: list[tuple[str, str, str]] = [
    (
        r"\bOracle\b",
        "Oracle",
        "Oracle may only be mentioned in reference to the DeWitt clause. "
        "Remove or rephrase to avoid implying Oracle platform support.",
    ),
]

# =============================================================================
# Configuration
# =============================================================================

# Glob patterns for content directories to validate
DEFAULT_CONTENT_PATTERNS: Sequence[str] = (
    "_blog/**/*.md",
    "docs/**/*.md",
    "docs/**/*.rst",
)

# Files to exclude from validation (relative to repo root)
VALIDATION_EXCLUDES: Sequence[str] = (
    "docs/_build",  # Built docs
    "docs/_tags",  # Generated tag pages
)

# =============================================================================
# Validated Exceptions
# Files with known, reviewed exceptions for specific rule categories.
# Format: {file_pattern: [categories]} - uses fnmatch for pattern matching
# =============================================================================

VALIDATED_EXCEPTIONS: dict[str, Sequence[str]] = {
    # SQLGlot dialect documentation - describes SQLGlot's capabilities, not BenchBox support
    "docs/usage/dialect-translation.md": ["restricted_vendor"],
    "docs/reference/python-api/utilities.rst": ["restricted_vendor"],
    # Comparative analysis of other benchmarking tools (HammerDB, etc.)
    "docs/concepts/benchmarking-tools-compared.md": ["restricted_vendor"],
    "_blog/**/hammerdb*.md": ["restricted_vendor"],
    "_blog/**/benchmarking-tools-compared.md": ["restricted_vendor"],
    # Free trial series mentions database connectors supported by cloud platforms
    "_blog/free-trial-benchmarking/**/*.md": ["restricted_vendor"],
    # Technical blog posts discussing database technology in general
    "_blog/analytics-architecture/**/*.md": ["restricted_vendor"],
    # Publishing guide intentionally uses negative examples to illustrate style violations
    "_blog/PUBLISHING.md": ["platform_advocacy", "vague_claims", "marketing", "punctuation", "cliche", "hedging"],
}

# Inline ignore directive pattern: <!-- content-ok: category1, category2 -->
# Can appear on the same line or the line immediately before
IGNORE_DIRECTIVE_PATTERN = re.compile(r"<!--\s*content-ok:\s*([^>]+?)\s*-->", re.IGNORECASE)

# Map rule categories to their rules and severity
RULE_CATEGORIES: dict[str, tuple[Severity, list[tuple[str, str, str]]]] = {
    "punctuation": (Severity.ERROR, PUNCTUATION_RULES),
    "platform_advocacy": (Severity.ERROR, PLATFORM_ADVOCACY_RULES),
    "restricted_vendor": (Severity.WARNING, RESTRICTED_VENDOR_RULES),
    "marketing": (Severity.WARNING, MARKETING_RULES),
    "vague_claims": (Severity.WARNING, VAGUE_CLAIMS_RULES),
    "voice": (Severity.WARNING, VOICE_RULES),
    "hedging": (Severity.SUGGESTION, HEDGING_RULES),
    "cliche": (Severity.SUGGESTION, CLICHE_RULES),
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ContentViolation:
    """A single content validation violation."""

    file_path: Path
    line_number: int
    column: int
    matched_text: str
    context: str
    rule: str
    category: str
    severity: Severity
    suggestion: str

    def __str__(self) -> str:
        severity_prefix = {
            Severity.ERROR: "❌",
            Severity.WARNING: "⚠️ ",
            Severity.SUGGESTION: "💡",
        }
        prefix = severity_prefix.get(self.severity, "")
        display_path = self.file_path.as_posix()
        return (
            f"{prefix} {display_path}:{self.line_number}:{self.column}: "
            f"'{self.matched_text}' [{self.category}]\n"
            f"   {self.context}\n"
            f"   → {self.suggestion}"
        )


@dataclass
class ValidationResult:
    """Result of content validation across files."""

    violations: list[ContentViolation] = field(default_factory=list)
    files_checked: int = 0
    files_with_violations: int = 0

    @property
    def passed(self) -> bool:
        """Check if validation passed (no errors)."""
        return not any(v.severity == Severity.ERROR for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    @property
    def suggestion_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.SUGGESTION)

    def summary(self) -> str:
        if len(self.violations) == 0:
            return f"✓ Content validation passed ({self.files_checked} files checked)"

        parts = []
        if self.error_count > 0:
            parts.append(f"{self.error_count} error(s)")
        if self.warning_count > 0:
            parts.append(f"{self.warning_count} warning(s)")
        if self.suggestion_count > 0:
            parts.append(f"{self.suggestion_count} suggestion(s)")

        status = "❌ FAILED" if not self.passed else "⚠️  WARNINGS"
        return f"{status}: {', '.join(parts)} in {self.files_with_violations} file(s)"


# =============================================================================
# Validation Functions
# =============================================================================


def _should_skip_file(file_path: Path, repo_root: Path) -> bool:
    """Check if a file should be skipped from validation.

    Args:
        file_path: Absolute path to the file
        repo_root: Repository root path

    Returns:
        True if the file should be skipped
    """
    try:
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        return True  # File outside repo

    rel_str = rel_path.as_posix()
    for exclude in VALIDATION_EXCLUDES:
        if rel_str.startswith(exclude):
            return True
    return False


def _get_file_exceptions(file_path: Path, repo_root: Path) -> set[str]:
    """Get categories that are excepted for a specific file.

    Args:
        file_path: Absolute path to the file
        repo_root: Repository root path

    Returns:
        Set of category names that should be skipped for this file
    """
    try:
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        return set()

    rel_str = rel_path.as_posix()
    excepted_categories: set[str] = set()

    for pattern, categories in VALIDATED_EXCEPTIONS.items():
        if fnmatch.fnmatch(rel_str, pattern):
            excepted_categories.update(categories)

    return excepted_categories


def _has_inline_ignore(lines: list[str], line_idx: int, category: str) -> bool:
    """Check if a line has an inline ignore directive for the given category.

    Checks both the current line and the previous line for directives like:
    <!-- content-ok: restricted_vendor -->
    <!-- content-ok: restricted_vendor, marketing -->

    Args:
        lines: All lines in the file
        line_idx: Index of the current line (0-based)
        category: Category to check for

    Returns:
        True if the line should be ignored for this category
    """
    # Check current line and previous line
    lines_to_check = [lines[line_idx]]
    if line_idx > 0:
        lines_to_check.append(lines[line_idx - 1])

    for check_line in lines_to_check:
        match = IGNORE_DIRECTIVE_PATTERN.search(check_line)
        if match:
            # Parse comma-separated categories
            directive_categories = [c.strip().lower() for c in match.group(1).split(",")]
            if category.lower() in directive_categories or "all" in directive_categories:
                return True

    return False


def _get_context(line: str, match_start: int, match_end: int, max_len: int = 60) -> str:
    """Extract context around a match for display.

    Args:
        line: The full line of text
        match_start: Start position of the match
        match_end: End position of the match
        max_len: Maximum context length

    Returns:
        Context string with ellipsis if truncated
    """
    half_context = (max_len - (match_end - match_start)) // 2
    start = max(0, match_start - half_context)
    end = min(len(line), match_end + half_context)
    context = line[start:end]
    if start > 0:
        context = "..." + context
    if end < len(line):
        context = context + "..."
    return context


def _is_example_line(line: str, lines: list[str], line_idx: int) -> bool:
    """Check if a line is an example of what NOT to do (skip validation).

    Style guides often show anti-patterns as examples. These lines should not
    be flagged as violations since they're demonstrating bad practices to avoid.

    Args:
        line: The line to check
        lines: All lines in the file (for context)
        line_idx: Index of the current line (0-based)

    Returns:
        True if the line appears to be a "don't do this" example
    """
    stripped = line.strip()

    # Lines with explicit ❌ markers (bullet, table column, or blockquote).
    if (
        stripped.startswith("❌")
        or stripped.startswith("- ❌")
        or "| ❌" in line
        or "|❌" in line
        or (stripped.startswith(">") and "❌" in stripped)
    ):
        return True

    # Table rows after a "| Don't |" or "| If you wrote |" header row
    # These tables show anti-patterns in the first column
    if stripped.startswith("|"):
        # Look back up to 20 lines for a header indicating anti-patterns
        anti_pattern_headers = ["Don't", "If you wrote", "Instead of"]
        for i in range(max(0, line_idx - 20), line_idx):
            prev_line = lines[i].strip()
            if prev_line.startswith("|"):
                for header in anti_pattern_headers:
                    if header in prev_line:
                        return True

    # Bullet points under "❌ **Don't**:" sections
    # Look back for a "Don't" header
    if stripped.startswith("-") and stripped.startswith('- "'):
        for i in range(max(0, line_idx - 10), line_idx):
            prev_line = lines[i].strip()
            if "Don't" in prev_line and ("❌" in prev_line or "**Don't**" in prev_line):
                return True

    # Blockquotes showing bad examples (lines starting with >)
    # Check if preceded by a "Bad" or "Don't" label
    if stripped.startswith(">"):
        for i in range(max(0, line_idx - 3), line_idx):
            prev_line = lines[i].strip()
            if "**Bad**" in prev_line or "Bad:" in prev_line or "Don't" in prev_line:
                return True

    return False


def _find_violations_for_rules(
    content: str,
    file_path: Path,
    category: str,
    severity: Severity,
    rules: list[tuple[str, str, str]],
) -> list[ContentViolation]:
    """Find violations for a set of rules.

    Args:
        content: File content to check
        file_path: Path to the file (for error reporting)
        category: Rule category name
        severity: Severity level for these rules
        rules: List of (pattern, display_name, suggestion) tuples

    Returns:
        List of violations found
    """
    violations: list[ContentViolation] = []
    lines = content.split("\n")

    for line_idx, line in enumerate(lines):
        line_num = line_idx + 1
        # Skip code blocks (basic heuristic: lines starting with spaces/tabs or ```)
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("    ") or stripped.startswith("\t"):
            continue
        # Skip lines that are clearly code (contain common code patterns)
        if "def " in line or "class " in line or "import " in line or "from " in line:
            continue
        # Skip example lines showing anti-patterns (style guide "Don't" examples)
        if _is_example_line(line, lines, line_idx):
            continue

        # Check for inline ignore directive for this category
        if _has_inline_ignore(lines, line_idx, category):
            continue

        for pattern, display_name, suggestion in rules:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                col = match.start() + 1
                context = _get_context(line, match.start(), match.end())
                matched_text = match.group()

                violations.append(
                    ContentViolation(
                        file_path=file_path,
                        line_number=line_num,
                        column=col,
                        matched_text=matched_text,
                        context=context,
                        rule=display_name,
                        category=category,
                        severity=severity,
                        suggestion=suggestion,
                    )
                )

    return violations


def validate_file(
    file_path: Path,
    categories: Sequence[str] | None = None,
    repo_root: Path | None = None,
) -> list[ContentViolation]:
    """Validate a single file for content violations.

    Args:
        file_path: Path to the file to validate
        categories: Rule categories to check (default: all)
        repo_root: Repository root for checking file-level exceptions

    Returns:
        List of violations found
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []  # Skip files that can't be read

    if categories is None:
        categories = list(RULE_CATEGORIES.keys())

    # Get file-level exceptions if repo_root is provided
    excepted_categories: set[str] = set()
    if repo_root is not None:
        excepted_categories = _get_file_exceptions(file_path, repo_root)

    violations: list[ContentViolation] = []

    for category in categories:
        if category not in RULE_CATEGORIES:
            continue
        # Skip categories that have validated exceptions for this file
        if category in excepted_categories:
            continue
        severity, rules = RULE_CATEGORIES[category]
        violations.extend(_find_violations_for_rules(content, file_path, category, severity, rules))

    return violations


def validate_content(
    repo_root: Path,
    patterns: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    verbose: bool = False,
) -> ValidationResult:
    """Validate content files in the repository for style violations.

    Args:
        repo_root: Root directory of the repository
        patterns: Glob patterns for files to check (default: blog and docs)
        categories: Rule categories to check (default: all)
        verbose: Print progress information

    Returns:
        ValidationResult with all violations found
    """
    if patterns is None:
        patterns = DEFAULT_CONTENT_PATTERNS

    result = ValidationResult()
    checked_files: set[Path] = set()
    files_with_issues: set[Path] = set()

    for pattern in patterns:
        for file_path in repo_root.glob(pattern):
            if not file_path.is_file():
                continue
            if file_path in checked_files:
                continue
            if _should_skip_file(file_path, repo_root):
                continue

            checked_files.add(file_path)

            if verbose:
                rel_path = file_path.relative_to(repo_root)
                emit(f"  Checking {rel_path}...")

            violations = validate_file(file_path, categories, repo_root)
            if violations:
                result.violations.extend(violations)
                files_with_issues.add(file_path)

    result.files_checked = len(checked_files)
    result.files_with_violations = len(files_with_issues)

    return result


def check_content_for_release(
    source: Path,
    auto_continue: bool = False,
    errors_only: bool = False,
) -> bool:
    """Run content validation as part of release process.

    This function is designed to be called from the release automation script.
    It validates blog and docs content and prints results.

    Args:
        source: Source repository path
        auto_continue: If True, print warning but don't fail on violations
        errors_only: If True, only check for ERROR-level violations

    Returns:
        True if validation passed (no errors), False otherwise
    """
    emit("\n" + "=" * 60)
    emit("Content Validation (Docs & Blog)")
    emit("=" * 60)
    emit("Checking for style guide violations...\n")

    result = validate_content(source, verbose=False)

    if len(result.violations) == 0:
        emit(result.summary())
        return True

    # Group violations by severity
    errors = [v for v in result.violations if v.severity == Severity.ERROR]
    warnings = [v for v in result.violations if v.severity == Severity.WARNING]
    suggestions = [v for v in result.violations if v.severity == Severity.SUGGESTION]

    # Show errors (always)
    if errors:
        emit(f"ERRORS ({len(errors)}) - Must fix before release:\n")
        for violation in errors[:15]:
            emit(str(violation))
            emit()
        if len(errors) > 15:
            emit(f"... and {len(errors) - 15} more errors\n")

    # Show warnings (unless errors_only)
    if warnings and not errors_only:
        emit(f"WARNINGS ({len(warnings)}) - Should fix:\n")
        for violation in warnings[:10]:
            emit(str(violation))
            emit()
        if len(warnings) > 10:
            emit(f"... and {len(warnings) - 10} more warnings\n")

    # Show suggestions count only
    if suggestions and not errors_only:
        emit(f"SUGGESTIONS ({len(suggestions)}) - Consider reviewing\n")

    emit(result.summary())
    emit("\nSee _blog/BenchBox_Blog_Style_Guide.md for voice and style guidance.")

    if auto_continue:
        emit("\n⚠️  Continuing despite violations (--auto-continue)")
        return True

    return result.passed


__all__ = [
    "ContentViolation",
    "ValidationResult",
    "Severity",
    "validate_file",
    "validate_content",
    "check_content_for_release",
    "RULE_CATEGORIES",
    "EM_DASH",
    "EN_DASH",
]
