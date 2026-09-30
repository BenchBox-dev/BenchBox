from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml
from comment_payloads import nested_sources
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Error


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str
    symbol: str = ""
    payload: str = ""

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return self.path, self.kind, self.symbol, self.text, self.payload


LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".sql": "sql",
    ".sh": "bash",
    ".zsh": "bash",
    ".bash": "bash",
    ".mk": "make",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".css": "css",
    ".html": "html",
    ".htm": "html",
    ".jinja": "html+jinja",
    ".j2": "html+jinja",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".ipynb": "notebook",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".ps1": "powershell",
    ".tf": "terraform",
    ".r": "r",
    ".tpl": "unsupported",
    ".jsonc": "json",
    ".json5": "json5",
    ".lua": "unsupported",
    ".scala": "unsupported",
    ".svelte": "unsupported",
    ".vue": "unsupported",
}


def language(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name in {".gitignore", ".gitattributes", ".dockerignore"}:
        return "line-config"
    if name == ".importlinter":
        return "ini"
    if name.startswith(".env"):
        return "bash"
    if name == "skill-sync.conf":
        return "line-config"
    if path == "tools/skill-sync":
        return "bash"
    if name.lower() in {"makefile", "gnumakefile"} or name.startswith("Makefile."):
        return "make"
    if name.startswith("Dockerfile"):
        return "docker"
    if path.endswith((".md", ".rst")) and not path.startswith(("_project/", "_blog/")):
        return "examples"
    if not PurePosixPath(path).suffix and path.startswith(("scripts/", "tools/", "_project/scripts/")):
        return "unsupported"
    suffix = PurePosixPath(path).suffix.lower()
    if (
        suffix not in LANGUAGES
        and suffix not in {".json", ".lock", ".md", ".txt", ".csv", ".svg", ".png", ".gitkeep"}
        and path.startswith(("scripts/", "tools/", "_project/scripts/"))
    ):
        return "unsupported"
    return LANGUAGES.get(suffix)


def source_language(path: str, source: str) -> str | None:
    if source.startswith("#!"):
        interpreter = source.splitlines()[0].split()[-1].split("/")[-1]
        return (
            "python"
            if interpreter.startswith("python")
            else {"sh": "bash", "bash": "bash", "node": "javascript"}.get(interpreter, "unsupported")
        )
    return language(path)


def sql_comments(source: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    pos = 0
    while pos < len(source):
        start = pos
        char = source[pos]
        dollar = re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", source[pos:]) if char == "$" else None
        if dollar:
            marker = dollar.group()
            end = source.find(marker, pos + len(marker))
            if end < 0:
                raise ValueError("unterminated SQL dollar string")
            pos = end + len(marker)
        elif char in "'\"`[" and not (
            char == "["
            and re.search(r"(?:\bARRAY|[\w)\]])\s*$", source[:pos], re.I)
            and not re.search(r"\b(?:SELECT|FROM|JOIN|AS|BY|WHERE)\s*$", source[:pos], re.I)
        ):
            closing = "]" if char == "[" else char
            pos += 1
            while pos < len(source):
                if source[pos] == "\\" and char != "[":
                    pos += 2
                elif source[pos] == closing:
                    pos += 1
                    if pos < len(source) and source[pos] == closing:
                        pos += 1
                    else:
                        break
                else:
                    pos += 1
            else:
                raise ValueError("unterminated SQL quoted value")
        elif source.startswith("--", pos) or (
            char == "#"
            and not source.startswith(("#>", "#-", "##"), pos)
            and not re.search(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s*$", source[:pos], re.I)
        ):
            end = source.find("\n", pos)
            pos = len(source) if end < 0 else end
            result.append((start, source[start:pos]))
        elif source.startswith("/*", pos):
            pos += 2
            depth = 1
            while pos < len(source) and depth:
                if source.startswith("/*", pos):
                    depth += 1
                    pos += 2
                elif source.startswith("*/", pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            if depth:
                raise ValueError("unterminated SQL comment")
            result.append((start, source[start:pos]))
        else:
            pos += 1
    return result


def python_findings(path: str, source: str) -> list[Finding]:
    tree = ast.parse(source)
    result: list[Finding] = []
    scopes: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, symbol: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol = f"{symbol}.{node.name}".strip(".")
            scopes.append((node.lineno, node.end_lineno or node.lineno, symbol))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            result.append(Finding(path, node.lineno, "docstring", node.value.value, symbol))
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and any(
            (isinstance(child, ast.Attribute) and child.attr == "__doc__" and isinstance(child.ctx, ast.Store))
            or (
                isinstance(child, ast.Subscript)
                and isinstance(child.ctx, ast.Store)
                and isinstance(child.slice, ast.Constant)
                and child.slice.value == "__doc__"
            )
            for child in ast.walk(node)
        ):
            result.append(Finding(path, node.lineno, "runtime-docstring", ast.unparse(node), symbol))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "__doc__"
        ):
            result.append(Finding(path, node.lineno, "runtime-docstring", ast.unparse(node), symbol))
        sql_text = ""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql_text = node.value
        elif isinstance(node, ast.JoinedStr):
            sql_text = "".join(
                str(value.value) if isinstance(value, ast.Constant) else "__expression__" for value in node.values
            )
        if re.match(
            r"\s*(?:--[^\n]*\n|/\*.*?\*/\s*)*(?:SELECT|WITH|CREATE|INSERT|UPDATE|DELETE|ALTER|DROP|VALUES|EXPLAIN|MERGE|COPY|SHOW|DESCRIBE|TRUNCATE|GRANT|REVOKE)\b",
            sql_text,
            re.I | re.S,
        ):
            try:
                result.extend(
                    Finding(path, node.lineno + sql_text[:offset].count("\n"), "comment", text, symbol, sql_text)
                    for offset, text in sql_comments(sql_text)
                )
            except ValueError as exc:
                result.append(Finding(path, node.lineno, "payload-error", str(exc), symbol, sql_text))
        for child in ast.iter_child_nodes(node):
            visit(child, symbol)

    visit(tree, "")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            symbol = next((name for start, end, name in reversed(scopes) if start <= token.start[0] <= end), "")
            result.append(Finding(path, token.start[0], "comment", token.string, symbol))
    return result


def javascript_key(path: str, source: str) -> str:
    suffix = ".tsx" if path.endswith((".tsx", ".jsx")) else ".ts"
    return hashlib.sha256(source.encode()).hexdigest() + suffix


def javascript_requests(path: str, source: str, lang: str) -> dict[str, str]:
    if source.startswith("#!"):
        lang = source_language(path, source) or lang
    if lang == "javascript":
        return {javascript_key(path, source): source}
    result = {}
    try:
        for _, child_path, text, child_lang, _ in nested_sources(path, source, lang):
            result.update(javascript_requests(child_path, text, child_lang))
    except (ValueError, KeyError, TypeError, yaml.YAMLError):
        return {}
    return result


def scan(path: str, source: str, lang: str, js_results: dict[str, list[dict]] | None = None) -> list[Finding]:
    try:
        if source.startswith("#!"):
            lang = source_language(path, source) or lang
        if lang == "python":
            return python_findings(path, source)
        if lang == "sql":
            return [
                Finding(path, source[:offset].count("\n") + 1, "comment", text) for offset, text in sql_comments(source)
            ]
        if lang == "javascript":
            key = javascript_key(path, source)
            if js_results is None or key not in js_results:
                raise ValueError("TypeScript parser result missing")
            return [Finding(path, row["line"], row["kind"], row["text"]) for row in js_results[key]]
        nested = [
            Finding(path, start + f.line - 1, f.kind, f.text, f"{symbol}:{f.symbol}")
            for start, child_path, text, child_lang, symbol in nested_sources(path, source, lang)
            for f in scan(child_path, text, child_lang, js_results)
        ]
        if lang in {"notebook", "examples"}:
            return nested
        if lang in {"html", "html+jinja"}:
            source = re.sub(
                r"(<(?:script|style)\b[^>]*>)(.*?)(</(?:script|style)\s*>)",
                lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(2)) + m.group(3),
                source,
                flags=re.I | re.S,
            )
        if lang == "unsupported":
            raise ValueError("source language has no registered adapter")
        if lang == "line-config":
            return [
                Finding(path, index, "comment", text)
                for index, text in enumerate(source.splitlines(), 1)
                if text.startswith("#")
            ]
        result = nested
        for offset, token, text in get_lexer_by_name(lang).get_tokens_unprocessed(source):
            if token in Error:
                raise ValueError(f"unrecognized {lang} syntax at line {source[:offset].count(chr(10)) + 1}")
            if token in Comment:
                if token in Comment.Preproc:
                    continue
                if lang == "bash" and offset and source[offset - 1] not in " \t\r\n;|&()":
                    continue
                result.append(Finding(path, source[:offset].count("\n") + 1, "comment", text.rstrip("\r\n")))
        return result
    except (SyntaxError, tokenize.TokenError, IndentationError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        return [Finding(path, 1, "coverage-error", str(exc))]
