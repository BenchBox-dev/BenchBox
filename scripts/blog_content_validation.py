#!/usr/bin/env python3
"""Blog content validation tool.

Validates blog posts, drafts, and style guides against editorial and voice rules
defined in _blog/STYLE_GUIDE.md and _blog/VOICE_REFERENCE.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    """Severity levels for content validation findings."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """A single validation finding."""

    file_path: Path
    line_number: int
    category: str
    severity: Severity
    message: str
    matched_text: str
    line_content: str


@dataclass
class ValidationResult:
    """Validation result for a single file."""

    file_path: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """True if any findings have ERROR severity."""
        return any(f.severity == Severity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        """True if any findings have WARNING severity."""
        return any(f.severity == Severity.WARNING for f in self.findings)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors."""
        return not self.has_errors


# Patterns for validation rules

# Error-level rules
RE_EM_DASH = re.compile(r"\u2014")
RE_EN_DASH = re.compile(r"\u2013")
RE_PLATFORM_WINNER = re.compile(
    r"\b(destroys? the competition|beats? the competition|clearly superior|clearly inferior|"
    r"clear winner|undisputed winner|wins across the board|"
    r"proves\s+(?:[\w-]+\s+){1,4}is\s+(?:the\s+)?best(?:\s+choice)?|"
    r"platform\s+[\w-]+\s+is\s+best(?:\s+for)?)\b",
    re.IGNORECASE,
)

# Warning-level rules
RE_SUPERLATIVE = re.compile(
    r"\b(revolutionary|game-changing|mind-blowing|groundbreaking|unmatched performance|"
    r"blazing(?:ly)? fast|lightning fast|infinitely faster)\b",
    re.IGNORECASE,
)
RE_VENDOR_SERMON = re.compile(
    r"\b(\w+ needs to fix|needs to rethink (?:their|its) architecture|clearly gouging|backed the wrong horse)\b",
    re.IGNORECASE,
)
RE_FIRST_PERSON = re.compile(r"\b(I(?!\s*/)|I'(?:m|ve|ll|d)|my|My|me|Me|mine|Mine|myself|Myself)\b")
RE_BANNED_HEDGE = re.compile(
    r"\b(your mileage may vary|worth considering|may help|each platform has different strengths)\b",
    re.IGNORECASE,
)

# LLM writing tells and conversational residue
RE_LLM_CONVERSATIONAL = re.compile(
    r"^\s*(?:>\s*)*(?:good point|you're right|certainly!|sure thing|as mentioned earlier)\b",
    re.IGNORECASE,
)
RE_LLM_TEMPORAL = re.compile(
    r"\b(going forward|moving forward)\b",
    re.IGNORECASE,
)
RE_LLM_CLICHE_OPENER = re.compile(
    r"\b(in today's (?:fast-paced )?(?:digital |tech )?(?:landscape|world)|"
    r"in the (?:fast-)?evolving (?:realm|landscape) of|"
    r"whether you're a seasoned \w+ or just starting out|"
    r"let's (?:dive|delve) into|take a deep dive into)\b",
    re.IGNORECASE,
)
RE_LLM_BUZZWORDS = re.compile(
    r"\b(delve|delving|delves|rich tapestry|stands? as a testament to|beacon of innovation|seamless(?:ly|ness)?)\b",
    re.IGNORECASE,
)
RE_LLM_FORMULAIC_CONCLUSION = re.compile(
    r"^\s*(?:#+\s*)?(?:In conclusion|To summarize|All in all|To sum up)\b",
    re.IGNORECASE,
)

# Content-ok override pattern: <!-- content-ok: category --> or <!-- content-ok -->
RE_CONTENT_OK = re.compile(r"<!--\s*content-ok(?::\s*([a-zA-Z0-9_-]+))?\s*-->")

# Allowed negation patterns that are not denial couplets
RE_ALLOWED_NEGATION = re.compile(
    r"\b(not yet supported|not supported yet|not supported|not_run|not run)\b",
    re.IGNORECASE,
)

# Affirmation-plus-denial couplet patterns
RE_SAME_LINE_AFFIRM_DENY = re.compile(
    r"[.?!;]\s+(?:It|They|This|We|That|[A-Z][a-zA-Z0-9_-]*)\s+(?:is not|are not|was not|were not|does not|do not|did not|cannot)\b",
    re.IGNORECASE,
)
RE_SAME_LINE_DENY_AFFIRM = re.compile(
    r"\b(?:this|it|they) is not\b.*?\b(?:it is|they are)\b|\bnot just\b.*?\bbut (?:also\b)?",
    re.IGNORECASE,
)
RE_LINE_START_DENIAL = re.compile(
    r"^(?:It|They|This|We|That|[A-Z][a-zA-Z0-9_-]*)\s+(?:is not|are not|was not|were not|does not|do not|did not|cannot)\b",
    re.IGNORECASE,
)

# Guide files where Avoid/Don't examples are legitimate
GUIDE_FILENAME_PATTERNS = ("STYLE_GUIDE.md", "VOICE_REFERENCE.md", "PUBLISHING.md", "_guide.md", "_reference.md")


def is_guide_file(path: Path) -> bool:
    """Check if the given path is a style guide or voice reference."""
    name = path.name.lower()
    return any(name.endswith(pattern.lower()) for pattern in GUIDE_FILENAME_PATTERNS)


def extract_content_ok_categories(text: str) -> set[str]:
    """Extract content-ok override categories from a line or comment."""
    categories: set[str] = set()
    for match in RE_CONTENT_OK.finditer(text):
        cat = match.group(1)
        if cat:
            categories.add(cat.strip().lower())
        else:
            categories.add("all")
    return categories


class GuideContextTracker:
    """Tracks state within style guide files to avoid false positives on negative examples."""

    def __init__(self, is_guide: bool) -> None:
        self.is_guide = is_guide
        self.in_dont_block = False
        self.in_before_block = False
        self.in_anti_patterns_section = False
        self.table_avoid_col_indices: set[int] = set()

    def update_line(self, line: str, stripped: str) -> None:
        """Update tracker state based on current line content."""
        if not self.is_guide:
            return
        if stripped.startswith("#"):
            self.in_dont_block = False
            self.in_before_block = False
            self.in_anti_patterns_section = bool(re.search(r"anti-patterns", line, re.IGNORECASE))
        elif stripped == "---":
            self.in_dont_block = False
            self.in_before_block = False
            self.in_anti_patterns_section = False
        elif stripped.startswith(("**Before", "> Before", "Before (")):
            self.in_before_block = True
        elif stripped.startswith(("**After", "> After", "After (")):
            self.in_before_block = False
        elif "❌" in line or line.startswith(("Don't:", "- ❌")):
            self.in_dont_block = True
        elif "✅" in line or line.startswith(("Do:", "- ✅")):
            self.in_dont_block = False

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if any(k in cells[0].lower() for k in ("write", "don't", "dont", "if you wrote", "instead of")):
                self.table_avoid_col_indices = {
                    i
                    for i, c in enumerate(cells)
                    if any(
                        k in c.lower() for k in ("avoid", "don't", "dont", "if you wrote", "anti-pattern", "instead of")
                    )
                }
        else:
            self.table_avoid_col_indices = set()

    def should_skip_prose(self) -> bool:
        """Check if current state requires skipping all prose checks."""
        if not self.is_guide:
            return False
        return self.in_dont_block or self.in_before_block or self.in_anti_patterns_section

    def filter_prose_line(self, line: str, stripped: str) -> str | None:
        """Filter Avoid cells from a table row or return full line if appropriate."""
        if self.should_skip_prose():
            return None
        if not self.is_guide:
            return line
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if any("---" in c for c in cells) or any(k in cells[0].lower() for k in ("write", "character")):
                return None
            prose_cells = [c for i, c in enumerate(cells) if i not in self.table_avoid_col_indices]
            return " ".join(prose_cells)
        return line


def check_punctuation(line: str, idx: int, path: Path, is_guide: bool) -> list[Finding]:
    """Check for forbidden em-dashes and en-dashes."""
    findings: list[Finding] = []
    em_match = RE_EM_DASH.search(line)
    if em_match and not (is_guide and ("U+2014" in line or "Prohibited" in line or "Punctuation Rules" in line)):
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="punctuation",
                severity=Severity.ERROR,
                message="Use of Unicode em-dash (U+2014) is prohibited. Use ASCII hyphen or punctuation.",
                matched_text=em_match.group(0),
                line_content=line,
            )
        )

    en_match = RE_EN_DASH.search(line)
    if en_match and not (is_guide and ("U+2013" in line or "Prohibited" in line or "Punctuation Rules" in line)):
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="punctuation",
                severity=Severity.ERROR,
                message="Use of Unicode en-dash (U+2013) is prohibited. Use ASCII hyphen.",
                matched_text=en_match.group(0),
                line_content=line,
            )
        )
    return findings


def check_platform_winner(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for platform-winner verdict claims."""
    match = RE_PLATFORM_WINNER.search(line)
    if match:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="platform_winner",
                severity=Severity.ERROR,
                message="Platform-winner verdicts violate neutral reporting policy.",
                matched_text=match.group(0),
                line_content=line,
            )
        ]
    return []


def check_marketing_and_superlatives(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for unsourced superlatives and marketing hype."""
    match = RE_SUPERLATIVE.search(line)
    if match:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="unsourced_superlatives",
                severity=Severity.WARNING,
                message="Avoid empty superlatives and marketing hype.",
                matched_text=match.group(0),
                line_content=line,
            )
        ]
    return []


def check_vendor_sermons(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for vendor critique sermons."""
    match = RE_VENDOR_SERMON.search(line)
    if match:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="vendor_sermons",
                severity=Severity.WARNING,
                message="Focus on benchmark findings rather than vendor advice or critiques.",
                matched_text=match.group(0),
                line_content=line,
            )
        ]
    return []


def check_first_person(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for first-person singular pronouns in post prose."""
    findings: list[Finding] = []
    for match in RE_FIRST_PERSON.finditer(line):
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="first_person",
                severity=Severity.WARNING,
                message="Use community 'we' rather than first-person singular 'I'.",
                matched_text=match.group(0),
                line_content=line,
            )
        )
    return findings


def check_banned_hedges(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for banned hedge phrases."""
    match = RE_BANNED_HEDGE.search(line)
    if match:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="banned_hedges",
                severity=Severity.WARNING,
                message="Banned hedge phrase; report the measurement and conditions or use direct imperatives.",
                matched_text=match.group(0),
                line_content=line,
            )
        ]
    return []


def check_llm_writing_tells(line: str, idx: int, path: Path) -> list[Finding]:
    """Check for conversational residue, cliché openers, and AI vocabulary."""
    findings: list[Finding] = []
    conv_match = RE_LLM_CONVERSATIONAL.search(line)
    if conv_match:
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="llm_tells",
                severity=Severity.WARNING,
                message="Conversational residue detected (e.g. 'good point', 'you're right'). State content directly.",
                matched_text=conv_match.group(0).strip(),
                line_content=line,
            )
        )

    temp_match = RE_LLM_TEMPORAL.search(line)
    if temp_match:
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="llm_tells",
                severity=Severity.WARNING,
                message="Vague temporal transition ('going forward' / 'moving forward'). Use concrete milestones or dates.",
                matched_text=temp_match.group(0),
                line_content=line,
            )
        )

    cliche_match = RE_LLM_CLICHE_OPENER.search(line)
    if cliche_match:
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="llm_tells",
                severity=Severity.WARNING,
                message="Formulaic AI opener detected. Cut empty throat-clearing and lead with what happened or was built.",
                matched_text=cliche_match.group(0),
                line_content=line,
            )
        )

    for buzz_match in RE_LLM_BUZZWORDS.finditer(line):
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="llm_tells",
                severity=Severity.WARNING,
                message=(
                    "AI vocabulary cliché detected ('delve', 'tapestry', 'testament to', 'seamless'). "
                    "Use concrete plain verbs."
                ),
                matched_text=buzz_match.group(0),
                line_content=line,
            )
        )

    conc_match = RE_LLM_FORMULAIC_CONCLUSION.search(line)
    if conc_match:
        findings.append(
            Finding(
                file_path=path,
                line_number=idx,
                category="llm_tells",
                severity=Severity.WARNING,
                message="Formulaic essay conclusion header. Use specific section headings.",
                matched_text=conc_match.group(0).strip(),
                line_content=line,
            )
        )

    return findings


def check_affirmation_denial_couplet(
    line: str,
    stripped: str,
    prev_line: str | None,
    idx: int,
    path: Path,
) -> list[Finding]:
    """Advisory check for affirmation-plus-denial singleton couplets."""
    if stripped.startswith("#") or RE_ALLOWED_NEGATION.search(line):
        return []

    m_affirm_deny = RE_SAME_LINE_AFFIRM_DENY.search(line)
    if m_affirm_deny:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="couplet",
                severity=Severity.INFO,
                message="Possible affirmation-plus-denial couplet. State the point once without echoing denial.",
                matched_text=m_affirm_deny.group(0).strip(".?!; "),
                line_content=line,
            )
        ]

    m_deny_affirm = RE_SAME_LINE_DENY_AFFIRM.search(line)
    if m_deny_affirm:
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="couplet",
                severity=Severity.INFO,
                message="Possible affirmation-plus-denial couplet. State the point once without echoing denial.",
                matched_text=m_deny_affirm.group(0).strip(),
                line_content=line,
            )
        ]

    if prev_line and prev_line.rstrip()[-1:] in ".?!;" and RE_LINE_START_DENIAL.search(stripped):
        m_start_denial = RE_LINE_START_DENIAL.search(stripped)
        matched = m_start_denial.group(0) if m_start_denial else stripped[:30]
        return [
            Finding(
                file_path=path,
                line_number=idx,
                category="couplet",
                severity=Severity.INFO,
                message=(
                    "Possible affirmation-plus-denial couplet across adjacent lines. "
                    "State the point once without echoing denial."
                ),
                matched_text=matched,
                line_content=line,
            )
        ]

    return []


def validate_file(file_path: Path | str, repo_root: Path | str | None = None) -> ValidationResult:
    """Validate a single markdown file against blog voice and style rules.

    Args:
        file_path: Path to the markdown file.
        repo_root: Optional root directory of the repository.

    Returns:
        ValidationResult containing all findings.
    """
    path = Path(file_path)
    result = ValidationResult(file_path=path)

    if not path.exists():
        result.findings.append(
            Finding(
                file_path=path,
                line_number=0,
                category="file_not_found",
                severity=Severity.ERROR,
                message=f"File not found: {path}",
                matched_text="",
                line_content="",
            )
        )
        return result

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        result.findings.append(
            Finding(
                file_path=path,
                line_number=0,
                category="encoding",
                severity=Severity.ERROR,
                message=f"Unable to read file as UTF-8: {err}",
                matched_text="",
                line_content="",
            )
        )
        return result

    lines = content.splitlines()
    in_code_block = False
    is_guide = is_guide_file(path)
    guide_tracker = GuideContextTracker(is_guide=is_guide)
    pending_override: set[str] = set()
    last_prose_line: str | None = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            last_prose_line = None
            continue

        current_override = extract_content_ok_categories(line)
        active_overrides = pending_override | current_override
        pending_override = (
            current_override if "<!-- content-ok" in line and not stripped.startswith("<!-- content-ok") else set()
        )
        if stripped.startswith("<!-- content-ok"):
            pending_override = current_override

        def is_suppressed(category: str) -> bool:
            return "all" in active_overrides or category.lower() in active_overrides

        guide_tracker.update_line(line, stripped)

        # Rule 1: Punctuation (em-dash and en-dash) - Error
        if not is_suppressed("punctuation"):
            result.findings.extend(check_punctuation(line, idx, path, is_guide))

        # Skip prose rules inside code blocks
        if in_code_block:
            last_prose_line = None
            continue

        prose_line = guide_tracker.filter_prose_line(line, stripped)
        if prose_line is None:
            last_prose_line = None
            continue

        clean_prose = re.sub(r"`[^`]*`", "", prose_line)

        # Rule 2: Platform winner verdicts - Error
        if not is_suppressed("platform_winner") and not is_suppressed("platform_advocacy"):
            result.findings.extend(check_platform_winner(clean_prose, idx, path))

        # Rule 3: Unsourced superlatives / marketing hype - Warning
        if not is_suppressed("unsourced_superlatives") and not is_suppressed("marketing"):
            result.findings.extend(check_marketing_and_superlatives(clean_prose, idx, path))

        # Rule 4: Vendor-fix sermons - Warning
        if not is_suppressed("vendor_sermons") and not is_suppressed("restricted_vendor"):
            result.findings.extend(check_vendor_sermons(clean_prose, idx, path))

        # Rule 5: First-person singular in post prose - Warning
        if not is_guide and not is_suppressed("first_person") and not is_suppressed("voice"):
            result.findings.extend(check_first_person(clean_prose, idx, path))

        # Rule 6: Banned hedges - Warning
        if not is_suppressed("banned_hedges") and not is_suppressed("hedging"):
            result.findings.extend(check_banned_hedges(clean_prose, idx, path))

        # Rule 7: LLM writing tells and conversational residue - Warning
        if not is_suppressed("llm_tells") and not is_suppressed("ai_tells"):
            result.findings.extend(check_llm_writing_tells(clean_prose, idx, path))

        # Rule 8: Affirmation-plus-denial couplet advisory check - Info
        if not is_guide and not is_suppressed("couplet"):
            result.findings.extend(check_affirmation_denial_couplet(clean_prose, stripped, last_prose_line, idx, path))

        # Update last prose line for adjacent line couplet detection
        if stripped and not stripped.startswith(("#", "```", "|", "- ", "* ", ">")):
            last_prose_line = clean_prose.strip()
        else:
            last_prose_line = None

    return result


def validate_content(
    root: Path | str,
    patterns: list[str] | None = None,
    verbose: bool = False,
) -> list[ValidationResult]:
    """Validate all markdown files matching patterns under root directory.

    Args:
        root: Root directory to search.
        patterns: List of glob patterns (default: ["_blog/**/*.md"]).
        verbose: If True, prints detailed progress.

    Returns:
        List of ValidationResult objects.
    """
    root_path = Path(root)
    if patterns is None:
        patterns = ["_blog/**/*.md"]

    matched_paths: set[Path] = set()
    for pattern in patterns:
        matched_paths.update(root_path.glob(pattern))

    results: list[ValidationResult] = []
    for file_path in sorted(matched_paths):
        if file_path.is_file():
            if verbose:
                print(f"Validating {file_path}...")
            result = validate_file(file_path, repo_root=root_path)
            results.append(result)

    return results


def format_finding(finding: Finding) -> str:
    """Format a single finding for terminal display."""
    color = {
        Severity.ERROR: "\033[31mERROR\033[0m",
        Severity.WARNING: "\033[33mWARN\033[0m",
        Severity.INFO: "\033[36mINFO\033[0m",
    }.get(finding.severity, finding.severity.value)

    return (
        f"  {finding.file_path}:{finding.line_number}: [{color}] ({finding.category}) "
        f"{finding.message}\n    '{finding.matched_text}'"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for blog content validation."""
    parser = argparse.ArgumentParser(
        description="Validate blog content and drafts against voice, tone, and editorial rules."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to validate. Defaults to '_blog/**/*.md' if not specified.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for all checked files.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only display errors.",
    )

    args = parser.parse_args(argv)

    if args.paths:
        target_files: list[Path] = []
        for p_str in args.paths:
            p = Path(p_str)
            if p.is_file():
                target_files.append(p)
            elif p.is_dir():
                target_files.extend(sorted(p.glob("**/*.md")))
            else:
                globbed = list(Path(".").glob(p_str))
                if globbed:
                    target_files.extend(sorted(f for f in globbed if f.is_file()))
                else:
                    target_files.append(p)
        results = [validate_file(f) for f in target_files]
    else:
        results = validate_content(Path("."), patterns=["_blog/**/*.md"], verbose=args.verbose)

    total_files = len(results)
    total_errors = sum(len([f for f in r.findings if f.severity == Severity.ERROR]) for r in results)
    total_warnings = sum(len([f for f in r.findings if f.severity == Severity.WARNING]) for r in results)
    total_info = sum(len([f for f in r.findings if f.severity == Severity.INFO]) for r in results)

    failed_files = [r for r in results if r.has_errors]

    for r in results:
        active_findings = r.findings
        if args.quiet:
            active_findings = [f for f in active_findings if f.severity == Severity.ERROR]
        if active_findings:
            print(f"\n{r.file_path}:")
            for f in active_findings:
                print(format_finding(f))

    print(
        f"\nBlog content validation: {total_files} file(s) checked, "
        f"{total_errors} error(s), {total_warnings} warning(s), {total_info} advisory note(s)."
    )

    if failed_files:
        print("FAILED: validation errors found.")
        return 1

    print("PASSED: all blog content checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
