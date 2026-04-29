"""Unit tests for cli/commands/submit.py."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

sub = importlib.import_module("benchbox.cli.commands.submit")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        benchmark_name="tpch",
        platform="duckdb",
        scale_factor=0.01,
        total_queries=22,
        duration_seconds=12.34,
    )


# ---------------------------------------------------------------------------
# 1. No args - explains usage, exit 1
# ---------------------------------------------------------------------------


def test_submit_requires_file_or_last(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sub, "console", SimpleNamespace(print=lambda *a, **k: None))
    result = CliRunner().invoke(sub.submit, [])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 2. --last with no results → "No results found", exit 1
# ---------------------------------------------------------------------------


def test_submit_last_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sub, "find_latest_result", lambda *_a, **_k: None)
    result = CliRunner().invoke(sub.submit, ["--last"])
    assert result.exit_code == 1
    assert "No results found" in result.output


# ---------------------------------------------------------------------------
# 3. --dry-run with mock result → prints preview, no files written
# ---------------------------------------------------------------------------


def test_submit_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(
        sub.submit,
        [str(src), "--dry-run", "--output", str(out_dir)],
    )

    assert result.exit_code == 0
    assert "Dry-run" in result.output or "dry-run" in result.output.lower()
    # Nothing should have been written
    assert not out_dir.exists()


# ---------------------------------------------------------------------------
# 4. Normal run → output dir created with expected files
# ---------------------------------------------------------------------------


def test_submit_creates_output_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(
        sub.submit,
        [str(src), "--output", str(out_dir)],
    )

    assert result.exit_code == 0
    assert (out_dir / "bundle" / src.name).exists()
    assert (out_dir / "tpch_duckdb.manifest.json").exists()
    assert (out_dir / "CONTRIBUTING.md").exists()


# ---------------------------------------------------------------------------
# 5. Manifest contains bundle_hash
# ---------------------------------------------------------------------------


def test_submit_manifest_contains_bundle_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    manifest = json.loads((out_dir / "tpch_duckdb.manifest.json").read_text(encoding="utf-8"))
    assert "bundle_hash" in manifest
    assert len(manifest["bundle_hash"]) == 64  # SHA-256 hex
    assert "submitted_by" in manifest  # Phase 2: optional, may be empty string


# ---------------------------------------------------------------------------
# 6. Bad file → user-friendly error, exit 1
# ---------------------------------------------------------------------------


def test_submit_load_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "bad.json"
    src.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        sub,
        "load_result_file",
        lambda *_a, **_k: (_ for _ in ()).throw(sub.ResultLoadError("bad data")),
    )

    result = CliRunner().invoke(sub.submit, [str(src)])
    assert result.exit_code == 1
    assert "Error loading result file" in result.output


# ---------------------------------------------------------------------------
# 7. Companion files (.plans.json, .tuning.json) are copied when present
# ---------------------------------------------------------------------------


def test_submit_copies_companion_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    plans = tmp_path / "tpch_duckdb.plans.json"
    plans.write_text('{"plans": []}', encoding="utf-8")

    tuning = tmp_path / "tpch_duckdb.tuning.json"
    tuning.write_text('{"tuning": {}}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(
        sub.submit,
        [str(src), "--output", str(out_dir)],
    )

    assert result.exit_code == 0
    assert (out_dir / "bundle" / "tpch_duckdb.plans.json").exists()
    assert (out_dir / "bundle" / "tpch_duckdb.tuning.json").exists()


# ---------------------------------------------------------------------------
# 8. --last with --benchmark/--platform passes filters to find_latest_result
# ---------------------------------------------------------------------------


def test_submit_last_passes_filters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict = {}

    def fake_find(results_dir, *, benchmark=None, platform=None):
        captured["benchmark"] = benchmark
        captured["platform"] = platform
        return None  # no result found is fine for this test

    monkeypatch.setattr(sub, "find_latest_result", fake_find)

    CliRunner().invoke(sub.submit, ["--last", "--benchmark", "tpch", "--platform", "duckdb"])

    assert captured["benchmark"] == "tpch"
    assert captured["platform"] == "duckdb"


# ---------------------------------------------------------------------------
# 9. UnsupportedSchemaError → schema version error message
# ---------------------------------------------------------------------------


def test_submit_unsupported_schema_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "old_result.json"
    src.write_text("{}", encoding="utf-8")

    def _raise(*_a, **_k):
        raise sub.UnsupportedSchemaError("Unsupported schema version: 1.0")

    monkeypatch.setattr(sub, "load_result_file", _raise)

    result = CliRunner().invoke(sub.submit, [str(src)])
    assert result.exit_code == 1
    assert "Unsupported schema version" in result.output
    assert "schema version 2.0" in result.output


# ---------------------------------------------------------------------------
# 10. FileNotFoundError → file not found error message
# ---------------------------------------------------------------------------


def test_submit_file_not_found_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "missing.json"
    src.write_text("{}", encoding="utf-8")

    def _raise(*_a, **_k):
        raise FileNotFoundError("Result file not found: missing.json")

    monkeypatch.setattr(sub, "load_result_file", _raise)

    result = CliRunner().invoke(sub.submit, [str(src)])
    assert result.exit_code == 1
    assert "Result file not found" in result.output


# ---------------------------------------------------------------------------
# 11. Generic Exception catch-all → unexpected error message
# ---------------------------------------------------------------------------


def test_submit_generic_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "weird.json"
    src.write_text("{}", encoding="utf-8")

    def _raise(*_a, **_k):
        raise Exception("something broke")

    monkeypatch.setattr(sub, "load_result_file", _raise)

    result = CliRunner().invoke(sub.submit, [str(src)])
    assert result.exit_code == 1
    assert "Unexpected error" in result.output


# ---------------------------------------------------------------------------
# Service mode (--service / Phase 3 hosted ingest)
# ---------------------------------------------------------------------------


def test_submit_service_dry_run_no_creds_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service --dry-run must work without any auth setup."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry-run - would upload" in result.output
    assert "Service URL:" in result.output
    assert "Visibility:" in result.output
    assert not (tmp_path / "submission").exists()


def test_submit_service_default_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service without an explicit URL must use the documented default."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run"])
    assert result.exit_code == 0
    assert sub._DEFAULT_SERVICE_URL in result.output


def test_submit_service_custom_url_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit --service URL flows into the dry-run output unchanged."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    custom = "https://staging.benchbox.dev/v1"
    result = CliRunner().invoke(sub.submit, [str(src), "--service", custom, "--dry-run"])
    assert result.exit_code == 0
    assert custom in result.output


def test_submit_service_visibility_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--visibility unlisted is reflected in the dry-run output."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run", "--visibility", "unlisted"])
    assert result.exit_code == 0
    assert "unlisted" in result.output


def test_submit_service_visibility_rejects_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unknown visibility value is rejected by Click before any work runs."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run", "--visibility", "secret"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output or "secret" in result.output


def test_submit_service_idempotency_key_passthrough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Caller-supplied --idempotency-key surfaces in the dry-run output."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    key = "11111111-2222-3333-4444-555555555555"
    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run", "--idempotency-key", key])
    assert result.exit_code == 0
    assert key in result.output


def test_submit_service_real_upload_returns_not_implemented(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service without --dry-run must fail loudly until w5 implementation lands."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service"])
    assert result.exit_code == 1
    assert "not yet implemented" in result.output.lower()


def test_submit_default_pr_path_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default behavior (no --service) is unchanged: PR-package mode."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])
    assert result.exit_code == 0
    assert out_dir.is_dir()
    assert (out_dir / "tpch_duckdb.manifest.json").is_file()


# ---------------------------------------------------------------------------
# Per-bundle manifest filename (dry-run-followup-manifest-filename-convention)
# ---------------------------------------------------------------------------


def test_submit_manifest_filename_inherits_bundle_stem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Manifest is named `<bundle_stem>.manifest.json`, not the legacy literal."""
    src = tmp_path / "tpch_sf001_duckdb_20260403_093653_9c0925d1.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0
    assert (out_dir / "tpch_sf001_duckdb_20260403_093653_9c0925d1.manifest.json").is_file()
    # Legacy singleton filename must NOT be written.
    assert not (out_dir / "submission-manifest.json").exists()


def test_submit_two_consecutive_submits_do_not_collide(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two submits to the same output dir produce two distinct manifest files."""
    src_a = tmp_path / "tpch_duckdb.json"
    src_a.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    src_b = tmp_path / "tpch_clickhouse.json"
    src_b.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    runner = CliRunner()
    result_a = runner.invoke(sub.submit, [str(src_a), "--output", str(out_dir)])
    result_b = runner.invoke(sub.submit, [str(src_b), "--output", str(out_dir)])

    assert result_a.exit_code == 0
    assert result_b.exit_code == 0
    assert (out_dir / "tpch_duckdb.manifest.json").is_file()
    assert (out_dir / "tpch_clickhouse.manifest.json").is_file()
