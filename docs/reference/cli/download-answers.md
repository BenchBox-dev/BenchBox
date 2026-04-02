(cli-download-answers)=
# `download-answers` - Answer Files

```{tags} reference, cli, validation
```

Pre-download TPC answer files for offline row-count validation of TPC-H and TPC-DS benchmark results.

## Basic Syntax

```bash
benchbox download-answers [OPTIONS]
```

## Options

- `--benchmark [tpch|tpcds|all]`: Which benchmark's answer files to download (default: `all`)
- `--force`: Re-download even if files already exist in cache
- `--show-cache-dir`: Print the cache directory path and exit. With `--benchmark tpch` or `--benchmark tpcds`, prints that benchmark's subdirectory; with `all` (default), prints the parent cache directory.

## Usage Examples

```bash
# Download both TPC-H and TPC-DS answer files
benchbox download-answers

# Download only TPC-H
benchbox download-answers --benchmark tpch

# Force re-download
benchbox download-answers --force

# Show where answer files are cached
benchbox download-answers --show-cache-dir
benchbox download-answers --show-cache-dir --benchmark tpch
```

## Cache Location

Answer files are cached at `$XDG_CACHE_HOME/benchbox/answers/` (or `~/.cache/benchbox/answers/` if `XDG_CACHE_HOME` is not set).

## Environment Variables

| Variable | Description |
|----------|-------------|
| `BENCHBOX_ANSWERS_URL` | Override the default download URL for answer files |
| `BENCHBOX_NO_DOWNLOAD` | Set to `1` to disable all automatic downloads |

## Notes

- Answer files are included in source distributions but not in wheel installs. This command bridges the gap for pip-installed users.
- Answer files are used automatically during the validation phase of benchmark runs. Pre-downloading is optional but useful for air-gapped or CI environments.

## Related

- [run](run.md) - Run benchmarks with validation
