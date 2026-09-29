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

Documents can be supplied as text/Markdown JSON or authenticated multipart PDF, DOCX, XLSX, CSV, TXT and MD uploads. See FILE_UPLOADS.md for extraction limits. OCR is not included. No server-side fetching of arbitrary URLs occurs.

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


## File ingestion operations

See [FILE_UPLOADS.md](FILE_UPLOADS.md) for multipart routes, limits and parser cleanup. Restart the API after upgrading dependencies/routes, and restart Vite to pick up the longer upload proxy timeout. Successful files commit independently. Retry uncertain indexing outcomes with the same document ID. Monitor `ingest.parse` and `ingest.index` spans; no binary originals are retained.


## Latency controls

Defaults now search the original question first. The live rewrite call runs only when retrieval/reranking/context assembly selected no usable context. This removes one serial provider round trip from answerable questions. Set `RAG_REWRITE_MODE=always` for expansion on every live query, or `off` to disable expansion. Fallback expansion can cost an extra retrieval pass on misses; compare recall on your own evaluation set before changing policies.

```dotenv
RAG_REWRITE_MODE=fallback
RAG_NLI_BATCH_SIZE=4
RAG_ANSWER_CACHE_TTL_S=60
RAG_ANSWER_CACHE_MAX_ENTRIES=128
```

NLI inference deduplicates identical premise/claim pairs, scores them in smaller batches and maps scores back to every required check. Citation authenticity, entailment thresholds, conflict checks and review rules remain in force. Four-pair batches were faster on the tested CPU; benchmark other hardware before tuning.

Only released `answered` results enter the bounded process-local cache. Cache keys include the normalized question, tenant, groups, roles, subject, settings and the current tenant corpus revision. Ingestion, replacement and deletion update the revision in the same SQLite transaction as the index mutation. The next lookup consequently misses after a supported index change, including changes committed by another updated worker. API authentication and input validation still run on every request. Reviews, abstentions and errors are not cached. Each hit returns a copied answer with fresh request/trace IDs, current timings and zero new provider usage. The inspector explicitly labels reuse. Set TTL to `0` for uncached evaluation or sensitive deployments; restarting clears cached answers. Expired entries are removed on subsequent lookups, eviction or process exit, so TTL is a reuse limit, not a strict memory-erasure deadline.

Restart all API processes after upgrading: startup initializes the additive corpus revision table automatically. No document re-ingestion is needed for these latency changes. Do not mix old and new writers or edit the index with direct SQL: those operations do not bump revisions. Frontend changes are under the same project's `frontend/` directory; refresh the page after Vite reloads them.

For a local restart, stop the existing API in its terminal, then run:

```bash
cd /Users/sandeepkumarboda/projects/enterprise-rag
.venv/bin/uvicorn rag.app:app --host 127.0.0.1 --port 8000
```

Run a question twice and inspect Execution. The first run should omit Rewrite when original-query retrieval succeeds; the second should show cache reuse with no new provider attempts. Cache entries live per worker; concurrent identical requests are not coalesced. Provider latency, rate limits, answer repairs and conflict adjudication can still dominate slow requests. Inspect their stages before increasing concurrency or reducing context. Measure HTTP/browser p50/p95/p99 separately; the included benchmark measures pipeline execution with warm models, not full network or browser latency.


### Further first-answer latency improvements

Every CPU inference worker now warms the embedding, reranking and NLI models before readiness, using representative batched passages. This moves per-thread/kernel initialization out of the first query. Startup takes longer as a result.

`RAG_GENERATION_EVIDENCE_MODE=spans` (default) asks for short source references rather than copied quotes. Sentence/line spans partition the original text without dropping characters and remain grouped by source; these do not alter stored chunks or retrieval. The server resolves every reference, rejects unknown IDs, constructs exact quotes, restores canonical IDs and runs the existing full guard (including all retrieved-context contradiction checks). Long passages over the quote contract's 2,000-character limit use the original quote mode, without truncation. Repair requests keep the original quote contract. Citation granularity may now be a full sentence/line rather than a model-selected substring. The provider-only ReferencedGeneration schema is converted back to the unchanged public Generation/Answer schema.

`RAG_COMPACT_EVIDENCE_IDS=true` shortens provider-facing IDs. `RAG_GENERATION_EVIDENCE_MODE=quote` restores model-copied quotes for evaluation comparisons. Neither setting bypasses grounding or review rules. Span mode adds input reference labels while reducing output copying, so compare both latency and token cost on your corpus.

`RAG_GENERATION_REASONING_EFFORT` is unset by default for compatibility. The current configured gateway accepted `none` with the configured `gpt-6-luna` model; this deployment's private `.env` now explicitly enables it. Only initial generation receives this parameter. Rewriting, repairs, conflict adjudication and evaluation judgments retain their existing settings. Other providers/models may reject it; omit it unless supported. Lower reasoning trades deliberation for speed and requires representative quality evaluation. See the [official reasoning-effort documentation](https://developers.openai.com/api/docs/guides/reasoning).

The final exact-question test took 3.35 seconds (generation 2.47 seconds, verification 0.51 seconds). Two additional uncached variants with the same final settings took 2.85 and 3.35 seconds. These are pipeline samples, not a promise of sub-three-second responses. Provider queuing, retries and repairs still create outliers. See `latency-v2-benchmark.json`. The supplied `.env` is private and is never included in the downloadable bundle; configure this explicitly on another deployment.

Restart the existing backend to load code and `.env` changes. The frontend and persisted corpus require no changes for this update. A restart is required even if the page has already been refreshed.


### Stable document-Q&A profile (source-selection-v1)

The previous paraphrase-first path could reject a correct-looking answer because the generated claim added document-meta wording or changed tense/scope. Repair could then abstain, adding a second model round trip and hiding the original failure. Splitting at every PDF line break also separated one logical sentence into several references.

The default is now `RAG_ANSWER_STYLE=extractive`. The LLM chooses sentence IDs using semantic question understanding; the server constructs each answer claim and citation from the original indexed sentence. Sentence spans preserve wrapped PDF lines and all source characters. This is live semantic selection, not the offline demo's lexical extractor. Source authenticity, NLI entailment, all-context contradiction checks, authorization, input/output policies and high-risk review remain enabled. Unsupported extracted answers stay withheld; they never enter the generative repair loop. Unknown IDs, inconsistent selection/abstention and oversized selected sentences fail closed. Oversized retrieved chunks outside the span contract retain the quoted-generation fallback and are labeled synthesis.

This deliberately trades polished paraphrases, computed answers and synthesized summaries for directly auditable factual answers. If the answer is absent or requires unsupported inference, abstention remains correct. Set `RAG_ANSWER_STYLE=synthesis` when paraphrases are required, then evaluate that profile separately. In synthesis mode, an abstaining repair now preserves the initial failure and reports `repair_abstained` instead of replacing it with an unexplained `model_abstained` result.

Answers expose `answer_style` and `initial_verification_reasons`. The workbench labels exact output as **Source sentences** and displays initial verification failures in the inspector. `/health/ready` returns `pipeline_revision: source-selection-v1` and the configured answer style. The UI warns when connected to a backend that has not loaded this revision. After restarting FastAPI, use **Check again** in the banner or refresh the page. An old API returning only status/mode has not loaded the update. No document re-ingestion is required.

The private local `.env` explicitly enables extractive mode and retains the previously tested generation reasoning setting. The downloadable archive contains only safe `.env` examples. Latency remains dependent on the provider and local CPU contention; removing the repair path does not establish a guaranteed response time.
