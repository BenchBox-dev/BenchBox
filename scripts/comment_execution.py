from __future__ import annotations

import ast
from collections import defaultdict

from comment_payloads import command_words, inline_source_index


class PythonBindings:
    def __init__(self, tree: ast.AST) -> None:
        self.parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        self.bindings: dict[tuple[ast.AST | None, str], list[ast.AST | str | None]] = defaultdict(list)
        for node in ast.walk(tree):
            scope = self.scope(node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                parent = self.parents.get(node)
                value = parent.value if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) else None
                self.bindings[scope, node.id].append(value)
            elif isinstance(node, ast.arg):
                self.bindings[scope, node.arg].append(None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bindings[scope, node.name].append(None)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    module = node.module if isinstance(node, ast.ImportFrom) else alias.name
                    actor = f"{module}.{alias.name}" if isinstance(node, ast.ImportFrom) else f"module:{module}"
                    self.bindings[scope, name].append(actor)

    def scope(self, node: ast.AST) -> ast.AST | None:
        node = self.parents.get(node)
        while node is not None and not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            node = self.parents.get(node)
        return node

    def lookup(self, node: ast.Name) -> tuple[bool, ast.AST | str | None]:
        scope = self.scope(node)
        while scope is not None:
            values = self.bindings.get((scope, node.id), [])
            if values:
                return True, values[0] if len(values) == 1 else None
            scope = self.scope(scope)
        return False, None

    def dereference(self, node: ast.AST, seen: frozenset[ast.AST] = frozenset()) -> ast.AST:
        if node in seen or not isinstance(node, ast.Name):
            return node
        _, value = self.lookup(node)
        return self.dereference(value, seen | {node}) if isinstance(value, ast.AST) else node

    def literal(self, node: ast.AST, seen: frozenset[ast.AST] = frozenset()) -> str | None:
        if node in seen:
            return None
        node = self.dereference(node)
        if node in seen:
            return None
        seen |= {node}
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.literal(node.left, seen), self.literal(node.right, seen)
            return left + right if left is not None and right is not None else None
        return None

    def actor(self, node: ast.AST, seen: frozenset[ast.AST] = frozenset()) -> str | None:
        if node in seen:
            return None
        if isinstance(node, ast.Name):
            bound, value = self.lookup(node)
            if not bound and node.id in {"exec", "eval", "compile", "str"}:
                return "builtins." + node.id
            if isinstance(value, str):
                return value
            if isinstance(value, ast.AST):
                return self.actor(value, seen | {node})
        if isinstance(node, ast.Attribute):
            owner = self.actor(node.value, seen | {node})
            if owner and owner.startswith("module:"):
                return owner.removeprefix("module:") + "." + node.attr
        return None

    def payload(self, node: ast.Call) -> tuple[ast.AST, str, str | None] | None:
        actor = self.actor(node.func)
        if actor in {"builtins.exec", "builtins.eval", "builtins.compile"} and node.args:
            value = self.dereference(node.args[0])
            if isinstance(value, ast.Call) and self.actor(value.func) == "builtins.compile":
                return None
            return node.args[0], "python", self.literal(node.args[0])
        if actor in {
            "subprocess.run",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
            "subprocess.Popen",
        }:
            command = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "args"), None)
            if command is None:
                return None
            value = self.dereference(command)
            if isinstance(value, (ast.List, ast.Tuple)):
                return self.process_payload(value.elts)
            if any(
                keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            ):
                return command, "bash", self.literal(command)
        return None

    def path_kind(self, node: ast.AST, seen: frozenset[ast.AST] = frozenset()) -> str | None:
        node = self.dereference(node)
        if node in seen:
            return None
        seen |= {node}
        if isinstance(node, ast.Call):
            if self.actor(node.func) == "pathlib.Path":
                value = self.literal(node.args[0]) if len(node.args) == 1 and not node.keywords else None
                return "absolute" if value and value.startswith("/") else "relative"
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"resolve", "absolute"}
                and not node.args
                and not node.keywords
                and self.path_kind(node.func.value, seen) is not None
            ):
                return "absolute"
            return None
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return self.path_kind(node.value, seen)
        if isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "parents"
                and isinstance(node.slice, ast.Constant)
                and type(node.slice.value) is int
            ):
                return self.path_kind(node.value.value, seen)
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and self.literal(node.right) is not None:
            return self.path_kind(node.left, seen)
        return None

    def command_word(self, node: ast.AST) -> str | None:
        literal = self.literal(node)
        if literal is not None:
            return literal
        value = self.dereference(node)
        if (
            isinstance(value, ast.Call)
            and self.actor(value.func) == "builtins.str"
            and len(value.args) == 1
            and not value.keywords
        ):
            path = self.dereference(value.args[0])
            if isinstance(path, ast.BinOp) and isinstance(path.op, ast.Div) and self.path_kind(path) == "absolute":
                suffix = self.literal(path.right)
                basename = suffix.replace("\\", "/").rsplit("/", 1)[-1] if suffix else ""
                if basename and not basename.startswith("-"):
                    return "/" + basename
        return None

    def process_payload(self, args: list[ast.expr]) -> tuple[ast.AST, str, str | None] | None:
        if not args:
            return None
        words = ["python" if self.actor(arg) == "sys.executable" else self.command_word(arg) for arg in args]
        symbolic_operands = [arg for arg in args if self.actor(arg) == "sys.executable"]
        program = words[0]
        name = program.rsplit("/", 1)[-1] if program else None
        if name in {"env", "uv"}:
            try:
                normalized = command_words(words)
            except ValueError:
                return args[0], "unsupported", None
            if normalized == words[-len(normalized) :]:
                args = args[-len(normalized) :]
            else:
                expanded_args = []
                for word in normalized:
                    origin = next(
                        (arg for arg, value in zip(args, words, strict=True) if value == word),
                        args[0],
                    )
                    expanded_args.append(
                        origin
                        if self.actor(origin) == "sys.executable" or self.literal(origin) is None
                        else ast.copy_location(ast.Constant(value=word), origin)
                    )
                args = expanded_args
            words = normalized
            program = words[0]
            name = program.rsplit("/", 1)[-1]
        if any(arg not in args for arg in symbolic_operands):
            return args[0], "unsupported", None
        words = [self.command_word(arg) for arg in args]
        if self.actor(args[0]) == "sys.executable":
            words[0] = "python"
        program = words[0]
        name = program.rsplit("/", 1)[-1] if program else None
        language = (
            "python"
            if program and program.rsplit("/", 1)[-1].startswith("python")
            else {
                "node": "javascript",
                "sh": "bash",
                "bash": "bash",
                "zsh": "bash",
                "psql": "sql",
                "duckdb": "sql",
            }.get(name or "")
        )
        if language is None and program is not None:
            return None
        return self.inline_process_payload(args, words, language)

    def inline_process_payload(
        self, args: list[ast.expr], words: list[str | None], language: str | None
    ) -> tuple[ast.AST, str, str | None] | None:
        try:
            index = inline_source_index(words, language)
        except ValueError:
            return args[0], "unsupported", None
        if index is not None:
            return args[index], language or "unsupported", self.literal(args[index])
        return None
