from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .policy import SEVERITIES

MAX_FINDINGS = 50
MAX_SUMMARY = 4000
MAX_TITLE = 200
MAX_DETAIL = 4000
MAX_PATH = 400

FINDING_KEYS = ("severity", "file", "line", "title", "detail")
VERDICT_KEYS = ("summary", "findings")

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(VERDICT_KEYS),
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(FINDING_KEYS),
                "properties": {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|private[_-]?key)\b(\s*[:=]\s*)"
        r"['\"]?[^\s'\"]{8,}"
    ),
)
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file|data|javascript):[^\s<>()]+|\bwww\.[^\s<>()]+")
_MENTION = re.compile(r"(?<![A-Za-z0-9_`])@(?=[A-Za-z0-9])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
REDACTED = "[redacted]"
LINK_REMOVED = "[link removed]"


class VerdictError(ValueError):
    pass


@dataclass(frozen=True)
class Finding:
    severity: str
    file: str
    line: int
    title: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Verdict:
    summary: str
    findings: tuple[Finding, ...]

    def blocking(self, severities: tuple[str, ...] | list[str]) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.severity in severities)

    def to_json(self) -> dict[str, Any]:
        return {"summary": self.summary, "findings": [finding.to_json() for finding in self.findings]}


def sanitize(text: str, limit: int) -> str:
    cleaned = _CONTROL.sub("", text)
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    cleaned = _MARKDOWN_LINK.sub(lambda match: match.group(1), cleaned)
    cleaned = _URL.sub(LINK_REMOVED, cleaned)
    cleaned = _MENTION.sub("", cleaned)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerdictError(message)


def _valid_path(path: str) -> bool:
    parts = path.split("/")
    return (
        0 < len(path) <= MAX_PATH
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in ("", ".", "..") for part in parts)
        and _CONTROL.search(path) is None
    )


def _finding(data: Any) -> Finding:
    _require(isinstance(data, dict), "each finding must be an object")
    _require(set(data) == set(FINDING_KEYS), f"each finding must have exactly the keys {FINDING_KEYS}")
    severity, path, line, title, detail = (data[key] for key in FINDING_KEYS)
    _require(isinstance(severity, str) and severity in SEVERITIES, f"severity must be one of {SEVERITIES}")
    _require(isinstance(path, str) and _valid_path(path), "file must be a repository-relative path")
    _require(isinstance(line, int) and not isinstance(line, bool) and line >= 1, "line must be a positive integer")
    _require(isinstance(title, str) and title.strip() != "", "title must be a non-empty string")
    _require(isinstance(detail, str), "detail must be a string")
    return Finding(severity, path, line, sanitize(title, MAX_TITLE), sanitize(detail, MAX_DETAIL))


def validate(data: Any) -> Verdict:
    _require(isinstance(data, dict), "the verdict must be a JSON object")
    _require(set(data) == set(VERDICT_KEYS), f"the verdict must have exactly the keys {VERDICT_KEYS}")
    _require(isinstance(data["summary"], str), "summary must be a string")
    _require(isinstance(data["findings"], list), "findings must be a list")
    _require(len(data["findings"]) <= MAX_FINDINGS, f"at most {MAX_FINDINGS} findings are accepted")
    findings = tuple(_finding(item) for item in data["findings"])
    return Verdict(sanitize(data["summary"], MAX_SUMMARY), findings)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def parse_output(harness: str, text: str) -> Any:
    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise VerdictError(f"the reviewer output is not JSON: {exc.msg}") from exc
    if harness == "claude":
        _require(isinstance(payload, dict), "the claude result envelope must be an object")
        _require(payload.get("is_error") is not True, "the claude result envelope reports an error")
        if "structured_output" in payload:
            return payload["structured_output"]
        result = payload.get("result")
        _require(isinstance(result, str), "the claude result envelope has no result")
        return parse_output("text", result)
    return payload


@dataclass(frozen=True)
class Placement:
    inline: tuple[Finding, ...]
    summary: tuple[Finding, ...]


def place(findings: tuple[Finding, ...], commentable: Mapping[str, frozenset[int]]) -> Placement:
    inline = tuple(finding for finding in findings if finding.line in commentable.get(finding.file, frozenset()))
    summary = tuple(finding for finding in findings if finding not in inline)
    return Placement(inline, summary)
