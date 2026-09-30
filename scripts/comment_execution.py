from __future__ import annotations

import ast
from collections import defaultdict


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
            if not bound and node.id in {"exec", "eval", "compile"}:
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
        if (
            actor
            in {
                "subprocess.run",
                "subprocess.call",
                "subprocess.check_call",
                "subprocess.check_output",
                "subprocess.Popen",
            }
            and node.args
        ):
            value = self.dereference(node.args[0])
            if isinstance(value, (ast.List, ast.Tuple)):
                return self.process_payload(value.elts)
            if any(
                keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            ):
                return node.args[0], "bash", self.literal(node.args[0])
        return None

    def process_payload(self, args: list[ast.expr]) -> tuple[ast.AST, str, str | None] | None:
        if not args:
            return None
        words = [self.literal(arg) for arg in args]
        program = words[0]
        if self.actor(args[0]) == "sys.executable":
            program = "python"
        if program == "uv":
            index = next((index for index, word in enumerate(words) if word and word.startswith("python")), None)
            if index is None:
                return None
            args, words, program = args[index:], words[index:], words[index]
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
            }.get(program or "")
        )
        flag = next(
            (index for index, word in enumerate(words[1:], 1) if word in {"-c", "-e", "--eval", "--command", "-lc"}),
            None,
        )
        if flag is not None and flag + 1 < len(args) and (language or program is None):
            return args[flag + 1], language or "unsupported", words[flag + 1]
        return None
