"""Orchestration: resolve manifest, ensure data is present + verified.

`fetch_data(benchmark_id, manifest_path, output_dir)` is the public
entrypoint. It:

  1. Loads + validates the manifest at `manifest_path`.
  2. If `output_dir` is fully pre-populated (every per-table file
     present and sha256-matches): returns the directory.
  3. Otherwise: downloads the archive (sha256-verified against
     `archive_sha256`). If the caller has not yet extracted the
     tarball, raises `ExtractionRequiredError` so the caller can
     drive extraction and re-call `fetch_data` to verify.
  4. If files are present after extraction but a sha256 mismatches:
     raises `ChecksumMismatchError`.

The manager NEVER constructs joinorder-specific paths; the caller
passes `output_dir` (typically resolved via
`benchbox.cli.config.DirectoryManager.get_datagen_path(benchmark, sf)`).
This is the contract that keeps the module benchmark-agnostic.

Cutover wires this entry point: the joinorder benchmark calls
`fetch_data(...)`, catches `ExtractionRequiredError` once, runs
tar extraction, then re-calls `fetch_data(...)` to assert the
files match the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .downloader import download, sha256_of
from .errors import ChecksumMismatchError, DataFetchError
from .locking import archive_lock
from .manifest import DataManifest, load_manifest


@dataclass(frozen=True)
class _BadFile:
    """Why a per-table file failed verification (structured, not stringly-typed)."""

    file: str
    kind: Literal["missing", "sha_mismatch"]
    expected_sha256: str | None = None
    actual_sha256: str | None = None


class ExtractionRequiredError(DataFetchError):
    """Raised when the archive has been downloaded but the per-table files
    are still missing — the caller must extract the tarball and re-call
    fetch_data() to complete verification.

    Carries the archive path so the caller can hand it to its tar driver.
    """

    def __init__(self, archive_path: str, output_dir: str):
        self.archive_path = archive_path
        self.output_dir = output_dir
        super().__init__(
            f"archive downloaded to {archive_path}; extract into {output_dir} "
            "and re-call fetch_data() to verify per-table sha256s"
        )


def _verify_table_files(manifest: DataManifest, data_dir: Path) -> list[_BadFile]:
    """Return structured diagnostics for any table file that fails verification.

    Empty list = every table file present + sha256 matches.
    """
    bad: list[_BadFile] = []
    for entry in manifest.tables:
        p = data_dir / entry.file
        if not p.exists():
            bad.append(_BadFile(file=entry.file, kind="missing"))
            continue
        actual = sha256_of(p)
        if actual != entry.sha256:
            bad.append(
                _BadFile(
                    file=entry.file,
                    kind="sha_mismatch",
                    expected_sha256=entry.sha256,
                    actual_sha256=actual,
                )
            )
    return bad


def fetch_data(
    benchmark_id: str,
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    downloader: object | None = None,
    archive_filename: str | None = None,
) -> Path:
    """Ensure the dataset declared by *manifest_path* is present at
    *output_dir* and sha256-verified.

    Args:
        benchmark_id: Logical benchmark id (used in error messages and
            in the default archive filename — the manager itself stays
            benchmark-agnostic).
        manifest_path: Path to the per-benchmark `data_manifest.toml`.
            Typically `benchbox/core/<benchmark>/data_manifest.toml`.
        output_dir: Directory where the per-table files should live.
            Typically resolved via
            ``DirectoryManager.get_datagen_path(benchmark, scale)``.
        downloader: Optional callable matching the
            ``download(url, dest, expected_sha256=...)`` signature.
            Tests inject a mock; production code uses the default.
        archive_filename: Optional name for the downloaded tarball.
            Defaults to the basename of the manifest's url.

    Returns:
        Resolved Path to *output_dir* after verification succeeds.

    Raises:
        ChecksumMismatchError: A pre-populated or post-extraction file
            has the wrong sha256.
        ExtractionRequiredError: The archive has been downloaded but
            the per-table files are still missing — the caller must
            extract and re-call ``fetch_data``.
        ManifestValidationError: Re-raised from load_manifest.
        DataFetchError / DownloadError: Re-raised from downloader.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)

    bad = _verify_table_files(manifest, out)
    if not bad:
        return out

    # Anything mismatched on disk is a hard error before we touch the
    # network — the caller may have populated a stale or corrupt cache.
    mismatches = [b for b in bad if b.kind == "sha_mismatch"]
    if mismatches:
        first = mismatches[0]
        raise ChecksumMismatchError(
            path=str(out / first.file),
            expected_sha256=first.expected_sha256 or "",
            actual_sha256=first.actual_sha256 or "",
        )

    # All bad files are simply absent — fetch the archive (sha-verified
    # against the manifest) and tell the caller it must extract.
    archive_name = archive_filename or Path(manifest.url).name or f"{benchmark_id}.tar.zst"
    archive_path = out / archive_name

    # Serialize the check-download-verify handoff per archive: two callers
    # that both saw the files missing must not both download. The first to
    # acquire the lock publishes a verified archive; the rest reuse it.
    with archive_lock(archive_path):
        # Re-check inside the lock — another process may have completed the
        # download (and extraction) while we were waiting for it.
        bad = _verify_table_files(manifest, out)
        if not bad:
            return out

        mismatches = [b for b in bad if b.kind == "sha_mismatch"]
        if mismatches:
            first = mismatches[0]
            raise ChecksumMismatchError(
                path=str(out / first.file),
                expected_sha256=first.expected_sha256 or "",
                actual_sha256=first.actual_sha256 or "",
            )

        if archive_path.exists() and sha256_of(archive_path) == manifest.archive_sha256:
            raise ExtractionRequiredError(archive_path=str(archive_path), output_dir=str(out))

        fetch = downloader or download
        fetch(manifest.url, archive_path, expected_sha256=manifest.archive_sha256)

        # Re-verify post-download. If the caller (e.g., test stub) has
        # arranged for the per-table files to materialize, we're done.
        bad = _verify_table_files(manifest, out)
        if not bad:
            return out

        mismatches = [b for b in bad if b.kind == "sha_mismatch"]
        if mismatches:
            first = mismatches[0]
            raise ChecksumMismatchError(
                path=str(out / first.file),
                expected_sha256=first.expected_sha256 or "",
                actual_sha256=first.actual_sha256 or "",
            )

        # Archive present, table files still missing — extraction is the
        # caller's responsibility. Surface a typed error.
        raise ExtractionRequiredError(archive_path=str(archive_path), output_dir=str(out))
