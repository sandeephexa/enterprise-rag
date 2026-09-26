"""Validate emitted OTel spans/metrics without an external collector or paid model call."""

import asyncio
import json
import tempfile
from pathlib import Path

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag.app import build_pipeline
from rag.config import Settings
from rag.schemas import Document, Principal, Query


async def main():
    spans = InMemorySpanExporter()
    trace_provider = TracerProvider()
    trace_provider.add_span_processor(SimpleSpanProcessor(spans))
    trace.set_tracer_provider(trace_provider)
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(mode="demo", database_path=Path(directory) / "index.db")
        pipeline = build_pipeline(settings)
        principal = Principal(tenant="test", groups=["staff"], roles=["query", "ingest"])
        try:
            document = Document(
                id="test",
                title="Policy",
                source="urn:test",
                groups=["staff"],
                text="Support is available 24 hours a day.",
            )
            pipeline.store.ingest([document], principal)
            answer = await pipeline.run(Query(text="Support available hours"), principal)
            finished = spans.get_finished_spans()
            names = [span.name for span in finished]
            assert {"rag.query", "retrieve", "rerank", "generate", "verify"}.issubset(names)
            assert all(document.text not in json.dumps(dict(span.attributes)) for span in finished)
            data = reader.get_metrics_data()
            metric_names = [
                metric.name
                for resource in data.resource_metrics
                for scope in resource.scope_metrics
                for metric in scope.metrics
            ]
            assert {"rag.requests", "rag.latency_ms", "rag.known_cost_usd"}.issubset(metric_names)
            assert answer.trace_id != "0" * 32
            print(
                json.dumps(
                    {
                        "passed": True,
                        "span_names": names,
                        "metric_names": metric_names,
                        "scope": "In-memory SDK emission; external OTLP collector not tested",
                    },
                    indent=2,
                )
            )
        finally:
            await pipeline.gateway.close()
            pipeline.workers.close()
    meter_provider.shutdown()
    trace_provider.shutdown()


asyncio.run(main())
