#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"

cd "${REPO_ROOT}"
export UV_CACHE_DIR
"${REPO_ROOT}/scripts/with_supported_java.sh" uv run -- python -m pytest tests/unit/platforms/dataframe/test_pyspark_df.py -q
