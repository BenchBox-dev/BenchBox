"""Authentication, tenancy, admission, and audit controls for remote MCP."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier, principal_components
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from benchbox.utils.clock import mono_time, utc_now

AUTHORIZATION_ERROR = -32003
ADMISSION_ERROR = -32004
READ_SCOPE = "benchbox:read"
EXECUTE_SCOPE = "benchbox:execute"
WRITE_SCOPE = "benchbox:write"


class TokenIdentity(BaseModel):
    """Trusted identity and permissions for one pre-provisioned bearer digest."""

    model_config = ConfigDict(frozen=True)

    token_sha256: str
    client_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    scopes: tuple[str, ...] = (READ_SCOPE,)

    @field_validator("token_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        """Require a lowercase SHA-256 digest, never a raw credential."""
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("token_sha256 must be a 64-character hexadecimal SHA-256 digest")
        return normalized


class AdmissionLimits(BaseModel):
    """Durable request limits shared by every HTTP worker."""

    model_config = ConfigDict(frozen=True)

    requests_per_minute: int = Field(default=120, ge=1, le=100_000)
    global_concurrency: int = Field(default=8, ge=1, le=10_000)
    principal_concurrency: int = Field(default=2, ge=1, le=10_000)
    queue_limit: int = Field(default=32, ge=0, le=100_000)
    queue_timeout_seconds: float = Field(default=5.0, ge=0.0, le=300.0)
    lease_seconds: float = Field(default=3_600.0, gt=0.0, le=86_400.0)


class RemoteSecurityConfig(BaseModel):
    """Fail-closed remote MCP security configuration."""

    model_config = ConfigDict(frozen=True)

    issuer_url: AnyHttpUrl
    resource_server_url: AnyHttpUrl
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    workspace_root: Path
    state_db: Path
    tokens: tuple[TokenIdentity, ...]
    allowed_platforms: tuple[str, ...] = ()
    allowed_benchmarks: tuple[str, ...] = ()
    max_scale_factor: float = Field(default=1.0, gt=0.0)
    admission: AdmissionLimits = Field(default_factory=AdmissionLimits)

    @field_validator("allowed_hosts", "allowed_origins", "tokens")
    @classmethod
    def require_nonempty(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        """Reject incomplete remote security configuration."""
        if not value:
            raise ValueError("remote security allowlists and tokens must not be empty")
        return value

    @field_validator("allowed_platforms", "allowed_benchmarks")
    @classmethod
    def normalize_policy_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize policy identifiers to the tool's comparison form."""
        return tuple(dict.fromkeys(item.strip().lower() for item in value if item.strip()))

    @model_validator(mode="after")
    def reject_ambiguous_token_digests(self) -> RemoteSecurityConfig:
        """Ensure one bearer digest cannot resolve to multiple principals."""
        digests = [identity.token_sha256 for identity in self.tokens]
        if len(digests) != len(set(digests)):
            raise ValueError("token_sha256 values must be unique")
        return self

    def require_remote_tls(self) -> None:
        """Require externally visible OAuth endpoints to use HTTPS."""
        if self.issuer_url.scheme != "https" or self.resource_server_url.scheme != "https":
            raise ValueError("remote MCP requires HTTPS issuer_url and resource_server_url")


def load_remote_security_config(path: str | Path) -> RemoteSecurityConfig:
    """Load validated security policy, resolving owned paths beside the config."""
    config_path = Path(path).expanduser().resolve(strict=True)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load MCP security configuration ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise ValueError("MCP security configuration must be a JSON object")
    for key in ("workspace_root", "state_db"):
        candidate = Path(str(raw.get(key, ""))).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        raw[key] = candidate.resolve()
    config = RemoteSecurityConfig.model_validate(raw)
    config.workspace_root.mkdir(parents=True, exist_ok=True)
    config.state_db.parent.mkdir(parents=True, exist_ok=True)
    return config


class _TransportSecurityLogFilter(logging.Filter):
    """Keep SDK rejection diagnostics without logging attacker headers."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if message.startswith("Invalid Host header:"):
            record.msg = "Rejected invalid Host header"
            record.args = ()
        elif message.startswith("Invalid Origin header:"):
            record.msg = "Rejected invalid Origin header"
            record.args = ()
        return True


def configure_transport_security_logging() -> None:
    """Install the idempotent SDK header-redaction filter."""
    logger = logging.getLogger("mcp.server.transport_security")
    if not any(isinstance(item, _TransportSecurityLogFilter) for item in logger.filters):
        logger.addFilter(_TransportSecurityLogFilter())


class DigestTokenVerifier(TokenVerifier):
    """Verify opaque bearer tokens against trusted SHA-256 digests."""

    def __init__(self, config: RemoteSecurityConfig):
        self._config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the configured identity without persisting or logging *token*."""
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for identity in self._config.tokens:
            if hmac.compare_digest(digest, identity.token_sha256):
                return AccessToken(
                    token=token,
                    client_id=identity.client_id,
                    subject=identity.subject,
                    scopes=list(identity.scopes),
                    resource=str(self._config.resource_server_url),
                    claims={"iss": str(self._config.issuer_url)},
                )
        return None


@dataclass(frozen=True, slots=True)
class Principal:
    """Opaque stable identity used for ownership, limits, and audit."""

    principal_id: str
    client_id: str
    issuer: str | None
    subject: str | None
    scopes: frozenset[str]

    @classmethod
    def from_access_token(cls, token: AccessToken) -> Principal:
        """Derive an opaque identifier from all SDK principal components."""
        client_id, issuer, subject = principal_components(token)
        material = json.dumps([client_id, issuer, subject], separators=(",", ":"), ensure_ascii=True)
        principal_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        return cls(principal_id, client_id, issuer, subject, frozenset(token.scopes))


def authenticated_principal() -> Principal:
    """Return the request principal or fail closed outside authenticated HTTP."""
    token = get_access_token()
    if token is None:
        raise MCPError(AUTHORIZATION_ERROR, "Authenticated principal required")
    return Principal.from_access_token(token)


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Server-owned paths for one authenticated tenant."""

    root: Path
    results_dir: Path
    charts_dir: Path


class TenantWorkspaceProvider:
    """Resolve request paths solely from the authenticated principal."""

    def __init__(self, workspace_root: Path):
        self._workspace_root = workspace_root.resolve()

    def paths_for(self, principal: Principal) -> WorkspacePaths:
        """Return contained, server-owned paths for *principal*."""
        root = (self._workspace_root / principal.principal_id).resolve()
        root.relative_to(self._workspace_root)
        results_dir = root / "results"
        charts_dir = root / "charts"
        results_dir.mkdir(parents=True, exist_ok=True)
        charts_dir.mkdir(parents=True, exist_ok=True)
        return WorkspacePaths(root, results_dir, charts_dir)

    def current_results_dir(self) -> Path:
        """Resolve the current request's result directory."""
        return self.paths_for(authenticated_principal()).results_dir

    def current_charts_dir(self) -> Path:
        """Resolve the current request's chart directory."""
        return self.paths_for(authenticated_principal()).charts_dir


@dataclass(frozen=True, slots=True)
class AdmissionLease:
    """A durable active admission ticket."""

    ticket_id: str
    principal_id: str


class DurableSecurityStore:
    """SQLite-backed rate, queue, lease, and redacted audit coordination."""

    def __init__(self, path: Path, limits: AdmissionLimits):
        self.path = path
        self.limits = limits
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mcp_rate_windows (
                    principal_id TEXT NOT NULL,
                    window_start INTEGER NOT NULL,
                    request_count INTEGER NOT NULL,
                    PRIMARY KEY (principal_id, window_start)
                );
                CREATE TABLE IF NOT EXISTS mcp_admission_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('waiting', 'active')),
                    created_at REAL NOT NULL,
                    lease_expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS mcp_admission_state_idx
                    ON mcp_admission_tickets (state, created_at);
                CREATE INDEX IF NOT EXISTS mcp_admission_principal_idx
                    ON mcp_admission_tickets (principal_id, state);
                CREATE TABLE IF NOT EXISTS mcp_audit_events (
                    event_id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    execution_id TEXT,
                    artifact_ref TEXT
                );
                """
            )

    def _begin(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def _cleanup_expired(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute("DELETE FROM mcp_admission_tickets WHERE state = 'active' AND lease_expires_at <= ?", (now,))

    def _check_rate(self, connection: sqlite3.Connection, principal_id: str, now: float) -> None:
        window_start = int(now // 60) * 60
        row = connection.execute(
            "SELECT request_count FROM mcp_rate_windows WHERE principal_id = ? AND window_start = ?",
            (principal_id, window_start),
        ).fetchone()
        if row is not None and int(row["request_count"]) >= self.limits.requests_per_minute:
            raise MCPError(ADMISSION_ERROR, "Request rate limit exceeded")
        connection.execute(
            """
            INSERT INTO mcp_rate_windows (principal_id, window_start, request_count) VALUES (?, ?, 1)
            ON CONFLICT (principal_id, window_start)
            DO UPDATE SET request_count = request_count + 1
            """,
            (principal_id, window_start),
        )
        connection.execute("DELETE FROM mcp_rate_windows WHERE window_start < ?", (window_start - 120,))

    def _capacity_available(self, connection: sqlite3.Connection, principal_id: str) -> bool:
        global_active = connection.execute(
            "SELECT COUNT(*) FROM mcp_admission_tickets WHERE state = 'active'"
        ).fetchone()[0]
        principal_active = connection.execute(
            "SELECT COUNT(*) FROM mcp_admission_tickets WHERE state = 'active' AND principal_id = ?",
            (principal_id,),
        ).fetchone()[0]
        return global_active < self.limits.global_concurrency and principal_active < self.limits.principal_concurrency

    def _enqueue(self, principal_id: str) -> str:
        ticket_id = uuid.uuid4().hex
        now = utc_now().timestamp()
        with self._connect() as connection:
            self._begin(connection)
            self._cleanup_expired(connection, now)
            self._check_rate(connection, principal_id, now)
            state = "active" if self._capacity_available(connection, principal_id) else "waiting"
            if state == "waiting":
                waiting = connection.execute(
                    "SELECT COUNT(*) FROM mcp_admission_tickets WHERE state = 'waiting'"
                ).fetchone()[0]
                if waiting >= self.limits.queue_limit:
                    connection.rollback()
                    raise MCPError(ADMISSION_ERROR, "Admission queue is full")
            expires_at = now + self.limits.lease_seconds if state == "active" else None
            connection.execute(
                """INSERT INTO mcp_admission_tickets
                   (ticket_id, principal_id, state, created_at, lease_expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (ticket_id, principal_id, state, now, expires_at),
            )
            connection.commit()
        return ticket_id

    def _try_promote(self, ticket_id: str, principal_id: str) -> bool:
        now = utc_now().timestamp()
        with self._connect() as connection:
            self._begin(connection)
            self._cleanup_expired(connection, now)
            row = connection.execute(
                "SELECT state FROM mcp_admission_tickets WHERE ticket_id = ? AND principal_id = ?",
                (ticket_id, principal_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            if row["state"] == "active":
                connection.commit()
                return True
            first_waiting = connection.execute(
                "SELECT ticket_id FROM mcp_admission_tickets WHERE state = 'waiting' ORDER BY created_at, ticket_id LIMIT 1"
            ).fetchone()
            if (
                first_waiting is not None
                and first_waiting["ticket_id"] == ticket_id
                and self._capacity_available(connection, principal_id)
            ):
                connection.execute(
                    "UPDATE mcp_admission_tickets SET state = 'active', lease_expires_at = ? WHERE ticket_id = ?",
                    (now + self.limits.lease_seconds, ticket_id),
                )
                connection.commit()
                return True
            connection.commit()
        return False

    async def admit(self, principal_id: str) -> AdmissionLease:
        """Rate-limit, queue, and acquire a shared concurrency lease."""
        ticket_id = await anyio.to_thread.run_sync(self._enqueue, principal_id)
        deadline_start = mono_time()
        while not await anyio.to_thread.run_sync(self._try_promote, ticket_id, principal_id):
            if mono_time() - deadline_start >= self.limits.queue_timeout_seconds:
                await anyio.to_thread.run_sync(self.release, AdmissionLease(ticket_id, principal_id))
                raise MCPError(ADMISSION_ERROR, "Admission queue wait timed out")
            await anyio.sleep(0.025)
        return AdmissionLease(ticket_id, principal_id)

    def release(self, lease: AdmissionLease) -> None:
        """Release a ticket idempotently."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM mcp_admission_tickets WHERE ticket_id = ? AND principal_id = ?",
                (lease.ticket_id, lease.principal_id),
            )

    def renew(self, lease: AdmissionLease) -> bool:
        """Extend an active lease while its request is still running."""
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE mcp_admission_tickets SET lease_expires_at = ?
                   WHERE ticket_id = ? AND principal_id = ? AND state = 'active'""",
                (utc_now().timestamp() + self.limits.lease_seconds, lease.ticket_id, lease.principal_id),
            )
        return cursor.rowcount == 1

    def audit(
        self,
        *,
        principal_id: str,
        tool_name: str,
        decision: str,
        execution_id: str | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        """Persist a bounded event without arguments, payloads, or credentials."""
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO mcp_audit_events
                   (event_id, recorded_at, principal_id, tool_name, decision, execution_id, artifact_ref)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    utc_now().isoformat(),
                    principal_id[:64],
                    tool_name[:120],
                    decision[:32],
                    execution_id[:120] if execution_id else None,
                    Path(artifact_ref).name[:255] if artifact_ref else None,
                ),
            )

    def audit_events(self) -> list[Mapping[str, Any]]:
        """Return audit rows for verification and operator diagnostics."""
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM mcp_audit_events ORDER BY recorded_at, event_id").fetchall()
        return [dict(row) for row in rows]


READ_ONLY_TOOLS = frozenset(
    {
        "list_available",
        "get_benchmark_info",
        "system_profile",
        "check_dependencies",
        "get_query_details",
        "get_results",
        "analyze_results",
        "get_query_plan",
        "validate_results",
        "suggest_charts",
    }
)
READ_METHODS = frozenset(
    {
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
    }
)


class RemoteSecurityMiddleware:
    """Authorize and admit each remote tool call using durable shared state."""

    def __init__(self, config: RemoteSecurityConfig, store: DurableSecurityStore):
        self.config = config
        self.store = store

    def _authorize(self, principal: Principal, tool_name: str, arguments: Mapping[str, Any]) -> None:
        required_scope = READ_SCOPE if tool_name in READ_ONLY_TOOLS else WRITE_SCOPE
        if tool_name == "run_benchmark":
            required_scope = EXECUTE_SCOPE
        elif tool_name == "get_results" and arguments.get("output_path"):
            required_scope = WRITE_SCOPE
        if required_scope not in principal.scopes:
            raise MCPError(AUTHORIZATION_ERROR, f"Scope required: {required_scope}")
        if tool_name != "run_benchmark":
            return
        platform = str(arguments.get("platform", "")).lower()
        benchmark = str(arguments.get("benchmark", "")).lower()
        try:
            scale_factor = float(arguments.get("scale_factor", 0.01))
        except (TypeError, ValueError) as exc:
            raise MCPError(AUTHORIZATION_ERROR, "Invalid benchmark scale factor") from exc
        if self.config.allowed_platforms and platform not in self.config.allowed_platforms:
            raise MCPError(AUTHORIZATION_ERROR, "Platform is not authorized")
        if self.config.allowed_benchmarks and benchmark not in self.config.allowed_benchmarks:
            raise MCPError(AUTHORIZATION_ERROR, "Benchmark is not authorized")
        if not math.isfinite(scale_factor) or scale_factor <= 0:
            raise MCPError(AUTHORIZATION_ERROR, "Benchmark scale factor must be finite and positive")
        if scale_factor > self.config.max_scale_factor:
            raise MCPError(AUTHORIZATION_ERROR, "Benchmark scale factor exceeds policy")

    @staticmethod
    def _tool_call(ctx: ServerRequestContext[Any, Any]) -> tuple[str, Mapping[str, Any]] | None:
        if ctx.method != "tools/call" or not isinstance(ctx.params, Mapping):
            return None
        name = ctx.params.get("name")
        arguments = ctx.params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            return None
        return name, arguments

    @staticmethod
    def _result_refs(result: HandlerResult) -> tuple[str | None, str | None]:
        """Extract only bounded identifiers from a tool result for audit."""
        payload: Mapping[str, Any] | None = result if isinstance(result, Mapping) else None
        if isinstance(result, CallToolResult):
            text = next((part.text for part in result.content if isinstance(part, TextContent)), None)
            if text is not None and len(text) <= 65_536:
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, Mapping):
                    payload = decoded
        if payload is None:
            return None, None
        metadata = payload.get("mcp_metadata")
        metadata_map = metadata if isinstance(metadata, Mapping) else {}
        execution = metadata_map.get("execution_id", payload.get("execution_id"))
        artifact = metadata_map.get("result_file", payload.get("file"))
        return (
            str(execution) if isinstance(execution, str) else None,
            str(artifact) if isinstance(artifact, str) else None,
        )

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        """Enforce policy around SDK dispatch without exposing raw inputs."""
        if ctx.request_id is None:
            return await call_next(ctx)
        principal = authenticated_principal()
        tool_call = self._tool_call(ctx)
        if tool_call is None:
            if ctx.method in READ_METHODS:
                if READ_SCOPE not in principal.scopes:
                    await self._audit(
                        principal_id=principal.principal_id,
                        tool_name=ctx.method,
                        decision="denied",
                    )
                    raise MCPError(AUTHORIZATION_ERROR, f"Scope required: {READ_SCOPE}")
            return await self._call_admitted(principal, ctx.method, ctx, call_next)
        tool_name, arguments = tool_call
        try:
            self._authorize(principal, tool_name, arguments)
        except MCPError:
            await self._audit(principal_id=principal.principal_id, tool_name=tool_name, decision="denied")
            raise

        return await self._call_admitted(principal, tool_name, ctx, call_next)

    async def _call_admitted(
        self,
        principal: Principal,
        operation: str,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        """Coordinate, dispatch, and audit one authenticated request."""

        lease: AdmissionLease | None = None
        try:
            lease = await self.store.admit(principal.principal_id)
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(self._renew_lease, lease)
                try:
                    result = await call_next(ctx)
                finally:
                    task_group.cancel_scope.cancel()
            execution_id, artifact_ref = self._result_refs(result)
            await self._audit(
                principal_id=principal.principal_id,
                tool_name=operation,
                decision="allowed",
                execution_id=execution_id,
                artifact_ref=artifact_ref,
            )
            return result
        except MCPError:
            await self._audit(principal_id=principal.principal_id, tool_name=operation, decision="failed")
            raise
        except Exception as exc:
            await self._audit(principal_id=principal.principal_id, tool_name=operation, decision="failed")
            raise MCPError(-32603, f"Tool execution failed ({type(exc).__name__})") from exc
        finally:
            if lease is not None:
                await anyio.to_thread.run_sync(self.store.release, lease)

    async def _renew_lease(self, lease: AdmissionLease) -> None:
        """Heartbeat one active request without process-local authority."""
        interval = max(0.05, min(self.store.limits.lease_seconds / 3, 30.0))
        while True:
            await anyio.sleep(interval)
            if not await anyio.to_thread.run_sync(self.store.renew, lease):
                return

    async def _audit(
        self,
        *,
        principal_id: str,
        tool_name: str,
        decision: str,
        execution_id: str | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        """Persist audit off the event loop."""
        await anyio.to_thread.run_sync(
            lambda: self.store.audit(
                principal_id=principal_id,
                tool_name=tool_name,
                decision=decision,
                execution_id=execution_id,
                artifact_ref=artifact_ref,
            )
        )


@dataclass(frozen=True, slots=True)
class RemoteSecurityRuntime:
    """Constructed remote security services shared by server and transport."""

    config: RemoteSecurityConfig
    verifier: DigestTokenVerifier
    workspaces: TenantWorkspaceProvider
    store: DurableSecurityStore
    middleware: RemoteSecurityMiddleware

    @classmethod
    def from_file(cls, path: str | Path) -> RemoteSecurityRuntime:
        """Construct the complete runtime from one validated config file."""
        config = load_remote_security_config(path)
        store = DurableSecurityStore(config.state_db, config.admission)
        return cls(
            config=config,
            verifier=DigestTokenVerifier(config),
            workspaces=TenantWorkspaceProvider(config.workspace_root),
            store=store,
            middleware=RemoteSecurityMiddleware(config, store),
        )

    def auth_settings(self) -> AuthSettings:
        """Return SDK resource-server auth settings."""
        return AuthSettings(
            issuer_url=self.config.issuer_url,
            resource_server_url=self.config.resource_server_url,
            required_scopes=[],
        )


PathProvider = Path | Callable[[], Path]


def resolve_path_provider(provider: PathProvider) -> Path:
    """Resolve a static local path or request-scoped tenant path."""
    if isinstance(provider, Path):
        return provider
    return Path(provider())


def token_sha256(token: str) -> str:
    """Return a provisioning digest without storing the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
