# TPC-DS Subscale Probe

Date: `2026-04-13`

Host:
`Darwin joe-mac-mini.local 25.3.0 Darwin Kernel Version 25.3.0: Wed Jan 28 20:54:55 PST 2026; root:xnu-12377.91.3~2/RELEASE_ARM64_T8132 arm64`

Source item:
`_project/TODO/main/active/support-unofficial-tpcds-scales-with-methodology-guardrails.yaml`

## Method

- Probe target tables: `call_center`, `store`, `warehouse`, `web_site`
- Required scales: `0.01`, `0.1`, `0.5`
- Control scale: `1.0`
- Command template:
  `(cd _binaries/tpc-ds/<bundle> && ./dsdgen -verbose y -force y -terminate n -scale <sf> -table <table> -dir <tmpdir>)`
- Captured per run: exit code, output file presence, row count, SHA-256, and stderr head
- Foreign-OS bundles were inspected with `file` only. This Darwin host has no `qemu-*` or `wine*` binaries installed, so `linux-*` and `windows-*` bundles were not runnable in this workspace.

## Bundle Inventory

| Bundle | Binary type | Executed here | Notes |
| --- | --- | --- | --- |
| `darwin-arm64` | `Mach-O 64-bit executable arm64` | Yes | Host-native |
| `darwin-x86_64` | `Mach-O 64-bit executable x86_64` | Yes | Runs on this host via Rosetta |
| `linux-arm64` | `ELF 64-bit LSB pie executable, ARM aarch64` | No | Foreign OS binary |
| `linux-x86_64` | `ELF 64-bit LSB pie executable, x86-64` | No | Foreign OS binary |
| `windows-arm64` | `PE32+ executable (console) x86-64` | No | Bundle name says arm64, binary is x86-64 |
| `windows-x86_64` | `PE32+ executable (console) x86-64` | No | Foreign OS binary |

## Measured Results

Both executed macOS bundles (`darwin-arm64`, `darwin-x86_64`) produced the same results.

| Table | `sf=0.01` | `sf=0.1` | `sf=0.5` | `sf=1.0` control |
| --- | --- | --- | --- | --- |
| `call_center` | Exit `139`, no file | Exit `139`, no file | Exit `139`, no file | Exit `0`, `call_center.dat`, `6` rows, `524fe085f9e12e5e6ee93aba8675e732f179290d933e39abb025d4b6b7def47f` |
| `store` | Exit `139`, no file | Exit `139`, no file | Exit `139`, no file | Exit `0`, `store.dat`, `12` rows, `2684b82f2600bfb8035bfb036d4cf4ecce1ebce50570148f3217cca61efb7e99` |
| `warehouse` | Exit `139`, no file | Exit `139`, no file | Exit `139`, no file | Exit `0`, `warehouse.dat`, `5` rows, `19d027ad7040658096053bed9c9210a9a6ed6a3459c6fbc6a8abd6a8a6d333cc` |
| `web_site` | Exit `139`, no file | Exit `139`, no file | Exit `139`, no file | Exit `0`, `web_site.dat`, `30` rows, `f251496d3fdcc09c3e10ac6642b668073be15e21a169ece805e65b9ec34edc1a` |

Observed stderr behavior:

- Every failing subscale run printed only the standard `dsdgen` banner before exiting with `139`.
- Every `sf=1.0` control succeeded and printed the usual qualification warning.
- The matching `sf=1.0` row counts and checksums across both macOS bundles show the probe harness itself is valid.

## Bundled Fallback Data

`examples/data/tpcds_sf001/README.txt` contains only:

`sample placeholder for scale factor 0.01`

There is no usable bundled `sf001` sample dataset in the repo today.

## Gate Zero Conclusion

- The currently runnable bundled macOS `dsdgen` binaries do **not** support unofficial TPC-DS subscales for required small-dimension tables. They crash before writing any data at `sf=0.01`, `0.1`, and `0.5`.
- BenchBox should **not** remove the current `scale_factor >= 1.0` guard or introduce unofficial-scale UX on top of the existing bundles.
- The higher-level unofficial-scale feature is blocked on a separate generator/distribution track: patched binaries with cross-bundle verification, or a different data-source strategy such as user-supplied/pre-generated datasets.

## Fault Boundary Investigation (Post-Gate-Zero Follow-up)

Date: `2026-04-13`

After Gate Zero confirmed exit 139 via the BenchBox wrapper, a follow-up investigation isolated the crash boundary and identified the exact source-level fault.

### Direct-Binary Minimal Repro

The BenchBox wrapper was removed from the equation by invoking the packaged host-native binary directly:

```
(cd _binaries/tpc-ds/darwin-arm64 && ./dsdgen -table call_center -scale 0.01 -dir /tmp/repro)
```

Result: exit `139`, no `call_center.dat` produced - identical to the wrapper-invoked result. The crash occurs before any BenchBox code path runs.

### Source Build

A fresh `dsdgen` was compiled from the checked-in TPC-DS C sources at `_sources/tpc-ds/tools` under `/tmp/tpcds_source_build/`. The same minimal repro was run against this source-built binary:

```
/tmp/tpcds_source_build/dsdgen -table call_center -scale 0.01 -dir /tmp/tpcds_source_repro2
```

Result: exit `139`, no output. Identical behavior to the bundled binary - the crash is in the upstream generator logic, not a packaging artifact.

### lldb Backtrace (source-built binary, macOS arm64)

| Frame | Location | Function |
| --- | --- | --- |
| 0 | `_sources/tpc-ds/tools/dist.c:512` | `dist_weight` |
| 1 | `_sources/tpc-ds/tools/scaling.c:124` | `LogScale` |
| 2 | `_sources/tpc-ds/tools/scaling.c:319` | `get_rowcount` |
| 3 | `_sources/tpc-ds/tools/parallel.c:64` | `split_work` |
| 4 | `_sources/tpc-ds/tools/driver.c:549` | `main` |

### Root Cause

`dist.c:512` dereferences `dist->weight_sets[wset - 1]`. When `wset=0` this accesses `weight_sets[-1]` - a null dereference causing SIGSEGV.

`wset=0` originates in `scaling.c:124` (`LogScale`):

```c
nDelta = dist_weight(NULL, "rowcounts", nTable + 1, i + 1)
       - dist_weight(NULL, "rowcounts", nTable + 1, i);
```

The subtracted call passes `i` as the weight-set index. When `i=0`, `dist_weight` receives `wset=0`.

`i` is returned by `getScaleSlot(nTargetGB)` at `scaling.c:90-96`:

```c
static int arScaleVolume[9] = {1, 10, 100, 300, 1000, 3000, 10000, 30000, 100000};

int getScaleSlot(int nTargetGB) {
    int i;
    for (i=0; nTargetGB > arScaleVolume[i]; i++);
    return(i);
}
```

`arScaleVolume[0] = 1`. Any scale factor below `1.0` satisfies `nTargetGB <= arScaleVolume[0]` immediately, so the loop exits with `i=0`. This is deterministic for any input scale < 1.0.

### Conclusion

The crash is an invariant of upstream `dsdgen` distribution-table logic, not a platform-specific quirk or a macOS packaging issue. Any scale factor < 1.0 causes `getScaleSlot` to return `0`, which propagates through `LogScale` → `dist_weight` → out-of-bounds `weight_sets[-1]` access. The fix must be applied at the source level in `_sources/tpc-ds/tools/scaling.c` by guarding against `i=0` in `LogScale` before calling `dist_weight` with a zero weight-set index. See `_project/TODO/main/planning/patch-and-redistribute-tpcds-dsdgen-subscale-support.yaml`.

## Post-Patch Gate Zero (w3)

Date: `2026-04-14`

The source patch described in `_sources/tpc-ds/PATCHES.md` ("Sub-SF1 Scale Factor Support") was applied to `_sources/tpc-ds/tools/` and a fresh `dsdgen` was built at `/tmp/tpcds_subscale_build/tools/dsdgen` on the native `darwin-arm64` host. The Gate Zero probe was rerun against the patched source-build binary using the same command template and tables as the pre-patch probe above.

### Approach

The patch follows DuckDB's approach in `duckdb/duckdb` `extension/tpcds/dsdgen/dsdgen-c/scaling.cpp`: rather than guarding `LogScale` against `i=0`, it prevents `LogScale` from being entered at all for sub-SF1 scales. The scale is read as a double via a new `get_dbl()` function, and a bridge variable `iScale = nScale < 1 ? 1 : (int)nScale` routes fractional scales into the existing `case 1:` branch of the `get_rowcount()` switch. A post-multiplier block then scales the SF=1 baseline row count by `nScale` and enforces a minimum of one row per table so no table ends up empty.

### Measured Results (darwin-arm64 source build)

| Table | `sf=0.01` | `sf=0.1` | `sf=0.5` | `sf=1.0` control |
| --- | --- | --- | --- | --- |
| `call_center` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `3` rows, `ecb94f621b827cc70c4a9d0d9e98b7044d9f52afcbbf581d7a4081652af92a97` | Exit `0`, `6` rows, `524fe085f9e12e5e6ee93aba8675e732f179290d933e39abb025d4b6b7def47f` |
| `store` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `6` rows, `f12ee4b2088a625c46babd5e0de1f90fc540bf215b8d95de6fce07caead07bcc` | Exit `0`, `12` rows, `2684b82f2600bfb8035bfb036d4cf4ecce1ebce50570148f3217cca61efb7e99` |
| `warehouse` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `2` rows, `838c47dbff662223b35d4d5ae1a4d10b6fb30c1c03dce2de2a040fd514466410` | Exit `0`, `5` rows, `19d027ad7040658096053bed9c9210a9a6ed6a3459c6fbc6a8abd6a8a6d333cc` |
| `web_site` | Exit `0`, `1` row, `5f1397f43ec6bc89420e4b88257a7a2cf726e5403c5fce5572518a6af8b47a30` | Exit `0`, `3` rows, `e1992549ccbfdfde42dcd12730edb5bde4763737c5258750a362e2fe7bc0f847` | Exit `0`, `15` rows, `80d3dd92af1105f8fe58dcd620543824cabe690aac30e9fc2c58afb5efcfbd59` | Exit `0`, `30` rows, `f251496d3fdcc09c3e10ac6642b668073be15e21a169ece805e65b9ec34edc1a` |

### SF=1.0 Regression Check

All four `sf=1.0` row counts and SHA-256 checksums from the patched source build **match the pre-patch control column exactly**. The patch does not perturb canonical TPC-DS generation.

### Fractional Scale Behavior

- `sf=0.5` row counts are exactly 50% of `sf=1.0` (with rounding): call_center 3/6, store 6/12, warehouse 2/5, web_site 15/30. This confirms the post-multiplier `kBaseRowcount * nScale` path works as designed.
- `sf=0.01` and `sf=0.1` row counts reflect the `if (kBaseRowcount == 0) kBaseRowcount = 1;` floor: SF=1 counts of 5-30 would round to 0 at these scales without it.
- Identical checksums for `sf=0.01` / `sf=0.1` on call_center / store / warehouse are expected: both scales produce a single row at the same PRNG seed, so the first-row content is byte-identical.

### Scope Limits of This Probe

- **Darwin-arm64 only.** Linux and Windows bundle targets (`linux-arm64`, `linux-x86_64`, `windows-x86_64`) were not rebuilt or reprobed in this session. Cross-bundle Gate Zero evidence remains required for w4.
- **Source patches only.** `_binaries/tpc-ds/` was not modified. The shipped bundles continue to exhibit the documented pre-patch crash.
- **BenchBox Python guard still in place.** `TPCDSDataGenerator._validate_parameters()` still rejects `scale_factor < 1.0`; it must not be removed until every shipped bundle passes Gate Zero.

## Cross-Bundle Gate Zero (w4)

Date: `2026-04-14`

The patched binaries were built for all distributable platforms and the Gate Zero probe was rerun for each native platform using a consistent harness. `windows-arm64` and `windows-x86_64` were not rebuilt (no MinGW cross-compiler available on the darwin-arm64 host); those bundles remain at their upstream unpatched versions and continue to exhibit exit 139 for sub-SF1 scales.

### Build Summary

| Bundle | Toolchain | Binary type |
| --- | --- | --- |
| `darwin-arm64` | macOS native gcc/clang (arm64 host) | `Mach-O 64-bit executable arm64` |
| `darwin-x86_64` | macOS native gcc/clang with `-arch x86_64` | `Mach-O 64-bit executable x86_64` |
| `linux-arm64` | Docker `ubuntu:22.04` / `--platform linux/arm64` | `ELF 64-bit LSB pie executable, ARM aarch64` |
| `linux-x86_64` | Docker `ubuntu:22.04` / `--platform linux/amd64` | `ELF 64-bit LSB pie executable, x86-64` |
| `windows-arm64` | **Not rebuilt** - no MinGW on host | upstream unpatched (exits 139 for sf < 1) |
| `windows-x86_64` | **Not rebuilt** - no MinGW on host | upstream unpatched (exits 139 for sf < 1) |

### Measured Results - darwin-x86_64 (Rosetta, native x86_64 binary)

All 16 SF×table combinations: exit 0. Checksums byte-identical to darwin-arm64 w3 reference.

| Table | `sf=0.01` | `sf=0.1` | `sf=0.5` | `sf=1.0` control |
| --- | --- | --- | --- | --- |
| `call_center` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `3` rows, `ecb94f621b827cc70c4a9d0d9e98b7044d9f52afcbbf581d7a4081652af92a97` | Exit `0`, `6` rows, `524fe085f9e12e5e6ee93aba8675e732f179290d933e39abb025d4b6b7def47f` |
| `store` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `6` rows, `f12ee4b2088a625c46babd5e0de1f90fc540bf215b8d95de6fce07caead07bcc` | Exit `0`, `12` rows, `2684b82f2600bfb8035bfb036d4cf4ecce1ebce50570148f3217cca61efb7e99` |
| `warehouse` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `2` rows, `838c47dbff662223b35d4d5ae1a4d10b6fb30c1c03dce2de2a040fd514466410` | Exit `0`, `5` rows, `19d027ad7040658096053bed9c9210a9a6ed6a3459c6fbc6a8abd6a8a6d333cc` |
| `web_site` | Exit `0`, `1` row, `5f1397f43ec6bc89420e4b88257a7a2cf726e5403c5fce5572518a6af8b47a30` | Exit `0`, `3` rows, `e1992549ccbfdfde42dcd12730edb5bde4763737c5258750a362e2fe7bc0f847` | Exit `0`, `15` rows, `80d3dd92af1105f8fe58dcd620543824cabe690aac30e9fc2c58afb5efcfbd59` | Exit `0`, `30` rows, `f251496d3fdcc09c3e10ac6642b668073be15e21a169ece805e65b9ec34edc1a` |

### Measured Results - linux-x86_64 (Docker `ubuntu:22.04`, `--platform linux/amd64`)

All 16 SF×table combinations: exit 0. Checksums byte-identical to darwin-arm64 w3 reference.

| Table | `sf=0.01` | `sf=0.1` | `sf=0.5` | `sf=1.0` control |
| --- | --- | --- | --- | --- |
| `call_center` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `3` rows, `ecb94f621b827cc70c4a9d0d9e98b7044d9f52afcbbf581d7a4081652af92a97` | Exit `0`, `6` rows, `524fe085f9e12e5e6ee93aba8675e732f179290d933e39abb025d4b6b7def47f` |
| `store` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `6` rows, `f12ee4b2088a625c46babd5e0de1f90fc540bf215b8d95de6fce07caead07bcc` | Exit `0`, `12` rows, `2684b82f2600bfb8035bfb036d4cf4ecce1ebce50570148f3217cca61efb7e99` |
| `warehouse` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `2` rows, `838c47dbff662223b35d4d5ae1a4d10b6fb30c1c03dce2de2a040fd514466410` | Exit `0`, `5` rows, `19d027ad7040658096053bed9c9210a9a6ed6a3459c6fbc6a8abd6a8a6d333cc` |
| `web_site` | Exit `0`, `1` row, `5f1397f43ec6bc89420e4b88257a7a2cf726e5403c5fce5572518a6af8b47a30` | Exit `0`, `3` rows, `e1992549ccbfdfde42dcd12730edb5bde4763737c5258750a362e2fe7bc0f847` | Exit `0`, `15` rows, `80d3dd92af1105f8fe58dcd620543824cabe690aac30e9fc2c58afb5efcfbd59` | Exit `0`, `30` rows, `f251496d3fdcc09c3e10ac6642b668073be15e21a169ece805e65b9ec34edc1a` |

### Measured Results - linux-arm64 (Docker `ubuntu:22.04`, `--platform linux/arm64`)

All 16 SF×table combinations: exit 0. Checksums byte-identical to darwin-arm64 w3 reference.

| Table | `sf=0.01` | `sf=0.1` | `sf=0.5` | `sf=1.0` control |
| --- | --- | --- | --- | --- |
| `call_center` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `1` row, `832caa83e42a04fad13fe71ee25a08c503c5dd20965ab3ccad6cea3c0d486059` | Exit `0`, `3` rows, `ecb94f621b827cc70c4a9d0d9e98b7044d9f52afcbbf581d7a4081652af92a97` | Exit `0`, `6` rows, `524fe085f9e12e5e6ee93aba8675e732f179290d933e39abb025d4b6b7def47f` |
| `store` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `1` row, `1b0d58cf0792613377fd796d88ced8e03408a4bc278085f66363fb7c179d1c22` | Exit `0`, `6` rows, `f12ee4b2088a625c46babd5e0de1f90fc540bf215b8d95de6fce07caead07bcc` | Exit `0`, `12` rows, `2684b82f2600bfb8035bfb036d4cf4ecce1ebce50570148f3217cca61efb7e99` |
| `warehouse` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `1` row, `0ce7e7ef2a236c2582353fc3a6a67b12039354adb2d74471c926ffc128371f3c` | Exit `0`, `2` rows, `838c47dbff662223b35d4d5ae1a4d10b6fb30c1c03dce2de2a040fd514466410` | Exit `0`, `5` rows, `19d027ad7040658096053bed9c9210a9a6ed6a3459c6fbc6a8abd6a8a6d333cc` |
| `web_site` | Exit `0`, `1` row, `5f1397f43ec6bc89420e4b88257a7a2cf726e5403c5fce5572518a6af8b47a30` | Exit `0`, `3` rows, `e1992549ccbfdfde42dcd12730edb5bde4763737c5258750a362e2fe7bc0f847` | Exit `0`, `15` rows, `80d3dd92af1105f8fe58dcd620543824cabe690aac30e9fc2c58afb5efcfbd59` | Exit `0`, `30` rows, `f251496d3fdcc09c3e10ac6642b668073be15e21a169ece805e65b9ec34edc1a` |

### Cross-Platform Checksum Consistency

SHA-256 checksums are **byte-identical** across darwin-arm64, darwin-x86_64, linux-arm64, and linux-x86_64 for every SF×table combination. This confirms the patch produces deterministic output independent of platform endianness, word size, or OS.

### Windows Status

`windows-arm64` and `windows-x86_64` binaries were NOT rebuilt. MinGW or a comparable Windows cross-compiler was not available on the darwin-arm64 build host. The shipped Windows bundles remain at the upstream unpatched version and will exhibit exit 139 for `sf < 1.0`. A separate TODO item should track obtaining or building a Windows cross-compilation environment.

### Deployment

- Patched `dsdgen` and `dsqgen` binaries deployed to `_binaries/tpc-ds/` for all four Linux/macOS targets.
- `EULA.txt` (copy of `_sources/tpc-ds/EULA.txt`) and `NOTICE.txt` added to all six bundle directories to satisfy TPC EULA v2.2 Clause 9a/9b compliance requirements.
- `_binaries/tpc-ds/NOTICE.txt` top-level notice also added.
