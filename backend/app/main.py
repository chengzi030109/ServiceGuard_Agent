import hashlib
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api import documents, logs, rag, tickets
from backend.app.core.config import get_settings
from backend.app.core.database import get_database
from backend.app.core.http_metrics import InMemoryHttpMetrics
from backend.app.core.rate_limit import InMemoryRateLimiter
from backend.app.services.vector_store import get_vector_store

START_TIME = time.time()
RATE_LIMIT_EXEMPT_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/metrics/prometheus",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_runtime_security()
    database = get_database()
    interrupted_batch_jobs = database.mark_interrupted_batch_jobs()
    app = FastAPI(
        title="ServiceGuard Agent",
        description="Enterprise knowledge-base driven customer service ticket QA Agent.",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_allowed_origins,
        allow_credentials="*" not in settings.parsed_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.rate_limiter = InMemoryRateLimiter()
    app.state.http_metrics = InMemoryHttpMetrics()
    app.state.interrupted_batch_jobs_on_startup = interrupted_batch_jobs

    @app.middleware("http")
    async def add_enterprise_headers(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"req_{uuid.uuid4().hex[:12]}")
        request.state.request_id = request_id
        start = time.perf_counter()

        content_length = request.headers.get("content-length")
        if _request_body_too_large(content_length, settings.max_upload_bytes):
            latency_ms = int((time.perf_counter() - start) * 1000)
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": 413,
                        "message": (
                            f"Request body is too large. Max size is {settings.max_upload_mb} MB"
                        ),
                        "request_id": request_id,
                    }
                },
            )
            _add_enterprise_response_headers(response, request_id, latency_ms)
            app.state.http_metrics.record(
                status_code=response.status_code,
                latency_ms=latency_ms,
            )
            _save_audit_event(database, request, response.status_code, latency_ms)
            return response

        rate_limit_result = None
        if settings.rate_limit_enabled and request.url.path not in RATE_LIMIT_EXEMPT_PATHS:
            rate_limit_key = _rate_limit_key(request)
            rate_limit_result = app.state.rate_limiter.check(
                rate_limit_key,
                settings.rate_limit_per_minute,
            )
            if not rate_limit_result.allowed:
                latency_ms = int((time.perf_counter() - start) * 1000)
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": 429,
                            "message": "Rate limit exceeded",
                            "request_id": request_id,
                        }
                    },
                    headers={"Retry-After": str(rate_limit_result.retry_after_seconds)},
                )
                _add_enterprise_response_headers(response, request_id, latency_ms)
                _add_rate_limit_headers(response, settings.rate_limit_per_minute, 0)
                app.state.http_metrics.record(
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                )
                _save_audit_event(database, request, response.status_code, latency_ms)
                return response

        response = await call_next(request)
        latency_ms = int((time.perf_counter() - start) * 1000)
        _add_enterprise_response_headers(response, request_id, latency_ms)
        app.state.http_metrics.record(
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        if rate_limit_result is not None:
            _add_rate_limit_headers(
                response,
                settings.rate_limit_per_minute,
                rate_limit_result.remaining,
            )
        if request.url.path not in {"/health", "/ready", "/metrics", "/metrics/prometheus"}:
            _save_audit_event(database, request, response.status_code, latency_ms)
        return response

    app.include_router(documents.router)
    app.include_router(rag.router)
    app.include_router(tickets.router)
    app.include_router(logs.router)

    @app.get("/health")
    def health() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "app_env": settings.app_env,
            "vector_db": settings.vector_db,
            "local_fallback": settings.use_local_fallback,
            "remote_llm_configured": settings.has_remote_llm,
            "auth_required": settings.require_api_key,
        }

    @app.get("/ready")
    def readiness() -> dict[str, str | int | bool]:
        database.health_check()
        sqlite_status = database.sqlite_runtime_status()
        vector_count = get_vector_store().collection.count()
        return {
            "status": "ready",
            "database": "ok",
            "database_quick_check_ok": sqlite_status["quick_check_ok"],
            "database_journal_mode": sqlite_status["journal_mode"],
            "vector_store": "ok",
            "vector_count": vector_count,
        }

    @app.get("/metrics")
    def metrics() -> dict[str, int | float]:
        return _collect_metrics(database, app.state.http_metrics)

    @app.get("/metrics/prometheus", response_class=PlainTextResponse)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            _format_prometheus_metrics(_collect_metrics(database, app.state.http_metrics)),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(
            request.state,
            "request_id",
            request.headers.get("x-request-id", "unknown"),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "request_id": request_id,
                }
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(
            request.state,
            "request_id",
            request.headers.get("x-request-id", "unknown"),
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": 422,
                    "message": "Request validation failed",
                    "request_id": request_id,
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(
            request.state,
            "request_id",
            request.headers.get("x-request-id", "unknown"),
        )
        database.save_audit_event(
            event_id=f"audit_{uuid.uuid4().hex[:12]}",
            request_id=request_id,
            actor_role=getattr(request.state, "actor_role", "anonymous"),
            actor_hash=getattr(request.state, "actor_hash", "none"),
            method=request.method,
            path=request.url.path,
            status_code=500,
            latency_ms=0,
            client_host=request.client.host if request.client else None,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": "Internal server error",
                    "request_id": request_id,
                }
            },
        )

    return app


def _add_enterprise_response_headers(
    response: Response,
    request_id: str,
    latency_ms: int,
) -> None:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = str(latency_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"


def _request_body_too_large(content_length: str | None, max_bytes: int) -> bool:
    if not content_length:
        return False
    try:
        return int(content_length) > max_bytes
    except ValueError:
        return False


def _collect_metrics(database, http_metrics: InMemoryHttpMetrics) -> dict[str, int | float]:
    stats = database.stats()
    review_stats = database.report_review_stats()
    batch_job_stats = database.batch_job_status_stats()
    schema_status = database.schema_status()
    sqlite_status = database.sqlite_runtime_status()
    return {
        "uptime_seconds": round(time.time() - START_TIME, 3),
        "documents_total": stats["documents"],
        "documents_quarantined": stats["documents_quarantined"],
        "chunks_total": stats["chunks"],
        "reports_total": stats["reports"],
        "reports_pending_review": review_stats.get("pending", 0),
        "reports_reviewed_total": sum(
            review_stats.get(status, 0) for status in ("approved", "rejected", "escalated")
        ),
        "llm_call_logs_total": stats["llm_call_logs"],
        "audit_events_total": stats["audit_events"],
        "batch_jobs_total": stats["batch_jobs"],
        "idempotency_records_total": stats["idempotency_records"],
        "batch_jobs_pending": batch_job_stats.get("pending", 0),
        "batch_jobs_running": batch_job_stats.get("running", 0),
        "batch_jobs_active": database.active_batch_job_count(),
        "batch_jobs_active_limit": get_settings().max_active_batch_jobs,
        "batch_jobs_active_per_actor_limit": get_settings().max_active_batch_jobs_per_actor,
        "batch_jobs_interrupted": batch_job_stats.get("interrupted", 0),
        "batch_jobs_canceled": batch_job_stats.get("canceled", 0),
        "batch_jobs_timed_out": batch_job_stats.get("timed_out", 0),
        "batch_jobs_failed": batch_job_stats.get("failed", 0),
        "database_schema_current_version": schema_status["current_version"],
        "database_schema_expected_version": schema_status["expected_version"],
        "database_schema_pending_migrations": len(schema_status["pending_versions"]),
        "database_sqlite_quick_check_ok": int(sqlite_status["quick_check_ok"]),
        "database_sqlite_foreign_keys_enabled": int(sqlite_status["foreign_keys_enabled"]),
        "database_sqlite_busy_timeout_ms": sqlite_status["busy_timeout_ms"],
        **http_metrics.snapshot().as_metrics(),
    }


def _format_prometheus_metrics(metrics: dict[str, int | float]) -> str:
    descriptions = {
        "uptime_seconds": "ServiceGuard process uptime in seconds.",
        "documents_total": "Indexed source documents.",
        "documents_quarantined": "Knowledge documents waiting for security review.",
        "chunks_total": "Indexed knowledge chunks.",
        "reports_total": "Persisted ticket quality reports.",
        "reports_pending_review": "Reports currently waiting for human review.",
        "reports_reviewed_total": "Reports with a completed human review decision.",
        "llm_call_logs_total": "Persisted LLM call log rows.",
        "audit_events_total": "Persisted audit events.",
        "batch_jobs_total": "Persisted background batch jobs.",
        "idempotency_records_total": "Persisted request idempotency records.",
        "batch_jobs_pending": "Background batch jobs waiting to run.",
        "batch_jobs_running": "Background batch jobs currently running.",
        "batch_jobs_active": "Background batch jobs currently pending or running.",
        "batch_jobs_active_limit": "Configured global active background batch job limit.",
        "batch_jobs_active_per_actor_limit": (
            "Configured per-requester active background batch job limit."
        ),
        "batch_jobs_interrupted": "Background batch jobs interrupted by process restart.",
        "batch_jobs_canceled": "Background batch jobs canceled by requesters.",
        "batch_jobs_timed_out": "Background batch jobs stopped after exceeding timeout.",
        "batch_jobs_failed": "Background batch jobs that failed.",
        "database_schema_current_version": "Current applied database schema version.",
        "database_schema_expected_version": "Expected database schema version for this app.",
        "database_schema_pending_migrations": "Pending database schema migration count.",
        "database_sqlite_quick_check_ok": "Whether SQLite PRAGMA quick_check reports ok.",
        "database_sqlite_foreign_keys_enabled": "Whether SQLite foreign key enforcement is on.",
        "database_sqlite_busy_timeout_ms": "Configured SQLite busy timeout in milliseconds.",
        "http_requests_total": "HTTP responses recorded by this process.",
        "http_error_responses_total": "HTTP 5xx responses recorded by this process.",
        "http_rate_limited_total": "HTTP 429 responses recorded by this process.",
        "http_latency_ms_sum": "Sum of HTTP response latency in milliseconds.",
        "http_latency_ms_count": "Number of HTTP responses with latency observations.",
        "http_latency_ms_max": "Maximum observed HTTP response latency in milliseconds.",
        "http_latency_ms_avg": "Average observed HTTP response latency in milliseconds.",
    }
    metric_types = {
        "http_requests_total": "counter",
        "http_error_responses_total": "counter",
        "http_rate_limited_total": "counter",
    }
    lines: list[str] = []
    for key, value in metrics.items():
        metric_name = f"serviceguard_{key}"
        lines.append(f"# HELP {metric_name} {descriptions[key]}")
        lines.append(f"# TYPE {metric_name} {metric_types.get(key, 'gauge')}")
        lines.append(f"{metric_name} {value}")
    return "\n".join(lines) + "\n"


def _add_rate_limit_headers(response: Response, limit: int, remaining: int) -> None:
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)


def _save_audit_event(database, request: Request, status_code: int, latency_ms: int) -> None:
    database.save_audit_event(
        event_id=f"audit_{uuid.uuid4().hex[:12]}",
        request_id=getattr(
            request.state, "request_id", request.headers.get("x-request-id", "unknown")
        ),
        actor_role=getattr(request.state, "actor_role", "anonymous"),
        actor_hash=getattr(request.state, "actor_hash", "none"),
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        latency_ms=latency_ms,
        client_host=request.client.host if request.client else None,
    )


def _rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("x-api-key", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        api_key = authorization.split(" ", maxsplit=1)[1].strip()
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        return f"api-key:{digest}"

    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_host = forwarded_for.split(",", maxsplit=1)[0].strip()
    if not client_host and request.client:
        client_host = request.client.host
    return f"ip:{client_host or 'unknown'}"


app = create_app()
