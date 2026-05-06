#!/usr/bin/env python3
"""Triage and report on blind-spot findings.

Subcommands::

    list [--status STATUS] [--kind KIND]    Show matching findings (default: open).
    show <id>                               Print one finding (frontmatter + body).
    report                                  Counts by status + kind, oldest open first.
    triage <id> --action ACTION [...]       Stamp frontmatter to record triage outcome.
        --action dismiss [--reason "..."]
        --action actioned [--reason "..."]
        --action actionable --reason "..."
        --action promote --todo-id <slug>

Triage edits only the frontmatter and appends one line under a
``## Triage log`` section. Triage does NOT author TODO files —
``promote`` records the link to a TODO id you authored separately
(see ``_project/TODO_ENTRY_TEMPLATE.yaml``).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as _date, datetime
from pathlib import Path

import yaml

ALLOWED_STATUS = {"open", "actionable", "actioned", "dismissed", "merged-to-todo"}
ACTION_TO_STATUS = {
    "dismiss": "dismissed",
    "actioned": "actioned",
    "actionable": "actionable",
    "promote": "merged-to-todo",
}
REQUIRES_REASON = {"actionable"}
FINDING_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
TRIAGE_LOG_HEADING_RE = re.compile(r"(?m)^## Triage log\s*$")
SECTION_HEADING_RE = re.compile(r"(?m)^## .+$")


def normalize_newlines(text: str) -> str:
    """Normalize markdown line endings before parsing or rewriting."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def find_blind_spots_dir(start: Path) -> Path:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / "_project" / "blind-spots"
        if candidate.is_dir():
            return candidate
    print("error: could not locate _project/blind-spots/", file=sys.stderr)
    sys.exit(2)


def split_frontmatter(text: str) -> tuple[dict, str, str]:
    """Return (data, raw_frontmatter, body)."""
    text = normalize_newlines(text)
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("file does not start with a YAML frontmatter block")
    raw = m.group(1)
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    body = text[m.end() :]
    return data, raw, body


def load_findings(bs_dir: Path) -> list[tuple[Path, dict, str]]:
    """Load every finding (skipping README). Returns [(path, data, body), ...]."""
    out: list[tuple[Path, dict, str]] = []
    for path in sorted(bs_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            data, _raw, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, yaml.YAMLError) as exc:
            print(f"warning: skipping {path.name}: {exc}", file=sys.stderr)
            continue
        out.append((path, data, body))
    return out


def find_one(bs_dir: Path, finding_id: str) -> tuple[Path, dict, str, str]:
    if not FINDING_ID_RE.match(finding_id):
        print(f"error: invalid finding id '{finding_id}'", file=sys.stderr)
        sys.exit(2)

    root = bs_dir.resolve()
    candidate = (bs_dir / f"{finding_id}.md").resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        print(f"error: invalid finding id '{finding_id}'", file=sys.stderr)
        sys.exit(2)

    if not candidate.exists():
        print(f"error: no finding with id '{finding_id}'", file=sys.stderr)
        sys.exit(2)
    try:
        data, raw, body = split_frontmatter(candidate.read_text(encoding="utf-8"))
    except (ValueError, yaml.YAMLError) as exc:
        print(f"error: finding '{finding_id}' is malformed: {exc}", file=sys.stderr)
        sys.exit(1)
    return candidate, data, raw, body


def extract_title(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "(untitled)"


def fmt_date(value) -> str:
    if isinstance(value, _date):
        return value.isoformat()
    return str(value)


def cmd_list(bs_dir: Path, args: argparse.Namespace) -> int:
    findings = load_findings(bs_dir)
    findings.sort(key=lambda t: fmt_date(t[1].get("date", "")))

    rows = []
    for path, data, body in findings:
        if args.status and data.get("status") != args.status:
            continue
        if args.kind and data.get("finding_kind") != args.kind:
            continue
        rows.append(
            (
                fmt_date(data.get("date", "????-??-??")),
                str(data.get("status", "?")),
                str(data.get("finding_kind", "?")),
                str(data.get("id", path.stem)),
                extract_title(body),
            )
        )

    if not rows:
        filt = []
        if args.status:
            filt.append(f"status={args.status}")
        if args.kind:
            filt.append(f"kind={args.kind}")
        suffix = f" matching {', '.join(filt)}" if filt else ""
        print(f"no findings{suffix}.")
        return 0

    w_date = max(len(r[0]) for r in rows)
    w_status = max(len(r[1]) for r in rows)
    w_kind = max(len(r[2]) for r in rows)
    w_id = max(len(r[3]) for r in rows)
    for d, st, k, fid, title in rows:
        print(f"{d:<{w_date}}  {st:<{w_status}}  {k:<{w_kind}}  {fid:<{w_id}}  {title}")
    print(f"\n{len(rows)} finding(s).")
    return 0


def cmd_show(bs_dir: Path, args: argparse.Namespace) -> int:
    path, data, _raw, body = find_one(bs_dir, args.id)
    print(f"# {path.relative_to(bs_dir.parent.parent)}\n")
    print("---")
    print(yaml.safe_dump(data, sort_keys=False).rstrip())
    print("---")
    print(body.rstrip())
    return 0


def cmd_report(bs_dir: Path, args: argparse.Namespace) -> int:
    findings = load_findings(bs_dir)
    if not findings:
        print("no findings recorded yet.")
        return 0

    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    active_findings: list[tuple[str, dict, str]] = []
    for path, data, body in findings:
        st = str(data.get("status", "?"))
        kn = str(data.get("finding_kind", "?"))
        by_status[st] = by_status.get(st, 0) + 1
        by_kind[kn] = by_kind.get(kn, 0) + 1
        if st in {"open", "actionable"}:
            active_findings.append((fmt_date(data.get("date", "")), data, body))

    print(f"Total findings: {len(findings)}\n")

    print("By status:")
    for st in sorted(by_status):
        print(f"  {st:<16} {by_status[st]:>4}")
    print()

    print("By finding_kind:")
    for kn in sorted(by_kind):
        print(f"  {kn:<16} {by_kind[kn]:>4}")
    print()

    if active_findings:
        active_findings.sort(key=lambda t: t[0])
        print(f"Oldest active ({min(args.top, len(active_findings))} of {len(active_findings)}):")
        for d, data, body in active_findings[: args.top]:
            st = str(data.get("status", "?"))
            print(f"  {d}  [{st}]  {data.get('id', '?')}  — {extract_title(body)}")
    else:
        print("No active findings.")

    print("\nTriage with: sweep_blind_spots.py triage <id> --action {dismiss|actioned|actionable|promote} [...]")
    return 0


def render_scalar_field(field: str, value: str) -> str:
    """Render one simple YAML scalar assignment without reformatting the block."""
    rendered = yaml.safe_dump({field: value}, sort_keys=False, width=10_000).strip()
    if "\n" in rendered:
        raise ValueError(f"{field} must render as a single YAML line")
    return rendered


def replace_frontmatter_field(raw: str, field: str, value: str) -> str:
    line = render_scalar_field(field, value)
    field_re = re.compile(rf"^{re.escape(field)}\s*:")
    lines = raw.splitlines()
    for start, existing in enumerate(lines):
        if not field_re.match(existing):
            continue
        end = start + 1
        while end < len(lines):
            next_line = lines[end]
            if next_line and not next_line[0].isspace():
                break
            end += 1
        return "\n".join([*lines[:start], line, *lines[end:]])
    return raw.rstrip() + f"\n{line}"


def stamp_frontmatter(path: Path, raw_frontmatter: str, body: str, new_status: str, todo_id: str | None) -> None:
    """Rewrite only status/todo_id while preserving the rest of the frontmatter."""
    new_raw = replace_frontmatter_field(raw_frontmatter, "status", new_status)
    if todo_id is not None:
        new_raw = replace_frontmatter_field(new_raw, "todo_id", todo_id)
    new_text = f"---\n{new_raw}\n---\n{body}"
    path.write_text(new_text, encoding="utf-8")


def append_triage_log(path: Path, line: str) -> None:
    text = normalize_newlines(path.read_text(encoding="utf-8"))
    match = TRIAGE_LOG_HEADING_RE.search(text)
    if match is None:
        new_text = text.rstrip() + f"\n\n## Triage log\n\n- {line}\n"
    else:
        next_section = SECTION_HEADING_RE.search(text, match.end())
        insert_at = next_section.start() if next_section else len(text)
        before = text[:insert_at].rstrip()
        after = text[insert_at:].lstrip("\n")
        if before.endswith("## Triage log"):
            before += "\n"
        new_text = f"{before}\n- {line}\n"
        if after:
            new_text += f"\n{after}"
    path.write_text(new_text, encoding="utf-8")


def cmd_triage(bs_dir: Path, args: argparse.Namespace) -> int:
    new_status = ACTION_TO_STATUS[args.action]

    if args.action == "promote":
        if args.reason:
            print("error: --reason cannot be combined with --action promote", file=sys.stderr)
            return 2
        if not args.todo_id:
            print("error: --todo-id is required for --action promote", file=sys.stderr)
            return 2
        todo_id: str | None = args.todo_id
        log_line = f"{datetime.now().date().isoformat()}: promoted to TODO `{todo_id}`"
    else:
        if args.todo_id:
            print("error: --todo-id is only valid with --action promote", file=sys.stderr)
            return 2
        if args.action in REQUIRES_REASON and not (args.reason and args.reason.strip()):
            print(f"error: --reason is required for --action {args.action}", file=sys.stderr)
            return 2
        todo_id = None
        reason = args.reason or ""
        suffix = f" — {reason}" if reason else ""
        log_line = f"{datetime.now().date().isoformat()}: {args.action}{suffix}"

    path, _data, raw, body = find_one(bs_dir, args.id)
    stamp_frontmatter(path, raw, body, new_status, todo_id)
    append_triage_log(path, log_line)
    print(f"OK   {path.relative_to(bs_dir.parent.parent)} → status={new_status}")
    if todo_id:
        print(f"     todo_id={todo_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep blind-spot findings.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list findings")
    p_list.add_argument("--status", choices=sorted(ALLOWED_STATUS), default="open")
    p_list.add_argument("--kind", default=None)

    p_show = sub.add_parser("show", help="show one finding")
    p_show.add_argument("id")

    p_report = sub.add_parser("report", help="aggregate report")
    p_report.add_argument("--top", type=int, default=10, help="oldest-N to surface")

    p_triage = sub.add_parser("triage", help="record a triage outcome")
    p_triage.add_argument("id")
    p_triage.add_argument("--action", choices=sorted(ACTION_TO_STATUS), required=True)
    p_triage.add_argument("--reason", default=None)
    p_triage.add_argument("--todo-id", dest="todo_id", default=None)

    args = parser.parse_args()
    bs_dir = find_blind_spots_dir(Path.cwd())

    if args.cmd == "list":
        return cmd_list(bs_dir, args)
    if args.cmd == "show":
        return cmd_show(bs_dir, args)
    if args.cmd == "report":
        return cmd_report(bs_dir, args)
    if args.cmd == "triage":
        return cmd_triage(bs_dir, args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
