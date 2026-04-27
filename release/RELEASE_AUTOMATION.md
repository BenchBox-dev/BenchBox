# BenchBox Release Automation

## Overview

The BenchBox release process is fully automated with comprehensive timestamp normalization. **All file timestamps** (filesystem, wheel/sdist archives, git commits/tags) are normalized to the **most recent Saturday at midnight UTC**, ensuring no trace of actual creation or modification times in released artifacts.

## Quick Start

```bash
# Run automated release for version 0.2.0
./scripts/automate_release.py --version 0.2.0

# This will:
# 1. Calculate most recent Saturday midnight (e.g., 2025-11-01 00:00:00 UTC)
# 2. Run pre-flight checks
# 3. Prepare curated public tree with normalized timestamps
# 4. Build wheel and sdist with SOURCE_DATE_EPOCH
# 5. Run smoke tests in isolated environment
# 6. Create git commit and tag with normalized timestamps
# 7. Archive artifacts in release/archive/v0.2.0/
```

## Pre-Release Version Updates

Before running the automated release, you should update the version in your source repository. The automation validates that the release version matches the source code version.

### Using update_version.py

```bash
# Update version in source code
python scripts/update_version.py --version 0.2.0 --update-pyproject

# This updates:
# - benchbox/__init__.py (__version__)
# - pyproject.toml (version field)
# - Documentation release markers
```

### Version Consistency Check

The automation includes a pre-flight check that compares the `--version` parameter with the source code's `__version__`. If they don't match, you'll see:

```
⚠️  Warning: Version mismatch!
   Source code version: 0.1.0
   Release version parameter: 0.2.0
   Consider running: python scripts/update_version.py --version 0.2.0
Continue with mismatched versions? (y/N):
```

### Complete Workflow

```bash
# 1. Update source version
python scripts/update_version.py --version 0.2.0 --update-pyproject

# 2. Update CHANGELOG.md manually
vim CHANGELOG.md

# 3. Run automated release
./scripts/automate_release.py --version 0.2.0

# 4. Review and push (manual)
cd ../BenchBox-public
git log --format=fuller
git push origin main && git push origin v0.2.0

# 5. Upload to PyPI (manual)
twine upload dist/benchbox-0.2.0*
```

## Timestamp Normalization

### What Gets Normalized

1. **File system timestamps** in curated tree (`../BenchBox-public/`)
   - All files and directories set to Saturday midnight
   - Uses `os.utime(path, (timestamp, timestamp))`

2. **Archive timestamps** in wheel/sdist
   - Controlled by `SOURCE_DATE_EPOCH` environment variable
   - All files inside ZIP/tar.gz have Saturday midnight timestamps

3. **Git commit timestamps**
   - Both author and committer dates set via `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE`

4. **Git tag timestamps**
   - Tag creation time set via `GIT_COMMITTER_DATE`

### Saturday Midnight Calculation

The timestamp is calculated as:
- **Most recent Saturday** relative to current date
- **00:00:00 UTC** (midnight)
- Example: If today is Tuesday, November 4, 2025 → Saturday, November 1, 2025 at 00:00:00 UTC

Why Saturday?
- Predictable and calculable
- Always in the past (never future-dated)
- Consistent within same week
- Easy to verify

### Verification

To verify timestamps in a built wheel:
```bash
# Extract and check timestamps
unzip -l dist/benchbox-0.2.0-py3-none-any.whl | head -20

# Or use the build script's verification
./scripts/build_release.py ../BenchBox-public --timestamp 1761955200
```

## Automation Scripts

### 1. `automate_release.py` (Main Orchestrator)

**Usage:**
```bash
./scripts/automate_release.py --version X.Y.Z [options]

Options:
  --version VERSION       Release version (required)
  --target DIR           Target directory (default: ../BenchBox-public)
  --source DIR           Source directory (default: current)
  --skip-preflight       Skip pre-flight validation
  --skip-tests           Skip smoke tests
  --skip-archive         Skip artifact archiving
  --dry-run             Preview without executing
  --verbose             Show detailed output
```

**What it does:**
1. Calculates Saturday midnight timestamp
2. Runs pre-flight checks (CHANGELOG, git status, version format)
3. Calls `prepare_release.py` to create curated tree
4. Calls `build_release.py` to build packages
5. Calls `verify_release.py` to run smoke tests
6. Calls `finalize_release.py` to create git commit/tag
7. Archives artifacts and displays summary

### 2. `prepare_release.py` (Tree Curation)

**Usage:**
```bash
./scripts/prepare_release.py TARGET --version X.Y.Z [options]

Options:
  --source DIR           Source repository (default: current)
  --version VERSION      Version string (default: 0.1.0)
  --no-clean            Don't delete target before copying
  --init-git            Initialize git repo in target
  --include PATH        Additional files to include
  --timestamp TS        Unix timestamp (auto-calculated if not provided)
```

**What it does:**
- Copies allowed files from source to target
- Excludes holdback paths (tests/, docs/, examples/, clickhouse, bigquery, etc.)
- Applies sanitized README and pyproject.toml
- **Normalizes all file timestamps** to provided/calculated Saturday midnight
- Optionally initializes git repo

### 3. `build_release.py` (Package Building)

**Usage:**
```bash
./scripts/build_release.py TARGET --timestamp TIMESTAMP [options]

Options:
  --timestamp TS        Unix timestamp for SOURCE_DATE_EPOCH (required)
  --no-verify          Skip timestamp verification in wheel
  --hash-only          Only calculate hashes (skip build)
```

**What it does:**
- Sets `SOURCE_DATE_EPOCH` environment variable
- Runs `uv build` to create wheel and sdist
- Verifies timestamps in wheel match expected value
- Calculates SHA256 hashes for both artifacts
- Displays formatted summary

### 4. `verify_release.py` (Smoke Tests)

**Usage:**
```bash
./scripts/verify_release.py TARGET [options]

Options:
  --skip-smoke-tests    Skip smoke tests (only verify artifacts exist)
  --verbose            Show detailed output from tests
```

**What it does:**
- Verifies wheel and sdist exist in `TARGET/dist/`
- Creates temporary isolated venv (Python 3.12)
- Installs built wheel
- Runs smoke tests:
  - `benchbox --version`
  - `benchbox run --dry-run ... --platform duckdb --benchmark tpch`
  - `benchbox check-deps`

### 5. `finalize_release.py` (Git Operations)

**Usage:**
```bash
./scripts/finalize_release.py REPO_PATH --version X.Y.Z --git-timestamp "YYYY-MM-DD HH:MM:SS +0000" [options]

Options:
  --git-timestamp TS    Git-formatted timestamp (required)
  --archive-base DIR    Base directory for archives (default: release/archive)
  --skip-commit        Skip git commit
  --skip-tag           Skip git tag
  --skip-archive       Skip artifact archiving
```

**What it does:**
- Verifies git repository status
- Creates commit with message: `chore(release): prepare vX.Y.Z`
- Creates annotated tag: `vX.Y.Z`
- Both commit and tag use normalized timestamp
- Archives artifacts to `release/archive/vX.Y.Z/`
- Displays next steps (push, PyPI upload)

## Workflow

### Standard Release

```bash
# 1. Update CHANGELOG.md manually
vim CHANGELOG.md

# 2. Run automation
./scripts/automate_release.py --version 0.2.0

# 3. Review the prepared release
cd ../BenchBox-public
git log --format=fuller  # Verify timestamps
git show v0.2.0

# 4. Push to remote (manual)
git push origin main
git push origin v0.2.0

# 5. Upload to PyPI (manual)
twine upload dist/benchbox-0.2.0*
```

### Skip Smoke Tests (Faster)

```bash
./scripts/automate_release.py --version 0.2.0 --skip-tests
```

### Dry Run (Preview Only)

```bash
./scripts/automate_release.py --version 0.2.0 --dry-run
```

## Manual Steps

The following steps remain **manual by design** for safety:

1. **CHANGELOG.md updates** - Requires human review and editing
2. **Git push to remote** - Explicit control over publication
3. **PyPI upload** - Explicit control over distribution

These can be automated in CI/CD if desired, but are manual in the local workflow.

## Pre-Flight Checks

The automation runs these checks before proceeding:

1. **CHANGELOG.md** - Warns if no entry for version found
2. **Git status** - Warns if uncommitted changes in main repo
3. **Version format** - Validates version string is alphanumeric with dots/dashes

You can skip these with `--skip-preflight`.

## Artifact Archive

Artifacts are archived in:
```
release/archive/v0.2.0/
├── benchbox-0.2.0-py3-none-any.whl
├── benchbox-0.2.0.tar.gz
└── MANIFEST.txt
```

The manifest contains version info, file sizes, and hash verification commands.

## Troubleshooting

### "Pre-flight checks failed"
- Ensure CHANGELOG.md has entry for version
- Commit any changes in main repo
- Use `--skip-preflight` if intentional

### "Build failed"
- Check pyproject.toml is valid
- Ensure uv is installed and working
- Check for syntax errors in source code

### "Timestamp verification failed"
- Indicates SOURCE_DATE_EPOCH not respected by build
- Usually means setuptools version issue
- Verify setuptools >= 58.0 in build environment

### "Smoke tests failed"
- Check wheel installs correctly
- Verify all dependencies are specified
- Review test output with `--verbose`

## Advanced Usage

### Use Specific Timestamp

```bash
# Calculate timestamp separately
TIMESTAMP=$(python -c "from benchbox.release.workflow import calculate_most_recent_saturday_midnight; print(calculate_most_recent_saturday_midnight()[0])")

# Run individual steps with same timestamp
./scripts/prepare_release.py ../BenchBox-public --version 0.2.0 --timestamp $TIMESTAMP --init-git
./scripts/build_release.py ../BenchBox-public --timestamp $TIMESTAMP
```

### Build Only (Skip Preparation)

```bash
# If tree already prepared
./scripts/build_release.py ../BenchBox-public --timestamp 1761955200
```

### Calculate Hashes Only

```bash
./scripts/build_release.py ../BenchBox-public --hash-only
```

## Implementation Details

### Core Infrastructure

File: `benchbox/release/workflow.py`

**`calculate_most_recent_saturday_midnight()`**
```python
Returns: (unix_timestamp, iso_format, git_format)
Example: (1761955200, "2025-11-01T00:00:00+00:00", "2025-11-01 00:00:00 +0000")
```

**`_normalize_timestamps(path, timestamp)`**
- Recursively sets all file/directory timestamps
- Uses `os.utime(entry, (timestamp, timestamp))`

**`prepare_public_release(..., timestamp=None)`**
- Accepts optional timestamp parameter
- Auto-calculates Saturday midnight if not provided

### Timestamp Formats

| Format | Use Case | Example |
|--------|----------|---------|
| Unix timestamp | `os.utime()`, `SOURCE_DATE_EPOCH` | `1761955200` |
| ISO 8601 | Human-readable display | `2025-11-01T00:00:00+00:00` |
| Git format | `GIT_*_DATE` env vars | `2025-11-01 00:00:00 +0000` |

## Testing

### Test with Fake Version

```bash
# Use test version to avoid polluting version namespace
./scripts/automate_release.py --version 0.1.1-test
```

### Verify Reproducibility

```bash
# Run automation twice on same day
./scripts/automate_release.py --version 0.2.0-test1
./scripts/automate_release.py --version 0.2.0-test2

# Compare artifacts - should be bit-for-bit identical (except version number)
diff -r ../BenchBox-public-test1 ../BenchBox-public-test2
```

### Verify No Timestamp Leakage

```bash
# Check file timestamps in curated tree
find ../BenchBox-public -type f -exec stat -f "%Sm %N" {} \; | head

# Check timestamps inside wheel
unzip -l ../BenchBox-public/dist/*.whl | less

# Check git timestamps
cd ../BenchBox-public
git log --format=fuller
```

## Security Note

This timestamp normalization is for **reproducibility and privacy**, not security. It ensures:
- Builds are reproducible from same source
- No metadata leaks about development environment timing
- Easier verification and auditing

It does **not** provide cryptographic guarantees or security properties.

## Repository Sync

The `sync_repos.py` script enables bidirectional sync between the private repository and the public release repository.

### Quick Start

```bash
# Show differences between repos
./scripts/sync_repos.py status

# Push changes to public repo (creates commit)
./scripts/sync_repos.py push --message "Sync bug fixes"

# Pull external contributions back (no auto-commit)
./scripts/sync_repos.py pull
```

### Commands

**status** - Show differences between repositories (read-only)
```bash
./scripts/sync_repos.py status
```

**push** - Push changes from private to public repo
```bash
./scripts/sync_repos.py push --message "Commit message"
./scripts/sync_repos.py push --force  # Overwrite conflicts
./scripts/sync_repos.py push --dry-run  # Preview only
```

**pull** - Pull changes from public to private repo
```bash
./scripts/sync_repos.py pull
./scripts/sync_repos.py pull --force  # Overwrite conflicts
./scripts/sync_repos.py pull --dry-run  # Preview only
```

### How It Works

1. **File filtering**: Uses the same `ALLOWED_ROOT_FILES`, `GLOBAL_EXCLUDES`, `DOCS_DIR_EXCLUDES`, `CLAUDE_DIR_EXCLUDES`, and `FORBIDDEN_PATTERNS` as `prepare_release.py`
2. **Transform application**: Applies email substitutions to `pyproject.toml` (private→public on push, public→private on pull)
3. **Conflict detection**: Uses git history to detect when both repos have modified the same file
4. **Commit on push**: Automatically commits changes to the public repo (never leaves uncommitted files)
5. **No commit on pull**: Leaves changes uncommitted in private repo for manual review

### Options

| Option | Description |
|--------|-------------|
| `--source` | Private repository (default: current directory) |
| `--target` | Public repository (default: ../BenchBox-public) |
| `--message, -m` | Commit message for push |
| `--force, -f` | Force sync even with conflicts |
| `--dry-run, -n` | Preview without making changes |

### Differences from Full Release

| Aspect | `sync_repos.py` | `automate_release.py` |
|--------|-----------------|----------------------|
| **Purpose** | Incremental sync | Full release |
| **Timestamp** | Not normalized | Saturday midnight |
| **Package build** | No | Yes |
| **Smoke tests** | No | Yes |
| **Git tag** | No | Yes |

Use `sync_repos.py` for quick bug fix syncs. Use `automate_release.py` for versioned releases.

## Future Enhancements

Potential improvements (not currently implemented):

- [ ] CHANGELOG auto-generation from git log
- [ ] GitHub release creation via API
- [ ] PyPI upload automation with confirmation
- [ ] Cross-platform testing (macOS, Linux)
- [ ] Resume capability for failed runs
- [ ] Parallel smoke testing (multiple Python versions)

## References

- [Reproducible Builds](https://reproducible-builds.org/)
- [SOURCE_DATE_EPOCH](https://reproducible-builds.org/docs/source-date-epoch/)
- [Git Environment Variables](https://git-scm.com/book/en/v2/Git-Internals-Environment-Variables)
