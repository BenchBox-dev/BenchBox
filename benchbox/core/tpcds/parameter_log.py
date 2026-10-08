# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from benchbox.core.tpcds.streams import _DSQGEN_BEGIN_STREAM_RE

_TEMPLATE_RE = re.compile(r"^Template:\s*(?:\S*[/\\])?query(\d+)([ab]?)\.tpl\s*$", re.IGNORECASE)
_END_STREAM_RE = re.compile(r"^END STREAM\s+(\d+)\s*$", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^(\S+)\s*=\s*(.*)$")


@dataclass(frozen=True)
class TemplateParameters:
    stream: int
    query_id: int
    variant: Optional[str]
    values: dict[str, str] = field(default_factory=dict)

    @property
    def substitutions(self) -> dict[str, str]:
        return {name: value for name, value in self.values.items() if not name.startswith("_")}


def parse_dsqgen_parameter_log(log_text: str) -> dict[int, list[TemplateParameters]]:
    streams: dict[int, list[TemplateParameters]] = {}
    current_stream: Optional[int] = None
    current: Optional[TemplateParameters] = None

    for line_number, raw_line in enumerate(log_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        begin = _DSQGEN_BEGIN_STREAM_RE.match(line)
        if begin:
            if current_stream is not None:
                raise ValueError(
                    f"dsqgen log line {line_number}: BEGIN STREAM {begin.group(1)} before END STREAM {current_stream}"
                )
            current_stream = int(begin.group(1))
            if current_stream in streams:
                raise ValueError(f"dsqgen log line {line_number}: stream {current_stream} appears twice")
            streams[current_stream] = []
            current = None
            continue

        end = _END_STREAM_RE.match(line)
        if end:
            if current_stream is None or int(end.group(1)) != current_stream:
                raise ValueError(f"dsqgen log line {line_number}: END STREAM {end.group(1)} without matching BEGIN")
            current_stream = None
            current = None
            continue

        template = _TEMPLATE_RE.match(line)
        if template:
            if current_stream is None:
                raise ValueError(f"dsqgen log line {line_number}: template outside a stream: {line!r}")
            current = TemplateParameters(
                stream=current_stream,
                query_id=int(template.group(1)),
                variant=template.group(2) or None,
            )
            streams[current_stream].append(current)
            continue

        parameter = _PARAMETER_RE.match(line)
        if parameter and current is not None:
            name, value = parameter.group(1), parameter.group(2).strip()
            if name in current.values:
                raise ValueError(f"dsqgen log line {line_number}: {name} repeated in query{current.query_id}")
            current.values[name] = value
            continue

        raise ValueError(f"dsqgen log line {line_number}: unrecognized content {line!r}")

    if current_stream is not None:
        raise ValueError(f"dsqgen log ended inside stream {current_stream} (truncated log)")
    return streams
