"""The shard evidence step must survive a failing pytest run.

`release-canary.yml` declares `shell: bash` for the shard steps, which GitHub
invokes as `bash --noprofile --norc -eo pipefail`. Under errexit a bare failing
pipeline aborts the script at that line. The shard step ends in exactly that
shape -- `pytest ... | tee <log>` -- so a shard with failing tests used to stop
before it recorded anything: no end stamp, no JUnit fallback, no capture marker,
and no `pytest_exit_code` output.

That is the worst case for this evidence, not the best. A red shard is precisely
when a reviewer needs to know what ran and how long it took, and the missing
capture marker made the summary report `junit_captured=false` even for a shard
whose pytest run had written a complete JUnit report with real per-test
durations. The summary then understated measured cost, which is the one failure
mode this evidence exists to prevent.

These tests execute the real `run:` blocks under errexit, substituting only the
`uv` entrypoint so the pytest outcome is controlled. Asserting that "set +e"
appears in the YAML would pin the spelling of the fix instead of the behaviour,
and would keep passing if the step were restructured to lose the evidence a
different way.
"""

from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from tests.utilities.posix_shell import posix_shell, skip_without_posix_shell

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-canary.yml"

# A real JUnit report is what makes junit_captured meaningful: the file exists
# and carries per-test durations. Absent it, the workflow writes a marked empty
# fallback. Both cases are exercised below.
_REAL_JUNIT = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<testsuite tests="1" errors="0" failures="1" skipped="0">'
    '<testcase classname="tests.unit.test_a" name="test_one" time="2.5"/></testsuite>'
)


def _steps() -> dict[str, dict]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return {step.get("name"): step for step in workflow["jobs"]["credential-free-non-fast"]["steps"]}


def _shell_has_mapfile() -> bool:
    """Whether the resolved shell provides the bash 4 `mapfile` builtin."""
    shell = posix_shell()
    if shell is None:
        return False
    # No trailing `exit 0`: the probe must return mapfile's own status, or it
    # would pass on a shell that lacks the builtin.
    probe = subprocess.run(
        [shell, "--noprofile", "--norc", "-c", 'mapfile -t probe <<< "a b c"'],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


# macOS ships bash 3.2, which predates `mapfile`, while the workflow runs on
# ubuntu-latest where the builtin exists. Skipping here would leave the errexit
# regression unverified on every macOS checkout, so instead the builtin is
# emulated for the one form the shard step uses (`mapfile -t NAME < FILE`). The
# shim is defined only when the real builtin is absent, so CI still exercises
# bash's own mapfile. Substituting the one line that cannot run locally, rather
# than the behaviour under test, is the same trade the other workflow-shell
# tests in this suite make.
_MAPFILE_SHIM = r"""\
if ! declare -F mapfile >/dev/null 2>&1; then
  mapfile() {
    local _name="" _line _arr=()
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -t) shift ;;
        *) _name="$1"; shift; break ;;
      esac
    done
    while IFS= read -r _line || [ -n "$_line" ]; do
      _arr[${#_arr[@]}]="$_line"
    done
    if [ -n "$_name" ]; then
      eval "$_name=(\"\${_arr[@]}\")"
    fi
  }
fi
"""


def _shard_prelude() -> str:
    """Shell prelude for executing the shard step's real block."""
    return "" if _shell_has_mapfile() else _MAPFILE_SHIM


def _run_under_errexit(script: str, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Execute a workflow `run:` block with the shell options GitHub applies.

    GitHub runs `shell: bash` as `bash --noprofile --norc -eo pipefail`. The
    blocks set `-o pipefail` themselves, so errexit is the missing half, and
    errexit is what this suite is about.
    """
    shell = posix_shell()
    assert shell is not None, "a real POSIX shell is required to execute workflow blocks"
    return subprocess.run(
        [shell, "--noprofile", "--norc", "-e", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def _stub_uv(write_report: bool) -> str:
    """A shell function replacing `uv`, so the real block runs verbatim.

    The stub stands in for the pytest invocation only. Running the real pytest
    would make this test depend on the suite it is meant to observe. Defining a
    function keeps the `run:` block unedited, so the pipeline shape, the errexit
    exposure, and the PIPESTATUS handling are all still the workflow's own.
    """
    report = ""
    if write_report:
        report = f"printf '%s' '{_REAL_JUNIT}' > \"$junit\"; "
    return (
        "uv() {\n"
        '  local junit=""\n'
        '  for a in "$@"; do case "$a" in --junitxml=*) junit="${a#--junitxml=}";; esac; done\n'
        f"  {report}"
        '  exit "$STUB_PYTEST_EXIT"\n'
        "}\n"
    )


def _shard_workspace(tmp_path: Path, *, node_ids: list[str], stamps: dict[str, str] | None = None) -> Path:
    """Lay out the workspace the shard steps expect."""
    workspace = tmp_path / "workspace"
    artifacts = workspace / "release-canary-artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "shard-0-nodeids.txt").write_text("\n".join(node_ids) + ("\n" if node_ids else ""), encoding="utf-8")
    (workspace / "gh_output.txt").touch()
    for name, value in (stamps or {}).items():
        (workspace / name).write_text(value, encoding="utf-8")
    return workspace


def _shard_env(workspace: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/root"),
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(workspace / "gh_output.txt"),
        "SHARD_INDEX": "0",
        "SHARD_COUNT": "6",
        "CHECKED_SHA": "deadbeef" * 5,
        "COLLECTED_COUNT": "42",
    }
    env.update(extra)
    return env


def _run_shard_step(tmp_path: Path, *, pytest_exit: int, write_report: bool, node_ids: list[str]) -> tuple[int, Path]:
    workspace = _shard_workspace(tmp_path, node_ids=node_ids)
    script = _shard_prelude() + _stub_uv(write_report) + _steps()["Run credential-free non-fast shard"]["run"]
    result = _run_under_errexit(
        script,
        cwd=workspace,
        env=_shard_env(workspace, STUB_PYTEST_EXIT=str(pytest_exit)),
    )
    assert result.returncode == pytest_exit, (
        f"the shard step must exit with pytest's status ({pytest_exit}), got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result.returncode, workspace


def _summary_json(workspace: Path, *, pytest_exit_code: str = "") -> dict:
    """Run the summary step and return the shard summary JSON it wrote."""
    script = _steps()["Write shard summary"]["run"]
    result = _run_under_errexit(
        script,
        cwd=workspace,
        env=_shard_env(workspace, PYTEST_EXIT_CODE=pytest_exit_code),
    )
    assert result.returncode == 0, (
        f"the summary step must succeed regardless of the shard outcome; stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    return json.loads((workspace / "release-canary-artifacts" / "shard-0-summary.json").read_text(encoding="utf-8"))


def test_failing_shard_still_records_its_evidence(tmp_path: Path) -> None:
    """must_preserve: a red shard must publish exit code, timing, and capture state.

    This is the errexit regression. Without `set +e` around the pytest pipeline
    the step aborts at the pipe, so none of these artifacts exist and the summary
    reports no durations for a shard that measured them.
    """
    skip_without_posix_shell()

    _status, workspace = _run_shard_step(
        tmp_path, pytest_exit=1, write_report=True, node_ids=["tests/unit/test_a.py::test_one"]
    )

    output = (workspace / "gh_output.txt").read_text(encoding="utf-8")
    assert "pytest_exit_code=1" in output, "a failing shard must still publish its pytest exit code"
    assert (workspace / ".canary-tests-end-mono").exists(), "a failing shard must still stamp its test end time"
    assert (workspace / ".canary-junit-captured").read_text(encoding="utf-8").strip() == "true", (
        "pytest wrote a real JUnit report, so capture state must be true; a missing marker would "
        "make the summary claim no per-test durations exist when they do"
    )


def test_failing_shard_summary_reports_captured_durations(tmp_path: Path) -> None:
    """The published summary must not invert capture state for a failed shard."""
    skip_without_posix_shell()

    _status, workspace = _run_shard_step(
        tmp_path, pytest_exit=1, write_report=True, node_ids=["tests/unit/test_a.py::test_one"]
    )
    summary = _summary_json(workspace, pytest_exit_code="1")

    assert summary["pytest_exit_code"] == "1"
    assert summary["junit_present"] is True
    assert summary["junit_captured"] is True, "the report holds real durations; the summary must say so"


def test_missing_junit_falls_back_to_a_marked_empty_report(tmp_path: Path) -> None:
    """A capture failure writes a fallback report and reports it as not captured."""
    skip_without_posix_shell()

    _status, workspace = _run_shard_step(
        tmp_path, pytest_exit=1, write_report=False, node_ids=["tests/unit/test_a.py::test_one"]
    )

    assert (workspace / ".canary-junit-captured").read_text(encoding="utf-8").strip() == "false"
    summary = _summary_json(workspace, pytest_exit_code="1")
    # The fallback makes the file present, so presence alone is not evidence of
    # durations. This pairing is the whole reason the two fields are separate.
    assert summary["junit_present"] is True
    assert summary["junit_captured"] is False


def test_shard_with_no_assigned_tests_reports_no_capture(tmp_path: Path) -> None:
    """An empty shard is not a capture failure and carries no durations."""
    skip_without_posix_shell()

    status, workspace = _run_shard_step(tmp_path, pytest_exit=0, write_report=False, node_ids=[])

    assert status == 0
    summary = _summary_json(workspace, pytest_exit_code="0")
    assert summary["junit_present"] is True
    assert summary["junit_captured"] is False
    assert summary["assigned_count"] == "0"


def test_passing_shard_still_reports_its_status(tmp_path: Path) -> None:
    """The errexit fix must not make a green shard red or drop its evidence."""
    skip_without_posix_shell()

    status, workspace = _run_shard_step(
        tmp_path, pytest_exit=0, write_report=True, node_ids=["tests/unit/test_a.py::test_one"]
    )

    assert status == 0
    assert "pytest_exit_code=0" in (workspace / "gh_output.txt").read_text(encoding="utf-8")
    summary = _summary_json(workspace, pytest_exit_code="0")
    assert summary["junit_present"] is True
    assert summary["junit_captured"] is True


def test_summary_degrades_when_the_test_step_never_ran(tmp_path: Path) -> None:
    """A shard that aborted before its stamps must yield empty fields, not a failure."""
    skip_without_posix_shell()

    workspace = _shard_workspace(tmp_path, node_ids=["tests/unit/test_a.py::test_one"])
    summary = _summary_json(workspace)

    assert summary["setup_seconds"] == ""
    assert summary["test_seconds"] == ""
    assert summary["junit_present"] is False
    assert summary["junit_captured"] is False


def test_durations_come_from_monotonic_stamps(tmp_path: Path) -> None:
    """Float monotonic stamps must yield integer elapsed seconds.

    The stamps are seconds since boot with a fractional part, so the summary
    cannot use shell integer arithmetic on them; it must subtract as floats and
    publish whole seconds.

    The fractional parts are chosen so that stripping them before subtracting
    gives a different answer: 100055.25 - 100000.75 is 54.50, which truncates
    to 54, while dropping the fractions first gives 100055 - 100000 = 55. A
    test whose stamps agree under both cannot tell the two apart, so this one
    must not use them.
    """
    skip_without_posix_shell()

    workspace = _shard_workspace(
        tmp_path,
        node_ids=["tests/unit/test_a.py::test_one"],
        stamps={
            ".canary-setup-start-mono": "100000.75",
            ".canary-tests-start-mono": "100055.25",
            ".canary-tests-end-mono": "100355.10",
        },
    )
    summary = _summary_json(workspace)

    assert summary["setup_seconds"] == "54", "54.50 elapsed truncates to 54 whole seconds"
    assert summary["test_seconds"] == "299", "299.85 elapsed truncates to 299 whole seconds"
    assert summary["setup_start_mono"] == "100000.75"
    assert summary["tests_end_mono"] == "100355.10"


def test_a_partial_stamp_leaves_only_the_missing_duration_empty(tmp_path: Path) -> None:
    """A stamp lost mid-job must not corrupt the duration it does not bound."""
    skip_without_posix_shell()

    workspace = _shard_workspace(
        tmp_path,
        node_ids=["tests/unit/test_a.py::test_one"],
        stamps={
            ".canary-setup-start-mono": "100000.75",
            ".canary-tests-start-mono": "100055.25",
        },
    )
    summary = _summary_json(workspace)

    assert summary["setup_seconds"] == "54", "setup is bounded by two present stamps"
    assert summary["test_seconds"] == "", "the end stamp is missing, so no duration may be inferred"


def test_a_non_true_capture_marker_degrades_to_false(tmp_path: Path) -> None:
    """Garbage in the marker file must never be published as captured."""
    skip_without_posix_shell()

    workspace = _shard_workspace(tmp_path, node_ids=["tests/unit/test_a.py::test_one"])
    (workspace / ".canary-junit-captured").write_text("yes\n", encoding="utf-8")
    summary = _summary_json(workspace)

    assert summary["junit_captured"] is False


def test_summary_json_is_valid_and_typed(tmp_path: Path) -> None:
    """The summary must parse, with the two junit fields as real JSON booleans."""
    skip_without_posix_shell()

    _status, workspace = _run_shard_step(
        tmp_path, pytest_exit=0, write_report=True, node_ids=["tests/unit/test_a.py::test_one"]
    )
    _summary_json(workspace)
    raw = (workspace / "release-canary-artifacts" / "shard-0-summary.json").read_text(encoding="utf-8")
    summary = json.loads(raw)

    assert summary["shard_index"] == 0
    assert isinstance(summary["junit_present"], bool)
    assert isinstance(summary["junit_captured"], bool)
    assert '"setup_start_epoch"' not in raw, "wall-clock epoch naming must not return"


# --------------------------------------------------------------------------
# The same blocks against a real pytest run.
#
# Everything above controls the pytest outcome by stubbing `uv`, which pins the
# workflow's control flow but says nothing about what a real pytest actually
# writes. Two acceptance criteria are about the artifact's content, not the
# shell's: that a report carries per-test durations, and that a report without
# them is never published as a capture. Those need a real pytest.
#
# The substitution here is one level thinner: `uv run --` forwards to the real
# interpreter instead of exiting with a fixed code. The pytest invocation, its
# marker expression, --junitxml, the tee pipeline, PIPESTATUS, and every
# evidence write below them are the workflow's own, unedited.
# --------------------------------------------------------------------------

_FIXTURE_MARKED = """\
import time

import pytest


@pytest.mark.slow
def test_marked():
    time.sleep(0.4)
    assert True
"""

_FIXTURE_UNMARKED = """\
import pytest


def test_deselected_by_the_marker_expression():
    assert True
"""


def _real_uv_shim() -> str:
    """Forward `uv run --` to the real interpreter so a real pytest runs."""
    return 'uv() {\n  if [ "$1" = "run" ] && [ "$2" = "--" ]; then shift 2; fi\n  "$@"\n}\n'


def _junit_testcases(xml_path: Path) -> list[tuple[str, str | None]]:
    """Return (name, time) for every testcase in a JUnit report."""
    root = ET.parse(xml_path).getroot()
    return [(node.get("name", ""), node.get("time")) for node in root.iter("testcase")]


def _run_real_shard(tmp_path: Path, *, fixture: str, node_id: str) -> tuple[int, Path]:
    """Run the real shard block against a real pytest with one fixture test."""
    workspace = _shard_workspace(tmp_path, node_ids=[node_id])
    (workspace / "fixture.py").write_text(fixture, encoding="utf-8")
    # The fixture lives outside the repository, so pytest finds no repo ini file
    # and inherits no addopts. Give it the marker registration the workflow's
    # marker expression needs, and keep the run hermetic.
    (workspace / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    slow: canary fixture marker\naddopts = -p no:cacheprovider\n",
        encoding="utf-8",
    )
    script = _shard_prelude() + _real_uv_shim() + _steps()["Run credential-free non-fast shard"]["run"]
    result = _run_under_errexit(script, cwd=workspace, env=_shard_env(workspace))
    return result.returncode, workspace


def test_a_real_pytest_run_publishes_real_per_test_durations(tmp_path: Path) -> None:
    """The artifact must hold measured durations, not just exist."""
    skip_without_posix_shell()
    pytest.importorskip("pytest", reason="the real shard block drives a real pytest")

    status, workspace = _run_real_shard(tmp_path, fixture=_FIXTURE_MARKED, node_id="fixture.py::test_marked")
    assert status == 0

    junit_xml = workspace / "release-canary-artifacts" / "shard-0-junit.xml"
    assert junit_xml.is_file(), "the real pytest must write the report the step asked for"

    testcases = _junit_testcases(junit_xml)
    assert [name for name, _ in testcases] == ["test_marked"]
    durations = [time for _, time in testcases]
    assert all(time is not None for time in durations), "every testcase must carry a duration"
    # The fixture sleeps 0.4s and the attribute is written with millisecond
    # rounding, so a real measurement is bounded well away from zero. This is
    # what distinguishes a captured duration from an absent or stubbed one; the
    # margin keeps it from flaking on a coarse or busy clock.
    assert float(durations[0]) >= 0.3, f"a real duration must reflect the work done: {durations[0]}"

    summary = _summary_json(workspace, pytest_exit_code="0")
    assert summary["junit_present"] is True
    assert summary["junit_captured"] is True
    assert summary["assigned_count"] == "1"


def test_a_real_pytest_that_collected_nothing_is_not_published_as_a_capture(
    tmp_path: Path,
) -> None:
    """A real report with no testcases carries no durations and must say so.

    pytest exits 5 when the marker expression deselects everything, and still
    writes a well-formed non-empty report with zero <testcase> elements. A
    presence check alone would publish that as a capture, which is the exact
    failure mode junit_captured exists to prevent: a consumer sizing shards
    would read real timing evidence where there is none.
    """
    skip_without_posix_shell()
    pytest.importorskip("pytest", reason="the real shard block drives a real pytest")

    status, workspace = _run_real_shard(
        tmp_path,
        fixture=_FIXTURE_UNMARKED,
        node_id="fixture.py::test_deselected_by_the_marker_expression",
    )
    assert status == 5, "pytest exits 5 when it collected nothing to run"

    junit_xml = workspace / "release-canary-artifacts" / "shard-0-junit.xml"
    assert junit_xml.stat().st_size > 0, "a real zero-test report is still a non-empty file"
    assert _junit_testcases(junit_xml) == [], "and it holds no durations"

    summary = _summary_json(workspace, pytest_exit_code="5")
    assert summary["pytest_exit_code"] == "5", "the shard result must still be published"
    assert summary["junit_present"] is True, "the real report is genuine evidence pytest ran"
    assert summary["junit_captured"] is False, "but it carries no durations to size a shard from"


def test_the_real_setup_stamp_step_survives_errexit_without_a_kernel_file(
    tmp_path: Path,
) -> None:
    """The stamp step must write its file and exit 0 whether or not /proc exists.

    This runs the real block against the real kernel. On Linux the file is
    readable and the stamp is a monotonic float; where it is not, the step must
    degrade to an empty stamp rather than abort, because it runs under errexit
    before the shard does. Either way the summary stays writable.
    """
    skip_without_posix_shell()

    workspace = _shard_workspace(tmp_path, node_ids=[])
    script = _steps()["Record setup start"]["run"]
    result = _run_under_errexit(script, cwd=workspace, env=_shard_env(workspace))
    assert result.returncode == 0, f"the stamp step must not fail the job: {result.stderr}"

    stamp_file = workspace / ".canary-setup-start-mono"
    assert stamp_file.is_file(), "the stamp file must exist so the summary can degrade gracefully"
    stamp = stamp_file.read_text(encoding="utf-8").strip()

    if Path("/proc/uptime").is_file():
        # The runner this workflow ships on. The stamp must be a real monotonic
        # reading, not a wall-clock integer and not an empty fallback.
        assert stamp, "/proc/uptime is readable, so a real stamp must be recorded"
        value = float(stamp)
        assert value > 0.0, "seconds since boot must be positive"
        assert "." in stamp, f"the stamp must keep its fractional part: {stamp}"
    else:
        assert stamp == "", f"with no kernel file the stamp degrades to empty, got {stamp!r}"
        summary = _summary_json(workspace)
        assert summary["setup_seconds"] == "", "an empty stamp must not invent a duration"
