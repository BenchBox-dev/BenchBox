# BenchBox Test Quality Guidelines

This document defines standards for writing effective, maintainable tests in BenchBox.

## Core Principles

1. **Test Behavior, Not Implementation** - Tests should verify what the code does, not how it does it.
2. **Distinct Purpose** - Every test should have a unique, documented purpose.
3. **Fail Meaningfully** - When a test fails, the failure message should clearly indicate what's wrong.
4. **Minimal Brittleness** - Tests should not break due to unrelated changes.

## Anti-Patterns to Avoid

### 1. Enum/Constant Count Tests

**Bad**: Testing that a collection has a specific count.

```python
# BAD - breaks when tables are added/removed
def test_table_count():
    assert len(TABLES) == 21
```

**Good**: Test structural properties or specific members.

```python
# GOOD - tests behavior, not implementation detail
def test_all_tables_have_required_columns():
    for table in TABLES:
        assert table.has_primary_key()
        assert "created_at" in table.column_names

# GOOD - tests specific requirements
def test_required_tables_present():
    required = {"users", "orders", "products"}
    assert required.issubset(set(TABLES.keys()))
```

### 2. Tautological Assertions

**Bad**: Asserting something that would raise an exception anyway.

```python
# BAD - import_module raises ImportError on failure, never returns None
module = importlib.import_module("mypackage")
assert module is not None  # Redundant

# BAD - constructor raises on failure
obj = MyClass()
assert obj is not None  # Redundant
```

**Good**: Remove redundant assertions or replace with meaningful ones.

```python
# GOOD - just import (failure = ImportError with clear message)
importlib.import_module("mypackage")

# GOOD - verify behavior after construction
obj = MyClass()
assert obj.is_initialized
assert obj.config == expected_config
```

### 3. Trivial isinstance Checks Without Follow-up

**Bad**: Checking type without verifying content.

```python
# BAD - doesn't verify the dict has expected content
result = get_stats()
assert isinstance(result, dict)
```

**Good**: Verify structure or content.

```python
# GOOD - verifies both type and content
result = get_stats()
assert isinstance(result, dict)
assert "row_count" in result
assert result["row_count"] >= 0
```

### 4. Constant Equality Tests

**Bad**: Testing that a constant equals its expected value.

```python
# BAD - just duplicates the constant definition
def test_default_scale():
    assert DEFAULT_SCALE == 0.01
```

**Good**: Test that the constant is used correctly.

```python
# GOOD - tests that default is actually applied
def test_default_scale_applied():
    benchmark = TPCH()  # No scale_factor arg
    assert benchmark.scale_factor == 0.01
```

### 5. Over-Specification

**Bad**: Testing format/structure instead of behavior.

```python
# BAD - tests format, not correctness
def test_query_format():
    query = generate_query(1)
    assert query.startswith("SELECT")
    assert "FROM" in query
    assert query.endswith(";")
```

**Good**: Test that the query works correctly.

```python
# GOOD - tests actual behavior
def test_query_returns_expected_rows():
    query = generate_query(1)
    result = conn.execute(query)
    assert len(result) == expected_count
```

## Valid Uses of `is not None`

Sometimes `assert x is not None` is appropriate:

```python
# VALID - function legitimately returns None for invalid input
plan = parser.parse(malformed_input)
if plan is not None:  # Parser returns None for unparseable input
    assert plan.logical_root is not None
```

```python
# VALID - optional field that should be present in this test case
result = get_user(user_id)
assert result.email is not None  # Some users might not have email
```

The key distinction: use `is not None` when `None` is a valid return value that you want to explicitly check for, not when the function would raise an exception instead.

## Good Test Characteristics

1. **Validates behavior that could break** - The test would fail if the feature regressed.
2. **Tests edge cases and error conditions** - Happy path + error handling.
3. **Prevents known regressions** - Captures bugs that were fixed.
4. **Documents expected behavior** - Reading the test shows what the code should do.
5. **Is independent and deterministic** - No order dependencies, no flakiness.
6. **Has a clear, descriptive name** - `test_empty_input_returns_empty_list` not `test_func1`.

## Parallel Safety Checklist

BenchBox runs many tests under pytest-xdist, so tests must also be safe under
concurrent execution.

### Avoid These Patterns

- Nested parallelism without limits. If code under test imports Polars, DuckDB,
  BLAS/OpenMP-backed libraries, or starts thread/process pools, either mock that
  work or make the thread/process count explicit.
- Shared fixed paths such as `/tmp/output.csv`, repo-root scratch files, or
  global cache directories.
- Tests that assume exclusive access to the current working directory, `HOME`,
  a shared git repo, or static ports.
- Controller-only fixes for xdist behavior. If a safeguard must change worker
  creation, it has to happen before xdist starts workers.

### Prefer These Patterns

- `tmp_path` or `tmp_path_factory` for unique per-test storage.
- Explicitly capped internal parallelism when running native or threaded code.
- Local temporary repos instead of mutating shared repository state.
- A small reproducer and resource measurements when changing pytest-xdist
  behavior.

See [Pytest xdist Safety](pytest-xdist-safety.md) for the current worker-cap
design and the validation matrix contributors must rerun before changing it.

## Test Organization

### Naming Convention

```python
def test_<what>_<condition>_<expected_result>():
    """Optional docstring explaining why this test exists."""
    ...

# Examples:
def test_parse_valid_json_returns_dict():
def test_connection_timeout_raises_error():
def test_empty_table_generates_no_rows():
```

### Docstrings

Add docstrings when the test name isn't self-explanatory:

```python
def test_sf10_customer_count():
    """TPC-H spec requires exactly 1.5M customers at SF=10.

    This is a compliance requirement, not an arbitrary count.
    Ref: TPC-H Specification v3.0.1, Section 4.2.2
    """
    assert get_customer_count(scale_factor=10) == 1_500_000
```

## Coverage vs. Quality

High test coverage with low-quality tests provides false confidence. Prefer:

- 80% coverage with meaningful tests
- Over 100% coverage with trivial assertions

When in doubt, ask: "If this test passes, what have I actually verified?"
