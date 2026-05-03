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


def _valid_submission_bundle() -> dict:
    return {
        "version": "2.1",
        "run": {
            "id": "abc123",
            "timestamp": "2026-05-03T00:00:00",
            "total_duration_ms": 500,
        },
        "benchmark": {"id": "tpch", "name": "TPC-H", "scale_factor": 0.01},
        "platform": {"name": "duckdb", "version": "1.3.0"},
        "summary": {"queries": {"total": 1, "passed": 1, "failed": 0}},
        "queries": [{"id": "Q1", "ms": 123, "status": "pass"}],
    }


def _write_valid_submission_bundle(path: Path) -> None:
    path.write_text(json.dumps(_valid_submission_bundle()), encoding="utf-8")


def _write_unavailable_cost_total_bundle(path: Path) -> None:
    bundle = _valid_submission_bundle()
    bundle["normalized_cost"] = {
        "normalized_cost_usd": None,
        "cost_model_version": "2026.05.0",
        "cost_model_source": "benchbox.core.cost.pricing",
        "cost_scope": "compute_only",
        "cost_status": "unavailable",
        "billing_unit": "not_applicable",
        "pricing_region": "not_applicable",
        "deployment": {
            "cloud_provider": None,
            "cloud_region": None,
            "instance_type": None,
            "node_count": None,
        },
    }
    bundle["cost"] = {"total_usd": 0, "model": "estimated"}
    path.write_text(json.dumps(bundle), encoding="utf-8")


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
    _write_valid_submission_bundle(src)

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


def test_submit_refuses_partial_query_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb_partial.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    partial = _fake_result()
    partial.total_queries = 2
    partial.successful_queries = 1
    partial.failed_queries = 1
    partial.validation_status = "PARTIAL"
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (partial, {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 1
    assert "not a clean pass" in result.output
    assert "1 failed query" in result.output
    assert not out_dir.exists()


# ---------------------------------------------------------------------------
# 4b. Packaged CONTRIBUTING.md aligns with canonical docs/contributing-results.md
#     (regression for dry-run-followup-package-canonical-contributing)
# ---------------------------------------------------------------------------


def test_submit_contributing_md_includes_canonical_required_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0
    contributing = (out_dir / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for required in (
        "published-results",
        "generate_corpus_inventory",
        "validate_submission",
        "docs.benchbox.dev",
        "<result>.manifest.json",
    ):
        assert required in contributing, f"missing {required!r} in packaged CONTRIBUTING.md"
    assert "submission-manifest.json" not in contributing


# ---------------------------------------------------------------------------
# 4c. Next-steps block is printed inline after a real submit
#     (regression for dry-run-followup-cli-ux-and-doc-polish-2026-04-29 W2)
# ---------------------------------------------------------------------------


def test_submit_prints_next_steps_with_pr_target_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0
    for required in (
        "published-results",
        "generate_corpus_inventory.py --write",
        "validate_submission.py",
        "results: tpch duckdb sf0.01",
        "results-data/bundles/tpch_duckdb.json",
    ):
        assert required in result.output, f"missing {required!r} in submit next-steps"


def test_submit_dry_run_matches_real_run_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """W6: dry-run output prints the same file/manifest/next-steps shape
    as a real submit, plus a "(dry run; no files written)" footer."""
    src = tmp_path / "tpch_duckdb.json"
    _write_valid_submission_bundle(src)

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--dry-run", "--output", str(out_dir)])

    assert result.exit_code == 0
    assert not out_dir.exists(), "dry-run must not write files"
    for required in (
        "Dry-run preview",
        "published-results",
        "generate_corpus_inventory.py --write",
        "results: tpch duckdb sf0.01",
        "(dry run; no files written)",
    ):
        assert required in result.output, f"missing {required!r} in dry-run output"


def test_submit_dry_run_validation_rejects_pr_package_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "tpch_duckdb_invalid_cost.json"
    _write_unavailable_cost_total_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--dry-run", "--output", str(out_dir)])

    assert result.exit_code == 1
    assert "Submission validation failed" in result.output
    assert "cannot accompany cost_status 'unavailable'" in result.output
    assert "Dry-run preview" not in result.output
    assert not out_dir.exists()


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
    _write_valid_submission_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(
        sub,
        "resolve_submission_token",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not resolve auth")),
    )

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry-run - would upload" in result.output
    assert "Service URL:" in result.output
    assert "Visibility:" in result.output
    assert not (tmp_path / "submission").exists()


def test_submit_service_dry_run_validation_rejects_bundle_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "tpch_duckdb_invalid_cost.json"
    _write_unavailable_cost_total_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(
        sub,
        "resolve_submission_token",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not resolve auth")),
    )

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run"])

    assert result.exit_code == 1
    assert "Submission validation failed" in result.output
    assert "cannot accompany cost_status 'unavailable'" in result.output
    assert "Dry-run - would upload" not in result.output
    assert not (tmp_path / "submission").exists()


def test_submit_service_default_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service without an explicit URL must use the documented default."""
    src = tmp_path / "tpch_duckdb.json"
    _write_valid_submission_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run"])
    assert result.exit_code == 0
    assert sub._DEFAULT_SERVICE_URL in result.output


def test_submit_service_custom_url_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit --service URL flows into the dry-run output unchanged."""
    src = tmp_path / "tpch_duckdb.json"
    _write_valid_submission_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    custom = "https://staging.benchbox.dev/v1"
    result = CliRunner().invoke(sub.submit, [str(src), "--service", custom, "--dry-run"])
    assert result.exit_code == 0
    assert custom in result.output


def test_submit_service_visibility_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--visibility unlisted is reflected in the dry-run output."""
    src = tmp_path / "tpch_duckdb.json"
    _write_valid_submission_bundle(src)
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
    _write_valid_submission_bundle(src)
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    key = "11111111-2222-3333-4444-555555555555"
    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--dry-run", "--idempotency-key", key])
    assert result.exit_code == 0
    assert key in result.output


def test_submit_service_real_upload_calls_transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service without --dry-run resolves auth and calls the hosted transport."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    auth_calls: list[str] = []
    upload_calls: list[dict] = []

    def fake_resolve(service_url: str):
        auth_calls.append(service_url)
        return SimpleNamespace(token="secret-token", source="keyring")

    def fake_upload(**kwargs):
        upload_calls.append(kwargs)
        return sub.HostedSubmitResult(
            status="published",
            submission_id="sub1",
            public_result_id="r1",
            public_url="https://benchbox.dev/results/r/r1",
            idempotency_key=kwargs["idempotency_key"] or "generated-key",
            status_history=("pending", "published"),
        )

    monkeypatch.setattr(sub, "resolve_submission_token", fake_resolve)
    monkeypatch.setattr(sub, "submit_hosted_bundle", fake_upload)

    result = CliRunner().invoke(sub.submit, [str(src), "--service"])
    assert result.exit_code == 0
    assert "Hosted submission complete" in result.output
    assert "https://benchbox.dev/results/r/r1" in result.output
    assert "secret-token" not in result.output
    assert auth_calls == [sub._DEFAULT_SERVICE_URL]
    assert upload_calls[0]["token"] == "secret-token"
    assert upload_calls[0]["manifest"]["submission_path"] == "hosted-service"
    history = json.loads((tmp_path / "tpch_duckdb.generated-key.submission.json").read_text(encoding="utf-8"))
    assert history["public_url"] == "https://benchbox.dev/results/r/r1"
    assert history["status"] == "published"
    assert "secret-token" not in json.dumps(history)


def test_submit_service_real_upload_requires_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--service without --dry-run stops before upload when auth is missing."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    def fake_resolve(_service_url: str):
        raise sub.SubmissionAuthError("No hosted-submit token found.")

    monkeypatch.setattr(sub, "resolve_submission_token", fake_resolve)

    result = CliRunner().invoke(sub.submit, [str(src), "--service"])
    assert result.exit_code == 1
    assert "Authentication required" in result.output
    assert "Uploading submission bundle" not in result.output


def test_submit_service_reauthenticates_once_on_401(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A 401 from the hosted service prompts refresh, then retries once."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    tokens: list[str] = []

    monkeypatch.setattr(sub, "resolve_submission_token", lambda _service_url: SimpleNamespace(token="stale-token"))
    monkeypatch.setattr(sub, "refresh_submission_token", lambda _service_url: SimpleNamespace(token="fresh-token"))

    def fake_upload(**kwargs):
        tokens.append(kwargs["token"])
        if kwargs["token"] == "stale-token":
            raise sub.HostedSubmitUnauthorized("bad token")
        return sub.HostedSubmitResult(
            status="published",
            submission_id="sub1",
            public_result_id="r1",
            public_url="https://benchbox.dev/results/r/r1",
            idempotency_key="generated-key",
            status_history=("pending", "published"),
        )

    monkeypatch.setattr(sub, "submit_hosted_bundle", fake_upload)

    result = CliRunner().invoke(sub.submit, [str(src), "--service"])

    assert result.exit_code == 0
    assert tokens == ["stale-token", "fresh-token"]
    assert "fresh-token" not in result.output


def test_submit_service_no_wait_reports_accepted_not_complete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--no-wait accepted submissions are not reported as completed publications."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(sub, "resolve_submission_token", lambda _service_url: SimpleNamespace(token="secret-token"))
    monkeypatch.setattr(
        sub,
        "submit_hosted_bundle",
        lambda **_kwargs: sub.HostedSubmitResult(
            status="pending",
            submission_id="sub1",
            idempotency_key="generated-key",
            status_history=("pending",),
        ),
    )

    result = CliRunner().invoke(sub.submit, [str(src), "--service", "--no-wait"])

    assert result.exit_code == 0
    assert "Hosted submission accepted" in result.output
    assert "Hosted submission complete" not in result.output


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


# ---------------------------------------------------------------------------
# --submitted-by precedence (dry-run-followup-submitted-by-flag)
# ---------------------------------------------------------------------------


def test_submit_submitted_by_flag_overrides_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit --submitted-by wins over git config user.name."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(sub, "_get_git_username", lambda: "git-config-name")

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(
        sub.submit,
        [str(src), "--output", str(out_dir), "--submitted-by", "Explicit Name"],
    )

    assert result.exit_code == 0
    manifest = json.loads((out_dir / "tpch_duckdb.manifest.json").read_text(encoding="utf-8"))
    assert manifest["submitted_by"] == "Explicit Name"


def test_submit_submitted_by_falls_back_to_git_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without --submitted-by, git config user.name is used."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(sub, "_get_git_username", lambda: "git-config-name")

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0
    manifest = json.loads((out_dir / "tpch_duckdb.manifest.json").read_text(encoding="utf-8"))
    assert manifest["submitted_by"] == "git-config-name"


def test_submit_submitted_by_warns_when_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When both flag and git config are empty, warn but do not fail."""
    src = tmp_path / "tpch_duckdb.json"
    src.write_text('{"schema_version": "2.0"}', encoding="utf-8")
    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))
    monkeypatch.setattr(sub, "_get_git_username", lambda: "")

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0
    assert "submitted_by is empty" in result.output
    assert "--submitted-by" in result.output
    manifest = json.loads((out_dir / "tpch_duckdb.manifest.json").read_text(encoding="utf-8"))
    assert manifest["submitted_by"] == ""


def test_submit_submitted_by_in_help_output() -> None:
    """The --submitted-by option appears in the help."""
    result = CliRunner().invoke(sub.submit, ["--help"])
    assert result.exit_code == 0
    assert "--submitted-by" in result.output


def test_submit_help_mentions_results_paths_affordance() -> None:
    """Submit help points contributors to exact result path discovery."""
    result = CliRunner().invoke(sub.submit, ["--help"])
    assert result.exit_code == 0
    assert "benchbox results --paths" in result.output
