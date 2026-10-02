from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

PYTHON_SUFFIXES = {".py", ".pyi"}
SCOPE_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
WORKTREE = "WORKTREE"


@dataclass
class FileReport:
    path: str
    status: str
    comments_removed: int = 0
    docstrings_removed: int = 0
    pass_added: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.status == "ok"


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def read_revision(root: Path, revision: str, path: str) -> bytes | None:
    if revision == WORKTREE:
        target = root / path
        return target.read_bytes() if target.is_file() else None
    result = subprocess.run(["git", "-C", str(root), "show", f"{revision}:{path}"], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    args = ["diff", "--name-only", "--no-renames", "-z", base]
    if head != WORKTREE:
        args.append(head)
    names = git(root, *args).decode().split("\0")
    if head == WORKTREE:
        names += git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    return sorted({name for name in names if name})


def comment_texts(source: bytes) -> list[str]:
    stream = io.BytesIO(source).readline
    return [token.string for token in tokenize.tokenize(stream) if token.type == tokenize.COMMENT]


ENCODING_COOKIE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def protected_lines(source: bytes) -> list[bytes]:
    kept = []
    for index, line in enumerate(source.splitlines()[:2]):
        if (index == 0 and line.startswith(b"#!")) or ENCODING_COOKIE.match(line):
            kept.append(line.strip())
    return kept


def leading_docstring(node: ast.AST) -> ast.Expr | None:
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first
    return None


def docstrings(tree: ast.AST) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = getattr(child, "name", None)
            label = f"{prefix}.{name}" if name and isinstance(child, SCOPE_NODES) else prefix
            if isinstance(child, SCOPE_NODES):
                docstring = leading_docstring(child)
                if docstring is not None:
                    found.append((label, docstring.value.value))
            visit(child, label)

    module_docstring = leading_docstring(tree)
    if module_docstring is not None:
        found.append(("", module_docstring.value.value))
    visit(tree, "")
    return found


class DocstringStripper(ast.NodeTransformer):
    def __init__(self) -> None:
        self.emptied = 0

    def generic_visit(self, node: ast.AST) -> ast.AST:
        visited = super().generic_visit(node)
        if isinstance(visited, SCOPE_NODES) and leading_docstring(visited) is not None:
            del visited.body[0]
            if not visited.body:
                visited.body.append(ast.Pass())
                self.emptied += 1
        return visited


def normalized(tree: ast.AST) -> tuple[str, int]:
    stripper = DocstringStripper()
    stripped = stripper.visit(tree)
    return ast.dump(stripped, include_attributes=False), stripper.emptied


def parse(source: bytes) -> ast.AST:
    return ast.parse(source, type_comments=True)


def compare_python(path: str, base: bytes, head: bytes) -> FileReport:
    report = FileReport(path, "ok")
    try:
        base_tree, head_tree = parse(base), parse(head)
        base_comments, head_comments = Counter(comment_texts(base)), Counter(comment_texts(head))
        base_docs, head_docs = Counter(docstrings(base_tree)), Counter(docstrings(head_tree))
    except (SyntaxError, ValueError, tokenize.TokenError, MemoryError, RecursionError) as exc:
        report.status = "error"
        report.problems.append(f"cannot parse: {exc}")
        return report
    base_dump, base_emptied = normalized(base_tree)
    head_dump, head_emptied = normalized(head_tree)
    if base_dump != head_dump:
        report.status = "drift"
        report.problems.append("the executable syntax tree differs beyond removed docstrings and comments")
    if protected_lines(base) != protected_lines(head):
        report.status = "drift"
        report.problems.append("the shebang or encoding declaration changed")
    added_comments = head_comments - base_comments
    added_docstrings = head_docs - base_docs
    if added_comments:
        report.status = "drift"
        report.problems.append(f"{sum(added_comments.values())} comment(s) not present in the base")
    if added_docstrings:
        report.status = "drift"
        report.problems.append(f"{sum(added_docstrings.values())} docstring(s) not present in the base")
    report.comments_removed = sum((base_comments - head_comments).values())
    report.docstrings_removed = sum((base_docs - head_docs).values())
    report.pass_added = max(base_emptied - head_emptied, 0)
    return report


def compare_file(root: Path, base: str, head: str, path: str, unverified_ok: set[str]) -> FileReport:
    before, after = read_revision(root, base, path), read_revision(root, head, path)
    suffix = Path(path).suffix.lower()
    if before is None:
        return FileReport(path, "drift", problems=["file added; a deletion-only change cannot add files"])
    if after is None:
        return FileReport(path, "drift", problems=["file deleted; a deletion-only change cannot delete files"])
    if suffix in PYTHON_SUFFIXES:
        return compare_python(path, before, after)
    if suffix in unverified_ok:
        return FileReport(path, "skipped")
    return FileReport(path, "unverified", problems=[f"no comparator for {suffix or 'files without a suffix'}"])


def compare(root: Path, base: str, head: str, prefixes: list[str], unverified_ok: set[str]) -> list[FileReport]:
    paths = changed_paths(root, base, head)
    if prefixes:
        paths = [path for path in paths if any(path == prefix or path.startswith(prefix) for prefix in prefixes)]
    return [compare_file(root, base, head, path, unverified_ok) for path in paths]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show that a change only removes comments and docstrings.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default=WORKTREE)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--unverified-ok", action="append", default=[])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        suffixes = {suffix if suffix.startswith(".") else f".{suffix}" for suffix in args.unverified_ok}
        reports = compare(root, args.base, args.head, args.path, {suffix.lower() for suffix in suffixes})
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"comment-parity: {exc}", file=sys.stderr)
        return 2
    for report in reports:
        if not report.clean and report.status != "skipped":
            print(f"{report.path}: {report.status}: {'; '.join(report.problems)}")
    totals = Counter(report.status for report in reports)
    print(
        f"comment-parity: {len(reports)} files, {totals['ok']} ok, {totals['drift']} drift, "
        f"{totals['error']} errors, {totals['unverified']} unverified, {totals['skipped']} skipped; "
        f"{sum(report.comments_removed for report in reports)} comments, "
        f"{sum(report.docstrings_removed for report in reports)} docstrings removed, "
        f"{sum(report.pass_added for report in reports)} bodies left to pass"
    )
    if args.json_out:
        args.json_out.write_text(json.dumps([asdict(report) for report in reports], indent=2) + "\n", encoding="utf-8")
    return int(any(report.status not in {"ok", "skipped"} for report in reports))


if __name__ == "__main__":
    sys.exit(main())
