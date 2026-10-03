# TPC-DS Source Patches

This document describes patches applied to the TPC-DS dsdgen/dsqgen source code in BenchBox.

## Patch: Stdout Data Generation Support (-FILTER Y flag)

**Date Applied:** 2026-01-15
**Original Fix By:** Greg Rahn (gregrahn)
**Reference:** tpcds-kit (https://github.com/gregrahn/tpcds-kit) commit 7992dbb

### Problem

The upstream TPC-DS dsdgen source code has broken stdout support due to two bugs
that were introduced when official TPC specification imports (v2.10.0, v4.0.0)
reverted community fixes. This prevented efficient workflows like:

- Direct piping to compression (zstd, gzip)
- Memory-efficient streaming pipelines
- Reduced disk I/O during data generation

**Observed behavior before fix:**
- `-FILTER Y` → "ERROR: option 'FILTER' unknown"
- `-_FILTER Y` → Creates file instead of stdout output (fpOutfile overwritten)

### Solution

Port the stdout output fix from tpcds-kit to the BenchBox TPC-DS source. This
enables the `-FILTER Y` flag to output generated data to stdout instead of files.

### Changes

#### 1. params.h - Fix parameter name (Bug #1)

The help text showed `_FILTER` but the code called `is_set("FILTER")` without
the underscore prefix. Since `fnd_param()` uses prefix matching, "FILTER" never
matched "_FILTER".

**File:** `_sources/tpc-ds/tools/params.h` line 64

```c
// Before (broken):
{"_FILTER",     OPT_FLG,            20, "output data to stdout", NULL, "N"},

// After (fixed):
{"FILTER",      OPT_FLG,            20, "output data to stdout", NULL, "N"},
```

#### 2. print.c - Fix fpOutfile overwrite (Bug #2)

When FILTER was set, line 449 correctly set `fpOutfile = stdout`, but line 485
unconditionally overwrote it with `fpOutfile = pTdef->outfile` (which is NULL),
causing "Failed to open output file!" errors.

**File:** `_sources/tpc-ds/tools/print.c` lines 480-486

```c
// Before (broken):
#endif
       }
   }

   fpOutfile = pTdef->outfile;  // Overwrites stdout!
   res = (fpOutfile != NULL);

// After (fixed):
#endif
       }
      fpOutfile = pTdef->outfile;  // Moved inside else block
   }

   res = (fpOutfile != NULL);
```

### Usage

```bash
# Generate ship_mode table to stdout (can be piped to compression)
./dsdgen -TABLE ship_mode -SCALE 1 -FILTER Y | zstd > ship_mode.dat.zst

# Generate date_dim to stdout with fixed seed for reproducibility
./dsdgen -TABLE date_dim -SCALE 1 -FILTER Y -RNGSEED 12345 > date_dim.dat

# Verify stdout output works
./dsdgen -TABLE ship_mode -SCALE 1 -FILTER Y -RNGSEED 1 | head -5
```

### Limitations

- The `-FILTER Y` flag outputs data to stdout; use shell redirection or piping
- When using `-FILTER Y`, no `.dat` file is created in the output directory
- For parallel generation, run multiple dsdgen processes with different table names

### Verification

After applying patches and recompiling:

```bash
# Verify FILTER flag appears in help (not _FILTER)
./dsdgen -help 2>&1 | grep FILTER
# Expected: "FILTER" without underscore prefix

# Test stdout output produces data
./dsdgen -TABLE ship_mode -SCALE 1 -FILTER Y -RNGSEED 1 | wc -l
# Expected: 20 (ship_mode has 20 rows at SF1)

# Verify output matches file-based generation
./dsdgen -TABLE ship_mode -SCALE 1 -FILTER Y -RNGSEED 1 > /tmp/stdout.dat
./dsdgen -TABLE ship_mode -SCALE 1 -RNGSEED 1 -DIR /tmp -FORCE
diff /tmp/stdout.dat /tmp/ship_mode.dat
# Expected: No differences
```

---

## Patch: Linux Build Compatibility

**Date Applied:** 2026-01-15

### Problem

The TPC-DS source failed to compile on Linux due to:
1. Missing `MAXINT` definition (not in glibc, only in some BSD headers)
2. GCC 10+ changed default from `-fcommon` to `-fno-common`, causing multiple
   definition errors for tentative definitions

### Solution

Add Linux-specific compatibility fixes to enable clean compilation.

### Changes

#### 1. porting.h - Add MAXINT definition for Linux

**File:** `_sources/tpc-ds/tools/porting.h` lines 120-122

```c
#ifdef LINUX
#define MAXINT INT_MAX
#endif
```

Location: After the existing `#ifdef MACOS` block for MAXINT

#### 2. makefile - Add -fcommon for GCC 10+ compatibility

**File:** `_sources/tpc-ds/tools/makefile` line 59

```make
# Before:
LINUX_CFLAGS    = -g -Wall

# After:
LINUX_CFLAGS    = -g -Wall -fcommon
```

### Verification

```bash
# Clean build on Linux
cd _sources/tpc-ds/tools
make clean
make

# Verify binaries were created
ls -la dsdgen dsqgen
```

---

## Patch: Query 72 Ambiguous Column Reference Fix

**Date Applied:** 2026-01-25

### Problem

TPC-DS Query 72 template has an ambiguous column reference in the ORDER BY clause.
The query joins `date_dim` three times with aliases d1, d2, d3, but the ORDER BY
clause uses unqualified `d_week_seq` which causes binding errors on strict SQL
engines like DuckDB:

```
Binder Error: Ambiguous reference to column name "d_week_seq"
(use: "d1.d_week_seq" or "d2.d_week_seq")
```

### Solution

Qualify the `d_week_seq` column in the ORDER BY clause with the `d1` table alias,
matching the SELECT and GROUP BY clauses which already use `d1.d_week_seq`.

### Changes

**File:** `query_templates/query72.tpl` line 65

```sql
-- Before (broken):
order by total_cnt desc, i_item_desc, w_warehouse_name, d_week_seq

-- After (fixed):
order by total_cnt desc, i_item_desc, w_warehouse_name, d1.d_week_seq
```

### Files Modified

This fix must be applied to all copies of the query template:

- `_sources/tpc-ds/query_templates/query72.tpl`
- `benchbox/_binaries/tpc-ds/templates/query_templates/query72.tpl`
- `_binaries/tpc-ds/darwin-arm64/query_templates/query72.tpl`
- `_binaries/tpc-ds/darwin-x86_64/query_templates/query72.tpl`
- `_binaries/tpc-ds/linux-arm64/query_templates/query72.tpl`
- `_binaries/tpc-ds/linux-x86_64/query_templates/query72.tpl`
- `_binaries/tpc-ds/windows-x86_64/query_templates/query72.tpl`

### Verification

```bash
# Generate Query 72 and verify the ORDER BY is qualified
uv run benchbox run --platform duckdb --benchmark tpcds --scale 1.0 \
    --phases throughput --seed 463933

# Should complete without "Ambiguous reference" errors for Query 72
```

### Notes

This is a bug in the official TPC-DS query template. The SELECT clause (line 43),
WHERE clause (line 58), and GROUP BY clause (line 64) all correctly use
`d1.d_week_seq`, but the ORDER BY clause (line 65) was missing the qualifier.

---

## Patch: Sub-SF1 Scale Factor Support

**Date Applied:** 2026-04-14
**Reference:** DuckDB TPC-DS extension - `duckdb/duckdb` `extension/tpcds/dsdgen/dsdgen-c/scaling.cpp`
**Probe evidence:** `_sources/tpcds-subscale-probe.md` → "Post-Patch Gate Zero (w3)"

### Problem

Upstream `dsdgen` crashes with `SIGSEGV` (exit 139) for any scale factor below 1.0 on the four small-dimension tables `call_center`, `store`, `warehouse`, and `web_site`. The crash is deterministic across platforms because it is rooted in `scaling.c` / `dist.c`, not in platform code. See `_sources/tpcds-subscale-probe.md` for full root-cause analysis.

Condensed fault path (for `dsdgen -table call_center -scale 0.01`):

1. `scaling.c:get_rowcount` calls `nScale = get_int("SCALE")`. `atoi("0.01")` returns **0**.
2. `switch(nScale)` with value `0` falls to the `default:` branch.
3. For `call_center` / `store` / `warehouse` / `web_site`, `dist_member(NULL, "rowcounts", nTable+1, 3)` returns 3 → `LogScale(nTable, 0)` is called.
4. `LogScale` calls `getScaleSlot(0)`, which returns `i=0` because `0 > arScaleVolume[0]=1` is false on the first loop iteration.
5. `LogScale` calls `dist_weight(NULL, "rowcounts", nTable+1, 0)` with weight-set index 0.
6. `dist.c:512` accesses `dist->weight_sets[0 - 1]` = `weight_sets[-1]` → `SIGSEGV`.

### Solution

Mirror the DuckDB TPC-DS extension's approach: prevent `LogScale` / `LinearScale` from being entered at all for sub-SF1 scales, then apply the fractional factor as a post-multiplier on the SF=1 baseline row count, with a minimum of one row per table so no small-dimension table ends up empty. Read the scale as a double so `"0.01"` survives CLI parsing rather than being truncated to zero.

### Changes

#### 1. `params.h` - Accept fractional scale from the CLI

**File:** `_sources/tpc-ds/tools/params.h` line 53

```c
// Before (rejects "0.01"):
{"SCALE",   OPT_INT,    9, "volume of data to generate in GB", SetScaleIndex, "1"},

// After (accepts "0.01"):
{"SCALE",   OPT_STR,    9, "volume of data to generate in GB", SetScaleIndex, "1"},
```

`OPT_INT` caused the option parser to reject non-integer strings before `main()` ran. Switching to `OPT_STR` preserves the raw string so downstream code can decide how to interpret it. `SetScaleIndex()` already guards `atoi(szValue) == 0` and clamps to 1, so `_SCALE_INDEX` stays correct for fractional scales.

#### 2. `r_params.h` / `r_params.c` - Add `get_dbl()`

**File:** `_sources/tpc-ds/tools/r_params.h`

```c
int     get_int(char *var);
double  get_dbl(char *var);   // NEW
void    set_int(char *var, char *val);
```

**File:** `_sources/tpc-ds/tools/r_params.c`

```c
double
get_dbl(char *var)
{
    int nParam;

    init_params();
    nParam = fnd_param(var);
    if (nParam >= 0)
        return(atof(params[options[nParam].index]));
    else
        return(0.0);
}
```

Mirrors `get_int()` but uses `atof()` instead of `atoi()`, so `"0.01"` yields `0.01` rather than `0`.

#### 3. `scaling.c` - Core row-count fix

**File:** `_sources/tpc-ds/tools/scaling.c` in `get_rowcount()`

Three coordinated changes:

```c
// Before:
static int bScaleSet = 0,
    nScale;
// ...
nScale = get_int("SCALE");
// ...
for (nTable=CALL_CENTER; nTable <= MAX_TABLE; nTable++) {
    switch(nScale) { ... }
    // multiplier loop ...
    arRowcount[nTable].kBaseRowcount *= nMultiplier;
} /* for each table */

// After:
static int bScaleSet = 0;
static double nScale;
int iScale;
// ...
nScale = get_dbl("SCALE");
// ...
iScale = (nScale < 1) ? 1 : (int)nScale;
for (nTable=CALL_CENTER; nTable <= MAX_TABLE; nTable++) {
    switch(iScale) { ... }
    // multiplier loop ...
    arRowcount[nTable].kBaseRowcount *= nMultiplier;

    if (arRowcount[nTable].kBaseRowcount >= 0) {
        if (nScale < 1) {
            int mem = dist_member(NULL, "rowcounts", nTable + 1, 3);
            if (!(mem == 1 && nMultiplier == 1)) {
                arRowcount[nTable].kBaseRowcount =
                    (ds_key_t)((double)arRowcount[nTable].kBaseRowcount * nScale);
            }
            if (arRowcount[nTable].kBaseRowcount == 0)
                arRowcount[nTable].kBaseRowcount = 1;
        }
    }
} /* for each table */
```

`iScale = max(1, (int)nScale)` forces fractional scales into the `case 1:` branch of the switch, which reads the SF=1 rowcount directly from the distribution file and never calls `LogScale` / `LinearScale`. The post-multiplier block then scales the result proportionally for sub-SF1, with the min-1 floor preserving the small-dimension tables.

The guard `!(mem == 1 && nMultiplier == 1)` skips the multiplication for `StaticScale`-type tables with no power-of-10 multiplier, matching DuckDB's behavior: those tables carry fixed row counts that should not shrink below the SF=1 definition.

Also updated:

```c
// Before:
if ((table == INVENTORY))
    return(sc_w_inventory(nScale));

// After:
if ((table == INVENTORY))
    return(sc_w_inventory((int)nScale));
```

`sc_w_inventory()` does not use the `nScale` parameter in its body, so the signature stays `int`; the cast suppresses the narrowing-conversion warning.

#### 4. `w_call_center.c` - Guard employee count upper bound

**File:** `_sources/tpc-ds/tools/w_call_center.c`

```c
// Before:
static int bInit = 0,
    nScale;
// ...
nScale = get_int("SCALE");
// ...
genrand_integer(&r->cc_employees, DIST_UNIFORM, 1,
    CC_EMPLOYEE_MAX * nScale * nScale, 0, CC_EMPLOYEES);

// After:
static int bInit = 0;
static double nScale;
// ...
nScale = get_dbl("SCALE");
// ...
genrand_integer(&r->cc_employees, DIST_UNIFORM, 1,
    nScale >= 1 ? (int)(CC_EMPLOYEE_MAX * nScale * nScale) : (int)CC_EMPLOYEE_MAX,
    0, CC_EMPLOYEES);
```

For fractional scales `CC_EMPLOYEE_MAX * nScale * nScale` collapses to 0 and yields an invalid `[1, 0]` `genrand_integer` range. For sub-SF1 we keep the unscaled `CC_EMPLOYEE_MAX` upper bound - scale-factor reduction is already carried by the row count drop in `scaling.c`, so the attribute range does not need to shrink further.

### Verification

Run on the host toolchain after rebuilding:

```bash
# Rebuild
cd _sources/tpc-ds/tools && make clean && make

# Gate Zero probe (darwin-arm64 source build)
for SF in 0.01 0.1 0.5 1.0; do
  for TBL in call_center store warehouse web_site; do
    ./dsdgen -verbose n -force y -terminate n -scale "$SF" -table "$TBL" -dir /tmp/probe
  done
done
```

Expected: all 16 combinations exit 0 with non-empty output. `sf=1.0` checksums must match the pre-patch control row in `_sources/tpcds-subscale-probe.md`. See the "Post-Patch Gate Zero (w3)" section of that document for row counts and SHA-256 checksums from the reference run.

### Limitations

- Sub-SF1 scale factors are **not TPC-DS compliant**. They are a development-only convenience; do not publish results generated at `sf < 1.0`.
- This patch has been validated on `darwin-arm64` only. Gate Zero must be rerun on every distributed bundle target (`darwin-x86_64`, `linux-arm64`, `linux-x86_64`, `windows-x86_64`) before shipped binaries can be replaced. See TODO `patch-and-redistribute-tpcds-dsdgen-subscale-support` `w4`.
- `dsqgen` uses `get_int("SCALE")` in `qgen.y:316` and `qgen.y:365`. Query generation at sub-SF1 is out of scope here; fractional-scale query substitution would need a separate patch.

---

## Attribution

The stdout fix was originally implemented by **Greg Rahn** ([@gregrahn](https://github.com/gregrahn))
in the [tpcds-kit](https://github.com/gregrahn/tpcds-kit) repository (commit 7992dbb, 2013).

The fix was lost when official TPC specification imports (v2.10.0 for tpcds-kit,
v4.0.0 for BenchBox) replaced the patched source files with upstream versions
that contained the original bugs.

BenchBox re-applied these fixes based on analysis of the tpcds-kit commit history
and verification of the root cause through testing.

---

## Applying the Patch

To apply these changes to a fresh TPC-DS source distribution:

```bash
# From the TPC-DS source root directory (containing tools/)
patch -p1 < stdout-support.patch

# Rebuild
cd tools
make
```

The patch file `stdout-support.patch` is provided in the same directory as this document.

**Note:** The patch uses unified diff format (`-p1` strips the leading `a/` or `b/` prefix).

---

## Related Files

- `_sources/tpc-h/PATCHES.md` - Similar patches for TPC-H dbgen
- `_project/DONE/tpcds-stdout-fix/` - Implementation TODO items
- `tests/unit/core/tpcds/test_stdout_datagen.py` - Regression tests
