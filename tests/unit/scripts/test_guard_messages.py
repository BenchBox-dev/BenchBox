"""Pin the remediation text of the drift-guard class covered by `make guards-fix`.

guards-fix-regen-target-2: each of these CHECK guards fails a "steady trickle"
of CI runs; the fix is a known mechanical regen command (or, for the two
guards with no regen mode, a specific hand edit). These tests pin that the
failure output actually names the exact fix -- not just "something drifted" --
so a future edit to any of these scripts can't silently regress the message
into something an agent has to rediscover from a hand-carried prompt again.

Covers:
  * dependency inventory (_project/scripts/dependency_audit/parse_deps.py)
  * UAT production-LOC ceiling gate (_project/scripts/uat_loc_table.py) --
    NOT a regen guard; pins that its message says so.
  * module-size guard (tests/system/test_module_size_thresholds.py) -- no
    regen mode; pins the ready-to-paste ALLOWLIST entry instead.
  * DDL governance drift (benchbox/sql_compat/inventory.py --check-ddl-drift)
    -- no regen mode; pins the _DDL_GOVERNANCE_TRANSFORMER_ALIASES mention.

The oracle-coverage-map guard's message is pinned alongside its other guards
in tests/unit/test_oracle_coverage_map.py rather than duplicated here.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


parse_deps = _load_module(
    "guard_messages_parse_deps",
    REPO_ROOT / "_project" / "scripts" / "dependency_audit" / "parse_deps.py",
)
uat_loc_table = _load_module(
    "guard_messages_uat_loc_table",
    REPO_ROOT / "_project" / "scripts" / "uat_loc_table.py",
)
module_size_guard = _load_module(
    "guard_messages_module_size_thresholds",
    REPO_ROOT / "tests" / "system" / "test_module_size_thresholds.py",
)


def test_parse_deps_check_message_names_exact_regen_command(tmp_path, monkeypatch):
    """audit-raw-check's drift message must name the exact regen invocation
    and point at `make guards-fix` as the one-command alternative."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["foo>=1"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(parse_deps, "_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["parse_deps.py", "--check"])

    buf = io.StringIO()
    with redirect_stderr(buf):
        exit_code = parse_deps.main()

    assert exit_code == 1
    message = buf.getvalue()
    assert "uv run -- python _project/scripts/dependency_audit/parse_deps.py" in message
    assert "make guards-fix" in message


def test_uat_loc_budget_breach_message_names_the_budget_file_and_denies_regen(tmp_path, monkeypatch):
    """uat_loc_table.py --check's breach message must name the ceiling file and
    the offending bucket, and must explicitly say `make guards-fix` will NOT fix
    it.

    must_preserve: this guard is deliberately NOT a regen guard (it replaced
    one -- uat-spec-module-loc-ceiling-gate). Every sibling guard in this module
    is fixed by a mechanical regen command, and `guards-fix` used to run this
    very script, so the standing assumption in this repo is "check guard failed
    -> run guards-fix". Here that is wrong and would waste the reader's time:
    exceeding a charter ceiling is fixed by removing code or by deliberately
    raising the ceiling. The denial has to be in the message itself."""
    budget = json.loads(uat_loc_table.BUDGET_PATH.read_text(encoding="utf-8"))
    # Squeeze one bucket's ceiling below its real size to force a breach.
    victim = uat_loc_table.BUCKETS[0][0]
    measured, _total = uat_loc_table.measure()
    budget["budgets"]["buckets"][victim] = measured[victim] - 1
    breached_path = tmp_path / "uat-loc-budget.json"
    breached_path.write_text(json.dumps(budget), encoding="utf-8")

    monkeypatch.setattr(uat_loc_table, "BUDGET_PATH", breached_path)
    monkeypatch.setattr(sys, "argv", ["uat_loc_table.py", "--check"])

    buf = io.StringIO()
    with redirect_stderr(buf):
        exit_code = uat_loc_table.main()

    assert exit_code == 1
    message = buf.getvalue()
    assert "_project/specs/uat-loc-budget.json" in message
    assert "OVER BUDGET" in message and victim in message
    assert "`make guards-fix` will NOT fix it" in message


def test_uat_loc_budget_check_passes_on_the_real_tree():
    """The committed ceilings must actually hold for the tree as shipped --
    otherwise the gate above is failing for everyone and the ceilings, not the
    code, are what needs attention."""
    monkey_argv = ["uat_loc_table.py", "--check"]
    original = sys.argv
    sys.argv = monkey_argv
    try:
        assert uat_loc_table.main() == 0
    finally:
        sys.argv = original


def test_module_size_allowlist_snippet_is_pasteable():
    """The module-size guard has no regen mode; its failure must print a
    ready-to-paste ALLOWLIST entry carrying the *current* line count."""
    snippet = module_size_guard._allowlist_snippet(Path("benchbox/example/module.py"), 1_337)
    assert "Path(" in snippet
    assert '"benchbox/example/module.py"' in snippet
    assert "1337" in snippet
    assert "<justification" in snippet


def test_module_size_violation_message_includes_snippet_and_no_regen_note(monkeypatch):
    """Simulate a tripped guard and confirm the raised message carries the
    pasteable ALLOWLIST entry plus a pointer that this guard has no
    `make guards-fix` regen mode."""
    fixture_relpath = Path("tests/unit/scripts/test_guard_messages.py")  # exists, real file, no allowlist entry
    monkeypatch.setattr(module_size_guard, "MODULE_PATHS", [fixture_relpath])
    monkeypatch.setattr(module_size_guard, "ALLOWLIST", {})
    monkeypatch.setattr(module_size_guard, "MAX_LINES_DEFAULT", 1)

    with pytest.raises(AssertionError) as excinfo:
        module_size_guard.test_runtime_modules_respect_size_limits()

    message = str(excinfo.value)
    assert "ALLOWLIST" in message
    assert "test_module_size_thresholds.py" in message
    assert "no `make guards-fix` regen exists for this guard" in message
    assert f'Path(\n        "{fixture_relpath.as_posix()}"\n    ):' in message


def test_ddl_drift_message_mentions_alias_dict_and_no_regen():
    """benchbox/sql_compat/inventory.py --check-ddl-drift has no regen mode;
    pin that its remediation names the exact fix mechanisms: registering the
    rule, adding a _DDL_GOVERNANCE_TRANSFORMER_ALIASES entry, or an explicit
    _DDL_DRIFT_EXEMPTIONS entry."""
    source = (REPO_ROOT / "benchbox" / "sql_compat" / "inventory.py").read_text(encoding="utf-8")
    # Locate the emitted remediation block for --check-ddl-drift drift findings.
    marker = 'emit(\n                "Fix by one of:'
    assert marker in source, "expected the DDL-drift remediation emit() block to be present verbatim"
    idx = source.index(marker)
    block = source[idx : idx + 900]
    assert "_DDL_GOVERNANCE_TRANSFORMER_ALIASES" in block
    assert "_DDL_DRIFT_EXEMPTIONS" in block
    assert "make guards-fix" in block
