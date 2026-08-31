"""Unit tests for scripts/blog_content_validation.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.blog_content_validation import (
    Severity,
    main,
    validate_content,
    validate_file,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def tmp_blog_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary directory for blog fixtures."""
    blog_dir = tmp_path / "_blog"
    blog_dir.mkdir(parents=True)
    return blog_dir


def test_clean_post_passes(tmp_blog_dir: Path) -> None:
    """A clean post adhering to all voice rules should pass without errors or warnings."""
    post_content = """# Benchmarking Partition Strategies at Scale

> Measuring query runtime across three partitioning strategies in DuckDB.

**TL;DR**: Hash partitioning reduced scan times by 42% for join-heavy queries.

## Methodology

We ran the test suite on an AWS c6i.4xlarge instance with cold cache between runs.
We tested three configurations across 5 iterations.

```bash
$ benchbox run --platform duckdb --benchmark tpch --scale 10
```

## Results

In our runs, hash partitioning completed query 12 in 1.4s compared to 2.4s for unpartitioned data.
Both configurations validate against the reference answers.

## Limitations

Our benchmarks reflect single-node execution and do not cover distributed clusters.
"""
    post_file = tmp_blog_dir / "clean-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert not result.has_errors
    assert not result.has_warnings
    assert len(result.findings) == 0


def test_em_dash_fails(tmp_blog_dir: Path) -> None:
    """An em-dash (U+2014) must trigger an ERROR under punctuation category."""
    post_content = """# Title

Here is a parenthetical—using an em dash—in prose.
"""
    post_file = tmp_blog_dir / "em-dash-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert not result.is_valid
    assert result.has_errors
    errors = [f for f in result.findings if f.severity == Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].category == "punctuation"
    assert "\u2014" in errors[0].matched_text


def test_en_dash_fails(tmp_blog_dir: Path) -> None:
    """An en-dash (U+2013) must trigger an ERROR under punctuation category."""
    post_content = """# Title

See pages 10–20 for details.
"""
    post_file = tmp_blog_dir / "en-dash-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert not result.is_valid
    assert result.has_errors
    errors = [f for f in result.findings if f.severity == Severity.ERROR]
    assert len(errors) == 1
    assert errors[0].category == "punctuation"
    assert "\u2013" in errors[0].matched_text


def test_platform_winner_verdict_fails(tmp_blog_dir: Path) -> None:
    """Platform winner verdicts must trigger an ERROR."""
    post_content = """# Title

In our testing, DuckDB clearly destroys the competition on all analytical queries.
"""
    post_file = tmp_blog_dir / "winner-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert not result.is_valid
    assert result.has_errors
    errors = [f for f in result.findings if f.severity == Severity.ERROR]
    assert any(f.category == "platform_winner" for f in errors)


def test_multiword_platform_winner_and_is_best_fails(tmp_blog_dir: Path) -> None:
    """Multiword platform winner verdicts and 'is best for' must trigger an ERROR."""
    post_content = """# Title

This proves Platform X is the best choice for fast analytics.
Platform X is best for analytical workloads.
"""
    post_file = tmp_blog_dir / "multiword-winner.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert not result.is_valid
    assert result.has_errors
    errors = [f for f in result.findings if f.severity == Severity.ERROR]
    assert len(errors) == 2
    assert all(f.category == "platform_winner" for f in errors)


def test_ordinary_first_person_singular_warns(tmp_blog_dir: Path) -> None:
    """Ordinary first-person singular prose (I, my, me) must emit warnings."""
    post_content = """# Title

I ran the benchmark on my machine.
Contact me with questions about these runs.
The execution was I/O-bound across all disks.
"""
    post_file = tmp_blog_dir / "first-person-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert result.has_warnings
    fp_findings = [f for f in result.findings if f.category == "first_person"]
    assert len(fp_findings) >= 3
    matched = [f.matched_text for f in fp_findings]
    assert "I" in matched
    assert "my" in matched
    assert "me" in matched
    # Ensure I/O was not matched
    assert not any("I/O" in f.matched_text for f in fp_findings)


def test_news_negation_title_passes(tmp_blog_dir: Path) -> None:
    """A title or H2 whose news is a negation must not be flagged as a couplet."""
    post_content = """# When two timings are not a comparison

## Why read_primitives was not enough

In this benchmark, we measured elapsed execution time.
"""
    post_file = tmp_blog_dir / "negation-title.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert not any(f.category == "couplet" for f in result.findings)


def test_allowed_legal_negation_passes(tmp_blog_dir: Path) -> None:
    """Legal scope boundaries ('not yet supported') and UI states ('not_run') must pass."""
    post_content = """# Status Report

Transactional benchmarks are not yet supported in this version.
The maintenance phase status was marked as not_run.
"""
    post_file = tmp_blog_dir / "legal-negation.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert not any(f.category == "couplet" for f in result.findings)


def test_affirmation_denial_couplet_same_line(tmp_blog_dir: Path) -> None:
    """Same-line affirmation-plus-denial echo should emit an INFO finding."""
    post_content = """# Architecture Overview

BenchBox is an execution engine. It is not a database.
"""
    post_file = tmp_blog_dir / "couplet-same-line.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    couplet_findings = [f for f in result.findings if f.category == "couplet"]
    assert len(couplet_findings) == 1
    assert couplet_findings[0].severity == Severity.INFO


def test_affirmation_denial_couplet_consecutive_lines(tmp_blog_dir: Path) -> None:
    """Consecutive-line affirmation-plus-denial echo should emit an INFO finding."""
    post_content = """# Lessons Learned

Benchmark names define contracts.
They are not marketing labels.
"""
    post_file = tmp_blog_dir / "couplet-consecutive.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    couplet_findings = [f for f in result.findings if f.category == "couplet"]
    assert len(couplet_findings) == 1
    assert couplet_findings[0].severity == Severity.INFO


def test_guide_file_quotes_dont_passes(tmp_blog_dir: Path) -> None:
    """A guide file quoting banned phrases in Don't or Avoid sections must not fail."""
    guide_content = """# BenchBox Blog Style Guide

### Voice Characteristics

✅ **Do**:
- "We tested against three platforms to demonstrate compatibility."

❌ **Don't**:
- "Platform B is clearly inferior and should be avoided."
- "Anyone still using Y is making a mistake."

| Write | Avoid |
| ----- | ----- |
| We got consistent results with cold cache | The only correct way to benchmark is |
| Validation caught ordering bugs | your mileage may vary |

**Before (platform advocacy):**
> DuckDB absolutely destroys the competition on analytical queries.

**After (methodology voice):**
> In our runs, DuckDB completed all queries in under 5 minutes.
"""
    guide_file = tmp_blog_dir / "STYLE_GUIDE.md"
    guide_file.write_text(guide_content, encoding="utf-8")

    result = validate_file(guide_file)
    assert result.is_valid
    assert not result.has_errors
    assert not result.has_warnings


def test_llm_writing_tells_warn(tmp_blog_dir: Path) -> None:
    """LLM writing tells (conversational residue, buzzwords, generic transitions) must emit warnings."""
    post_content = """# Title

> Good point!

Going forward, we should optimize our indexes.
In today's fast-paced digital landscape, data generation matters.
Let's delve into query execution plans for seamless integration.

## In conclusion

That concludes our findings.
"""
    post_file = tmp_blog_dir / "ai-tells-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid  # Warnings don't fail validation
    assert result.has_warnings
    tells = [f for f in result.findings if f.category == "llm_tells"]
    assert len(tells) >= 5
    matched_texts = [f.matched_text.lower() for f in tells]
    assert any("good point" in t for t in matched_texts)
    assert any("going forward" in t for t in matched_texts)
    assert any("delve" in t for t in matched_texts)
    assert any("seamless" in t for t in matched_texts)


def test_content_ok_override(tmp_blog_dir: Path) -> None:
    """The <!-- content-ok: category --> comment must suppress findings."""
    post_content = """# Title

<!-- content-ok: platform_winner -->
DuckDB destroys the competition in this specific test.

<!-- content-ok -->
Here is an em-dash — intentionally preserved in quote.
"""
    post_file = tmp_blog_dir / "override-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert not result.has_errors


def test_code_block_skips_prose_rules(tmp_blog_dir: Path) -> None:
    """Code blocks should not trigger prose rules like first-person or marketing hype."""
    post_content = """# Title

```python
# I think this is a revolutionary algorithm
def optimize():
    pass
```
"""
    post_file = tmp_blog_dir / "code-post.md"
    post_file.write_text(post_content, encoding="utf-8")

    result = validate_file(post_file)
    assert result.is_valid
    assert not result.has_warnings


def test_validate_content_and_cli(tmp_blog_dir: Path) -> None:
    """Test validate_content batch runner and main CLI."""
    clean = tmp_blog_dir / "clean.md"
    clean.write_text("# Clean\n\nWe ran the benchmark.\n", encoding="utf-8")

    broken = tmp_blog_dir / "broken.md"
    broken.write_text("# Broken\n\nEm-dash—here.\n", encoding="utf-8")

    results = validate_content(tmp_blog_dir, patterns=["*.md"])
    assert len(results) == 2

    # CLI test on clean file
    assert main([str(clean)]) == 0

    # CLI test on broken file
    assert main([str(broken)]) == 1
