import re
from pathlib import Path

from sphinx.application import Sphinx

TAG_CATEGORIES = {
    "audience": (
        "By Audience",
        [
            "beginner",
            "intermediate",
            "advanced",
            "contributor",
        ],
    ),
    "benchmark": (
        "By Benchmark",
        [
            "tpc-h",
            "tpc-ds",
            "tpc-di",
            "tpc-havoc",
            "tpch-skew",
            "ssb",
            "clickbench",
            "h2odb",
            "join-order",
            "amplab",
            "nyctaxi",
            "coffeeshop",
            "datavault",
            "tsbs-devops",
            "read-primitives",
            "write-primitives",
            "transaction-primitives",
            "metadata-primitives",
            "ai-primitives",
            "custom-benchmark",
        ],
    ),
    "platform": (
        "By Platform",
        [
            "duckdb",
            "sqlite",
            "postgresql",
            "datafusion",
            "snowflake",
            "databricks",
            "bigquery",
            "redshift",
            "motherduck",
            "starburst",
            "clickhouse",
            "trino",
            "presto",
            "firebolt",
            "timescaledb",
            "influxdb",
            "athena",
            "aws-glue",
            "emr-serverless",
            "athena-spark",
            "dataproc",
            "dataproc-serverless",
            "azure",
            "fabric",
            "fabric-spark",
            "synapse-spark",
            "spark",
            "pyspark",
            "pandas",
            "polars",
            "dask",
            "modin",
            "cudf",
            "datafusion-df",
        ],
    ),
    "platform-type": (
        "By Platform Type",
        [
            "sql-platform",
            "dataframe-platform",
            "cloud-platform",
            "embedded-platform",
            "cloud-storage",
        ],
    ),
    "content-type": (
        "By Content Type",
        [
            "guide",
            "tutorial",
            "reference",
            "concept",
            "quickstart",
        ],
    ),
    "feature": (
        "By Feature",
        [
            "architecture",
            "cli",
            "cloud",
            "e2e",
            "python-api",
            "configuration",
            "data-generation",
            "performance",
            "tuning",
            "validation",
            "testing",
            "visualization",
        ],
    ),
}

_tag_counts: dict[str, str] = {}


def create_category_pages(app: Sphinx) -> None:
    global _tag_counts

    tags_output_dir = getattr(app.config, "tags_output_dir", "_tags")
    tags_dir = Path(app.srcdir) / tags_output_dir

    tags_dir.mkdir(parents=True, exist_ok=True)

    tagsindex_file = tags_dir / "tagsindex.md"
    if tagsindex_file.exists():
        content = tagsindex_file.read_text()
        tag_pattern = re.compile(r"^([a-z0-9-]+)\s+\((\d+)\)\s+<([a-z0-9-]+)>$", re.MULTILINE)
        _tag_counts = {match.group(1): match.group(2) for match in tag_pattern.finditer(content)}

    for category_slug in TAG_CATEGORIES:
        category_file = tags_dir / f"cat-{category_slug}.md"
        if not category_file.exists():
            category_file.write_text(f"# Category: {category_slug}\n")


def fix_tag_sources(app: Sphinx, docname: str, source: list) -> None:
    tags_output_dir = getattr(app.config, "tags_output_dir", "_tags")

    if not docname.startswith(tags_output_dir + "/"):
        return

    basename = docname.split("/")[-1]

    if basename == "tagsindex":
        source[0] = _reorganize_tagsindex(source[0])
    elif basename.startswith("cat-"):
        category_slug = basename[4:]
        source[0] = _generate_category_page(category_slug)
    else:
        source[0] = _hide_tag_page_toctree(source[0])


def _hide_tag_page_toctree(content: str) -> str:
    pattern = re.compile(
        r"```\{toctree\}\n"
        r"---\n"
        r"maxdepth:\s*\d+\n"
        r"caption:\s*([^\n]+)\n"
        r"---\n"
        r"(.*?)"
        r"```",
        re.DOTALL,
    )

    def replace_with_refs(match: re.Match) -> str:
        caption = match.group(1)
        entries = match.group(2).strip().split("\n")

        lines = [f"**{caption}**", ""]
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            doc_path = re.sub(r"\.(md|rst)$", "", entry)
            lines.append(f"- {{doc}}`{doc_path}`")

        return "\n".join(lines)

    return pattern.sub(replace_with_refs, content)


def _reorganize_tagsindex(content: str) -> str:
    global _tag_counts

    tag_pattern = re.compile(r"^([a-z0-9-]+)\s+\((\d+)\)\s+<([a-z0-9-]+)>$", re.MULTILINE)
    _tag_counts = {match.group(1): match.group(2) for match in tag_pattern.finditer(content)}

    if not _tag_counts:
        return content

    lines = [
        "(tagoverview)=",
        "",
        "# Browse by Tag",
        "",
        "Select a category to browse tags:",
        "",
        "```{toctree}",
        "---",
        "maxdepth: 2",
        "---",
    ]

    for category_slug, (display_name, _tags) in TAG_CATEGORIES.items():
        lines.append(f"{display_name} <cat-{category_slug}>")

    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _generate_category_page(category_slug: str) -> str:
    if category_slug not in TAG_CATEGORIES:
        return f"# Unknown category: {category_slug}\n"

    display_name, category_tags = TAG_CATEGORIES[category_slug]

    existing_tags = [(t, _tag_counts.get(t, "?")) for t in category_tags if t in _tag_counts]

    lines = [
        f"# {display_name}",
        "",
    ]

    if existing_tags:
        lines.append("```{toctree}")
        lines.append("---")
        lines.append("maxdepth: 1")
        lines.append("---")
        for tag_name, count in existing_tags:
            lines.append(f"{tag_name} ({count}) <{tag_name}>")
        lines.append("```")
    else:
        lines.append("*No tags in this category yet.*")

    lines.append("")
    return "\n".join(lines)


def setup(app: Sphinx) -> dict:
    app.connect("builder-inited", create_category_pages)
    app.connect("source-read", fix_tag_sources)

    return {
        "version": "0.3",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
