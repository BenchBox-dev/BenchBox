"""Dependency guards for the optional MCP integration."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


REPO_ROOT = Path(__file__).parents[3]


def _declared_requirements(config: dict) -> list[str]:
    project = config["project"]
    requirements = list(project.get("dependencies", []))
    requirements.extend(
        requirement
        for group in project.get("optional-dependencies", {}).values()
        for requirement in group
        if isinstance(requirement, str)
    )
    requirements.extend(
        requirement
        for group in config.get("dependency-groups", {}).values()
        for requirement in group
        if isinstance(requirement, str)
    )
    return requirements


def test_every_mcp_dependency_excludes_major_version_2() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)

    mcp_requirements = [
        Requirement(value) for value in _declared_requirements(config) if Requirement(value).name == "mcp"
    ]

    assert mcp_requirements, "pyproject.toml must declare the MCP SDK"
    for requirement in mcp_requirements:
        upper_bounds = [
            Version(specifier.version) for specifier in requirement.specifier if specifier.operator in {"<", "<="}
        ]
        assert upper_bounds and min(upper_bounds) <= Version("2"), (
            f"MCP requirement {requirement!s} can resolve incompatible SDK 2; "
            "keep every declaration below 2 until mcp-sdk-v2-server-migration-v2 lands"
        )
