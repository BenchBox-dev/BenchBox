from __future__ import annotations

from pathlib import Path

TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"

TEMPLATE_PLATFORM_KEYS = {
    "clickhouse-local": "clickhouse",
    "clickhouse-server": "clickhouse",
    "clickhouse-cloud": "clickhouse",
    "chdb": "clickhouse",
}


def template_platform_key(platform: str) -> str:
    base = platform.lower().split(":", 1)[0]
    return TEMPLATE_PLATFORM_KEYS.get(base, platform.lower())


def packaged_template_path(platform: str, benchmark: str) -> Path:
    return TEMPLATES_ROOT / platform.lower() / f"{benchmark.lower()}_tuned.yaml"


def list_packaged_templates(
    platform: str | None = None,
    benchmark: str | None = None,
) -> dict[str, list[Path]]:
    templates: dict[str, list[Path]] = {}

    if not TEMPLATES_ROOT.exists():
        return templates

    for platform_dir in sorted(TEMPLATES_ROOT.iterdir()):
        if not platform_dir.is_dir():
            continue

        platform_name = platform_dir.name
        if platform and platform.lower() != platform_name.lower():
            continue

        platform_templates = []
        for template_file in sorted(platform_dir.glob("*.yaml")):
            if benchmark and not template_file.stem.lower().startswith(benchmark.lower()):
                continue
            platform_templates.append(template_file)

        if platform_templates:
            templates[platform_name] = platform_templates

    return templates
