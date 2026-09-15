# TPC-DS DuckDB Diagnostic Cross-Check

Date: `2026-04-14`

Source item:
`_project/TODO/main/active/support-unofficial-tpcds-scales-with-methodology-guardrails.yaml` (w10)

Purpose: diagnostic cross-check - verify schema, table presence, and downstream
load compatibility. **Not a product-path evaluation.**

DuckDB version: `1.2.2 7c039464e4` (Python binding `1.5.1`)

---

## Method

```python
import duckdb
con = duckdb.connect(':memory:')
con.execute("INSTALL tpcds; LOAD tpcds;")
con.execute(f"CALL dsdgen(sf={sf})")
```

Scales tested: `sf=0` (schema only), `sf=0.01`, `sf=0.1`, `sf=1.0`.

Row counts were captured for all 24 BenchBox-canonical tables. Column counts were
compared against the 4 tables where dsdgen sf=1.0 `.dat` files are available from
the Gate Zero probe (`call_center`, `store`, `warehouse`, `web_site`). A pipe-
separated export was compared against dsdgen output to verify delimiter compatibility.

---

## Table Presence

DuckDB produces all **24 BenchBox-canonical tables** at every tested scale including
`sf=0.01` and `sf=0.1`. No crashes, no missing tables.

The `dbgen_version` metadata table is **not** present in DuckDB's output.
BenchBox's manifest records an `expected_table_count` of 25 (24 canonical + 1
`dbgen_version`). Any load path using DuckDB-generated data would need to either
omit `dbgen_version` from manifest expectations or supply a synthetic substitute.

---

## Row Counts

### sf=0.01 and sf=0.1 - all tables present

No zero-row tables at either subscale. Fixed-dimension tables that BenchBox marks
as scale-invariant (and expects to hold sf=1.0 row counts) produce **reduced row
counts** at fractional scales in DuckDB:

| Table | sf=0.01 | sf=0.1 | sf=1.0 | BenchBox fixed? | BenchBox sf=1.0 expected |
| --- | --- | --- | --- | --- | --- |
| `call_center` | 1 | 1 | 6 | Yes | 6 |
| `store` | 1 | 1 | 12 | Yes | 12 |
| `warehouse` | 1 | 1 | 5 | Yes | 5 |
| `web_site` | 1 | 3 | 30 | Yes | 30 |
| `reason` | 1 | 3 | 35 | Yes | 35 |
| `ship_mode` | 20 | 20 | 20 | Yes | 20 |
| `income_band` | 20 | 20 | 20 | Yes | 20 |
| `time_dim` | 86,400 | 86,400 | 86,400 | Yes | 86,400 |
| `date_dim` | 73,049 | 73,049 | 73,049 | No | 73,049 |
| `household_demographics` | 7,200 | 7,200 | 7,200 | No | 7,200 |
| `catalog_page` | 11,718 | 11,718 | 11,718 | No | 11,718 |

**Implication for w2 (data contract):** BenchBox's current `FIXED_TABLES` set
assumes these tables always contain their sf=1.0 row counts. DuckDB's behavior
shows that several "fixed" tables (`call_center`, `store`, `warehouse`, `web_site`,
`reason`) actually scale down at fractional scales. A subscale data contract must
not assume fixed-table row counts hold at sf<1.0.

### sf=1.0 vs BenchBox expectations

| Table | DuckDB sf=1.0 | BenchBox expected | Match? |
| --- | --- | --- | --- |
| `call_center` | 6 | 6 | OK |
| `catalog_page` | 11,718 | 11,718 | OK |
| `catalog_returns` | 144,067 | 144,067 | OK |
| `catalog_sales` | 1,441,548 | 1,441,548 | OK |
| `customer` | 100,000 | 100,000 | OK |
| `customer_address` | 50,000 | 50,000 | OK |
| `customer_demographics` | 1,920,800 | 1,920,800 | OK |
| `date_dim` | 73,049 | 73,049 | OK |
| `household_demographics` | 7,200 | 7,200 | OK |
| `income_band` | 20 | 20 | OK |
| `inventory` | 11,745,000 | 11,745,000 | OK |
| `item` | 18,000 | 18,000 | OK |
| `promotion` | 300 | 300 | OK |
| `reason` | 35 | 35 | OK |
| `ship_mode` | 20 | 20 | OK |
| `store` | 12 | 12 | OK |
| `store_returns` | 287,867 | 287,514 | **DIFF +353 (+0.12%)** |
| `store_sales` | 2,880,404 | 2,880,404 | OK |
| `time_dim` | 86,400 | 86,400 | OK |
| `warehouse` | 5 | 5 | OK |
| `web_page` | 60 | 60 | OK |
| `web_returns` | 71,654 | 71,763 | **DIFF −109 (−0.15%)** |
| `web_sales` | 719,384 | 719,384 | OK |
| `web_site` | 30 | 30 | OK |

22/24 tables match BenchBox sf=1.0 expectations exactly. `store_returns` and
`web_returns` differ by < 0.2%, well within BenchBox's 5% large-table tolerance.
The two small discrepancies are consistent with DuckDB using a slightly different
random seed or row-count interpolation strategy for returns tables; they do not
indicate a schema or join-key incompatibility.

---

## Column Counts (Schema)

Verified against dsdgen sf=1.0 `.dat` files from the Gate Zero probe for the four
tables that crashed at subscale:

| Table | dsdgen columns | DuckDB columns | Match? |
| --- | --- | --- | --- |
| `call_center` | 31 | 31 | OK |
| `store` | 29 | 29 | OK |
| `warehouse` | 14 | 14 | OK |
| `web_site` | 26 | 26 | OK |

Column counts match for all four verified tables. Full column-by-column type
comparison was not performed; the schema model in
`benchbox/core/tpcds/schema/models.py` is the authoritative source for type
expectations.

---

## Delimiter Format Compatibility

dsdgen produces **pipe-terminated** lines (trailing `|`):
```
1|AAAAAAAABAAAAAAA|...|12|
```

DuckDB `COPY ... (DELIMITER '|', HEADER false)` produces **pipe-separated** lines
(no trailing `|`):
```
1|AAAAAAAABAAAAAAA|...|12
```

BenchBox's load stack auto-detects trailing delimiters via
`benchbox/utils/file_format.py:has_trailing_delimiter` and handles both formats
transparently. **No format incompatibility with BenchBox's current load path.**

---

## Downstream Scale-Factor Dependencies

The `scale_factor >= 1.0` guard lives exclusively in two places:

| Location | Type | Effect |
| --- | --- | --- |
| `benchbox/core/benchmark_registry.py:546-551` | hard reject | rejects sf<1.0 at benchmark-registration lookup |
| `benchbox/core/tpcds/benchmark/runner.py:162-171` | warn + round up | silently promotes sf<1.0 to 1.0 |

The **data loading path** (`benchbox/platforms/base/data_loading.py`,
`benchbox/platforms/duckdb.py`) does **not** read or check `scale_factor` at all.
It operates on file paths, column names, and table names. Downstream load and
execution code does **not** inherently require official scale points - the guards
are upstream of the load phase.

This confirms that removing or conditionally bypassing the sf<1.0 guard would
expose a functional load path for DuckDB-generated (or patched-dsdgen-generated)
subscale data without changes to the load layer.

---

## Summary for w2 / w3

| Question | Finding |
| --- | --- |
| Does DuckDB produce all 24 tables at sf<1.0? | Yes - no crashes, no missing tables |
| Are "fixed" tables actually fixed at sf<1.0? | **No** - `call_center`, `store`, `warehouse`, `web_site`, `reason` scale down |
| Does DuckDB produce `dbgen_version`? | No - manifest expected_table_count would need adjustment |
| Are column counts compatible with dsdgen? | Yes (verified for the 4 previously-failing tables) |
| Is DuckDB's pipe-delimited output compatible with BenchBox loaders? | Yes - trailing-delimiter auto-detection handles both formats |
| Does downstream load code require official scale points? | No - scale guard is upstream of the load path |
| Should DuckDB become the product data-generation path? | **No** - this remains a diagnostic only; see anti-patterns in the active TODO |

---

## Diagnostic Conclusion

DuckDB's TPC-DS tooling confirms that:

1. All 24 TPC-DS tables are generable at fractional scales - "fractional scales are
   impossible" is too strong a claim in the tooling ecosystem.
2. BenchBox's downstream load code is already compatible with fractional-scale data;
   the block is upstream (generator + registry guards only).
3. The subscale data contract for w2 **must not** assume "fixed" tables hold their
   sf=1.0 row counts at sf<1.0 - at least `call_center`, `store`, `warehouse`,
   `web_site`, and `reason` produce fewer rows.
4. A `dbgen_version` placeholder or manifest schema adjustment will be needed for
   any non-dsdgen data source.

None of these findings change the Gate Zero conclusion: the bundled `dsdgen` binaries
remain broken at sf<1.0 and the generator/distribution track
(`patch-and-redistribute-tpcds-dsdgen-subscale-support`) must complete before the
feature can proceed. DuckDB data is **not** a substitute for dsdgen output in
BenchBox's methodology context.
