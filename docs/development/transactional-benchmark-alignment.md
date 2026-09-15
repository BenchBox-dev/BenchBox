---
title: Transactional Benchmark Alignment
status: reference
owner: quality-extract-transactional-benchmark-base
created: 2026-04-14
---

# Transactional Benchmark Alignment

Companion doc for `quality-extract-transactional-benchmark-base`. Maps
`TransactionPrimitivesBenchmark` (from
`benchbox/core/transaction_primitives/benchmark.py`) and
`WritePrimitivesBenchmark` (from `benchbox/core/write_primitives/benchmark.py`)
field-by-field and method-by-method against each other, then does the same
for their two `*OperationsManager` classes.

---

## Current Pylint R-08 Clusters (at --min-similarity-lines=15)

| Cluster | Files | Lines | Content |
|---|---|---|---|
| C1 | `transaction.benchmark:[737:838]` ↔ `write.benchmark:[882:983]` | 101 | `get_benchmark_info`, `get_query`, `get_queries`, `get_queries_by_category`, `execute_operation` preamble |
| C2 | `transaction.benchmark:[180:251]` ↔ `write.benchmark:[195:265]` | 71 | `generate_data` body, `ensure_auxiliary_data_files`, `_acquire_setup_lock` signature+preamble |
| C3 | `transaction.operations:[25:118]` ↔ `write.operations:[25:118]` | 93 | Entire `*OperationsManager` class body |
| C4 | `transaction.benchmark:[1008:1054]` ↔ `write.benchmark:[1147:1186]` | 46 | `run_benchmark` body |

**Total targeted**: 311 lines across benchmark.py + operations.py.

Additional clusters exist in catalog/loader.py, schema.py, and
dataframe_operations.py but are **out of scope** for this TODO (see
`files_affected` constraint). The verification command below is scoped to the
four target files.

---

## OperationsManager: TransactionOperationsManager ↔ WriteOperationsManager

Both classes are **completely identical** except:

| Aspect | Transaction | Write |
|---|---|---|
| Class name | `TransactionOperationsManager` | `WriteOperationsManager` |
| `__init__` catalog loader | `load_transaction_primitives_catalog()` | `load_write_primitives_catalog()` |
| `WriteOperation` import source | `benchbox.core.transaction_primitives.catalog` | `benchbox.core.write_primitives.catalog` |

Every other method body, signature, and logic is character-for-character
identical (lines 30-117 in each file).

**Extraction**: `OperationsRegistryBase[OperationT]` in
`benchbox/core/transactional/operations_registry_base.py`.

```python
class OperationsRegistryBase(Generic[OperationT]):
    def __init__(self, version: int, operations: dict[str, OperationT]) -> None:
        ...

# Subclass:
class TransactionOperationsManager(OperationsRegistryBase[WriteOperation]):
    def __init__(self) -> None:
        catalog = load_transaction_primitives_catalog()
        super().__init__(catalog.version, catalog.operations)
```

---

## Benchmark: Method-by-Method Comparison

### Shared - identical, extract to base

| Method | Lines (txn) | Lines (write) | Notes |
|---|---|---|---|
| `get_data_source_benchmark()` | 134-140 | 149-155 | Identical; both return `"tpch"` |
| `output_dir` property | 142-148 | 157-163 | Identical |
| `output_dir.setter` | 150-164 | 165-179 | Identical |
| `generate_data()` | 166-185 | 181-200 | Body identical; only log prefix differs (`"Transaction Primitives"` vs `"Write Primitives"`) - parameterize via `_benchmark_label` class var |
| `ensure_auxiliary_data_files()` | 187-221 | 202-236 | **Completely identical** |
| `get_benchmark_info()` | 741-756 | 886-901 | Identical; uses `STAGING_TABLES` (module-level) - expose as `_staging_tables` instance var set in subclass `__init__` |
| `get_query()` | 758-772 | 903-917 | **Completely identical** |
| `get_queries()` | 774-784 | 919-929 | **Completely identical** |
| `get_queries_by_category()` | 786-796 | 931-941 | **Completely identical** |
| `run_benchmark()` | 992-1033 | 1131-1172 | **Completely identical** body; return type differs (`list[OperationResult]` both, but different `OperationResult` classes) |

### execute_operation preamble - extract as helper

The first 41 lines of `execute_operation()` are identical (connection
validation + `kwargs` extraction + `operations_manager.get_operation()` +
auto-setup):

```python
# Both files lines 823-842 / 968-988 (identical logic):
if not connection: raise ValueError(...)
if not hasattr(connection, "execute"): raise ValueError(...)
platform_key = kwargs.get("platform_key")
sql_override = kwargs.get("sql_override")
operation = self.operations_manager.get_operation(operation_id)
if operation.requires_setup and not self.is_setup(connection):
    self.setup(connection, ...)
```

**Extraction**: `_prepare_operation(operation_id, connection, **kwargs)` helper
on the base returns `(operation, platform_key, sql_override)`.

### Divergent - stay spec-local

| Method | Divergence |
|---|---|
| `__init__` | Different `_name`, `_version`, `_description` strings; different manager/generator types |
| `execute_operation()` body | Transaction: inline SQL resolution + validation; Write: delegates to helpers |
| `_acquire_setup_lock()` | Lock table name (`transaction_primitives_setup_lock` vs `write_primitives_setup_lock`); transaction has `import time` inline |
| `_release_setup_lock()` | Lock table name |
| `setup()` / `teardown()` / `reset()` | Schema-specific SQL |
| `supports_dataframe_mode()` | Transaction: takes `platform_name: str`, validates; Write: returns `True` |
| `get_dataframe_operations()` | Different signatures and delegation |

### OperationResult dataclass

| Field | Transaction | Write |
|---|---|---|
| `status` | `Optional[str] = None` | `str = "SUCCESS"` |
| `skip_reason` | `Optional[str] = None` | `Optional[str] = None` |
| Order of `error`, `status` | `error` first | `status` first |

These are spec-specific - each stays in its own module. The base class
methods use `ResultT = TypeVar("ResultT")` for return-type annotations.

---

## Extraction Decisions

### `benchbox/core/transactional/operations_registry_base.py`

- `OperationsRegistryBase[OperationT](Generic[OperationT])`
- `__init__(self, version: int, operations: dict[str, OperationT])` - callers
  load their catalog and call `super().__init__(catalog.version, catalog.operations)`
- All 8 methods from the current managers move here verbatim

### `benchbox/core/transactional/benchmark_base.py`

- `TransactionalBenchmarkBase(BaseBenchmark, OperationExecutor)`
- Two class variables subclasses set: `_benchmark_label: str` and
  `_staging_tables: dict[str, Any]`
- Methods extracted: `get_data_source_benchmark`, `output_dir` property+setter,
  `generate_data`, `ensure_auxiliary_data_files`, `get_benchmark_info`,
  `get_query`, `get_queries`, `get_queries_by_category`, `run_benchmark`,
  `_prepare_operation` helper
- Remaining spec-local: `__init__`, `execute_operation` body, `_acquire_setup_lock`,
  `_release_setup_lock`, `setup`, `teardown`, `reset`, `supports_dataframe_mode`,
  `get_dataframe_operations`, etc.

### Verification (scoped to target files)

```bash
uv run --with pylint --with pandas --with polars pylint \
  --disable=all --enable=duplicate-code --min-similarity-lines=15 \
  benchbox/core/transaction_primitives/benchmark.py \
  benchbox/core/transaction_primitives/operations.py \
  benchbox/core/write_primitives/benchmark.py \
  benchbox/core/write_primitives/operations.py \
  2>&1 | grep -c 'R0801'
```

Expected: `0` after full extraction.
