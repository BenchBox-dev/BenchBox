# TPC Binary Auto-Compilation Guide

```{tags} contributor, guide, tpc-h, tpc-ds
```

This document describes how BenchBox compiles the TPC-H and TPC-DS tools from source.

Installed packages ship pre-compiled binaries in `benchbox/_binaries/`, so most
users never compile anything. Auto-compilation applies only in a source
checkout, because it needs the TPC source tree under `_sources/`, which wheels
do not include.

## Overview

In a source checkout, BenchBox can build the TPC-H and TPC-DS tools automatically when the source code is present but no usable binary is found. This saves contributors a manual compilation step.

## Supported Binaries

The auto-compilation system supports the following TPC binary tools:

### TPC-H Tools
- **dbgen**: Data generation tool for TPC-H benchmark
- **qgen**: Query generation tool for TPC-H benchmark

### TPC-DS Tools
- **dsdgen**: Data generation tool for TPC-DS benchmark
- **dsqgen**: Query generation tool for TPC-DS benchmark

## How It Works

1. **Detection**: The system checks for source directories in `_sources/tpc-h/dbgen/` and `_sources/tpc-ds/tools/` (present only in a source checkout)
2. **Binary Check**: Verifies if compiled binaries already exist and are executable
3. **Auto-Compilation**: If source exists but binaries are missing, attempts automatic compilation
4. **Fallback**: Falls back to traditional error reporting if compilation fails

## System Requirements

### Required Dependencies

#### All Platforms
- **make**: Build system (GNU Make or compatible)
- **gcc**: C compiler (or equivalent like clang)

#### TPC-DS Specific
- **yacc/bison**: Parser generator (required for TPC-DS query templates)

### Platform Support
- **macOS**: Full support with Xcode Command Line Tools or Homebrew
- **Linux**: Full support with build-essential package
- **Windows**: Full TPC-H support via Docker cross-compilation (MinGW), TPC-DS has cross-compilation limitations

## Installation Instructions

### macOS
```bash
# Install Xcode Command Line Tools
xcode-select --install

# OR install via Homebrew
brew install make gcc bison
```

### Ubuntu/Debian Linux
```bash
sudo apt update
sudo apt install build-essential bison flex
```

### CentOS/RHEL/Fedora Linux
```bash
# CentOS/RHEL
sudo yum groupinstall "Development Tools"
sudo yum install bison flex

# Fedora
sudo dnf groupinstall "Development Tools"
sudo dnf install bison flex
```

### Windows
```bash
# Pre-compiled binaries available via Docker cross-compilation
# No manual installation required for TPC-H (dbgen, qgen)

# For development/custom builds using WSL (recommended)
sudo apt update
sudo apt install build-essential bison flex

# For development/custom builds using MSYS2
pacman -S make gcc bison flex

# Docker-based compilation (automatic)
# Windows binaries are auto-compiled using MinGW cross-compilation
# TPC-H: Full support (dbgen.exe, qgen.exe)
# TPC-DS: Limited support due to cross-compilation constraints
```

## Configuration

### Enable/Disable Auto-Compilation

Auto-compilation can be controlled programmatically:

```python
from benchbox.utils.tpc_compilation import get_tpc_compiler

# Enable auto-compilation (default)
compiler = get_tpc_compiler(auto_compile=True)

# Disable auto-compilation
compiler = get_tpc_compiler(auto_compile=False)
```

### Environment Variables

The system respects standard build environment variables:
- `CC`: C compiler (defaults to gcc)
- `CFLAGS`: Compiler flags
- `MAKE`: Make command (defaults to make)

## Usage Examples

### Programmatic Usage

```python
from benchbox.utils.tpc_compilation import ensure_tpc_binaries

# Ensure specific binaries are available
results = ensure_tpc_binaries(["dbgen", "qgen"])

for binary, result in results.items():
    if result.status.value in ["success", "not_needed"]:
        print(f"{binary} is available at {result.binary_path}")
    else:
        print(f"{binary} failed: {result.error_message}")
```

### Status Reporting

```python
from benchbox.utils.tpc_compilation import get_tpc_compiler

compiler = get_tpc_compiler()
report = compiler.get_status_report()

print(f"Auto-compile enabled: {report['auto_compile_enabled']}")
print(f"TPC-H source: {report['tpc_h_source']}")
print(f"TPC-DS source: {report['tpc_ds_source']}")

for binary, info in report['binaries'].items():
    print(f"{binary}: exists={info['exists']}, needs_compilation={info['needs_compilation']}")
```

## Troubleshooting

### Common Issues

#### 1. Missing Dependencies
**Error**: "Missing dependencies: make, gcc, yacc"

**Solution**: Install required build tools for your platform (see Installation Instructions above)

#### 2. Compilation Timeout
**Error**: "Compilation timed out after X minutes"

**Solution**:
- Check system resources (CPU, memory)
- Try compiling manually to diagnose issues
- Increase timeout if needed (contact support)

#### 3. Source Directory Not Found
**Error**: "TPC-H dbgen source not found"

**Solution**:
- Auto-compilation needs a source checkout; installed packages do not include `_sources/`
- Ensure TPC source files are properly extracted in `_sources/tpc-h/dbgen/` or `_sources/tpc-ds/tools/`
- Check that source files include the necessary .c files (dbgen.c, driver.c, etc.)

#### 4. Permission Issues
**Error**: "Permission denied" or "executable not found after build"

**Solution**:
- Check filesystem permissions
- Ensure build directory is writable
- On Unix systems, verify execute permissions: `chmod +x binary_name`

#### 5. Platform-Specific Compilation Issues
**macOS**:
- Install Xcode Command Line Tools: `xcode-select --install`
- For M1/M2 Macs, ensure ARM64 compatibility

**Linux**:
- Install development packages: `sudo apt install build-essential`
- Check for missing system libraries

**Windows**:
- Windows binaries are pre-compiled via Docker cross-compilation
- TPC-H binaries (dbgen.exe, qgen.exe) available for x86_64 and ARM64
- TPC-DS has limited Windows support due to cross-compilation constraints
- For custom builds, use WSL for best compatibility

### Manual Compilation

If auto-compilation fails, you can compile manually from a source checkout:

#### TPC-H
```bash
cd _sources/tpc-h/dbgen
make -f makefile.suite MACHINE=LINUX DATABASE=SQLSERVER CC=gcc
```

#### TPC-DS
```bash
cd _sources/tpc-ds/tools
make dsdgen dsqgen
```

### Source Modifications

BenchBox includes patches to the TPC source code that enable additional features
and fix compatibility issues:

#### TPC-H Patches
- **Stdout output (`-z` flag)**: Enables streaming data to stdout for compression pipelines
- See `_sources/tpc-h/PATCHES.md` for details

#### TPC-DS Patches
- **Stdout output (`-FILTER Y` flag)**: Enables streaming data to stdout
- **Linux build fixes**: MAXINT definition and GCC 10+ compatibility
- See `_sources/tpc-ds/PATCHES.md` for details

These patches are based on community fixes from [tpch-kit](https://github.com/gregrahn/tpch-kit)
and [tpcds-kit](https://github.com/gregrahn/tpcds-kit) by Greg Rahn.

### Debugging

#### Enable Verbose Output
```python
from benchbox.utils.tpc_compilation import get_tpc_compiler

compiler = get_tpc_compiler(verbose=True)
```

#### Check Compilation Logs
The system captures stdout and stderr from compilation attempts. Check the `CompilationResult` objects for detailed error information.

#### Validate Dependencies
```python
compiler = get_tpc_compiler()
deps_available, missing = compiler.check_dependencies("dbgen")
if not deps_available:
    print(f"Missing: {missing}")
```

## Performance Notes

- **TPC-H**: Compilation typically takes 30-60 seconds
- **TPC-DS**: Compilation typically takes 2-5 minutes (yacc processing)
- **Parallel**: Each binary is compiled independently
- **Caching**: Compiled binaries are reused until source changes

## Security Considerations

- Auto-compilation runs make commands in source directories
- Only trusted source code should be present in `_sources/`
- Build processes do not require elevated privileges
- Generated binaries are created in source directories only

## Windows Compilation Support

### TPC-H Windows Support
- **Full support** for Windows x86_64 and ARM64 platforms
- Pre-compiled Windows binaries available via Docker cross-compilation
- Automatic MinGW integer literal compatibility fixes applied during compilation
- Binaries: `dbgen.exe`, `qgen.exe`, and support files

### TPC-DS Windows Support
- **Partial support** due to cross-compilation limitations
- Wine emulation used for `mkheader.exe` tool during build process
- Data files (`tpcds.dst`) and query templates successfully compiled
- Limited executable generation due to cross-compilation constraints

### Technical Implementation
- **Docker-based compilation**: Uses Ubuntu 22.04 with MinGW cross-compiler
- **Wine integration**: Headless Wine emulation for Windows tools during build
- **Automatic fixes**: Integer literal compatibility patches for MinGW
- **Platform detection**: Automatic platform-specific compilation paths

## Full Manual Recompilation

For advanced users who need to rebuild TPC binaries from source (e.g., for custom
modifications, unsupported platforms, or debugging), BenchBox provides complete
recompilation infrastructure.

### Obtaining TPC Source Code

TPC source code must be obtained directly from the TPC organization:

1. Visit [TPC Current Specifications](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp)
2. Download "TPC-H Tools" and/or "TPC-DS Tools" (requires free TPC account)
3. Extract to `_sources/tpc-h/` and `_sources/tpc-ds/` respectively

### Applying BenchBox Patches

BenchBox includes patches that enable stdout streaming and fix Linux compatibility:

```bash
# TPC-H: Add -z flag for stdout output
cd _sources/tpc-h
patch -p1 < stdout-support.patch

# TPC-DS: Fix FILTER flag and Linux/GCC 10+ compatibility
cd _sources/tpc-ds
patch -p1 < stdout-support.patch
```

### Building for other platforms

The patched sources build natively on macOS and Linux. Linux and Windows
cross-builds run in a container (`mocker`, `docker` or `podman`; override with
`BENCHBOX_CONTAINER_ENGINE=<engine>`) through
`_sources/compilation/scripts/compile-all-platforms.sh`.

All `dbgen` builds compile with `-DEOL_HANDLING` (no trailing field separator),
matching TPC-DS `-terminate n`. Keep this consistent across every build path;
see `_sources/tpc-h/PATCHES.md`.

### Detailed Source Documentation

For comprehensive documentation on the source directory structure, compilation
process, and troubleshooting, see:

- **`_sources/README.md`** - Complete guide to obtaining source, applying patches, and compiling
- **`_sources/tpc-h/PATCHES.md`** - TPC-H patch documentation
- **`_sources/tpc-ds/PATCHES.md`** - TPC-DS patch documentation

## Support

For compilation issues:

1. Check this troubleshooting guide
2. Verify your platform meets system requirements
3. Try manual compilation to isolate the issue
4. Check BenchBox logs for detailed error messages
5. Report issues with compilation logs and system information

## API Reference

### Classes

#### `TPCCompiler`
Main class for TPC binary compilation management.

**Methods**:
- `is_binary_available(binary_name: str) -> bool`
- `needs_compilation(binary_name: str) -> bool`
- `compile_binary(binary_name: str) -> CompilationResult`
- `compile_all_needed() -> Dict[str, CompilationResult]`
- `get_status_report() -> Dict[str, Any]`

#### `CompilationResult`
Result object containing compilation status and details.

**Attributes**:
- `status: CompilationStatus` - Compilation status enum
- `binary_path: Optional[Path]` - Path to compiled binary
- `error_message: Optional[str]` - Error message if failed
- `compilation_time: Optional[float]` - Time taken to compile

#### `CompilationStatus`
Enum representing compilation status.

**Values**:
- `SUCCESS` - Compilation succeeded
- `FAILED` - Compilation failed
- `SKIPPED` - Compilation skipped
- `DISABLED` - Auto-compilation disabled
- `NOT_NEEDED` - Binary already available

### Functions

#### `ensure_tpc_binaries(binaries: List[str], auto_compile: bool = True) -> Dict[str, CompilationResult]`
Ensure specified TPC binaries are available, compiling if needed.

#### `get_tpc_compiler(auto_compile: bool = True, verbose: bool = False) -> TPCCompiler`
Get TPC compiler instance with specified configuration.

## Examples

### Integration Example
```python
# In your benchmark code
from benchbox.utils.tpc_compilation import ensure_tpc_binaries

def initialize_tpc_h():
    # Ensure TPC-H binaries are available
    results = ensure_tpc_binaries(["dbgen", "qgen"])

    for binary, result in results.items():
        if result.status.value not in ["success", "not_needed"]:
            raise RuntimeError(f"TPC-H {binary} not available: {result.error_message}")

    return results
```

### Status Check Example
```python
from benchbox.utils.tpc_compilation import get_tpc_compiler

def check_tpc_status():
    compiler = get_tpc_compiler()

    if not compiler.tpc_h_source:
        print("TPC-H source not found")

    if not compiler.tpc_ds_source:
        print("TPC-DS source not found")

    # Check each binary
    for binary in ["dbgen", "qgen", "dsdgen", "dsqgen"]:
        if binary in compiler.binaries:
            available = compiler.is_binary_available(binary)
            needs_compile = compiler.needs_compilation(binary)
            print(f"{binary}: available={available}, needs_compile={needs_compile}")
```

## Source tree build outputs

The TPC-H auto-compilation path writes `Makefile.auto` and the object files into
`_sources/tpc-h/dbgen/`. The Makefile depends on the host platform, so it is
generated on each build and not tracked. Neither it nor the `.o` files, `dbgen`
or `qgen` are tracked; `.gitignore` lists them. A tracked object file can be
newer than its source after a checkout and be linked into a fresh build.
`tests/unit/core/tpch/test_tpch_dbgen_framing.py` fails if one is tracked again.
The tracked build configuration is `makefile.suite`; the same test checks that it
and the generated Makefile both define `-DEOL_HANDLING`.

## Bundled binary checks

Hosted CI runs the bundled binaries on each supported platform and compares
their output. The Linux and macOS results must agree; the Windows results are
advisory.
