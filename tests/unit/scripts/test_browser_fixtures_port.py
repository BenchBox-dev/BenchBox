from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MJS_GEN = ROOT / "results-explorer/scripts/generate-browser-fixtures.mjs"
MJS_VERIFY = ROOT / "results-explorer/scripts/verify-browser-fixtures.mjs"
SOURCE_BUNDLES = ROOT / "results-explorer/test-fixtures/source"

pytestmark = [pytest.mark.unit]


def _run_c(script: str, *args: str) -> bytes:
    proc = subprocess.run(
        ["uv", "run", "--", "python", "-c", script, *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    return proc.stdout


def _extract_template(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const " + name + r" = `(.*?)`.trim\(\);", text, re.DOTALL)
    assert match, f"{name} block not found in {path.name}"
    return match.group(1)


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("fixture-db")
    out = work / "data"
    out.mkdir()
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--",
            "python",
            "_project/scripts/explorer_publish.py",
            "build",
            "--data-dir",
            str(SOURCE_BUNDLES),
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    db = out / "results.duckdb"
    assert db.is_file()
    return db


def _port(command: str, db: Path) -> bytes:
    proc = subprocess.run(
        [sys.executable, "_project/scripts/explorer_pipeline/browser_fixtures.py", command, str(db)],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    return proc.stdout


def test_short_ids_match_mjs_inline_query(fixture_db: Path) -> None:
    script = "\n".join(
        [
            "import duckdb, json, sys",
            f"con = duckdb.connect({json.dumps(str(fixture_db))}, read_only=True)",
            'rows = con.execute("select result_id, short_id from short_ids").fetchall()',
            "json.dump({result_id: short_id for result_id, short_id in rows}, sys.stdout)",
        ]
    )
    assert _port("short-ids", fixture_db) == _run_c(script)


def test_summary_matches_mjs_inline_query(fixture_db: Path) -> None:
    script = _extract_template(MJS_VERIFY, "fixtureSummaryPython")
    ported = json.loads(_port("summary", fixture_db))
    reference = json.loads(_run_c(script, str(fixture_db)))
    assert sorted(map(tuple, ported.pop("platforms_per_cohort"))) == sorted(
        map(tuple, reference.pop("platforms_per_cohort"))
    )
    assert json.dumps(ported, sort_keys=True) == json.dumps(reference, sort_keys=True)


def test_digest_matches_mjs_inline_query(fixture_db: Path) -> None:
    script = _extract_template(MJS_VERIFY, "logicalDigestPython")
    assert _port("digest", fixture_db) == _run_c(script, str(fixture_db))
