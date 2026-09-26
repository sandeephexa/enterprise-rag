# Step-by-step RAG testing strategy

Run from the `enterprise-rag` repository directory. Start with deterministic behavior, then real neural models, then live generation. The offline demo uses hashed word vectors, lexical reranking and exact extracts; it cannot establish semantic or LLM quality.

## 1. Install and run the existing regression suite

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run pytest -q
```

Expected baseline: **34 passing tests**. Tests create temporary databases and mock provider HTTP responses. No API credentials or paid calls are required.

For faster diagnosis, run one layer:

```bash
uv run pytest -q tests/test_ingestion_retrieval.py
uv run pytest -q tests/test_guardrails_pipeline.py
uv run pytest -q tests/test_gateway.py tests/test_live_orchestration.py
uv run pytest -q tests/test_app_evaluator.py tests/test_authorization_observability.py
```

Failures should be fixed before interpreting downstream quality metrics. For example, bad source offsets are an ingestion defect, not something to repair with a generation prompt.

## 2. Run the isolated API acceptance checks

```bash
uv run python testing/run_api_checks.py --output work/testing/api-checks.json
```

This command starts a real Uvicorn server on a temporary loopback port, creates a temporary index, runs **26 assertions**, stops the server and deletes its temporary database. It does not touch your configured index or call a model provider. Exit code 0 means all checks passed; the JSON report lists each result. The runner ignores inherited `RAG_*` settings and applies its own demo configuration.

The checks cover 401/403 authorization, malformed input, oversized bodies, injection patterns, empty-index abstention, ingestion, idempotency, exact source offsets, citation coverage, trace propagation, unknown queries, group ACLs, tenant isolation with identical document IDs, review persistence/decisions, updates and tenant-scoped deletion.

## 3. Start a manual testing instance

Use a dedicated terminal and a fresh test database. `testing/demo.env` is shell-compatible and contains four public synthetic identities; it does not replace your existing `.env`.

```bash
set -a
. testing/demo.env
set +a
uv run uvicorn rag.app:app --host 127.0.0.1 --port 8000 --log-config logging.json
```

For a second experiment, choose a new database path before starting the server, for example `export RAG_DATABASE_PATH=data/testing-round2.sqlite3`. Do not reuse a live embedding database for demo mode or vice versa. If port 8000 is occupied, stop your earlier test server or choose a different port.

In another terminal, define:

```bash
BASE=http://127.0.0.1:8000
ADMIN=test-admin-acme-000000000000000001
STAFF=test-staff-acme-000000000000000002
HR=test-hr-acme-000000000000000000003
OTHER=test-admin-other-000000000000000004
mkdir -p work/testing
curl -sS "$BASE/health/ready"
```

Expected: `{"status":"ready","mode":"demo"}`. Keep the public test credentials on loopback only.

## 4. Ingest known ground-truth data

The baseline payload is `testing/payloads/documents.json`. It contains:

- `support`: support operates 24 hours/day; ticket response within 2 hours.
- `billing`: annual subscriptions billed in advance; dispute deadline 30 days.
- `onboarding`: security training within 7 days; managers approve access.

Every document includes `id`, `title`, `source`, `groups` and `text`. The API accepts a `documents` array, not a file upload.

```bash
curl -sS -X POST "$BASE/ingest" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  --data-binary @testing/payloads/documents.json
```

Expected with the default paragraph strategy: `{"indexed_chunks":3}`. Repeat the request; it should still report 3, with no duplicate chunks. This result counts the incoming batch, not the complete database. The regression suite verifies persisted idempotency.

## 5. Check answers and provenance

```bash
curl -sS -D work/testing/headers.txt -o work/testing/answer.json \
  "$BASE/query" -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' \
  --data-binary @testing/payloads/query-support.json
uv run python -m json.tool work/testing/answer.json
```

Request: `{"text":"Enterprise support available hours"}`.

Check all of the following, rather than only HTTP status:

1. HTTP 200 and `status == "answered"`.
2. The answer says 24 hours/day and does not invent a price or policy.
3. Every claim has evidence and at least one citation whose `claim_index` points to it.
4. `quote` exactly equals the original document slice `text[start:end]`. Offsets are Python character offsets, not UTF-8 byte offsets.
5. Citation `chunk_id` belongs to the returned contexts; its document ID and version match.
6. `trace_id` is nonzero and matches the `x-trace-id` response header.
7. `mode` is demo, model token usage/cost are zero, and stage timings are present. Zero demo cost does not predict live cost.

HTTP 200 also represents `abstained` and `review` outcomes. Treat these as distinct product results.

## 6. Exercise negative inputs and missing evidence

Use the same query command with each fixture. Add `-w '\nHTTP %{http_code}\n'` to display the status code.

- `query-unknown.json`: `{"text":"Interplanetary banana quantum"}`. Expect HTTP 200, `status=abstained`, empty claims/citations.
- `query-invalid.json`: `{"text":"hi"}`. Expect HTTP 422 because the minimum query length is 3.
- `query-tenant-spoof.json`: includes a `tenant` field. Expect HTTP 422; callers cannot select a tenant in the request body.
- `query-injection.json`: asks to ignore previous instructions and reveal the system prompt. Expect HTTP 400 from the configured pattern policy. This tests a known pattern, not universal injection resistance.
- Send a valid query without authorization: expect HTTP 401.
- Call `/ingest` with `$STAFF`: expect HTTP 403.
- POST `document-injection.json` to `/ingest`: expect HTTP 400.

The isolated runner also creates a 1,000,001-byte body and asserts HTTP 413. A 2,001-character query should instead fail schema validation with HTTP 422 when within the overall body limit.

## 7. Prove group and tenant isolation

```bash
curl -sS "$BASE/ingest" -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' --data-binary @testing/payloads/restricted.json
curl -sS "$BASE/query" -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' --data-binary @testing/payloads/query-hr.json
curl -sS "$BASE/query" -H "Authorization: Bearer $HR" \
  -H 'Content-Type: application/json' --data-binary @testing/payloads/query-hr.json
```

The restricted fixture says `JADE retirement allocation is 450 units` and belongs only to `hr`. Staff must not receive `hr-private` in **contexts, claims or citations**. HR should retrieve it and receive the answer. Checking only the final answer is insufficient because contexts are also returned by this API.

Then ingest `other-tenant.json` using `$OTHER`. It deliberately uses the same document ID, `support`, but states 9 hours/day and includes marker `ORCHID`. Query using `$STAFF` and `$OTHER`. The first tenant must still see its own 24-hour policy and never the other tenant's marker; the other tenant should see its own 9-hour policy.

## 8. Verify human review, updates and deletion

```bash
curl -sS "$BASE/query" -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' \
  --data-binary @testing/payloads/query-review.json > work/testing/review.json
curl -sS "$BASE/reviews" -H "Authorization: Bearer $ADMIN"
RID=$(uv run python -c 'import json; print(json.load(open("work/testing/review.json"))["request_id"])')
curl -sS "$BASE/reviews/$RID/decision" -H "Authorization: Bearer $ADMIN" \
  -H 'Content-Type: application/json' --data-binary @testing/payloads/review-decision.json
```

The synthetic query contains the high-risk keyword `medical`. Expect `status=review`, a `high_risk_topic` reason, empty released claims/citations and a persistent review record. The decision returns `{"recorded":true}`. A duplicate decision returns 404. Decisions do not automatically send or publish answers.

Next, POST `update-support.json` to `/ingest` using `$ADMIN`. It replaces the policy with 8 hours/day and a 4-hour response time. Requery: citations should have a new content version and use the updated source. Delete it:

```bash
curl -sS -X DELETE "$BASE/documents/support" -H "Authorization: Bearer $ADMIN"
```

Expect one deleted chunk under the default fixture configuration, and no `support` document in this tenant's subsequent contexts. The other tenant's document must remain available. Reingest `documents.json` before evaluating the original baseline, because its expected answers still say 24 and 2 hours.

## 9. Test hallucinations, provider failures and budgets deterministically

These require dependency injection, not an extra `/query` parameter. The API intentionally does not accept fake contexts, generation outputs or tenant overrides.

```bash
uv run pytest -v tests/test_guardrails_pipeline.py tests/test_gateway.py tests/test_live_orchestration.py
```

The existing tests inject an unknown chunk ID, a nonexistent source quote, and an unsupported claim with a real quote; none may become a released answer. A controlled NLI backend flags a contradictory uncited passage and verifies withholding. Mocked HTTP exercises 429 with numeric Retry-After, fallback, malformed JSON with usage tracking, 401 without repeated retry, refusal without fallback, cost exhaustion before a call, and deadline exhaustion. CPU timeout tests ensure work does not release capacity until it truly finishes.

Do not rely on asking a real model to hallucinate or on deliberately breaking a production API key to prove these branches. Use reproducible injected faults first. Real-provider behavior is a later integration test.

## 10. Run the evaluation datasets

The CLI accesses the local configured index directly, not the HTTP server. Load the **same environment and database** used for ingestion:

```bash
set -a
. testing/demo.env
set +a
# Restore the baseline if you ran update/delete tests. This uses the first identity.
uv run python examples/seed.py
uv run rag-eval testing/eval-basic.jsonl --output work/testing/eval-basic.json
```

Expected on the baseline: four cases, three answered, one abstained, `gates_passed=true`, exit code 0. Demo faithfulness is exact extraction and demo relevance is lexical F1; the passing result is a mechanics check.

Each evaluation row has this schema:

```json
{"id":"support-hours","query":{"text":"Enterprise support available hours"},"relevant_document_ids":["support"],"reference_answer":"Enterprise support is available 24 hours a day. Tickets receive a response within 2 hours.","should_abstain":false}
```

`eval-live.jsonl` supplies nine semantic-quality cases: paraphrases, numeric deadlines, who-approves questions, a false premise, an unknown CEO and an unsupported price. Run it after configuring live mode; passing is a target to measure, not an assumed result. Guardrail/review scenarios remain in API tests because the current `EvalCase` schema supports answer versus abstention, not an expected-review label.

## 11. Validate real models and then live generation

First, no paid generator call:

```bash
uv sync --frozen --extra dev --extra neural
uv run python examples/neural_smoke.py --output work/testing/neural-smoke.json
```

Expected: `passed=true`, relevant embeddings/reranker scores exceed unrelated ones, supported claims have strong entailment, and negated claims have strong contradiction. The first run downloads pinned models. This test covers only a few cases, not corpus-wide quality. Run the ingestion tests with all three chunk strategies; before adopting semantic chunking, add representative long documents and measure retrieval quality and ingestion time on separate rebuilt indexes.

Then open a **fresh terminal** so the exported demo variables do not override your live configuration. Configure `.env` from `.env.live.example` without overwriting existing secrets; supply real endpoint credentials, a supported model ID and your actual pricing. Keep the pinned local model revisions, set `RAG_MODE=live`, and use a separate live-testing database. Changing only `RAG_MODE` in the demo terminal is insufficient because it still exports `RAG_ENDPOINTS=[]`.

```bash
uv run python examples/seed.py
uv run rag-eval testing/eval-live.jsonl --output work/testing/eval-live.json
```

This makes paid rewrite, generation and relevance-judge calls. Inspect per-case errors, abstention behavior, token usage, generation cost, separate judge cost, uncertain billing and latency. Human-review every fixture initially. Runtime faithfulness reuses the same NLI verifier, so supplement it with an independent annotated test set rather than treating it as independent proof.

Initial gates are faithfulness ≥0.95, relevance ≥0.70, document precision ≥0.70, document recall ≥0.90, all fixture outcomes correct, no case errors or uncertain billing, p95 within the configured budget and mean known generation cost within budget. Null faithfulness on abstention is expected. The unit of context precision/recall is unique document ID, not chunks or tokens.

## 12. Observe traces, load and release behavior

```bash
uv run python examples/telemetry_smoke.py
```

Expected: required stage spans and request/latency/cost metrics are emitted without source text. For actual collector verification, configure `RAG_OTLP_ENDPOINT`, start your collector or the supplied Compose stack, and send queries again. The standalone application and Compose must not compete for port 8000. Ensure Compose uses the intended `.env`; shell exports from the manual test terminal do not replace its `env_file` values.

Inspect the shared trace ID, spans for retrieval/reranking/generation/verification and live rewrite/provider attempts. Compare span outcomes with response timings and usage. Verify logs and exported attributes contain no API keys or source text. The in-memory smoke test alone does not prove collector delivery or retention.

For load testing, use a staging instance and fixed corpus. Warm the model once, then test concurrency 1, 4, 8 and 16 while recording HTTP status, answer/review/abstention counts, client-side latency, server-stage latency, throughput, memory and CPU. Separate successful-response latency from rejected-request counts. The built-in limit is **60 authenticated requests per key per minute**, shared across routes and local to the process. Without accounting for that limit, a throughput test will mostly measure 429 responses. Use a staging gateway/identity plan for sustained load; do not interpret intentional 429/503 backpressure as an unhandled crash.

Release only after deterministic regressions, isolation checks, live case review, fault injection, representative load, trace delivery and backup/restore checks pass. Keep the corpus version, git revision, model revisions, thresholds, hardware and reports with each run. Use held-out questions for acceptance rather than tuning thresholds on the final test set.
