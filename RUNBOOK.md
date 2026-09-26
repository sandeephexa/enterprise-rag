# Operating Evidence RAG

## Release procedure

1. Install from `uv.lock`; run lint, unit/integration tests and the offline evaluation. Record the git revision with the evaluation artifact. Pin container images to scanned digests in your deployment.
2. Replace all example secrets/model identifiers/rates. Use separate query, ingestion and reviewer credentials. Secrets are not committed or printed. Put the API behind TLS, a trusted identity gateway and distributed rate limits. Static bearer mapping is suitable for a controlled service deployment; user federation, key rotation and revocation should use your existing identity system.
3. Pin local model revisions to approved commit hashes. Prefetch models into your deployment image or persistent cache, set `RAG_LOCAL_MODELS_ONLY=true`, and record model licenses and artifact hashes. Changing the embedding model requires a new index/database, followed by evaluation and a deployment switch.
4. Supply a representative, versioned evaluation set with document relevance labels, correct reference answers and unanswerable cases. Include abbreviations, numbers, negation, contradictory documents, denied permissions and prompt injection. Review NLI false positives/negatives manually. Tune thresholds on a development split; report a held-out test split.
5. Run live-provider contract tests with approved credentials, a bounded spend limit and both configured routes. Confirm actual pricing and token context limits. Streaming is intentionally absent: no unverified draft is released.
6. Load test your chosen corpus and hardware. Measure request latency, event-loop responsiveness, CPU queue pressure, throughput, memory and ingestion/query contention. Set the tenant cap below the observed safe limit. This implementation has not established a 20,000-chunk production performance envelope.
7. Attach the collector and verify traces, metrics, redacted JSON logs, failure alerts, backups and review ownership before exposing the service.

## Deployment boundaries

Use one Uvicorn worker per container with a local durable filesystem. SQLite WAL supports local concurrency, not multi-host shared network filesystem writes. Scale the storage adapter and rate limits before horizontally scaling this deployment. Schema version 1 is initialized on startup; future schema changes require an explicit migration.

The Docker image is non-root; model files and the database live on `/app/data`. Secure volume permissions and encryption through the platform. Model loading occurs at startup; readiness is unavailable until it succeeds. Health checks verify local readiness, not every upstream provider's health.

Inference defaults to CPU. Set `RAG_INFERENCE_DEVICE=cuda` only after testing your accelerator stack. Startup warms all three neural adapters before readiness. The reranker materializes contiguous parameter storage: on the tested macOS runtime, its original safetensors-backed parameter storage caused non-finite outputs and occasional pooler failures; materializing the same weights resolved the controlled comparison. Re-run the neural smoke test after runtime upgrades.

Document ingestion is an administrative synchronous operation capped at 120 seconds. Because Python threads cannot be killed, an ingestion request that times out may still finish its atomic transaction; retrying the same document IDs is idempotent. Use a background job service for large imports and cancellation requirements. The 20-document/1 MB HTTP body limits are deliberate.

Documents are UTF-8 text/Markdown supplied as JSON. Binary PDF, DOCX and OCR extraction are outside this service's ingestion contract. Extract and review text upstream, preserving your original source URI. No server-side fetching of arbitrary URLs occurs.

Input patterns target obvious instruction injection and credential exfiltration. They are not a universal moderation classifier. Deploy content policies appropriate to your data and jurisdiction. NLI is English-focused and does not certify factual accuracy, policy correctness or source freshness.

## Useful monitoring queries

Collector's default Prometheus name translation turns dots into underscores and adds counter suffixes. Verify exported names on your collector version before installing alerts.

```promql
# Pipeline p95 in milliseconds over five minutes
histogram_quantile(0.95, sum by (le) (rate(rag_latency_ms_bucket[5m])))

# Request outcomes per second
sum by (status) (rate(rag_requests_total[5m]))

# Known provider spend, USD per hour (not a reconciled invoice)
sum(rate(rag_known_cost_usd_total[1h])) * 3600

# Token consumption by direction and model
sum by (direction, model) (rate(rag_tokens_total[5m]))

# Provider retries per second
sum by (endpoint) (rate(rag_provider_retries_total[5m]))
```

Inspect `http.request` → `rag.query` → stage spans and `llm.attempt` spans in Jaeger. Both HTTP response headers and answer JSON expose trace IDs. HTTP and pipeline request IDs are distinct correlation identifiers; the trace ID joins them. Application logs do not include raw request paths for unrecognized routes, query strings, prompts, source text or credentials.

Suggested alerts: p95 above deadline for sustained intervals; elevated 5xx/429 ingress rate; provider retry spikes; sudden abstention/review-rate shifts; index capacity approaching its configured bound; missing collector data; stale review backlog; rising uncertain billing. HTTP status/latency are captured in spans/logs; derive ingress SLOs at the gateway or collector rather than only counting successful pipeline returns.

Telemetry export failures do not fail user requests. Exporters use bounded batches and short timeouts; a disconnected collector can lose telemetry, so monitor it separately. The supplied Jaeger/Prometheus containers are a development observation stack without durable retention, authentication or alert routing.

## Review workflow

`GET /reviews` returns at most 100 recent records for the reviewer's tenant and authorized groups. Records include the question, accessible context, reasons, and a draft only when it passed grounding. Rejected claims are not retained as valid drafts. `POST /reviews/{id}/decision` accepts `approve`/`reject` plus a note and records reviewer identity and UTC time. Decisions are one-way for a pending record and do not auto-release or send answers. A reviewer can document the corrected response in the note or use the existing support system to respond.

The review queue stores sensitive questions and source snapshots. Use encrypted storage, scoped reviewer credentials and an organization-defined retention policy. Deleting a source document does not delete historical review records; process legal/retention deletion explicitly in both stores. Historical reviews preserve the source state used for the original decision.

## Failure recovery

- Provider outage: check route spans and error category, credentials, quota and actual model availability. Retries are bounded; configure a provisioned fallback route. Refusals intentionally never fail over.
- Excess abstention: inspect authorized retrieval results, labels, chunk size and reranking thresholds before changing generation prompts. Preserve zero-result behavior.
- Verification rejects valid answers: inspect the NLI model's domain fit, quote granularity and input length. Never lower thresholds just to maximize answer rate; use labeled development data.
- High latency: reduce reranking candidates and context, provision inference hardware, or move inference to a separately bounded service. Disabling reranking in this implementation routes answers to review.
- Index corruption/mismatch: stop ingestion, restore a consistent SQLite backup or rebuild into a new database from authoritative documents. Do not load vectors produced by a different encoder into an existing index.
- Backups: use SQLite's online backup API or stop the service and take a consistent database snapshot including WAL state. Do not copy only the main file during active writes. Test restoration.

## Evaluation interpretation

Document-level precision and recall compare distinct retrieved document IDs with human labels. They are not token-level context metrics or Ragas scores. Missing gold labels make recall null; abstention makes faithfulness/relevance null. Success-rate gates prevent selective answering from making quality averages look artificially high.

Live relevance judging is an additional model call with separate cost and latency. Known generation cost includes rewriting and retries with reported usage. Unknown attempt billing fails the evaluation gate. Averages do not imply statistical confidence; report dataset size, stratified results, bootstrap intervals and human review for consequential releases.

The GitHub workflow runs weekly offline regression after you host this repository. For continuous live evaluation, run `rag-eval` on a scheduled CI runner with protected secrets, approved sample data and spending limits; no external automation or paid calls are created by this project delivery.
