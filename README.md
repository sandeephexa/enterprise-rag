# Evidence RAG — enterprise support knowledge assistant

This repository implements the requested eight-module Python system, with a durable hybrid index, grounded structured generation, claim-level evidence, evaluation gates and OpenTelemetry. The supplied screenshots informed the architecture; their instructional text was treated as reference material, not additional execution instructions.

Two explicit operating profiles exist: **live** uses real semantic embeddings, cross-encoder reranking, a separate NLI verifier and configured Responses-compatible model endpoints; **demo** uses deterministic offline substitutes to exercise system mechanics. Live mode is the default and refuses to start without identities and model configuration. No demo backend is silently substituted in live mode.

This is a complete implementation for a bounded, single-service deployment. Production acceptance still depends on corpus-specific calibration, load testing, identity provisioning, infrastructure security and live-provider validation. It does not guarantee hallucination-free output.

See [the executed validation record](VALIDATION.md) for the 117 passing backend tests, real neural smoke results, HTTP/telemetry checks and untested deployment boundaries.

For a hands-on walkthrough, use the [step-by-step testing guide](testing/TESTING_GUIDE.md). The `testing/` folder includes request payloads, separate demo/live evaluation datasets, and an isolated real-HTTP runner with 26 passing acceptance checks.

The [React workbench](frontend/README.md) provides query execution, evidence inspection, document ingestion and review decisions. Start it with `cd frontend && npm ci && npm run dev` after starting the API. Complete component code is collected in [the frontend code guide](frontend/FRONTEND_CODE_GUIDE.md).

Direct file ingestion supports PDF, Markdown, XLSX, DOCX, CSV and TXT. See [file upload setup, API contracts, parsing limits and end-to-end tests](FILE_UPLOADS.md).

## PART 1: SYSTEM DESIGN & PORTFOLIO DOCUMENTATION

### Problem statement and target enterprise use case

An enterprise support team must answer questions across policy documents, operating procedures and product guidance. Keyword-only search misses paraphrases; unconstrained generation can invent policy. Employees also have different access rights, so retrieval itself must enforce authorization.

The system answers only from accessible, versioned documents. Each released factual claim has exact supporting quotes and source offsets. Missing evidence produces abstention. Unsupported or conflicting claims, sensitive topics and degraded reranking route to a durable human review queue.

The business objective is lower handling time without increasing incorrect policy advice. Rollout should compare assisted and unassisted tickets using resolution time, verified answer rate, escalation rate and quality-review outcomes.

### Architectural flow

```mermaid
flowchart TD
    D[Authorized document ingestion] --> V[Validate and preserve source text]
    V --> C[Sentence / paragraph / semantic chunks]
    C --> I[Atomic SQLite vector + lexical index]
    Q[Authenticated query] --> G[Schema and input guardrails]
    G --> CACHED{Verified cache match}
    CACHED -->|Hit| O
    CACHED -->|Miss| A[Tenant and group filtered snapshot]
    I --> A
    A --> S[Semantic vector search]
    A --> B[BM25 keyword search]
    S --> R[Reciprocal rank fusion]
    B --> R
    R --> X[Cross-encoder reranking]
    X --> K[Threshold-based dynamic K]
    K --> T[Deduplicate and assemble bounded context]
    T -->|Evidence available| P[Structured grounded generation]
    T -->|No evidence, once| W[Bounded query expansion; retain original]
    W --> A
    P --> H[Exact evidence + NLI support + contradiction checks]
    H --> F{Release decision}
    F --> O[Deterministic cited answer]
    F --> N[Abstention]
    F --> U[Durable human review]
    E[Deadline / cost accounting / OTel] -.-> W
    E -.-> P
    E -.-> H
    O --> EV[Reference dataset and quality gates]
```

### Decisions and structural trade-offs

- **Transactional hybrid storage:** embeddings, token postings and chunk provenance commit in one SQLite transaction. Both retrievers rank the same authorized snapshot. Exact vector search is easy to audit and has no approximate-recall loss, but scan cost grows with the corpus. The default cap is 20,000 chunks per tenant; it is a guardrail, not a demonstrated capacity guarantee. Benchmark before increasing it. A large deployment should replace the `HybridStore` adapter with an access-filtered distributed vector/keyword service and versioned ingestion jobs.
- **Reciprocal rank fusion:** each candidate receives `sum(1 / (60 + rank))` across the semantic and BM25 rankings for the original query and up to two expansions. This avoids adding incompatible raw cosine and BM25 scores. More searches improve coverage but increase work and can introduce expansion drift. Reranking always uses the original question.
- **Latency policy:** search the original query first; expand only when no usable contexts were selected. `RAG_REWRITE_MODE=always` restores expansion on every live query for recall experiments; `off` disables it. Test this trade-off on your labeled corpus. Verified answers can be reused for 60 seconds under the same identity, settings and corpus revision. Supported document mutations invalidate the tenant cache; cache hits have fresh trace IDs and zero new provider usage. See the [latency operation notes](RUNBOOK.md#latency-controls) and [measured results](latency-benchmark.json).
- **Cross-encoder ranking:** a joint query-passage model scores up to 30 fused candidates. This is more expensive than vector similarity, but separates topical similarity from answer-bearing context. At most six chunks pass both an absolute score threshold and a relative-to-best threshold. No minimum K forces irrelevant chunks into the prompt. Sigmoid scores are not calibrated probabilities.
- **Chunk strategies:** sentence chunks favor precise evidence but lose surrounding conditions; paragraph chunks retain local explanations but may mix topics; semantic boundaries add embedding work during ingestion. A hard character cap and optional overlap apply. Exact source slices preserve provenance. The live embedding and pair models reject overlength inputs instead of silently truncating; reduce chunk/query lengths when rejected. Sentence boundary detection is deliberately a configurable simple regex, so evaluate abbreviations and multilingual corpora before use.
- **Document-Q&A default:** `RAG_ANSWER_STYLE=extractive` uses the LLM to select source sentence IDs; the server constructs answer wording and citations from those exact sentences. PDF line wraps remain within a sentence. Semantic embeddings, hybrid retrieval, reranking and full grounding checks remain enabled. This avoids the generation/repair loop for ordinary factual lookups. Use `synthesis` explicitly for generated paraphrases; exact excerpts are labeled in the workbench.
- **Optional compact synthesized generation:** the model returns claims and references to exact sentence/line spans. The server constructs quotes from the original indexed text and restores canonical chunk IDs before all grounding checks. Source text is fully preserved; the public answer/citation schema is unchanged. Set `RAG_GENERATION_EVIDENCE_MODE=quote` to use the original quote-emitting contract.
- **Separate evidence and entailment checks:** exact quote matching prevents fabricated citations. A local NLI model checks claim support and contradictions, independently of the generator. Neither quotes nor NLI constitute proof of truth; source quality, missing evidence and domain shift remain risks. Contradictory retrieved passages withhold the entire answer.
- **Whole-answer release:** the public answer is rendered exclusively from validated claims. There is no unvalidated summary field. A rejected claim withholds the whole draft, trading coverage for easier auditability.
- **Single process, bounded inference:** CPU work uses a fixed thread pool and admission permits. A timed-out worker retains its permit until it actually finishes, preventing a growing backlog of abandoned neural work. Threads cannot forcibly interrupt model execution; process isolation is appropriate for hard compute cancellation requirements.
- **OTel rather than dual tracing:** OpenTelemetry is the implemented observability integration. Collector exports support traces and metrics without coupling the application to LangSmith. Raw prompts, documents, API keys and generated text are excluded from telemetry.

### Failure cases and mitigation

- Missing/weak context: return a typed abstention without claims or invented citations.
- Wrong source, invented quote or unsupported paraphrase: exact-ID/substring checks plus NLI withhold the answer and persist a review.
- Conflicting policy versions in retrieved context: contradiction check triggers review. Source lifecycle management must retire obsolete documents; the system cannot detect a relevant conflict it never retrieved.
- Provider timeouts, 408, 429 and 5xx: bounded jittered backoff, numeric `Retry-After` handling and explicit endpoint fallback under the remaining deadline. Authentication/schema errors are not repeatedly retried against the same endpoint. Provider refusals stop fallback entirely.
- Invalid or incomplete model output: usage is recorded before schema parsing, then the next route is tried. No unparsed text reaches the caller.
- Unknown billing after timeout: reserve the conservative attempt estimate and increment `uncertain_attempts`. Known cost is never presented as a complete invoice when uncertainty remains. Prices must be operator-maintained; caching discounts are not assumed.
- Index failure or embedding mismatch: reject inconsistent startup/index operations. Document replacements and capacity failures roll back atomically. Deleting a document removes both representations.
- Prompt injection or malicious payload: schema and byte limits, control-character/pattern checks, untrusted-data prompts, no tool execution, and output verification provide defense in depth. Pattern filtering is intentionally limited and cannot establish that arbitrary text is safe. Domain-specific moderation and adversarial tests remain necessary.
- Tenant leakage: tenant comes from the server-owned bearer credential, never the query body. Group filtering happens before both retrieval algorithms. Review access requires the tenant and all originating groups.
- Overload: per-key request windows and bounded concurrent work return 429/503. These limits are process-local; distributed quotas belong at the gateway.
- Review persistence failure: return a dependency failure instead of claiming that review was queued. Decisions are recorded with reviewer identity and time; approval does not automatically publish an answer.

### Cost, latency and business impact metrics

The default overall pipeline budget is 20 seconds, with 1.5 seconds for optional rewriting, up to 3 seconds each for retrieval and reranking, a 3-second verification reserve, and a maximum 6 seconds per provider attempt. These are configurable upper bounds, not a promise that every stage receives its full allowance. HTTP body reception and administration/ingestion have separate limits.

Per request, the response exposes actual provider input/output token counts, known USD cost, reserved uncertain cost, attempts, elapsed latency and stage timings. Prompt sizing uses a conservative UTF-8 byte upper bound, including the JSON schema and framing allowance; this wastes some context capacity but avoids relying on an approximate word count. For a different tokenizer family, replace this bound with a verified tokenizer.

`known model cost = sum(input_tokens × input_rate + output_tokens × output_rate) / 1,000,000`.

Local embedding, reranking and NLI compute are represented by latency, not a fabricated token charge. Attribute infrastructure cost separately using CPU/GPU utilization, instance cost and throughput. Reconcile uncertain model charges against provider billing.

Initial **proposed release gates**, not measured enterprise results: faithfulness ≥0.95, reference-judged answer relevance ≥0.70, document precision ≥0.70, document recall ≥0.90, all fixture outcomes correct, no case errors/unknown billing, p95 within the configured deadline and mean known generation cost within budget. The supplied tiny fixture validates mechanics only; it is not statistically representative.

For business planning, monthly labor value can be estimated as `resolved_tickets × minutes_saved / 60 × hourly_cost`, then subtract inference, infrastructure and review cost. For example, 10,000 tickets saving 3 minutes at $30/hour implies **$15,000 hypothetical gross time value**, not measured savings. Track incorrect-answer rate and rework alongside time saved; abstentions and review labor must stay in the denominator.

## PART 2: MODULE-BY-MODULE EXPLANATIONS

### Input layer

`schemas.py`, `guardrails.py` and `pipeline.py` validate shape and length, normalize queries, filter suspicious content, retain the original query during expansion, and assemble only accessible bounded context. A toy implementation often accepts arbitrary text and trusts rewritten queries; a production service needs predictable contracts, a clear trust boundary and safe failure behavior.

### Hybrid retrieval engine

`ingestion.py` preserves source offsets, creates configurable chunks, computes normalized embeddings and stores a durable lexical representation. `retriever.py` executes cosine and Okapi BM25 ranking, fuses ranks, applies a cross-encoder, selects dynamic K, and deduplicates overlapping context. Atomic index updates, model identity checks and authorization before search protect consistency and isolation that a notebook usually ignores.

### Model execution and hallucination guard

`pipeline.py` owns deadlines, model request construction, strict JSON schemas, retries, fallback, cost reservations and deterministic release. `guardrails.py` verifies citation membership, exact quotes, NLI support and cross-context contradiction. In live mode, supported claims with suspected conflicts receive a bounded structured conflict assessment that distinguishes omissions from incompatible facts. Uncertain or failed assessments stay in review. The renderer appends numbered evidence references only after verification. Production behavior includes refusals, malformed outputs, uncertain billing and zero-evidence cases, not just successful completions.

### Evaluation suite

`evaluator.py` runs JSONL cases through the same pipeline, checks expected answer/abstention behavior and measures faithfulness, answer relevance, document-level precision/recall, latency and cost. It reports null for inapplicable scores instead of giving abstentions perfect faithfulness. Failures remain in denominators. Live relevance uses a reference-aware LLM judge; demo relevance is explicitly lexical F1. Runtime NLI is reused for faithfulness, so the metric is correlated with the guard and must be supplemented by human annotations or an independent evaluator for release decisions. CI runs tests and fixture evaluations on changes and a weekly schedule when the repository is hosted on GitHub.

### Observability

`app.py` provides a redacted ASGI tracing/logging boundary, health/readiness endpoints, OTLP trace/metric exporters, authentication and dependency injection. `pipeline.py` adds spans for rewrite, retrieve, rerank, generate, verify and each provider attempt; request, retry, token, latency and known-cost instruments support monitoring. Compose includes a collector, Jaeger trace UI and Prometheus. Full operational observability requires your deployment to collect these signals, retain them and attach alerts; merely creating spans is not sufficient.

## PART 3: PRODUCTION IMPLEMENTATION CODE

All code is implemented in the repository; no omitted functions, placeholder bodies or pseudocode are required to run the demo or configured live profile.

1. [`rag/config.py`](rag/config.py): environment-backed settings, secrets, model routes, rates, limits and startup invariants.
2. [`rag/schemas.py`](rag/schemas.py): strict request, source, evidence, output, usage and evaluation contracts.
3. [`rag/ingestion.py`](rag/ingestion.py): three chunking modes, local embedding adapters, transactional hybrid storage and review persistence.
4. [`rag/retriever.py`](rag/retriever.py): BM25, vector search, fusion, cross-encoder ranking, threshold K and context assembly.
5. [`rag/pipeline.py`](rag/pipeline.py): rewriting, prompts, structured HTTP model calls, budgets, retries/fallbacks and final answer construction.
6. [`rag/guardrails.py`](rag/guardrails.py): input/content rules, evidence verification, NLI checks and deterministic citation formatting.
7. [`rag/evaluator.py`](rag/evaluator.py): dataset runner, reference-based metrics, aggregate reports and release gates.
8. [`rag/app.py`](rag/app.py): FastAPI factory, authentication, authorization, rate/admission control, ingestion/query/review endpoints and telemetry.

Additional deliverables: tests, a hash-bearing `uv.lock`, example corpus/evaluations, Docker/Compose, OTel/Prometheus configuration, CI workflow, neural smoke script, and an operations runbook.

### Run the offline profile

Requires Python 3.12 and `uv`. Run commands from this repository directory:

```bash
uv sync --frozen --extra dev
cp .env.example .env
uv run python examples/seed.py
uv run uvicorn rag.app:app --host 127.0.0.1 --port 8000 --log-config logging.json
```

In another terminal:

```bash
curl http://127.0.0.1:8000/query \
  -H 'Authorization: Bearer demo-only-change-before-sharing-12345' \
  -H 'Content-Type: application/json' \
  -d '{"text":"Enterprise support available hours"}'

uv run pytest -q
uv run rag-eval examples/eval.jsonl --output eval-report.json
```

The public demo credential is for loopback development only. The generated answer is an exact extraction in demo mode, not an LLM-generated answer. API schema documentation is served at `/docs`.

### Run the live profile

```bash
uv sync --frozen --extra neural --extra dev
cp .env.live.example .env
# Configure real access tokens, API endpoint(s), model IDs and actual price rates.
# Pin the three local model revisions and use a separate live database.
uv run python examples/neural_smoke.py
uv run python examples/seed.py
uv run uvicorn rag.app:app --host 127.0.0.1 --port 8000 --log-config logging.json
```

Provision a second endpoint object in `RAG_ENDPOINTS` to enable endpoint failover. Each route must support the Responses API's strict JSON-schema output format. No live generator request was necessary for the offline test suite.

For local observability, `docker compose up --build` runs the configured profile plus Jaeger at `http://127.0.0.1:16686` and Prometheus at `http://127.0.0.1:9090`. The API remains bound to loopback. Use the [operations runbook](RUNBOOK.md) for production deployment and alerts.

### Verified API and model references

The HTTP generator integration uses the Responses API `text.format` strict JSON-schema contract and handles refusal/incomplete outputs explicitly. See [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Reranking uses joint query/passage inference with an explicit sigmoid activation; scores require calibration on your corpus. See [Sentence Transformers cross-encoder usage](https://sbert.net/docs/cross_encoder/usage/usage.html).

The default verifier uses the model card's contradiction/entailment/neutral label ordering. See [NLI DeBERTa model card](https://huggingface.co/cross-encoder/nli-deberta-v3-small).

Trace/metric providers use OTLP/HTTP exporters and batch/periodic export. See [OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/).
