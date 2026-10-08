from __future__ import annotations

from .scale_factor import format_scale_factor

REMOTE_SCHEMES = ("s3://", "gs://", "abfss://", "dbfs:/")


def _ensure_suffix(root: str, suffix: str) -> str:
    r = root.rstrip("/")
    last = r.split("/")[-1] if r else ""
    if last.lower() == suffix.lower():
        return r
    return f"{r}/{suffix}" if r else suffix


def normalize_output_root(output_root: str | None, benchmark: str, scale: float) -> str | None:

    if not output_root:
        return output_root

    bench = (benchmark or "").strip().lower()
    sf = format_scale_factor(scale)
    suffix = f"{bench}_{sf}" if bench else sf
    return _ensure_suffix(output_root, suffix)
