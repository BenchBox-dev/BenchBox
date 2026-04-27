"""Tests for prepare_local_load_file() context manager.

Covers the W3 decision gate:
- gzip and zstd input decompresses correctly
- uncompressed pass-through yields original path (no temp file written)
- trailing-pipe stripped only when strip_trailing_delim=True
- True/False → 1/0 only when dialect.normalize_booleans is True
- context manager cleans up temp file on exit
"""

from __future__ import annotations

import gzip
import subprocess
import tempfile
from pathlib import Path

import pytest

from benchbox.platforms.base.data_loading import CsvDialect, prepare_local_load_file

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dialect(
    delimiter: str = "|",
    has_header: bool = False,
    null_marker: str | None = "",
    normalize_booleans: bool = False,
    quote: str | None = None,
) -> CsvDialect:
    return CsvDialect(
        delimiter=delimiter,
        has_header=has_header,
        null_marker=null_marker,
        normalize_booleans=normalize_booleans,
        quote=quote,
    )


def _write_plain(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gzip(path: Path, lines: list[str]) -> None:
    content = ("\n".join(lines) + "\n").encode()
    with gzip.open(path, "wb") as f:
        f.write(content)


def _write_zstd(path: Path, lines: list[str]) -> None:
    """Write lines as a .zst file using the system zstd command (matches ZstdHandler)."""
    content = ("\n".join(lines) + "\n").encode()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(content)
        tmp_name = tmp.name
    subprocess.run(["zstd", "-f", tmp_name, "-o", str(path)], check=True, capture_output=True)
    Path(tmp_name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Pass-through (no transformation)
# ---------------------------------------------------------------------------


def test_uncompressed_passthrough_yields_original_path(tmp_path: Path) -> None:
    """Uncompressed file with no transforms yields the original path — no copy."""
    data_file = tmp_path / "lineitem.csv"
    _write_plain(data_file, ["1,a,b", "2,c,d"])

    with prepare_local_load_file(data_file, dialect=_dialect(delimiter=","), strip_trailing_delim=False) as result:
        assert result == data_file  # same object — no temp file


def test_passthrough_no_temp_file_created(tmp_path: Path) -> None:
    """No extra file is created in the directory during passthrough."""
    data_file = tmp_path / "lineitem.csv"
    _write_plain(data_file, ["1,2,3"])
    before = set(tmp_path.iterdir())

    with prepare_local_load_file(data_file, dialect=_dialect(delimiter=","), strip_trailing_delim=False):
        assert set(tmp_path.iterdir()) == before  # no new file


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------


def test_gzip_decompresses_correctly(tmp_path: Path) -> None:
    """Gzip-compressed input is transparently decompressed."""
    data_file = tmp_path / "lineitem.tbl.gz"
    _write_gzip(data_file, ["1|a|b|", "2|c|d|"])

    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=False) as result:
        content = result.read_text(encoding="utf-8")

    assert "1|a|b|" in content
    assert "2|c|d|" in content


@pytest.mark.slow
def test_zstd_decompresses_correctly(tmp_path: Path) -> None:
    """Zstd-compressed input is transparently decompressed via system zstd command."""
    pytest.importorskip("subprocess")
    data_file = tmp_path / "lineitem.tbl.zst"
    _write_zstd(data_file, ["1|a|b|", "2|c|d|"])

    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=False) as result:
        content = result.read_text(encoding="utf-8")

    assert "1|a|b|" in content
    assert "2|c|d|" in content


# ---------------------------------------------------------------------------
# Trailing delimiter strip
# ---------------------------------------------------------------------------


def test_trailing_pipe_stripped_when_requested(tmp_path: Path) -> None:
    """Trailing delimiter is stripped per-line when strip_trailing_delim=True."""
    data_file = tmp_path / "lineitem.tbl"
    _write_plain(data_file, ["1|a|b|", "2|c|d|"])

    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=True) as result:
        lines = result.read_text(encoding="utf-8").splitlines()

    assert lines == ["1|a|b", "2|c|d"]


def test_trailing_pipe_not_stripped_when_not_requested(tmp_path: Path) -> None:
    """Trailing delimiter is preserved when strip_trailing_delim=False."""
    data_file = tmp_path / "lineitem.tbl"
    _write_plain(data_file, ["1|a|b|", "2|c|d|"])

    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=False) as result:
        lines = result.read_text(encoding="utf-8").splitlines()

    assert lines == ["1|a|b|", "2|c|d|"]


def test_trailing_strip_with_no_trailing_delim_is_safe(tmp_path: Path) -> None:
    """Lines without trailing delimiter are unaffected by strip_trailing_delim=True."""
    data_file = tmp_path / "data.dat"
    _write_plain(data_file, ["1|a|b", "2|c|"])  # second line has trailing |

    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=True) as result:
        lines = result.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "1|a|b"  # unchanged
    assert lines[1] == "2|c"  # trailing stripped


# ---------------------------------------------------------------------------
# Boolean normalization
# ---------------------------------------------------------------------------


def test_boolean_normalize_rewrites_true_false(tmp_path: Path) -> None:
    """True/False fields are rewritten to 1/0 when normalize_booleans=True."""
    data_file = tmp_path / "dbo_dimaccount.csv"
    _write_plain(data_file, ["1,True,some text", "2,False,other"])

    with prepare_local_load_file(
        data_file, dialect=_dialect(delimiter=",", normalize_booleans=True), strip_trailing_delim=False
    ) as result:
        lines = result.read_text(encoding="utf-8").splitlines()

    assert lines == ["1,1,some text", "2,0,other"]


def test_boolean_normalize_off_preserves_true_false(tmp_path: Path) -> None:
    """True/False is NOT rewritten when normalize_booleans=False."""
    data_file = tmp_path / "dbo_dimaccount.csv"
    _write_plain(data_file, ["1,True,some text"])

    with prepare_local_load_file(
        data_file, dialect=_dialect(delimiter=",", normalize_booleans=False), strip_trailing_delim=False
    ) as result:
        content = result.read_text(encoding="utf-8")

    assert "True" in content


def test_boolean_normalize_does_not_affect_partial_matches(tmp_path: Path) -> None:
    """'TrueValue' or 'FalseAlarm' should NOT be rewritten — only exact field match."""
    data_file = tmp_path / "data.csv"
    _write_plain(data_file, ["TrueValue,FalseAlarm,True,False"])

    with prepare_local_load_file(
        data_file, dialect=_dialect(delimiter=",", normalize_booleans=True), strip_trailing_delim=False
    ) as result:
        lines = result.read_text(encoding="utf-8").splitlines()

    assert lines == ["TrueValue,FalseAlarm,1,0"]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_temp_file_cleaned_up_after_context_exit(tmp_path: Path) -> None:
    """Temp file is deleted when the context manager exits normally."""
    data_file = tmp_path / "lineitem.tbl"
    _write_plain(data_file, ["1|a|b|"])

    tmp_file_path: Path | None = None
    with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=True) as result:
        tmp_file_path = result
        assert result != data_file  # a temp file was created
        assert result.exists()

    assert tmp_file_path is not None
    assert not tmp_file_path.exists()  # cleaned up


def test_temp_file_cleaned_up_after_exception(tmp_path: Path) -> None:
    """Temp file is deleted even when an exception is raised inside the context."""
    data_file = tmp_path / "lineitem.tbl"
    _write_plain(data_file, ["1|a|b|"])

    tmp_file_path: Path | None = None
    with pytest.raises(RuntimeError):
        with prepare_local_load_file(data_file, dialect=_dialect(), strip_trailing_delim=True) as result:
            tmp_file_path = result
            raise RuntimeError("simulated load failure")

    assert tmp_file_path is not None
    assert not tmp_file_path.exists()  # cleaned up despite exception
