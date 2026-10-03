from __future__ import annotations

import ast
import re
from collections import defaultdict

from comment_payloads import command_words, inline_source_index

REVIEWED_PROCESS_ARGV: dict[tuple[str, str], str] = {
    (
        "_project/scripts/build_joinorder_data.py",
        "[container_cli(), 'rm', '-f', container_name]",
    ): "container_cli() returns BENCHBOX_CONTAINER_CLI or docker; this call removes a container",
    (
        "benchbox/core/tpcds/generator/runner.py",
        "[str(self.dsdgen_exe), '-verbose', '-force', '-terminate', 'n', '-scale', str(self.scale_factor), '-child', str(chunk_id), '-parallel', str(self.parallel)]",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpcds/generator/runner.py",
        "[str(self.dsdgen_exe), '-verbose', '-force', '-terminate', 'n', '-scale', str(self.scale_factor)]",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpcds/generator/streaming.py",
        "[str(self.dsdgen_exe), '-verbose' if self.verbose else '-quiet', '-force', '-terminate', 'n', '-scale', str(self.scale_factor), '-table', parent_table, '-child', str(chunk_id), '-parallel', str(self.parallel)]",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpcds/generator/streaming.py",
        "[str(self.dsdgen_exe), '-verbose' if self.verbose else '-quiet', '-force', '-terminate', 'n', '-scale', str(self.scale_factor), '-table', parent_table]",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpcds/generator/streaming.py",
        "[str(self.dsdgen_exe), '-verbose' if self.verbose else '-quiet', '-force', '-terminate', 'n', '-scale', str(self.scale_factor), '-table', table_name, '-child', str(chunk_id), '-parallel', str(self.parallel), '-FILTER', 'Y']",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpcds/generator/streaming.py",
        "[str(self.dsdgen_exe), '-verbose' if self.verbose else '-quiet', '-force', '-terminate', 'n', '-scale', str(self.scale_factor), '-table', table_name]",
    ): "self.dsdgen_exe is the bundled TPC-DS dsdgen data generator binary",
    (
        "benchbox/core/tpch/generator.py",
        "[str(dbgen_exe), '-vf', '-s', str(self.scale_factor)]",
    ): "the executable is the bundled TPC-H dbgen data generator binary",
    (
        "benchbox/core/tpch/generator.py",
        "[str(self.dbgen_exe), '-vf', '-s', str(self.scale_factor), '-S', str(chunk_id), '-C', str(self.parallel)]",
    ): "the executable is the bundled TPC-H dbgen data generator binary",
    (
        "benchbox/core/tpch/generator.py",
        "[str(self.dbgen_exe), '-vf', '-s', str(self.scale_factor)]",
    ): "the executable is the bundled TPC-H dbgen data generator binary",
    (
        "benchbox/core/tpch/generator.py",
        "[str(self.dbgen_exe), '-z', '-q', '-f', '-s', str(self.scale_factor), '-T', table_code]",
    ): "the executable is the bundled TPC-H dbgen data generator binary",
    (
        "benchbox/core/tpch/streams.py",
        "[str(qgen_exe), '-p', str(stream_id + 1), '-s', str(self.scale_factor), '-r', str(self.rng_seed + stream_id), '-o', str(work_dir)]",
    ): "qgen_exe is the bundled TPC-H qgen query generator binary",
    (
        "scripts/_render_blog_charts.py",
        "['uv', 'run', '--project', str(ROOT), *cmd]",
    ): "uv runs the textcharts CLI; every CHARTS command starts with textcharts",
    (
        "scripts/capture_chart_images.py",
        "[str(CHROME), '--headless=new', '--disable-gpu', '--no-sandbox', '--disable-web-security', f'--window-size={width},{height}', f'--screenshot={out_path}', '--hide-scrollbars', f'file://{tmp_html}']",
    ): "CHROME is the headless Chrome browser binary",
    (
        "scripts/capture_release_heroes.py",
        "[str(CHROME), '--headless=new', '--disable-gpu', '--no-sandbox', '--disable-web-security', f'--window-size={width},{height}', f'--screenshot={out_path}', '--hide-scrollbars', '--run-all-compositor-stages-before-draw', '--virtual-time-budget=8000', target]",
    ): "CHROME is the headless Chrome browser binary",
    (
        "scripts/heavy_tier_needed.py",
        "[sys.executable, '-I', '-S', str(root / PREDICATE_REPO_PATH), '--stdin', '--format', 'github-output']",
    ): "Python runs the soundness predicate script file; no -c or -m source",
    (
        "scripts/run_comment_policy.py",
        "['node', '--test', str(root / 'tests/unit/scripts/test_comment_syntax_js.cjs')]",
    ): "node --test runs the native parser test file; no inline source",
    (
        "scripts/validate_todo_indexes.py",
        "[sys.executable, str(repo_root / '_project' / 'scripts' / script), '--strict']",
    ): "Python runs the named index-check script files; no -c or -m source",
    (
        "scripts/verify_mcp_conformance.py",
        "['node', str(conformance), 'server', '--url', url, '--scenario', scenario, '--spec-version', protocol_version]",
    ): "node runs the MCP conformance CLI script file; no inline source",
}


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
                if all(isinstance(value, str) for value in values) and len(set(values)) == 1:
                    return True, values[0]
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

    def reviewed_argv(self, path: str, node: ast.Call) -> bool:
        command = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "args"), None)
        return command is not None and (path, ast.unparse(self.dereference(command))) in REVIEWED_PROCESS_ARGV

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

    def html_path(self, node: ast.AST, seen: frozenset[tuple[ast.AST | None, str]] = frozenset()) -> bool:
        if isinstance(node, ast.Name):
            scope = self.scope(node)
            while scope is not None and (scope, node.id) not in self.bindings:
                scope = self.scope(scope)
            key = (scope, node.id)
            if key in seen or key not in self.bindings:
                return False
            values = self.bindings[key]
            parameter = isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                argument.arg == node.id
                and argument.annotation is not None
                and self.actor(argument.annotation) == "pathlib.Path"
                for argument in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
            )
            anchored = parameter or any(
                isinstance(value, ast.AST) and self.html_path(value, seen | {key}) for value in values
            )

            def derived(value: ast.AST) -> bool:
                if isinstance(value, ast.Name) and value.id == node.id and self.scope(value) is scope:
                    return anchored
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr in {"resolve", "absolute"}
                    and not value.args
                    and not value.keywords
                ):
                    return derived(value.func.value)
                return self.html_path(value, seen | {key})

            return anchored and all(
                parameter if value is None else isinstance(value, ast.AST) and derived(value) for value in values
            )
        if isinstance(node, ast.Call):
            if self.actor(node.func) == "pathlib.Path":
                return True
            return (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"resolve", "absolute"}
                and not node.args
                and not node.keywords
                and self.html_path(node.func.value, seen)
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.literal(node.right) is not None and self.html_path(node.left, seen)
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return self.html_path(node.value, seen)
        return False

    def html_non_path(self, node: ast.AST) -> bool:
        node = self.dereference(node)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.html_non_path(node.left)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            return False
        scope = self.scope(node.func)
        while scope is not None and (scope, node.func.id) not in self.bindings:
            scope = self.scope(scope)
        if self.bindings.get((scope, node.func.id)) != [None]:
            return False
        return any(
            isinstance(definition, ast.ClassDef)
            and definition.name == node.func.id
            and self.scope(definition) is scope
            and not definition.bases
            and not definition.keywords
            and not definition.decorator_list
            and {method.name for method in definition.body if isinstance(method, ast.FunctionDef)}
            == {"__truediv__", "write_text"}
            and all(
                isinstance(method, ast.FunctionDef)
                and not method.decorator_list
                and not method.args.defaults
                and not method.args.kwonlyargs
                and method.args.vararg is None
                and method.args.kwarg is None
                and len(method.args.args) == 2
                and len(method.body) == 1
                and isinstance(method.body[0], ast.Return)
                and isinstance(method.body[0].value, ast.Name)
                and method.body[0].value.id == method.args.args[0 if method.name == "__truediv__" else 1].arg
                for method in definition.body
            )
            for definition in self.parents
        )

    def html_payload(self, node: ast.Call) -> ast.AST | None:
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "write_text":
            return None
        target = self.dereference(node.func.value)
        leaf = None
        if isinstance(target, ast.BinOp) and isinstance(target.op, ast.Div):
            leaf = self.literal(target.right)
        elif isinstance(target, ast.Call) and self.actor(target.func) == "pathlib.Path" and len(target.args) == 1:
            leaf = self.literal(target.args[0])
        if leaf is None or not leaf.lower().endswith((".html", ".htm")):
            return None
        if not self.html_path(node.func.value):
            return None if self.html_non_path(node.func.value) else node
        data = [kw.value for kw in node.keywords if kw.arg == "data"]
        if (
            any(isinstance(argument, ast.Starred) for argument in node.args)
            or any(keyword.arg is None for keyword in node.keywords)
            or len(node.args) > 4
            or len(data) > 1
            or (node.args and data)
        ):
            return node
        return node.args[0] if node.args else data[0] if data else node

    def path_kind(self, node: ast.AST, seen: frozenset[ast.AST] = frozenset()) -> str | None:
        node = self.dereference(node)
        if node in seen:
            return None
        seen |= {node}
        if isinstance(node, ast.Call):
            if self.actor(node.func) == "pathlib.Path":
                if (
                    len(node.args) == 1
                    and not node.keywords
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "__file__"
                    and self.lookup(node.args[0]) == (False, None)
                ):
                    return "absolute"
                value = self.literal(node.args[0]) if len(node.args) == 1 and not node.keywords else None
                return "absolute" if value and value.startswith("/") else "relative"
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "with_name"
                and len(node.args) == 1
                and not node.keywords
                and self.literal(node.args[0])
            ):
                return self.path_kind(node.func.value, seen)
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
            if (
                isinstance(path, ast.Call)
                and self.actor(path.func) == "pathlib.Path"
                and len(path.args) == 1
                and not path.keywords
                and (self.literal(path.args[0]) or "").startswith("/")
            ):
                return self.literal(path.args[0])
            leaf = None
            if isinstance(path, ast.BinOp) and isinstance(path.op, ast.Div):
                leaf = path.right
            elif isinstance(path, ast.Call) and isinstance(path.func, ast.Attribute) and path.func.attr == "with_name":
                leaf = path.args[0] if path.args else None
            if leaf is not None and self.path_kind(path) == "absolute":
                suffix = self.literal(leaf)
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


def python_html_sources(source: str, tree: ast.AST | None = None) -> list[tuple[int, str | None, str]]:
    tree = ast.parse(source) if tree is None else tree
    bindings = PythonBindings(tree)
    result = []
    for node in ast.walk(tree):
        expression = bindings.html_payload(node) if isinstance(node, ast.Call) else None
        if expression is None:
            continue
        origin = bindings.dereference(expression)
        segment = ast.get_source_segment(source, origin) or ""
        quoted = re.fullmatch(r"""[rRuU]*(?P<quote>["']{3}|["'])(?P<body>.*)(?P=quote)""", segment, re.S)
        text = (
            origin.value
            if isinstance(origin, ast.Constant)
            and isinstance(origin.value, str)
            and quoted is not None
            and quoted.group("body") == origin.value
            else None
        )
        result.append(
            (origin.lineno if text is not None else node.lineno, text, "html-output:" + ast.unparse(node.func.value))
        )
    return result
