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


def _wrapper_tail(words: list[str], *, value_options: set[str], flag_options: set[str], wrapper: str) -> list[str]:
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--":
            return words[index + 1 :]
        if word in {"-S", "--split-string"} and word in value_options:
            if index + 1 >= len(words):
                raise ValueError(f"{wrapper} option requires an operand: {word}")
            if any(token in words[index + 1] for token in ("#", "\\c", "$")):
                raise ValueError(f"unsupported {wrapper} split-string syntax")
            try:
                split_words = shlex.split(words[index + 1])
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
            if index + 1 >= len(words):
                raise ValueError(f"{wrapper} option requires an operand: {word}")
            index += 2
            continue
        if word in flag_options:
            index += 1
            continue
        if word.startswith("-"):
            raise ValueError(f"unregistered {wrapper} option: {word}")
        return words[index:]
    return []


def stdin_language(words: list[str]) -> str | None:
    if not words:
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
        while tail and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tail[0]):
            tail = tail[1:]
        return stdin_language(tail)
    if name == "uv" and words[1:2] == ["run"]:
        return stdin_language(
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
                    "--module",
                },
                wrapper="uv run",
            )
        )
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
