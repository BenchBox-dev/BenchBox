"""Guard customer-facing configuration guidance against dead CLI routes."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli
from benchbox.core.hooks.platform_hooks import PlatformHookRegistry

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("relative_path", "forbidden_advice"),
    [
        (
            "benchbox/platforms/bigquery.py",
            ("benchbox platforms setup --platform", "--platform-option project_id="),
        ),
        (
            "benchbox/platforms/databricks/adapter.py",
            (
                "benchbox platforms setup --platform",
                "--platform-option server_hostname=",
                "--platform-option http_path=",
            ),
        ),
        ("benchbox/platforms/snowflake.py", ("benchbox platforms setup --platform", "--platform-option account=")),
        ("benchbox/platforms/redshift.py", ("benchbox platforms setup --platform", "--platform-option host=")),
        (
            "benchbox/platforms/starburst.py",
            ("--platform-option host=", "--platform-option username=", "--platform-option password="),
        ),
        (
            "benchbox/platforms/presto_trino_adapter_base.py",
            ("--platform-option host=<host>", "--platform-option port=<port>"),
        ),
    ],
)
def test_connection_guidance_does_not_advertise_unregistered_platform_options(
    relative_path: str, forbidden_advice: tuple[str, ...]
) -> None:
    """Connection keys must not be presented as ``--platform-option`` unless registered."""
    source = (REPO_ROOT / relative_path).read_text()
    for advice in forbidden_advice:
        assert advice not in source


@pytest.mark.parametrize(
    ("platform", "option", "value"),
    [
        ("bigquery", "biglake_connection", "my-project.us.my-connection"),
        ("fabric_dw", "warehouse", "example-warehouse"),
        ("clickhouse-cloud", "host", "example.us-east-2.aws.clickhouse.cloud"),
        ("clickhouse-server", "host", "my-clickhouse.example.com"),
        ("clickhouse-server", "port", "9000"),
        ("clickhouse-server", "username", "default"),
        ("clickhouse-server", "password", "secret"),
    ],
)
def test_advertised_connection_options_are_accepted_by_the_cli(
    tmp_path: Path, platform: str, option: str, value: str
) -> None:
    """Keep the test honest for platforms that do expose connection options."""
    assert option in PlatformHookRegistry.list_option_specs(platform)

    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--platform",
            platform,
            "--benchmark",
            "tpch",
            "--scale",
            "0.01",
            "--dry-run",
            str(tmp_path / platform),
            "--non-interactive",
            "--platform-option",
            f"{option}={value}",
        ],
    )

    assert result.exit_code == 0, result.output
