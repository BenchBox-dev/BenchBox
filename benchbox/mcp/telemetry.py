"""Redacted shared telemetry for the BenchBox MCP service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

from benchbox.mcp.readiness import CURRENT_PROTOCOL_VERSION, SUPPORTED_LEGACY_VERSION

TELEMETRY_SCOPE = "benchbox.mcp"
_MAX_ATTRIBUTE_LENGTH = 64
_configured_provider: TracerProvider | None = None
_KNOWN_METHODS = frozenset(
    {
        "initialize",
        "notifications/cancelled",
        "notifications/initialized",
        "prompts/get",
        "prompts/list",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "server/discover",
        "subscriptions/listen",
        "tools/call",
        "tools/list",
    }
)


def _bounded(value: object) -> str:
    """Return a bounded identifier suitable for a telemetry attribute."""
    return str(value)[:_MAX_ATTRIBUTE_LENGTH]


@dataclass(frozen=True, slots=True)
class TelemetrySettings:
    """Environment-derived OTLP configuration without embedded credentials."""

    endpoint: str | None
    service_name: str = "benchbox-mcp"

    def __post_init__(self) -> None:
        if self.endpoint is None:
            return
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("MCP OTLP endpoint must be an HTTP(S) URL without embedded credentials")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TelemetrySettings:
        endpoint = env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or None
        generic_endpoint = env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None
        if endpoint is None and generic_endpoint is not None:
            parsed = urlsplit(generic_endpoint)
            endpoint = urlunsplit(parsed._replace(path=f"{parsed.path.rstrip('/')}/v1/traces"))
        return cls(endpoint=endpoint)


class ScopeFilteringExporter(SpanExporter):
    """Export only BenchBox's deliberately bounded spans.

    The MCP SDK emits useful outer spans, but they include the raw JSON-RPC
    request identifier. BenchBox exports its inner span instead, inheriting the
    SDK-extracted W3C parent while keeping the exported schema allow-listed.
    """

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        safe = [span for span in spans if span.instrumentation_scope.name == TELEMETRY_SCOPE]
        return self._delegate.export(safe) if safe else SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._delegate.force_flush(timeout_millis)


class RedactedTelemetryMiddleware:
    """Create one bounded span per MCP request without inputs or payloads."""

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        method = ctx.method if ctx.method in _KNOWN_METHODS else "unknown"
        protocol = (
            ctx.protocol_version
            if ctx.protocol_version in {CURRENT_PROTOCOL_VERSION, SUPPORTED_LEGACY_VERSION}
            else "unsupported"
        )
        attributes: dict[str, str] = {
            "mcp.method.name": method,
            "mcp.protocol.version": protocol,
        }

        tracer = trace.get_tracer(TELEMETRY_SCOPE)
        with tracer.start_as_current_span(method, attributes=attributes) as span:
            try:
                result = await call_next(ctx)
            except MCPError as exc:
                span.set_attribute("error.type", _bounded(exc.error.code))
                span.set_status(Status(StatusCode.ERROR))
                raise
            except Exception as exc:
                span.set_attribute("error.type", _bounded(type(exc).__qualname__))
                span.set_status(Status(StatusCode.ERROR))
                raise
            span.set_attribute("mcp.response.status", "ok")
            return result


def configure_telemetry(settings: TelemetrySettings) -> bool:
    """Configure process-wide OTLP export once when an endpoint is present."""
    global _configured_provider

    if settings.endpoint is None:
        return False
    if _configured_provider is not None:
        return True
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        raise ValueError("MCP OTLP export requires control of an unconfigured global tracer provider")

    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    # Headers/certificates remain in the standard OTEL environment and stay
    # out of BenchBox configuration and logs.
    exporter = ScopeFilteringExporter(OTLPSpanExporter(endpoint=settings.endpoint))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    if trace.get_tracer_provider() is not provider:
        provider.shutdown()
        raise ValueError("MCP could not install its redacted tracer provider")
    _configured_provider = provider
    return True
