from __future__ import annotations

import json
import re
import shlex
import textwrap
from typing import Any

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
    "c": "c",
    "powershell": "powershell",
    "console": "console",
    "groovy": "groovy",
    "sql+jinja": "sql+jinja",
}
DISPLAY_FENCES = {"", "text", "plaintext", "none", "output", "mermaid", "diff", "csv", "md", "markdown"}


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


def _wrapper_operand(words: list[str | None], index: int, wrapper: str) -> str:
    if index + 1 >= len(words):
        raise ValueError(f"{wrapper} option requires an operand: {words[index]}")
    operand = words[index + 1]
    if operand is None:
        raise ValueError(f"dynamic {wrapper} option operand requires an adapter")
    return operand


def _wrapper_tail(
    words: list[str | None], *, value_options: set[str], flag_options: set[str], wrapper: str
) -> list[str | None]:
    index = 0
    while index < len(words):
        word = words[index]
        if word is None:
            raise ValueError(f"dynamic {wrapper} option or executable requires an adapter")
        if word == "--":
            return words[index + 1 :]
        if word in {"-S", "--split-string"} and word in value_options:
            operand = _wrapper_operand(words, index, wrapper)
            if any(token in operand for token in ("#", "\\c", "$")):
                raise ValueError(f"unsupported {wrapper} split-string syntax")
            try:
                split_words = shlex.split(operand)
            except ValueError as exc:
                raise ValueError(f"malformed {wrapper} split-string operand") from exc
            if not split_words:
                raise ValueError(f"empty {wrapper} split-string operand")
            return _wrapper_tail(
                [*split_words, *words[index + 2 :]],
                value_options=value_options,
                flag_options=flag_options,
                wrapper=wrapper,
            )
        if word.startswith("--split-string=") and "--split-string" in value_options:
            if any(token in word.split("=", 1)[1] for token in ("#", "\\c", "$")):
                raise ValueError(f"unsupported {wrapper} split-string syntax")
            try:
                split_words = shlex.split(word.split("=", 1)[1])
            except ValueError as exc:
                raise ValueError(f"malformed {wrapper} split-string operand") from exc
            if not split_words:
                raise ValueError(f"empty {wrapper} split-string operand")
            return _wrapper_tail(
                [*split_words, *words[index + 1 :]],
                value_options=value_options,
                flag_options=flag_options,
                wrapper=wrapper,
            )
        if "=" in word and word.startswith("--"):
            option, _ = word.split("=", 1)
            if option in value_options:
                index += 1
                continue
        if word in value_options:
            _wrapper_operand(words, index, wrapper)
            index += 2
            continue
        if word in flag_options:
            index += 1
            continue
        if word.startswith("-"):
            raise ValueError(f"unregistered {wrapper} option: {word}")
        return words[index:]
    return []


def inline_source_index(words: list[str | None], language: str | None) -> int | None:
    inline_flags = {
        "python": {"-c"},
        "bash": {"-c", "-lc"},
        "javascript": {"-e", "--eval"},
        "sql": {"-c", "--command"},
    }.get(language or "", {"-c", "-e", "--eval", "--command", "-lc"})
    python_flags = {
        "-b",
        "-bb",
        "-B",
        "-d",
        "-E",
        "-i",
        "-I",
        "-O",
        "-OO",
        "-P",
        "-q",
        "-R",
        "-s",
        "-S",
        "-u",
        "-v",
        "-x",
    }
    index = 1
    while index < len(words):
        word = words[index]
        if word is None:
            raise ValueError("dynamic interpreter option requires an adapter")
        if word in inline_flags:
            if index + 1 < len(words):
                return index + 1
            raise ValueError("inline interpreter argument requires explicit support")
        if language == "python":
            if word == "-m" or word == "--" or (word and not word.startswith("-")):
                return None
            if word not in python_flags and not word.startswith(("-W", "-X")):
                raise ValueError("interpreter option operand requires explicit support")
        if language == "bash" and word in {"-o", "+o"}:
            if index + 1 >= len(words) or words[index + 1] is None:
                raise ValueError("interpreter option operand requires explicit support")
            index += 2
            continue
        if language == "bash" and (word == "--" or (word and not word.startswith("-"))):
            return None
        if language == "python" and word in {"-W", "-X"}:
            if index + 1 >= len(words) or words[index + 1] is None:
                raise ValueError("interpreter option operand requires explicit support")
            index += 2
        else:
            index += 1
    return None


def command_words(words: list[str | None]) -> list[str | None]:
    if not words or words[0] is None:
        raise ValueError("dynamic shell command receiving a heredoc")
    name = words[0].rsplit("/", 1)[-1]
    if name == "env":
        tail = _wrapper_tail(
            words[1:],
            value_options={
                "-u",
                "--unset",
                "-C",
                "--chdir",
                "-S",
                "--split-string",
                "--block-signal",
                "--default-signal",
                "--ignore-signal",
                "--argv0",
            },
            flag_options={"-i", "--ignore-environment", "-0", "--null"},
            wrapper="env",
        )
        while tail and tail[0] is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tail[0]):
            tail = tail[1:]
        return command_words(tail)
    if name == "uv" and words[1:2] == [None]:
        raise ValueError("dynamic uv command requires an adapter")
    if name == "uv" and words[1:2] == ["run"]:
        return command_words(
            _wrapper_tail(
                words[2:],
                value_options={
                    "--allow-insecure-host",
                    "--config-setting",
                    "--config-settings-package",
                    "--cache-dir",
                    "--config-file",
                    "--directory",
                    "--env-file",
                    "--exclude-newer",
                    "--exclude-newer-package",
                    "--extra",
                    "--extra-index-url",
                    "--find-links",
                    "--fork-strategy",
                    "--group",
                    "--index",
                    "--index-strategy",
                    "--index-url",
                    "--keyring-provider",
                    "--link-mode",
                    "--no-editable-package",
                    "--no-extra",
                    "--no-group",
                    "--no-sources-package",
                    "--only-group",
                    "--package",
                    "--python-platform",
                    "--project",
                    "--python",
                    "--prerelease",
                    "--refresh-package",
                    "--reinstall-package",
                    "--resolution",
                    "--upgrade-group",
                    "--upgrade-package",
                    "--with",
                    "--with-editable",
                    "--with-requirements",
                    "--color",
                    "-C",
                    "-f",
                    "-i",
                    "-p",
                    "-P",
                    "-w",
                },
                flag_options={
                    "--active",
                    "--all-extras",
                    "--all-groups",
                    "--all-packages",
                    "--compile-bytecode",
                    "--exact",
                    "--frozen",
                    "--inexact",
                    "--isolated",
                    "--locked",
                    "--managed-python",
                    "--native-tls",
                    "--no-active",
                    "--no-binary",
                    "--no-build",
                    "--no-build-isolation",
                    "--no-cache",
                    "--no-config",
                    "--no-default-groups",
                    "--no-dev",
                    "--no-editable",
                    "--no-managed-python",
                    "--no-project",
                    "--no-python-downloads",
                    "--no-reinstall",
                    "--no-sources",
                    "--no-sync",
                    "--offline",
                    "--only-dev",
                    "--quiet",
                    "--refresh",
                    "--reinstall",
                    "--verbose",
                    "--system-certs",
                    "--no-env-file",
                    "--no-index",
                    "--no-progress",
                    "-U",
                    "-n",
                    "-q",
                    "-v",
                },
                wrapper="uv run",
            )
        )
    return words


def stdin_language(words: list[str]) -> str | None:
    words = command_words(words)
    name = words[0].rsplit("/", 1)[-1]
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
    header = re.sub(r"^(\s*)if(?=\s)", lambda match: match.group(1) + "  ", header)
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
                    if any(word.parts for word in words):
                        raise ValueError("dynamic inline wrapper arguments require an adapter")
                    normalized = command_words([word.word for word in words])
                    if normalized != [word.word for word in words[-len(normalized) :]]:
                        raise ValueError("inline split-string wrapper requires an adapter")
                    words = words[-len(normalized) :]
                    command = words[0].word.rsplit("/", 1)[-1]
                language = (
                    "python"
                    if re.fullmatch(r"python[0-9.]*", command)
                    else {"node": "javascript", "sh": "bash", "bash": "bash", "zsh": "bash", "eval": "bash"}.get(
                        command
                    )
                )
                source_index = (
                    inline_source_index([None if word.parts else word.word for word in words], language)
                    if language and command != "eval"
                    else None
                )
                payload_words = (
                    words[1:]
                    if command == "eval"
                    else words[source_index : source_index + 1]
                    if source_index is not None
                    else []
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


def notebook_pip_install(line: str) -> bool:
    words = line.split()
    arguments = words[2:]
    archives = (
        ".whl",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".tgz",
        ".tbz",
        ".tbz2",
        ".txz",
        ".tlz",
        ".lz",
        ".lzma",
        ".egg",
    )
    return (
        words[:2] in [["%pip", "install"], ["!pip", "install"], ["!pip3", "install"]]
        and any(word not in {"--quiet", "-q"} for word in arguments)
        and all(
            word in {"--quiet", "-q"}
            or (
                not ("[" in word and "." in word.split("[", 1)[0])
                and not word.split("[", 1)[0].lower().endswith(archives)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?", word)
            )
            for word in arguments
        )
    )


def notebook_python_sources(path: str, source: str, symbol: str, ipython: bool) -> list[tuple[int, str, str, str, str]]:
    import io
    import tokenize

    if not ipython:
        return [(1, path + ".python", source, "python", symbol)]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ValueError("unresolved notebook Python tokenization") from exc
    protected = {
        line
        for token in tokens
        if token.type == tokenize.STRING and token.start[0] != token.end[0]
        for line in range(token.start[0], token.end[0] + 1)
    }
    lines = source.splitlines(keepends=True)
    shells = []
    magic_lines = set()
    for index, line in enumerate(lines):
        if index + 1 in protected or not line.lstrip().startswith(("!", "%")):
            continue
        if line[0].isspace():
            raise ValueError("unresolved indented notebook magic")
        if line.startswith("!") and not line.startswith("!!"):
            command = line[1:].rstrip("\r\n")
            if not command.strip() or any(char in command for char in "${}\\"):
                raise ValueError("unresolved notebook shell interpolation or continuation")
            shells.append((index + 1, path + ".sh", command, "bash", symbol + ":shell"))
            if not notebook_pip_install(line):
                shells.append((index + 1, path + ".unsupported", command, "unsupported", symbol + ":shell-semantics"))
        elif line.rstrip("\r\n") != "%matplotlib inline" and not notebook_pip_install(line):
            raise ValueError("unresolved notebook magic")
        magic_lines.add(index + 1)
        lines[index] = "\n" if line.endswith("\n") else ""
    python = "".join(lines)
    depth = 0
    for token in tokenize.generate_tokens(io.StringIO(python).readline):
        if token.start[0] in magic_lines and depth:
            raise ValueError("unresolved notebook magic in Python continuation")
        if token.type == tokenize.OP:
            depth += int(token.string in "([{") - int(token.string in ")]}")
    if any(start > 1 and source.splitlines()[start - 2].rstrip().endswith(chr(92)) for start in magic_lines):
        raise ValueError("unresolved notebook magic in Python continuation")
    return [(1, path + ".python", python, "python", symbol), *shells]


def notebook_sources(path: str, source: str) -> list[tuple[int, str, str, str, str]]:
    notebook = json.loads(source)
    info = notebook.get("metadata", {}).get("language_info", {})
    if not isinstance(info, dict):
        raise ValueError("unresolved notebook language metadata")
    declared = info.get("name", "python")
    mode = info.get("codemirror_mode")
    ipython = info.get("pygments_lexer") == "ipython3" or (isinstance(mode, dict) and mode.get("name") == "ipython")
    result = []
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        text = "".join(cell["source"])
        symbol = f"cell:{cell.get('id', index)}"
        if declared == "python":
            try:
                result.extend(notebook_python_sources(path, text, symbol, ipython))
            except ValueError:
                result.append((1, path + ".unsupported", text, "unsupported", symbol))
        else:
            result.append((1, path + "." + declared, text, FENCE_LANGUAGES.get(declared, "unsupported"), symbol))
    return result


def nested_sources(path: str, source: str, lang: str) -> list[tuple[int, str, str, str, str]]:
    if lang == "groovy":
        return groovy_payloads(path, source)
    if lang == "html+jinja":
        parsed_template(source)
    if lang == "bash":
        return shell_payloads(path, source) + shell_command_payloads(path, source)
    if lang == "examples":
        return [
            (start, path + "." + tag, text, FENCE_LANGUAGES.get(tag, "unsupported"), symbol)
            for start, tag, text, symbol in example_blocks(source)
        ]
    if lang == "notebook":
        return notebook_sources(path, source)
    if lang in {"yaml", "json"}:
        trees = list(yaml.compose_all(source)) if lang == "yaml" else [yaml.compose(source)]
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

        for index, tree in enumerate(trees):
            visit(tree, f"document:{index}" if len(trees) > 1 else "")
        return result
    if lang in {"html", "html+jinja"}:
        spans = template_data_spans(source) if lang == "html+jinja" else [(0, len(source))]
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
            if any(start <= match.start() and match.end() <= end for start, end in spans)
        ]
    return []


def parsed_template(source: str) -> Any:
    from jinja2 import Environment, TemplateSyntaxError

    try:
        return Environment().parse(source)
    except TemplateSyntaxError as exc:
        raise ValueError(f"invalid template syntax at line {exc.lineno}: {exc.message}") from exc


def bounded_html_template(source: str) -> None:
    from jinja2 import nodes

    tree = parsed_template(source)
    for match in re.finditer(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", source, re.I | re.S):
        if re.search(r"\{\{|\{%|\{#", match.group(2)):
            raise ValueError("template syntax inside script or style requires an adapter")
    for constant in tree.find_all(nodes.Const):
        if isinstance(constant.value, str) and "<" in constant.value:
            raise ValueError("template string constant may emit markup")


def static_html_template(source: str) -> None:
    from jinja2 import nodes

    tree = parsed_template(source)
    for statement in tree.body:
        if not isinstance(statement, nodes.Output) or any(
            not isinstance(expression, nodes.TemplateData) for expression in statement.nodes
        ):
            raise ValueError("unresolved emitted HTML template source")


def _template_call(node: Any) -> str:
    from jinja2 import nodes

    if not isinstance(node.node, nodes.Name) or node.dyn_args is not None or node.dyn_kwargs is not None:
        raise ValueError("unresolved SQL template call")
    name = node.node.name
    if name in {"source", "ref"}:
        if node.kwargs or len(node.args) not in ({2} if name == "source" else {1, 2}):
            raise ValueError("unresolved SQL template identifier")
        if any(
            not isinstance(arg, nodes.Const)
            or not isinstance(arg.value, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", arg.value) is None
            for arg in node.args
        ):
            raise ValueError("unresolved SQL template identifier")
        return "__dbt_identifier__"
    if name == "is_incremental" and not node.args and not node.kwargs:
        return "__dbt_flag__"
    if name == "config":
        if node.args:
            raise ValueError("unresolved SQL template configuration")
        values = {
            "materialized": {"table", "view", "incremental", "ephemeral"},
            "on_schema_change": {"ignore", "fail", "append_new_columns", "sync_all_columns"},
        }
        for keyword in node.kwargs:
            if not isinstance(keyword.value, nodes.Const) or not isinstance(keyword.value.value, str):
                raise ValueError("unresolved SQL template configuration")
            value = keyword.value.value
            valid = (
                re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value)
                if keyword.key == "unique_key"
                else value in values.get(keyword.key, set())
            )
            if not valid:
                raise ValueError("unresolved SQL template configuration")
        return ""
    raise ValueError("unresolved SQL template call")


def _template_literal(node: Any, bindings: dict[str, list[Any]], seen: frozenset[str] = frozenset()) -> Any:
    from jinja2 import nodes

    if isinstance(node, nodes.Const) and isinstance(node.value, (str, int, float, bool, type(None))):
        return node.value
    if isinstance(node, nodes.Name):
        values = bindings.get(node.name, [])
        if not values and node.name == "this":
            return "__dbt_identifier__"
        if len(values) != 1 or node.name in seen:
            raise ValueError(f"unresolved SQL template output: {node.name}")
        return _template_literal(values[0], bindings, seen | {node.name})
    if isinstance(node, nodes.Concat):
        return "".join(str(_template_literal(operand, bindings, seen)) for operand in node.nodes)
    if isinstance(node, nodes.Add):
        return _template_literal(node.left, bindings, seen) + _template_literal(node.right, bindings, seen)
    if isinstance(node, nodes.Call):
        return _template_call(node)
    raise ValueError("unresolved SQL template output")


def _template_append(text: str, line: int, original: bool, parts: list[str], line_map: list[int]) -> None:
    parts.append(text)
    for char in text:
        line_map.append(line)
        if original and char == "\n":
            line += 1


def _template_render(
    body: list[Any], bindings: dict[str, list[Any]], variants: list[Any], branch: bool = False
) -> list[Any]:
    from jinja2 import nodes

    for statement in body:
        if isinstance(statement, nodes.Output):
            for expression in statement.nodes:
                original = isinstance(expression, nodes.TemplateData)
                text = expression.data if original else str(_template_literal(expression, bindings))
                for parts, line_map in variants:
                    _template_append(text, expression.lineno, original, parts, line_map)
        elif isinstance(statement, nodes.If):
            bodies = [statement.body, *(item.body for item in statement.elif_), statement.else_]
            expanded = []
            for parts, line_map in variants:
                for alternative in bodies:
                    expanded.extend(
                        _template_render(alternative, dict(bindings), [(parts.copy(), line_map.copy())], True)
                    )
                    if len(expanded) > 64:
                        raise ValueError("SQL template branch limit exceeded")
            variants = expanded
        elif isinstance(statement, nodes.Assign):
            if branch or not isinstance(statement.target, nodes.Name) or statement.target.name in bindings:
                raise ValueError("unresolved SQL template assignment")
            _template_literal(statement.node, bindings)
            bindings[statement.target.name] = [statement.node]
        else:
            raise ValueError("unresolved SQL template statement")
    return variants


def sql_template_sources(source: str) -> list[tuple[str, list[int]]]:
    from jinja2 import nodes

    tree = parsed_template(source)
    for call in tree.find_all(nodes.Call):
        _template_call(call)
    if next(tree.find_all(nodes.Filter), None) is not None:
        raise ValueError("unresolved SQL template filter")
    return [("".join(parts), line_map) for parts, line_map in _template_render(tree.body, {}, [([], [])])]


def groovy_payloads(path: str, source: str) -> list[tuple[int, str, str, str, str]]:
    from pygments.lexers import get_lexer_by_name
    from pygments.token import Comment, Name, Operator, String, Text

    tokens = [
        (offset, token, text)
        for offset, token, text in get_lexer_by_name("groovy").get_tokens_unprocessed(source)
        if token not in Text.Whitespace and token not in Comment
    ]
    result = []
    for index, (_, token, text) in enumerate(tokens):
        if (
            token in String
            and index
            and tokens[index - 1][2] == "."
            and text.strip("\"'") in {"sh", "execute", "bat", "powershell", "pwsh"}
        ):
            raise ValueError("unresolved quoted Groovy process callee")
        if token in Name and text in {"execute", "ProcessBuilder", "bat", "powershell", "pwsh"}:
            raise ValueError(f"unresolved Groovy process carrier: {text}")
        if token not in Name or text != "sh":
            continue
        cursor = index + 1
        parenthesized = cursor < len(tokens) and tokens[cursor][2] == "("
        if parenthesized:
            cursor += 1
        if cursor < len(tokens) and tokens[cursor][2] == "script:":
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor][1] not in String:
            raise ValueError("unresolved Groovy sh source")
        offset, _, value = tokens[cursor]
        delimiter = next((quote for quote in ("'''", '"""', "'", '"') if value.startswith(quote)), None)
        if delimiter is None or not value.endswith(delimiter):
            raise ValueError("unresolved Groovy sh literal")
        body = value[len(delimiter) : -len(delimiter)]
        if "\\" in body or delimiter.startswith('"') and "$" in body:
            raise ValueError("unresolved Groovy sh escapes or interpolation")
        if (
            cursor + 1 < len(tokens)
            and tokens[cursor + 1][1] in Operator
            and tokens[cursor + 1][2] not in {")", "}", ";", "]", ","}
        ):
            raise ValueError("unresolved Groovy sh expression")
        if cursor + 1 < len(tokens) and tokens[cursor + 1][2] == ",":
            raise ValueError("unresolved Groovy sh option arguments")
        if parenthesized and (cursor + 1 >= len(tokens) or tokens[cursor + 1][2] != ")"):
            raise ValueError("unresolved Groovy sh call boundary")
        line = source[: offset + len(delimiter)].count("\n") + 1
        result.append((line, path + ".sh", body, "bash", f"groovy:sh:{index}"))
    return result


def template_data_spans(source: str) -> list[tuple[int, int]]:
    from jinja2 import Environment

    cursor = 0
    result = []
    for _, token, value in Environment().lex(source):
        start = source.find(value, cursor)
        if start < 0:
            raise ValueError("unresolved HTML template source mapping")
        cursor = start + len(value)
        if token == "data":
            result.append((start, cursor))
    return result
