"""FastAPI composition root, authorization, bounded HTTP ingress and OTel export."""

import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .config import Settings
from .guardrails import DemoEntailment, HallucinationGuard, NeuralEntailment, RejectedInput
from .ingestion import DemoEncoder, HybridStore, SemanticEncoder
from .pipeline import CPUWorkers, ModelGateway, RAGPipeline
from .retriever import CrossEncoderRanker, DemoRanker, HybridRetriever
from .schemas import Answer, IngestRequest, Principal, Query, ReviewDecision

LOGGER = logging.getLogger("rag.audit")
SECURITY = HTTPBearer(auto_error=False)


def build_pipeline(settings: Settings) -> RAGPipeline:
    """Load models once at startup; live mode never silently substitutes demo models."""
    encoder = DemoEncoder() if settings.mode == "demo" else SemanticEncoder(settings)
    ranker = DemoRanker() if settings.mode == "demo" else CrossEncoderRanker(settings)
    nli = DemoEntailment() if settings.mode == "demo" else NeuralEntailment(settings)
    if settings.mode == "live":
        # Warm up all adapters before readiness, detecting kernel/model incompatibility.
        encoder.encode(["Service readiness check."])
        ranker.score([("Service readiness", "Service readiness check.")])
        nli.scores([("Service is ready.", "Service is ready.")])
    store = HybridStore(settings, encoder)
    return RAGPipeline(
        settings,
        store,
        HybridRetriever(settings, store, encoder, ranker),
        HallucinationGuard(settings, nli),
        ModelGateway(settings),
        CPUWorkers(settings.cpu_workers),
    )


def configure_telemetry(settings: Settings) -> tuple[TracerProvider, MeterProvider]:
    """Export redacted spans and metrics via OTLP/HTTP when a collector is configured."""
    resource = Resource.create({"service.name": settings.service_name, "service.version": "1.0.0"})
    tracer = TracerProvider(resource=resource)
    readers = []
    if settings.otlp_endpoint:
        base = settings.otlp_endpoint.rstrip("/")
        tracer.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=base + "/v1/traces", timeout=2))
        )
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=base + "/v1/metrics", timeout=2),
                export_interval_millis=10000,
            )
        )
    meter = MeterProvider(resource=resource, metric_readers=readers)
    trace.set_tracer_provider(tracer)
    metrics.set_meter_provider(meter)
    return tracer, meter


class IngressMiddleware:
    """ASGI middleware rejects oversized/chunked bodies before JSON parsing, traces errors."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings: Settings = scope["app"].state.settings
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        # Never let caller-controlled path/query/header values become metric labels or logs.
        path = scope.get("path", "")
        route = (
            path
            if path in {"/query", "/ingest", "/reviews", "/health/live", "/health/ready"}
            else "/other"
        )
        headers = {k.decode("latin1"): v.decode("latin1") for k, v in scope.get("headers", [])}
        parent = TraceContextTextMapPropagator().extract(headers)
        status = 500
        with trace.get_tracer(__name__).start_as_current_span(
            "http.request",
            context=parent,
            kind=trace.SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            async def wrapped_send(message: dict) -> None:
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                    message["headers"] = list(message.get("headers", [])) + [
                        (b"x-request-id", request_id.encode()),
                        (b"x-trace-id", f"{span.get_span_context().trace_id:032x}".encode()),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                await send(message)

            try:
                try:
                    declared = int(headers.get("content-length", "0"))
                except ValueError:
                    declared = -1
                if declared < 0 or declared > settings.max_body_bytes:
                    await JSONResponse({"detail": "Invalid or oversized body"}, status_code=413)(
                        scope, receive, wrapped_send
                    )
                    return
                body = bytearray()
                async with asyncio.timeout(5):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > settings.max_body_bytes:
                            await JSONResponse(
                                {"detail": "Request body too large"}, status_code=413
                            )(scope, receive, wrapped_send)
                            return
                        if not message.get("more_body", False):
                            break
                delivered = False

                async def replay() -> dict:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, wrapped_send)
            except TimeoutError:
                await JSONResponse({"detail": "Request timed out"}, status_code=408)(
                    scope, receive, wrapped_send
                )
            finally:
                span.set_attribute("http.request.method", scope["method"])
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(trace.StatusCode.ERROR)
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "trace_id": f"{span.get_span_context().trace_id:032x}",
                            "route": route,
                            "status": status,
                            "latency_ms": round((time.monotonic() - started) * 1000, 2),
                        }
                    )
                )


async def identity(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(SECURITY)]
) -> Principal:
    supplied = credentials.credentials if credentials else ""
    match = None
    for key in request.app.state.settings.access_keys:
        if hmac.compare_digest(
            supplied.encode("utf-8"), key.token.get_secret_value().encode("utf-8")
        ):
            match = key
    if match is None:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    # Bounded by configured key count, not by attacker-selected identities.
    key_id = hashlib.sha256(supplied.encode()).hexdigest()
    window = request.app.state.rate_windows[key_id]
    now = time.monotonic()
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= 60:
        raise HTTPException(429, "Request limit exceeded", headers={"Retry-After": "60"})
    window.append(now)
    return Principal(
        tenant=match.tenant, groups=match.groups, roles=match.roles, subject=key_id[:16]
    )


def require(role: str):
    async def authorized(principal: Annotated[Principal, Depends(identity)]) -> Principal:
        if role not in principal.roles:
            raise HTTPException(403, "Insufficient privileges")
        return principal

    return authorized


async def pipeline_dependency(request: Request):
    slots = request.app.state.slots
    try:
        await asyncio.wait_for(slots.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(503, "Service busy", headers={"Retry-After": "1"}) from exc
    try:
        yield request.app.state.pipeline
    finally:
        slots.release()


def create_app(
    settings: Settings | None = None, pipeline: RAGPipeline | None = None, telemetry: bool = True
) -> FastAPI:
    """Factory supports dependency injection without loading neural models in tests."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config = settings or Settings()
        application.state.settings = config
        providers = configure_telemetry(config) if telemetry else ()
        application.state.pipeline = pipeline or await asyncio.to_thread(build_pipeline, config)
        application.state.slots = asyncio.Semaphore(config.max_concurrent_requests)
        application.state.rate_windows = defaultdict(deque)
        try:
            yield
        finally:
            await application.state.pipeline.gateway.close()
            await asyncio.to_thread(application.state.pipeline.workers.close)
            for provider in providers:
                await asyncio.to_thread(provider.shutdown)

    application = FastAPI(title="Evidence RAG", version="1.0.0", lifespan=lifespan)
    application.add_middleware(IngressMiddleware)

    @application.exception_handler(RequestValidationError)
    async def schema_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse({"detail": "Request schema validation failed"}, status_code=422)

    @application.exception_handler(RejectedInput)
    async def policy_error(_request: Request, _exc: RejectedInput):
        return JSONResponse({"detail": "Content requires security review"}, status_code=400)

    @application.exception_handler(ValueError)
    async def invalid_data(_request: Request, _exc: ValueError):
        return JSONResponse({"detail": "Input or index configuration is invalid"}, status_code=422)

    async def dependency_error(_request: Request, _exc: Exception):
        return JSONResponse({"detail": "Service dependency unavailable"}, status_code=503)

    application.add_exception_handler(sqlite3.Error, dependency_error)
    application.add_exception_handler(TimeoutError, dependency_error)
    application.add_exception_handler(RuntimeError, dependency_error)

    @application.get("/health/live")
    async def live():
        return {"status": "alive"}

    @application.get("/health/ready")
    async def ready(request: Request):
        def probe():
            with request.app.state.pipeline.store.connect() as db:
                db.execute("SELECT 1").fetchone()

        await request.app.state.pipeline.workers.run(probe, timeout=1)
        return {"status": "ready", "mode": request.app.state.settings.mode}

    @application.post("/query", response_model=Answer)
    async def query_endpoint(
        query: Query,
        principal: Annotated[Principal, Depends(require("query"))],
        service: Annotated[RAGPipeline, Depends(pipeline_dependency)],
    ):
        return await service.run(query, principal)

    @application.post("/ingest")
    async def ingest_endpoint(
        batch: IngestRequest,
        principal: Annotated[Principal, Depends(require("ingest"))],
        service: Annotated[RAGPipeline, Depends(pipeline_dependency)],
    ):
        # Ingest is an administrative operation with a separate 120-second deadline.
        count = await service.workers.run(
            service.store.ingest, batch.documents, principal, timeout=120
        )
        return {"indexed_chunks": count}

    @application.delete("/documents/{document_id}")
    async def delete_endpoint(
        document_id: str,
        principal: Annotated[Principal, Depends(require("ingest"))],
        service: Annotated[RAGPipeline, Depends(pipeline_dependency)],
    ):
        count = await service.workers.run(
            service.store.delete, document_id, principal.tenant, timeout=5
        )
        return {"deleted_chunks": count}

    @application.get("/reviews")
    async def review_endpoint(
        principal: Annotated[Principal, Depends(require("review"))],
        service: Annotated[RAGPipeline, Depends(pipeline_dependency)],
    ):
        return await service.workers.run(service.store.reviews, principal, timeout=5)

    @application.post("/reviews/{request_id}/decision")
    async def decision_endpoint(
        request_id: str,
        decision: ReviewDecision,
        principal: Annotated[Principal, Depends(require("review"))],
        service: Annotated[RAGPipeline, Depends(pipeline_dependency)],
    ):
        if not await service.workers.run(
            service.store.decide, request_id, decision, principal, timeout=5
        ):
            raise HTTPException(404, "Pending review not found")
        return {"recorded": True}

    return application


app = create_app()
