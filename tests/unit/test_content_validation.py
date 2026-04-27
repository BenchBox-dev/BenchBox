"""Tests for content validation (benchbox/release/content_validation.py).

Verifies dataclass formatting, all 8 rule categories, example line detection,
inline ignore directives, file exceptions, context extraction, and the
top-level validate_file / validate_content / check_content_for_release entry points.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.utils.printing import set_quiet

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def _ensure_quiet_off():
    """Ensure quiet mode is off so emit() output reaches capsys."""
    set_quiet(False)
    yield
    set_quiet(False)


from benchbox.release.content_validation import (
    EM_DASH,
    EN_DASH,
    ContentViolation,
    Severity,
    ValidationResult,
    _get_context,
    _get_file_exceptions,
    _has_inline_ignore,
    _is_example_line,
    _should_skip_file,
    check_content_for_release,
    validate_content,
    validate_file,
)


# =============================================================================
# Dataclass Tests
# =============================================================================
class TestContentViolation:
    """Test ContentViolation dataclass."""

    def _make_violation(self, severity: Severity = Severity.ERROR) -> ContentViolation:
        return ContentViolation(
            file_path=Path("docs/test.md"),
            line_number=10,
            column=5,
            matched_text="bad text",
            context="some bad text here",
            rule="bad-text",
            category="punctuation",
            severity=severity,
            suggestion="Fix it",
        )

    def test_str_format_includes_file_line_col(self):
        """__str__ includes file:line:col location."""
        v = self._make_violation()
        s = str(v)
        assert "docs/test.md:10:5" in s

    def test_str_format_includes_matched_text(self):
        """__str__ includes the matched text in quotes."""
        v = self._make_violation()
        s = str(v)
        assert "'bad text'" in s

    def test_str_format_includes_category(self):
        """__str__ includes the rule category."""
        v = self._make_violation()
        s = str(v)
        assert "[punctuation]" in s

    def test_str_format_includes_severity_emoji(self):
        """__str__ includes severity-specific emoji prefix."""
        assert "\u274c" in str(self._make_violation(Severity.ERROR))  # cross mark
        assert "\u26a0" in str(self._make_violation(Severity.WARNING))  # warning
        assert "\U0001f4a1" in str(self._make_violation(Severity.SUGGESTION))  # light bulb


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_passed_true_when_no_violations(self):
        """passed is True when there are no violations."""
        result = ValidationResult()
        assert result.passed is True

    def test_passed_true_when_only_warnings(self):
        """passed is True when there are only WARNING violations (no ERRORs)."""
        v = ContentViolation(
            file_path=Path("f.md"),
            line_number=1,
            column=1,
            matched_text="x",
            context="x",
            rule="r",
            category="c",
            severity=Severity.WARNING,
            suggestion="s",
        )
        result = ValidationResult(violations=[v])
        assert result.passed is True

    def test_passed_false_when_errors_present(self):
        """passed is False when ERROR violations exist."""
        v = ContentViolation(
            file_path=Path("f.md"),
            line_number=1,
            column=1,
            matched_text="x",
            context="x",
            rule="r",
            category="c",
            severity=Severity.ERROR,
            suggestion="s",
        )
        result = ValidationResult(violations=[v])
        assert result.passed is False

    def test_counts(self):
        """error_count, warning_count, suggestion_count return correct values."""
        violations = [
            ContentViolation(
                file_path=Path("f.md"),
                line_number=1,
                column=1,
                matched_text="x",
                context="x",
                rule="r",
                category="c",
                severity=sev,
                suggestion="s",
            )
            for sev in [Severity.ERROR, Severity.ERROR, Severity.WARNING, Severity.SUGGESTION]
        ]
        result = ValidationResult(violations=violations)
        assert result.error_count == 2
        assert result.warning_count == 1
        assert result.suggestion_count == 1

    def test_summary_no_violations(self):
        """summary() mentions 'passed' when no violations."""
        result = ValidationResult(files_checked=5)
        s = result.summary()
        assert "passed" in s.lower() or "\u2713" in s
        assert "5" in s

    def test_summary_with_errors(self):
        """summary() includes FAILED when errors present."""
        v = ContentViolation(
            file_path=Path("f.md"),
            line_number=1,
            column=1,
            matched_text="x",
            context="x",
            rule="r",
            category="c",
            severity=Severity.ERROR,
            suggestion="s",
        )
        result = ValidationResult(violations=[v], files_with_violations=1)
        s = result.summary()
        assert "FAILED" in s


# =============================================================================
# Rule Category Tests
# =============================================================================


def _violations_for_text(text: str, category: str, tmp_dir: Path) -> list[ContentViolation]:
    """Helper: run validate_file on in-memory text for a specific category."""
    path = tmp_dir / "test_input.md"
    path.write_text(text, encoding="utf-8")
    return validate_file(path, categories=[category])


class TestPunctuationRules:
    """Test punctuation rule detection (ERROR severity)."""

    def test_em_dash_detected(self, tmp_path: Path):
        """Em-dash character is flagged as ERROR."""
        vs = _violations_for_text(f"This is a test{EM_DASH}with em-dash", "punctuation", tmp_path)
        assert len(vs) >= 1
        assert all(v.severity == Severity.ERROR for v in vs)

    def test_en_dash_detected(self, tmp_path: Path):
        """En-dash character is flagged as ERROR."""
        vs = _violations_for_text(f"Range: 1{EN_DASH}10", "punctuation", tmp_path)
        assert len(vs) >= 1

    def test_clean_hyphens_pass(self, tmp_path: Path):
        """Regular hyphens do not trigger violations."""
        vs = _violations_for_text("This is a test - with regular hyphens and 1-10 ranges", "punctuation", tmp_path)
        assert len(vs) == 0

    def test_mixed_content(self, tmp_path: Path):
        """Only prohibited characters are flagged, not regular text."""
        text = f"Line one is fine.\nLine two has em-dash{EM_DASH}here.\nLine three is fine."
        vs = _violations_for_text(text, "punctuation", tmp_path)
        assert len(vs) == 1
        assert vs[0].line_number == 2


class TestVagueClaimsRules:
    """Test vague claims rule detection (WARNING severity)."""

    def test_much_faster_flagged(self, tmp_path: Path):
        """'much faster' is flagged."""
        vs = _violations_for_text("DuckDB is much faster than SQLite.", "vague_claims", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.WARNING

    def test_significantly_better_flagged(self, tmp_path: Path):
        """'significantly better' is flagged."""
        vs = _violations_for_text("Results are significantly better now.", "vague_claims", tmp_path)
        assert len(vs) >= 1

    def test_large_dataset_flagged(self, tmp_path: Path):
        """'large dataset' is flagged."""
        vs = _violations_for_text("We tested on a large dataset.", "vague_claims", tmp_path)
        assert len(vs) >= 1

    def test_quantified_text_passes(self, tmp_path: Path):
        """Quantified claims like '2.3x faster' do not trigger."""
        vs = _violations_for_text("DuckDB completed queries 2.3x faster at SF100.", "vague_claims", tmp_path)
        assert len(vs) == 0


class TestMarketingRules:
    """Test marketing language rule detection (WARNING severity)."""

    def test_revolutionary_flagged(self, tmp_path: Path):
        """'revolutionary' is flagged."""
        vs = _violations_for_text("This is a revolutionary approach.", "marketing", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.WARNING

    def test_game_changing_flagged(self, tmp_path: Path):
        """'game-changing' is flagged."""
        vs = _violations_for_text("A game-changing improvement.", "marketing", tmp_path)
        assert len(vs) >= 1

    def test_leverage_flagged(self, tmp_path: Path):
        """'leverage' is flagged."""
        vs = _violations_for_text("We leverage advanced techniques.", "marketing", tmp_path)
        assert len(vs) >= 1

    def test_clean_descriptive_text_passes(self, tmp_path: Path):
        """Descriptive technical text passes."""
        vs = _violations_for_text("The query optimizer rewrites subqueries into joins.", "marketing", tmp_path)
        assert len(vs) == 0


class TestPlatformAdvocacyRules:
    """Test platform advocacy rule detection (ERROR severity)."""

    def test_clearly_superior_flagged(self, tmp_path: Path):
        """'clearly superior' is flagged as ERROR."""
        vs = _violations_for_text("DuckDB is clearly superior.", "platform_advocacy", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.ERROR

    def test_obviously_better_flagged(self, tmp_path: Path):
        """'obviously better' is flagged."""
        vs = _violations_for_text("This is obviously better.", "platform_advocacy", tmp_path)
        assert len(vs) >= 1

    def test_the_best_choice_flagged(self, tmp_path: Path):
        """'the best choice' is flagged."""
        vs = _violations_for_text("DuckDB is the best choice for analytics.", "platform_advocacy", tmp_path)
        assert len(vs) >= 1

    def test_neutral_comparison_passes(self, tmp_path: Path):
        """Neutral data-driven comparison passes."""
        vs = _violations_for_text("DuckDB completed Q1 in 2.3s while SQLite took 5.1s.", "platform_advocacy", tmp_path)
        assert len(vs) == 0


class TestVoiceRules:
    """Test voice rule detection (WARNING severity)."""

    def test_i_think_flagged(self, tmp_path: Path):
        """'I think' is flagged."""
        vs = _violations_for_text("I think DuckDB is fast.", "voice", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.WARNING

    def test_i_found_flagged(self, tmp_path: Path):
        """'I found' is flagged."""
        vs = _violations_for_text("I found that queries improved.", "voice", tmp_path)
        assert len(vs) >= 1

    def test_in_my_opinion_flagged(self, tmp_path: Path):
        """'In my opinion' is flagged."""
        vs = _violations_for_text("In my opinion this is the right approach.", "voice", tmp_path)
        assert len(vs) >= 1

    def test_we_found_passes(self, tmp_path: Path):
        """'we found' passes (community-inclusive voice)."""
        vs = _violations_for_text("We found that performance improved by 23%.", "voice", tmp_path)
        assert len(vs) == 0


class TestRestrictedVendorRules:
    """Test restricted vendor rule detection (WARNING severity)."""

    def test_oracle_flagged(self, tmp_path: Path):
        """'Oracle' is flagged as WARNING."""
        vs = _violations_for_text("Oracle database supports this feature.", "restricted_vendor", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.WARNING

    def test_no_vendor_passes(self, tmp_path: Path):
        """Text without vendor names passes."""
        vs = _violations_for_text("The database supports OLAP workloads.", "restricted_vendor", tmp_path)
        assert len(vs) == 0

    def test_case_sensitivity(self, tmp_path: Path):
        """'Oracle' is case-insensitive (regex uses re.IGNORECASE in _find_violations_for_rules)."""
        vs = _violations_for_text("oracle database is popular.", "restricted_vendor", tmp_path)
        assert len(vs) >= 1


class TestHedgingRules:
    """Test hedging rule detection (SUGGESTION severity)."""

    def test_it_might_possibly_flagged(self, tmp_path: Path):
        """'it might possibly' is flagged."""
        vs = _violations_for_text("It might possibly be faster.", "hedging", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.SUGGESTION

    def test_kind_of_flagged(self, tmp_path: Path):
        """'kind of' is flagged."""
        vs = _violations_for_text("This is kind of slow.", "hedging", tmp_path)
        assert len(vs) >= 1

    def test_direct_statements_pass(self, tmp_path: Path):
        """Direct statements without hedging pass."""
        vs = _violations_for_text("Query Q1 completed in 2.3 seconds.", "hedging", tmp_path)
        assert len(vs) == 0


class TestClicheRules:
    """Test cliche rule detection (SUGGESTION severity)."""

    def test_low_hanging_fruit_flagged(self, tmp_path: Path):
        """'low-hanging fruit' is flagged."""
        vs = _violations_for_text("These are low-hanging fruit optimizations.", "cliche", tmp_path)
        assert len(vs) >= 1
        assert vs[0].severity == Severity.SUGGESTION

    def test_deep_dive_flagged(self, tmp_path: Path):
        """'deep dive' is flagged."""
        vs = _violations_for_text("Let's do a deep dive into performance.", "cliche", tmp_path)
        assert len(vs) >= 1

    def test_clean_text_passes(self, tmp_path: Path):
        """Clean alternative text passes."""
        vs = _violations_for_text("This section provides a detailed analysis of query performance.", "cliche", tmp_path)
        assert len(vs) == 0


# =============================================================================
# Helper Function Tests
# =============================================================================
class TestIsExampleLine:
    """Test _is_example_line() function."""

    def test_cross_emoji_line(self):
        """Lines starting with cross emoji are examples."""
        lines = ["\u274c Don't write like this"]
        assert _is_example_line(lines[0], lines, 0) is True

    def test_cross_emoji_table_cell(self):
        """Table cells with cross emoji are examples."""
        lines = ["| \u274c much faster | \u2713 2.3x faster |"]
        assert _is_example_line(lines[0], lines, 0) is True

    def test_blockquote_with_cross_emoji(self):
        """Blockquote lines with cross emoji are examples."""
        lines = ["> \u274c This is a bad example"]
        assert _is_example_line(lines[0], lines, 0) is True

    def test_dont_section_bullets(self):
        """Lines under a Don't section heading are examples."""
        lines = [
            "\u274c **Don't**:",
            '- "This is much faster"',
        ]
        assert _is_example_line(lines[1], lines, 1) is True

    def test_normal_content_not_example(self):
        """Normal content lines are not examples."""
        lines = ["DuckDB completed Q1 in 2.3 seconds."]
        assert _is_example_line(lines[0], lines, 0) is False


class TestHasInlineIgnore:
    """Test _has_inline_ignore() function."""

    def test_same_line_directive(self):
        """Directive on same line suppresses the category."""
        lines = ["Oracle is mentioned <!-- content-ok: restricted_vendor -->"]
        assert _has_inline_ignore(lines, 0, "restricted_vendor") is True

    def test_previous_line_directive(self):
        """Directive on previous line suppresses the category."""
        lines = [
            "<!-- content-ok: restricted_vendor -->",
            "Oracle is mentioned here.",
        ]
        assert _has_inline_ignore(lines, 1, "restricted_vendor") is True

    def test_all_keyword(self):
        """'all' keyword suppresses any category."""
        lines = ["Some text <!-- content-ok: all -->"]
        assert _has_inline_ignore(lines, 0, "marketing") is True
        assert _has_inline_ignore(lines, 0, "punctuation") is True

    def test_multiple_categories(self):
        """Multiple comma-separated categories work."""
        lines = ["Text <!-- content-ok: restricted_vendor, marketing -->"]
        assert _has_inline_ignore(lines, 0, "restricted_vendor") is True
        assert _has_inline_ignore(lines, 0, "marketing") is True

    def test_case_insensitive(self):
        """Category matching is case-insensitive."""
        lines = ["Text <!-- content-ok: RESTRICTED_VENDOR -->"]
        assert _has_inline_ignore(lines, 0, "restricted_vendor") is True

    def test_wrong_category_not_suppressed(self):
        """Wrong category is not suppressed."""
        lines = ["Text <!-- content-ok: marketing -->"]
        assert _has_inline_ignore(lines, 0, "punctuation") is False

    def test_line_idx_zero_no_previous(self):
        """line_idx=0 doesn't crash (no previous line to check)."""
        lines = ["No directive here"]
        assert _has_inline_ignore(lines, 0, "marketing") is False


class TestGetContext:
    """Test _get_context() function."""

    def test_short_line_returned_as_is(self):
        """Short lines are returned without truncation."""
        ctx = _get_context("short line", 0, 5)
        assert "short" in ctx
        assert "..." not in ctx

    def test_long_line_truncated_with_ellipsis(self):
        """Long lines are truncated with ellipsis."""
        long_line = "x" * 200
        ctx = _get_context(long_line, 100, 105, max_len=60)
        assert "..." in ctx
        assert len(ctx) < 200

    def test_match_at_start(self):
        """Match at start of line handled correctly."""
        ctx = _get_context("match at the very start of a long line here ok", 0, 5, max_len=20)
        assert "match" in ctx


# =============================================================================
# File Exception Tests
# =============================================================================
class TestFileExceptions:
    """Test _get_file_exceptions() function."""

    def test_dialect_translation_excepted(self):
        """dialect-translation.md is excepted from restricted_vendor."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/usage/dialect-translation.md")
        exceptions = _get_file_exceptions(file_path, repo_root)
        assert "restricted_vendor" in exceptions

    def test_blog_glob_patterns(self):
        """Blog glob patterns match correctly."""
        repo_root = Path("/repo")
        file_path = Path("/repo/_blog/free-trial-benchmarking/post1/index.md")
        exceptions = _get_file_exceptions(file_path, repo_root)
        assert "restricted_vendor" in exceptions

    def test_non_matching_file_no_exceptions(self):
        """Non-matching files get no exceptions."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/getting-started.md")
        exceptions = _get_file_exceptions(file_path, repo_root)
        assert len(exceptions) == 0

    def test_returns_set_of_strings(self):
        """_get_file_exceptions returns a set of category strings."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/getting-started.md")
        exceptions = _get_file_exceptions(file_path, repo_root)
        assert isinstance(exceptions, set)


class TestShouldSkipFile:
    """Test _should_skip_file() function."""

    def test_docs_build_skipped(self):
        """Files under docs/_build are skipped."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/_build/html/index.html")
        assert _should_skip_file(file_path, repo_root) is True

    def test_docs_tags_skipped(self):
        """Files under docs/_tags are skipped."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/_tags/tag1.html")
        assert _should_skip_file(file_path, repo_root) is True

    def test_normal_docs_not_skipped(self):
        """Normal docs files are not skipped."""
        repo_root = Path("/repo")
        file_path = Path("/repo/docs/getting-started.md")
        assert _should_skip_file(file_path, repo_root) is False


# =============================================================================
# Integration Tests
# =============================================================================
class TestValidateFile:
    """Test validate_file() end-to-end."""

    def test_detects_violations(self, tmp_path: Path):
        """Finds violations in a file with known bad content."""
        f = tmp_path / "test.md"
        f.write_text(f"This has an em-dash{EM_DASH}here.\n", encoding="utf-8")

        violations = validate_file(f, categories=["punctuation"])
        assert len(violations) >= 1
        assert violations[0].category == "punctuation"

    def test_category_filtering(self, tmp_path: Path):
        """Only checks specified categories."""
        f = tmp_path / "test.md"
        f.write_text("I think this is much faster and revolutionary.\n", encoding="utf-8")

        # Only check voice
        violations = validate_file(f, categories=["voice"])
        categories = {v.category for v in violations}
        assert categories == {"voice"}

    def test_file_exceptions_applied(self, tmp_path: Path):
        """File-level exceptions skip excepted categories."""
        repo = tmp_path / "repo"
        repo.mkdir()
        docs = repo / "docs" / "usage"
        docs.mkdir(parents=True)
        f = docs / "dialect-translation.md"
        f.write_text("Oracle supports this dialect.\n", encoding="utf-8")

        # Without repo_root: Oracle flagged
        vs_without = validate_file(f, categories=["restricted_vendor"])
        assert len(vs_without) >= 1

        # With repo_root: Oracle excepted for this file
        vs_with = validate_file(f, categories=["restricted_vendor"], repo_root=repo)
        assert len(vs_with) == 0

    def test_unreadable_file_returns_empty(self, tmp_path: Path):
        """File that can't be read returns empty list."""
        f = tmp_path / "nonexistent.md"
        violations = validate_file(f)
        assert violations == []

    def test_clean_file_returns_empty(self, tmp_path: Path):
        """Clean file with no violations returns empty list."""
        f = tmp_path / "clean.md"
        f.write_text("We found that DuckDB completed Q1 in 2.3 seconds at SF100.\n", encoding="utf-8")
        violations = validate_file(f)
        assert violations == []


class TestValidateContent:
    """Test validate_content() end-to-end."""

    def test_scans_matching_files(self, tmp_path: Path):
        """Scans files matching glob patterns."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "page1.md").write_text(f"Has em-dash{EM_DASH}here.\n", encoding="utf-8")
        (docs / "page2.md").write_text("Clean content.\n", encoding="utf-8")

        result = validate_content(tmp_path, patterns=["docs/**/*.md"])
        assert result.files_checked == 2
        assert result.files_with_violations == 1

    def test_files_checked_count(self, tmp_path: Path):
        """files_checked count is accurate."""
        docs = tmp_path / "docs"
        docs.mkdir()
        for i in range(3):
            (docs / f"page{i}.md").write_text("Clean.\n", encoding="utf-8")

        result = validate_content(tmp_path, patterns=["docs/**/*.md"])
        assert result.files_checked == 3

    def test_skipped_files_not_counted(self, tmp_path: Path):
        """Files in VALIDATION_EXCLUDES are not counted."""
        docs = tmp_path / "docs"
        build = docs / "_build"
        build.mkdir(parents=True)
        (build / "output.md").write_text(f"Has em-dash{EM_DASH}here.\n", encoding="utf-8")
        (docs / "real.md").write_text("Clean.\n", encoding="utf-8")

        result = validate_content(tmp_path, patterns=["docs/**/*.md"])
        assert result.files_checked == 1  # Only real.md

    def test_default_patterns_used(self, tmp_path: Path):
        """When no patterns specified, default patterns are used (no crash)."""
        result = validate_content(tmp_path)
        assert result.files_checked == 0  # No matching files in tmp_path


class TestCheckContentForRelease:
    """Test check_content_for_release() end-to-end."""

    def test_returns_true_when_no_violations(self, tmp_path: Path):
        """Returns True when no violations found."""
        result = check_content_for_release(tmp_path)
        assert result is True

    def test_returns_false_when_errors_present(self, tmp_path: Path):
        """Returns False when ERROR violations exist."""
        blog = tmp_path / "_blog"
        blog.mkdir()
        (blog / "post.md").write_text(f"Has em-dash{EM_DASH}here and clearly superior claims.\n", encoding="utf-8")

        result = check_content_for_release(tmp_path)
        assert result is False

    def test_auto_continue_returns_true(self, tmp_path: Path):
        """auto_continue=True returns True despite violations."""
        blog = tmp_path / "_blog"
        blog.mkdir()
        (blog / "post.md").write_text(f"Has em-dash{EM_DASH}here and clearly superior claims.\n", encoding="utf-8")

        result = check_content_for_release(tmp_path, auto_continue=True)
        assert result is True

    def test_errors_only_mode(self, tmp_path: Path, capsys):
        """errors_only=True suppresses warning/suggestion display."""
        blog = tmp_path / "_blog"
        blog.mkdir()
        # Only include WARNING-level content (no ERRORs)
        (blog / "post.md").write_text("I think this is much faster.\n", encoding="utf-8")

        check_content_for_release(tmp_path, errors_only=True)
        captured = capsys.readouterr()
        # Should not show "WARNINGS" section header
        assert "Should fix" not in captured.out

    def test_prints_summary(self, tmp_path: Path, capsys):
        """Prints summary to stdout."""
        check_content_for_release(tmp_path)
        captured = capsys.readouterr()
        assert "Content Validation" in captured.out
