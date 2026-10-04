from __future__ import annotations

import json
import re
import shlex
import textwrap

import bashlex
import bashlex.ast
import bashlex.errors
import yaml
from markdown_it import MarkdownIt

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


ASTRO_FENCE_OPEN = re.compile(r"---[ \t]*\r?\n")
ASTRO_FENCE_CLOSE = re.compile(r"---[ \t]*(?:\r?\n|\Z)")
ASTRO_EMBEDDED_BLOCK = re.compile(r"(<(?:script|style)\b[^>]*>)(.*?)(</(?:script|style)\s*>)", re.I | re.S)
EXPRESSION_PREFIX = "[\n"
EXPRESSION_SUFFIX = "\n];"


def blank_text(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def js_string_end(text: str, pos: int, multiline: bool) -> int:
    quote = text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
        elif text[pos] == quote or (text[pos] == "\n" and not multiline):
            return pos + 1
        else:
            pos += 1
    raise ValueError("unterminated string in Astro source")


def js_template_end(text: str, pos: int, sink: list[tuple[int, str]] | None = None) -> int:
    pos += 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
        elif text[pos] == "`":
            return pos + 1
        elif text.startswith("${", pos):
            pos = expression_end(text, pos + 2, sink) + 1
        else:
            pos += 1
    raise ValueError("unterminated template literal in Astro source")


def jsx_starts(text: str, pos: int) -> bool:
    following = text[pos + 1 : pos + 2]
    previous = text[max(0, pos - 64) : pos].rstrip()[-1:]
    return (following.isalpha() or following == ">") and not (previous.isalnum() or previous in {"_", "$", ")", "]"})


def tag_end(
    text: str, pos: int, found: list[tuple[int, int]] | None = None, sink: list[tuple[int, str]] | None = None
) -> int:
    pos += 1
    while pos < len(text):
        char = text[pos]
        if char in "'\"":
            pos = js_string_end(text, pos, True)
        elif char == "{":
            end = expression_end(text, pos + 1, sink)
            if found is not None:
                found.append((pos + 1, end))
            pos = end + 1
        elif char == ">":
            return pos + 1
        else:
            pos += 1
    raise ValueError("unterminated tag in Astro source")


def jsx_end(text: str, pos: int, sink: list[tuple[int, str]] | None = None) -> int:
    pos = tag_end(text, pos, None, sink)
    if text[pos - 2 : pos] == "/>":
        return pos
    depth = 1
    while pos < len(text):
        if text[pos] == "{":
            pos = expression_end(text, pos + 1, sink) + 1
        elif text.startswith("<!--", pos):
            end = text.find("-->", pos + 4)
            if end < 0:
                raise ValueError("unterminated HTML comment in Astro source")
            if sink is not None:
                sink.append((pos, text[pos : end + 3]))
            pos = end + 3
        elif text.startswith("</", pos):
            pos = text.index(">", pos) + 1
            depth -= 1
            if depth == 0:
                return pos
        elif text[pos] == "<" and jsx_starts(text, pos):
            pos = tag_end(text, pos, None, sink)
            depth += text[pos - 2 : pos] != "/>"
        else:
            pos += 1
    raise ValueError("unterminated JSX element in Astro source")


REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
REGEX_KEYWORDS = {"return", "typeof", "case", "in", "of", "void", "delete", "throw", "new", "yield", "await"}


def regex_allowed(text: str, pos: int, floor: int) -> bool:
    before = text[floor:pos].rstrip()
    if not before:
        return True
    if before[-2:] in {"++", "--"}:
        return False
    if before[-1] in REGEX_PRECEDERS:
        return True
    word = re.search(r"[A-Za-z_$][\w$]*\Z", before)
    return bool(word) and word.group() in REGEX_KEYWORDS


def regex_end(text: str, pos: int) -> int:
    pos += 1
    in_class = False
    while pos < len(text) and text[pos] != "\n":
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            pos += 1
            while pos < len(text) and (text[pos].isalnum() or text[pos] in "_$"):
                pos += 1
            return pos
        pos += 1
    raise ValueError("unterminated regular expression in Astro source")


def skip_js_comment(text: str, pos: int) -> int:
    if text.startswith("//", pos):
        end = text.find("\n", pos)
        return len(text) if end < 0 else end
    end = text.find("*/", pos + 2)
    if end < 0:
        raise ValueError("unterminated comment in Astro source")
    return end + 2


def expression_end(text: str, pos: int, sink: list[tuple[int, str]] | None = None) -> int:
    depth = 0
    floor = pos
    while pos < len(text):
        char = text[pos]
        if char in "'\"":
            pos = js_string_end(text, pos, False)
        elif char == "`":
            pos = js_template_end(text, pos, sink)
        elif text.startswith(("//", "/*"), pos):
            pos = skip_js_comment(text, pos)
        elif char == "/" and regex_allowed(text, pos, floor):
            pos = regex_end(text, pos)
        elif char == "<" and jsx_starts(text, pos):
            pos = jsx_end(text, pos, sink)
        elif char == "}" and depth == 0:
            return pos
        else:
            depth += (char == "{") - (char == "}")
            pos += 1
    raise ValueError("unterminated expression in Astro source")


def next_frontmatter_state(text: str, pos: int, state: str, nesting: list[int], floor: int) -> tuple[int, str]:
    char = text[pos]
    if state == "block":
        return (pos + 2, "code") if text.startswith("*/", pos) else (pos + 1, state)
    if state == "line":
        return pos + 1, "code" if char == "\n" else state
    if state in {"'", '"'}:
        if char == "\\":
            return pos + 2, state
        return pos + 1, "code" if char in {state, "\n"} else state
    if state == "`":
        if char == "\\":
            return pos + 2, state
        if text.startswith("${", pos):
            nesting.append(0)
            return pos + 2, "code"
        return pos + 1, "code" if char == "`" else state
    if text.startswith("//", pos):
        return pos + 2, "line"
    if text.startswith("/*", pos):
        return pos + 2, "block"
    if char in "'\"`":
        return pos + 1, char
    if char == "/" and regex_allowed(text, pos, floor):
        return regex_end(text, pos), state
    if nesting and char == "}" and nesting[-1] == 0:
        nesting.pop()
        return pos + 1, "`"
    if nesting and char in "{}":
        nesting[-1] += 1 if char == "{" else -1
    return pos + 1, state


def astro_frontmatter_span(source: str) -> tuple[int, int, int] | None:
    opening = ASTRO_FENCE_OPEN.match(source)
    if not opening:
        return None
    pos, state, nesting, line_start = opening.end(), "code", [], True
    while pos < len(source):
        if line_start and state == "code" and not nesting:
            closing = ASTRO_FENCE_CLOSE.match(source, pos)
            if closing:
                return opening.end(), pos, closing.end()
        line_start = source[pos] == "\n"
        pos, state = next_frontmatter_state(source, pos, state, nesting, opening.end())
    raise ValueError("unterminated Astro frontmatter")


def blank_astro_frontmatter(source: str) -> str:
    span = astro_frontmatter_span(source)
    return source if span is None else blank_text(source[: span[2]]) + source[span[2] :]


def astro_template(source: str) -> str:
    return ASTRO_EMBEDDED_BLOCK.sub(
        lambda m: m.group(1) + blank_text(m.group(2)) + m.group(3), blank_astro_frontmatter(source)
    )


def astro_template_parts(source: str) -> tuple[list[tuple[int, str]], list[tuple[int, int]]]:
    template = astro_template(source)
    comments: list[tuple[int, str]] = []
    nested: list[tuple[int, str]] = []
    expressions: list[tuple[int, int]] = []
    pos = 0
    while pos < len(template):
        if template.startswith("<!--", pos):
            end = template.find("-->", pos + 4)
            if end < 0:
                raise ValueError("unterminated HTML comment in Astro source")
            comments.append((template[:pos].count("\n") + 1, template[pos : end + 3]))
            pos = end + 3
        elif template[pos] == "<" and (
            template[pos + 1 : pos + 2].isalpha() or template[pos + 1 : pos + 2] in {"/", ">"}
        ):
            pos = tag_end(template, pos, expressions, nested)
        elif template[pos] == "{":
            end = expression_end(template, pos + 1, nested)
            expressions.append((pos + 1, end))
            pos = end + 1
        else:
            pos += 1
    comments.extend((template[:start].count("\n") + 1, text) for start, text in nested)
    return sorted(comments, key=lambda item: item[0]), expressions


def astro_template_comments(source: str) -> list[tuple[int, str]]:
    return astro_template_parts(source)[0]


def astro_expression_sources(path: str, source: str) -> list[tuple[int, str, str, str, str]]:
    template = astro_template(source)
    return [
        (
            template[:start].count("\n"),
            path + ".tsx",
            EXPRESSION_PREFIX + template[start:end] + EXPRESSION_SUFFIX,
            "javascript",
            f"expression:{index}",
        )
        for index, (start, end) in enumerate(astro_template_parts(source)[1])
        if re.search(r"//|/\*", template[start:end])
    ]


def example_blocks(source: str) -> list[tuple[int, str, str, str]]:
    blocks: list[tuple[int, str, str, str]] = []
    display_directives = {"tags", "toctree", "mermaid", "image", "figure", "include", "literalinclude"}
    containers = {
        "note",
        "tip",
        "warning",
        "important",
        "attention",
        "caution",
        "danger",
        "error",
        "hint",
        "admonition",
        "deprecated",
        "versionadded",
        "versionchanged",
        "seealso",
        "dropdown",
        "tab-set",
        "tab-item",
        "grid",
        "grid-item",
        "grid-item-card",
    }
    for token in MarkdownIt("commonmark").parse(source):
        if token.type != "fence" or token.map is None:
            continue
        info = token.info.strip()
        directive = re.fullmatch(r"\{([^}]+)\}(?:\s+(.*))?", info)
        start = token.map[0] + 2
        if directive:
            name, argument = directive.groups()
            if name in display_directives:
                continue
            if name in containers:
                for child_start, tag, text, identity in example_blocks(token.content):
                    blocks.append((start + child_start - 1, tag, text, f"block:{len(blocks)}:{identity}"))
                continue
            if name not in {"code", "code-block", "sourcecode", "code-cell"}:
                raise ValueError(f"unregistered documentation directive: {name}")
            tag = (argument or "").split()[0] if argument else ""
            lines = token.content.splitlines(keepends=True)
            while lines and (not lines[0].strip() or lines[0].lstrip().startswith(":")):
                lines.pop(0)
                start += 1
            text = textwrap.dedent("".join(lines))
        else:
            tag = info.split()[0] if info else ""
            text = token.content
        if tag not in DISPLAY_FENCES:
            blocks.append((start, tag, text, f"block:{len(blocks)}"))
    lines = source.splitlines(keepends=True)
    pos = 0
    while pos < len(lines):
        directive = re.match(r"(\s*)\.\.\s+(?:code-block|code|sourcecode)::\s*(\S+)\s*$", lines[pos])
        if not directive:
            pos += 1
            continue
        indent, tag = directive.groups()
        pos += 1
        while pos < len(lines) and (not lines[pos].strip() or lines[pos].lstrip().startswith(":")):
            pos += 1
        start = pos
        while pos < len(lines) and (not lines[pos].strip() or len(lines[pos]) - len(lines[pos].lstrip()) > len(indent)):
            pos += 1
        blocks.append((start + 1, tag, textwrap.dedent("".join(lines[start:pos])), f"block:{len(blocks)}"))
    return blocks


def stdin_language(words: list[str]) -> str | None:
    if not words:
        raise ValueError("dynamic shell command receiving a heredoc")
    name = words[0].rsplit("/", 1)[-1]
    if name == "env":
        return stdin_language([word for word in words[1:] if not word.startswith("-") and "=" not in word])
    if name == "uv" and words[1:2] == ["run"]:
        tail = words[2:]
        if "--" in tail:
            tail = tail[tail.index("--") + 1 :]
        return stdin_language(tail)
    if name.startswith("python") or name in {"node", "bash", "sh", "zsh", "ksh"}:
        args = words[1:]
        if "-c" in args or "-e" in args or "--eval" in args or any(not arg.startswith("-") for arg in args):
            return None
        return "python" if name.startswith("python") else "javascript" if name == "node" else "bash"
    if name in {"psql", "duckdb", "mysql", "sqlite3"}:
        return "sql"
    if name in {"cat", "printf", "tee", "curl", "wget", "sed", "awk"}:
        return None
    raise ValueError(f"unregistered heredoc consumer: {name}")


def heredoc_redirects(header: str) -> list[tuple[bashlex.ast.node, list[str], bool]]:
    redirects = []
    try:
        trees = bashlex.parse(header, strictmode=False)
    except (bashlex.errors.ParsingError, NotImplementedError) as exc:
        raise ValueError("shell heredoc header requires an adapter") from exc

    def visit(node: bashlex.ast.node, pipeline: list | None = None) -> None:
        if node.kind == "pipeline":
            pipeline = [child for child in node.parts if child.kind == "command"]
        if node.kind == "command":
            words = [part.word for part in node.parts if part.kind == "word"]
            redirs = [part for part in node.parts if part.kind == "redirect" and part.type in {"<<", "<<-"}]
            for redirect in redirs:
                consumer = words
                if words[:1] == ["cat"] and pipeline and pipeline[0] is node:
                    if len(pipeline) != 2:
                        raise ValueError("multi-stage heredoc pipeline requires an adapter")
                    consumer = [part.word for part in pipeline[1].parts if part.kind == "word"]
                redirects.append((redirect, consumer, redirect is redirs[-1]))
        for child in getattr(node, "parts", []):
            visit(child, pipeline)
        for child in getattr(node, "list", []):
            visit(child, pipeline)

    for tree in trees:
        visit(tree)
    return sorted(redirects, key=lambda item: item[0].pos[0])


def shell_payloads(path: str, source: str, include_data: bool = False) -> list[tuple[int, str, str, str, str]]:
    result = []
    lines = source.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        header = lines[index]
        index += 1
        while header.rstrip().endswith("\\") and index < len(lines):
            header += lines[index]
            index += 1
        if not re.search(r"(?<!<)<<(?!<)", header):
            if "<<<" in header and not re.match(r"\s*done\s+<<<\s+", header):
                raise ValueError("shell here-string requires an executable-payload adapter")
            continue
        redirects = heredoc_redirects(header)
        for redirect, consumer, effective in redirects:
            raw_marker = header[redirect.output.pos[0] : redirect.output.pos[1]]
            parsed = shlex.split(raw_marker)
            if len(parsed) != 1:
                raise ValueError("dynamic heredoc delimiter requires an adapter")
            marker = parsed[0]
            start = index
            while (
                index < len(lines)
                and (lines[index].lstrip("\t") if redirect.type == "<<-" else lines[index]).rstrip("\r\n") != marker
            ):
                index += 1
            if index == len(lines):
                raise ValueError("unterminated shell heredoc")
            text = "".join(lines[start:index])
            if redirect.type == "<<-":
                text = "".join(line.lstrip("\t") for line in lines[start:index])
            if not any(char in raw_marker for char in "'\"\\") and ("$(" in text or "`" in text):
                raise ValueError("executable substitution in a shell heredoc requires an adapter")
            nested_lang = stdin_language(consumer) if effective else None
            if nested_lang or include_data:
                nested_lang = nested_lang or "data"
                result.append((start + 1, path + "." + nested_lang, text, nested_lang, f"heredoc:{marker}"))
            index += 1
    return result


def shell_command_payloads(path: str, source: str) -> list[tuple[int, str, str, str, str]]:
    if not re.search(r"\beval\b|\b(?:python[0-9.]*|node|bash|sh|zsh)\b[^\n]*\s(?:-[A-Za-z]*[ce]|--eval)\b", source):
        return []
    try:
        trees = bashlex.parse(source)
    except (bashlex.errors.ParsingError, NotImplementedError) as exc:
        raise ValueError("shell command source requires an executable-payload adapter") from exc
    result = []

    def visit(node: bashlex.ast.node, symbol: str = "") -> None:
        if node.kind == "function":
            symbol = f"{symbol}.{node.name.word}".strip(".")
        if node.kind == "command":
            words = [part for part in node.parts if part.kind == "word"]
            if words:
                command = words[0].word.rsplit("/", 1)[-1]
                if command in {"env", "uv"}:
                    interpreter = next(
                        (
                            index
                            for index, word in enumerate(words[1:], 1)
                            if re.fullmatch(r"python[0-9.]*|node|bash|sh|zsh", word.word)
                        ),
                        None,
                    )
                    if interpreter is not None:
                        words = words[interpreter:]
                        command = words[0].word
                language = (
                    "python"
                    if re.fullmatch(r"python[0-9.]*", command)
                    else {"node": "javascript", "sh": "bash", "bash": "bash", "zsh": "bash", "eval": "bash"}.get(
                        command
                    )
                )
                flag = next(
                    (index for index, word in enumerate(words[1:], 1) if word.word in {"-c", "-e", "--eval", "-lc"}),
                    None,
                )
                payload_words = (
                    words[1:] if command == "eval" else words[flag + 1 : flag + 2] if flag is not None else []
                )
                if language and payload_words:
                    if any(word.parts for word in payload_words):
                        raise ValueError("unresolved executable shell argument: " + source[node.pos[0] : node.pos[1]])
                    text = " ".join(word.word for word in payload_words)
                    line = source[: payload_words[0].pos[0]].count("\n") + 1
                    result.append((line, path + "." + language, text, language, f"{symbol}:command:{command}"))
        for child in getattr(node, "parts", []):
            visit(child, symbol)
        for child in getattr(node, "list", []):
            visit(child, symbol)
        if node.kind in {"commandsubstitution", "processsubstitution"}:
            visit(node.command, symbol)

    for tree in trees:
        visit(tree)
    return result


def nested_sources(path: str, source: str, lang: str) -> list[tuple[int, str, str, str, str]]:
    if lang == "bash":
        return shell_payloads(path, source) + shell_command_payloads(path, source)
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
    if lang in {"yaml", "json"}:
        tree = yaml.compose(source)
        result = []

        active: set[int] = set()

        def visit(
            node: yaml.Node | None, symbol: str = "", github_script: bool = False, sql_mapping: bool = False
        ) -> None:
            if node is not None and id(node) in active:
                raise ValueError("recursive YAML alias requires an adapter")
            active.add(id(node))
            if isinstance(node, yaml.MappingNode):
                github_script = github_script or any(
                    isinstance(k, yaml.ScalarNode)
                    and k.value == "uses"
                    and isinstance(v, yaml.ScalarNode)
                    and v.value.startswith("actions/github-script@")
                    for k, v in node.value
                )
                for key, value in node.value:
                    if (
                        isinstance(key, yaml.ScalarNode)
                        and isinstance(value, yaml.ScalarNode)
                        and (
                            key.value in {"run", "sql", "query"}
                            or key.value.endswith("_sql")
                            or (github_script and key.value == "script")
                            or sql_mapping
                        )
                    ):
                        nested_lang = (
                            "bash"
                            if key.value == "run"
                            else "javascript"
                            if github_script and key.value == "script"
                            else "sql"
                        )
                        result.append(
                            (
                                value.start_mark.line + 1,
                                path + "." + nested_lang,
                                value.value,
                                nested_lang,
                                f"{symbol}.{key.value}",
                            )
                        )
                    visit(
                        value,
                        f"{symbol}.{key.value}" if isinstance(key, yaml.ScalarNode) else symbol,
                        github_script,
                        isinstance(key, yaml.ScalarNode) and key.value == "platform_overrides",
                    )
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
    if lang == "astro":
        span = astro_frontmatter_span(source)
        frontmatter = (
            [(1 + source[: span[0]].count("\n"), path + ".ts", source[span[0] : span[1]], "javascript", "frontmatter")]
            if span
            else []
        )
        return (
            frontmatter
            + nested_sources(path, blank_astro_frontmatter(source), "html")
            + astro_expression_sources(path, source)
        )
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
