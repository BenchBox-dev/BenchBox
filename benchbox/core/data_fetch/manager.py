"""Orchestration: resolve manifest, ensure data is present + verified.

`fetch_data(benchmark_id, manifest_path, output_dir)` is the public
entrypoint. It:

  1. Loads + validates the manifest at `manifest_path`.
  2. If `output_dir` is empty: downloads the archive, verifies its
     sha256 against the manifest, and would extract it (extraction
     itself is left to the call site for now — the cutover wires
     this up alongside the joinorder Parquet load).
  3. If `output_dir` is pre-populated: verifies each expected
     per-table file exists with the manifest-declared sha256
     (air-gapped path — no download attempted).

The manager NEVER constructs joinorder-specific paths; the caller
passes `output_dir` (typically resolved via
`benchbox.cli.config.DirectoryManager.get_datagen_path(benchmark, sf)`).
This is the contract that keeps the module benchmark-agnostic.
"""

from __future__ import annotations

from pathlib import Path

from .downloader import _sha256_of, download
from .errors import ChecksumMismatchError
from .manifest import DataManifest, load_manifest


def _verify_table_files(manifest: DataManifest, data_dir: Path) -> list[str]:
    """Return list of missing-or-mismatched table files.

    Empty list = every table file present + sha256 matches.
    """
    bad: list[str] = []
    for entry in manifest.tables:
        p = data_dir / entry.file
        if not p.exists():
            bad.append(f"{entry.file} (missing)")
            continue
        actual = _sha256_of(p)
        if actual != entry.sha256:
            bad.append(f"{entry.file} (sha256 mismatch: expected {entry.sha256}, got {actual})")
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
        benchmark_id: Logical benchmark id (used in messages only —
            the manager itself stays benchmark-agnostic).
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
        Resolved Path to *output_dir* after verification.

    Raises:
        ChecksumMismatchError: A pre-populated file or downloaded
            archive has the wrong sha256.
        ManifestValidationError: Re-raised from load_manifest.
        DataFetchError / DownloadError: Re-raised from downloader.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)

    # Air-gapped / pre-populated path: every table file is already there.
    bad = _verify_table_files(manifest, out)
    if not bad:
        return out

    # Otherwise download the archive next to output_dir. (Extraction is
    # the call site's responsibility for now — cutover wires the
    # tar.zst → per-table Parquet step alongside the joinorder load.)
    archive_name = archive_filename or Path(manifest.url).name or f"{benchmark_id}.tar.zst"
    archive_path = out / archive_name
    fetch = downloader or download
    fetch(manifest.url, archive_path, expected_sha256=manifest.archive_sha256)

    # Re-verify per-table files after extraction-by-caller. The caller
    # is expected to extract the tarball into out/ between the download
    # and a subsequent fetch_data() call. Until that happens, surface
    # the still-missing files clearly.
    bad = _verify_table_files(manifest, out)
    if bad:
        # Caller hasn't extracted yet, OR extraction left mismatches.
        # We treat the latter as a checksum mismatch on the first
        # offending file so the error path is uniform.
        first = bad[0]
        if "sha256 mismatch" in first:
            # Extract the filename — the verifier produced a deterministic
            # message shape we can re-parse.
            fname = first.split(" (sha256 mismatch", 1)[0]
            entry = manifest.table(Path(fname).stem)
            raise ChecksumMismatchError(
                path=str(out / entry.file),
                expected_sha256=entry.sha256,
                actual_sha256=_sha256_of(out / entry.file),
            )
        # Files just aren't there yet — extraction is the caller's job.
    return out
