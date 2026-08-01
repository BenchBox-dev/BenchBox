"""MCP-specific CLI entrypoint and argument parsing."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from benchbox.core.runtime_paths import resolve_runtime_paths
from benchbox.mcp import run_server


def _http_port(value: str) -> int:
    """Parse an HTTP port with an argparse-friendly error."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    """Build parser for MCP server startup options."""
    parser = argparse.ArgumentParser(
        prog="benchbox-mcp",
        description="Run the BenchBox MCP server.",
    )
    parser.add_argument(
        "--results-dir",
        help=(
            "Directory for MCP result reads/writes. "
            "Precedence: --results-dir > BENCHBOX_RESULTS_DIR > "
            "BENCHBOX_OUTPUT_DIR/results > benchmark_runs/results."
        ),
    )
    parser.add_argument(
        "--charts-dir",
        help=(
            "Directory for MCP chart assets. "
            "Precedence: --charts-dir > BENCHBOX_CHARTS_DIR > "
            "BENCHBOX_OUTPUT_DIR/charts > benchmark_runs/charts."
        ),
    )
    parser.add_argument(
        "--log-level",
        help="Logging level (e.g., DEBUG, INFO, WARNING). Falls back to BENCHBOX_LOG_LEVEL.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio; Streamable HTTP is localhost-only).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Streamable HTTP bind host (loopback interfaces only; default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=_http_port,
        default=8000,
        help="Streamable HTTP bind port (default: 8000).",
    )
    parser.add_argument(
        "--streamable-http-path",
        default="/mcp",
        help="Streamable HTTP endpoint path (default: /mcp).",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for MCP startup."""
    parser = build_parser()
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> None:
    """Parse MCP CLI args and run the server."""
    args = parse_args(argv)
    runtime_paths = resolve_runtime_paths(
        results_dir=args.results_dir,
        charts_dir=args.charts_dir,
        env=os.environ,
    )
    run_server(
        results_dir=runtime_paths.results_dir,
        charts_dir=runtime_paths.charts_dir,
        log_level=args.log_level,
        env=os.environ,
        transport=args.transport,
        host=args.host,
        port=args.port,
        streamable_http_path=args.streamable_http_path,
    )
