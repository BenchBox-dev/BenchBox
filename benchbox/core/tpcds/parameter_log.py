"""Parser for the substitution parameters that dsqgen records with ``-LOG``.

dsqgen writes one block per stream and template::

    BEGIN STREAM 0
    Template: query39.tpl
        YEAR.01 = 2002
        MONTH.01 = 4
        ...
    END STREAM 0

The values are the ones substituted into the generated SQL, so they are the
authoritative source for DataFrame implementations that must use the same
parameters as the SQL. The log records base variables only: an expression such
as ``[MONTH]+1`` in a template appears as ``MONTH.01`` here.

The per-stream query ordering in the same log is consumed by
``benchbox.core.tpcds.streams``; this module reads the parameter lines.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from benchbox.core.tpcds.streams import _DSQGEN_BEGIN_STREAM_RE, _DSQGEN_TEMPLATE_RE

_END_STREAM_RE = re.compile(r"^END STREAM\s+(\d+)\s*$", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^(\S+)\s*=\s*(.*)$")


@dataclass(frozen=True)
class TemplateParameters:
    """Substituted parameters for one template in one dsqgen stream.

    ``values`` maps each logged name (for example ``YEAR.01``) to its string
    value, in log order. Names that start with an underscore are dsqgen's own
    bookkeeping (``_LIMIT.01``, ``_END.01``); ``substitutions`` omits them.
    """

    stream: int
    query_id: int
    variant: Optional[str]
    values: dict[str, str] = field(default_factory=dict)

    @property
    def substitutions(self) -> dict[str, str]:
        """Template variables only, without dsqgen's underscore-prefixed bookkeeping."""
        return {name: value for name, value in self.values.items() if not name.startswith("_")}


def parse_dsqgen_parameter_log(log_text: str) -> dict[int, list[TemplateParameters]]:
    """Parse a dsqgen ``-LOG`` file into per-stream template parameters.

    Returns a mapping from stream number to the templates of that stream in log
    order. Malformed input raises ``ValueError`` rather than being skipped, so a
    truncated or unexpected log cannot silently yield partial parameters.
    """
    streams: dict[int, list[TemplateParameters]] = {}
    current_stream: Optional[int] = None
    current: Optional[TemplateParameters] = None

    for line_number, raw_line in enumerate(log_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        begin = _DSQGEN_BEGIN_STREAM_RE.match(line)
        if begin:
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

        template = _DSQGEN_TEMPLATE_RE.match(line)
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
