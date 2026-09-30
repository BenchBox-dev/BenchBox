from __future__ import annotations

import json
import re

import yaml

FENCE_LANGUAGES = {
    "py": "python",
    "python": "python",
    "python3": "python",
    "bash": "bash",
    "sh": "bash",
    "shell": "bash",
    "sql": "sql",
    "javascript": "javascript",
    "js": "javascript",
    "ts": "javascript",
    "typescript": "javascript",
    "tsx": "javascript",
    "jsx": "javascript",
    "css": "css",
    "html": "html",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "makefile": "make",
    "dockerfile": "docker",
    "json": "json",
    "ini": "ini",
    "console": "console",
}
DISPLAY_FENCES = {"", "text", "plaintext", "none", "output", "mermaid", "diff", "csv", "md", "markdown"}


def example_blocks(source: str) -> list[tuple[int, str, str, str]]:
    lines = source.splitlines(keepends=True)
    blocks: list[tuple[int, str, str, str]] = []
    pos = 0
    while pos < len(lines):
        fence = re.match(r"\s*(`{3,}|~{3,})([^\s]*).*$", lines[pos])
        directive = re.match(r"\s*\.\.\s+(?:code-block|code)::\s*(\S+)\s*$", lines[pos])
        if fence:
            marker, tag = fence.groups()
            start = pos + 1
            pos = start
            while pos < len(lines) and not re.match(rf"\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", lines[pos]):
                pos += 1
            if pos == len(lines):
                raise ValueError("unterminated documentation fence")
            if tag not in DISPLAY_FENCES:
                blocks.append((start + 1, tag, "".join(lines[start:pos]), f"block:{len(blocks)}"))
        elif directive:
            tag = directive.group(1)
            pos += 1
            while pos < len(lines) and (not lines[pos].strip() or lines[pos].lstrip().startswith(":")):
                pos += 1
            start = pos
            while pos < len(lines) and (not lines[pos].strip() or lines[pos].startswith("   ")):
                pos += 1
            blocks.append((start + 1, tag, "".join(line[3:] for line in lines[start:pos]), f"block:{len(blocks)}"))
            continue
        pos += 1
    return blocks


def shell_payloads(path: str, source: str) -> list[tuple[int, str, str, str, str]]:
    result = []
    lines = source.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        heredoc = re.search(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\2", lines[index])
        if not heredoc:
            index += 1
            continue
        strip_tabs, quote, marker = heredoc.groups()
        header = lines[index][: heredoc.start()]
        start = index + 1
        index = start
        while (
            index < len(lines) and (lines[index].lstrip("\t") if strip_tabs else lines[index]).rstrip("\r\n") != marker
        ):
            index += 1
        if index == len(lines):
            raise ValueError("unterminated shell heredoc")
        text = "".join(lines[start:index])
        if strip_tabs:
            text = "".join(line.lstrip("\t") for line in lines[start:index])
        command = re.search(r"\b(python[0-9.]*|node|bash|sh|ruby|perl|Rscript|psql|duckdb|mysql|sqlite3)\b", header)
        if command:
            name = command.group(1)
            nested_lang = (
                "python"
                if name.startswith("python")
                else {
                    "node": "javascript",
                    "bash": "bash",
                    "sh": "bash",
                    "psql": "sql",
                    "duckdb": "sql",
                    "mysql": "sql",
                    "sqlite3": "sql",
                }.get(name, "unsupported")
            )
            result.append(
                (
                    start + 1,
                    path + (".js" if name == "node" else "." + nested_lang),
                    text,
                    nested_lang,
                    f"heredoc:{marker}",
                )
            )
        elif not quote and ("$(" in text or "`" in text):
            raise ValueError("executable substitution in a shell heredoc requires an adapter")
        index += 1
    return result


def nested_sources(path: str, source: str, lang: str) -> list[tuple[int, str, str, str, str]]:
    if lang == "bash":
        return shell_payloads(path, source)
    if lang == "examples":
        return [
            (start, path + "." + tag, text, FENCE_LANGUAGES.get(tag, "unsupported"), symbol)
            for start, tag, text, symbol in example_blocks(source)
        ]
    if lang == "notebook":
        notebook = json.loads(source)
        declared = notebook.get("metadata", {}).get("language_info", {}).get("name", "python")
        return [
            (
                1,
                path + "." + declared,
                "".join(cell["source"]),
                FENCE_LANGUAGES.get(declared, "unsupported"),
                f"cell:{cell.get('id', index)}",
            )
            for index, cell in enumerate(notebook["cells"])
            if cell["cell_type"] == "code"
        ]
    if lang == "yaml":
        tree = yaml.compose(source)
        result = []

        active: set[int] = set()

        def visit(node: yaml.Node | None, symbol: str = "") -> None:
            if node is not None and id(node) in active:
                raise ValueError("recursive YAML alias requires an adapter")
            active.add(id(node))
            if isinstance(node, yaml.MappingNode):
                for key, value in node.value:
                    if (
                        isinstance(key, yaml.ScalarNode)
                        and isinstance(value, yaml.ScalarNode)
                        and key.value in {"run", "sql", "query"}
                    ):
                        nested_lang = "bash" if key.value == "run" else "sql"
                        result.append(
                            (
                                value.start_mark.line + 1,
                                path + "." + nested_lang,
                                value.value,
                                nested_lang,
                                f"{symbol}.{key.value}",
                            )
                        )
                    visit(value, f"{symbol}.{key.value}" if isinstance(key, yaml.ScalarNode) else symbol)
            elif isinstance(node, yaml.SequenceNode):
                for index, item in enumerate(node.value):
                    identity = str(index)
                    if isinstance(item, yaml.MappingNode):
                        identities = {
                            key.value: value.value
                            for key, value in item.value
                            if isinstance(key, yaml.ScalarNode) and isinstance(value, yaml.ScalarNode)
                        }
                        identity = identities.get("id", identities.get("name", identity))
                    visit(item, f"{symbol}[{identity}]")
            active.remove(id(node))

        visit(tree)
        return result
    if lang in {"html", "html+jinja"}:
        return [
            (
                source[: match.start(2)].count("\n") + 1,
                path + (".js" if match.group(1).lower() == "script" else ".css"),
                match.group(2),
                (
                    "json"
                    if re.search(r"\btype\s*=\s*['\"]application/(?:ld\+)?json['\"]", match.group(), re.I)
                    else "javascript"
                )
                if match.group(1).lower() == "script"
                else "css",
                f"{match.group(1)}:{index}",
            )
            for index, match in enumerate(re.finditer(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", source, re.I | re.S))
        ]
    return []
