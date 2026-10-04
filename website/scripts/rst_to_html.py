import json
import re
import sys
from pathlib import Path

from docutils import nodes
from docutils.core import publish_parts
from docutils.parsers.rst import Directive, directives, roles

DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"


def target_title(docname: str) -> str:
    for suffix in (".md", ".rst"):
        candidate = DOCS_ROOT / f"{docname}{suffix}"
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    return line[2:].strip()
            lines = candidate.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines[1:], start=1):
                if line and set(line) <= set("=-~") and len(line) >= len(lines[index - 1].strip()) > 0:
                    return lines[index - 1].strip()
    return docname


def resolve(current: Path, docname: str) -> str:
    base = current.parent.relative_to(DOCS_ROOT)
    resolved = (DOCS_ROOT / base / docname).resolve().relative_to(DOCS_ROOT)
    return resolved.as_posix()


class Toctree(Directive):
    has_content = True
    option_spec = {"maxdepth": directives.nonnegative_int, "caption": directives.unchanged, "hidden": directives.flag}

    def run(self):
        source = Path(self.state.document["source"])
        items = nodes.bullet_list(classes=["toctree"])
        for entry in self.content:
            name = entry.strip()
            if not name or name.startswith(":"):
                continue
            target = resolve(source, name)
            link = nodes.reference("", target_title(target), refuri=f"/docs/{target}.html")
            items += nodes.list_item("", nodes.paragraph("", "", link))
        return [items]


class Tags(Directive):
    has_content = False
    optional_arguments = 1
    final_argument_whitespace = True

    def run(self):
        return []


def doc_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    match = re.match(r"^(.*?)\s*<([^>]+)>$", text, re.S)
    label, docname = (match.group(1), match.group(2)) if match else (None, text)
    source = Path(inliner.document["source"])
    target = resolve(source, docname)
    return [nodes.reference(rawtext, label or target_title(target), refuri=f"/docs/{target}.html")], []


directives.register_directive("toctree", Toctree)
directives.register_directive("tags", Tags)
roles.register_local_role("doc", doc_role)

source_path = Path(sys.argv[1]).resolve()
parts = publish_parts(
    source=source_path.read_text(encoding="utf-8"),
    source_path=str(source_path),
    writer_name="html5",
    settings_overrides={
        "initial_header_level": 2,
        "doctitle_xform": True,
        "sectsubtitle_xform": False,
        "report_level": 4,
        "halt_level": 5,
        "syntax_highlight": "none",
    },
)
body = parts["body"]
headings = [
    {"depth": int(m.group(2)), "slug": m.group(1), "text": re.sub(r"<[^>]+>", "", m.group(3)).strip()}
    for m in re.finditer(r'<section id="([^"]+)">\s*<h([2-6])>(.*?)</h\2>', body, re.S)
]
json.dump({"title": parts["title"], "html": body, "headings": headings}, sys.stdout)
