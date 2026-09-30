# Validation record

Validation performed on macOS ARM64 with Python 3.12.14. Dependency versions are captured in `uv.lock`. This record describes executed checks; it is not a production certification.

- **Lint and formatting:** Ruff passes across modules, examples and tests.
- **Automated tests:** 34 pass. Coverage includes source offsets for every chunk strategy; transactional updates/rollback; persistence and embedding identity; tenant/group isolation; BM25 and semantic-branch retrieval; dynamic K; fabricated citations; unsupported claims; conflicting context; empty-index abstention; review persistence; bounded CPU cancellation; model retries, fallback, refusal, invalid JSON, billing uncertainty and budgets; live orchestration with mocked HTTP; ingress authentication/authorization, body limits and redacted logs; reference metrics and evaluation gates.
- **Real neural adapters:** passed with pinned model revisions. Password-reset query cosine similarity was approximately 0.716 for the relevant passage versus -0.0045 for the unrelated passage. Reranker scores were approximately 0.9893 versus 0.0000125. NLI scored an exact supported claim at approximately 0.9898 entailment and a negated claim at approximately 0.9974 contradiction. See `neural-smoke.json`. These are smoke cases, not a benchmark.
- **Runtime compatibility fix:** the reranker's original parameter storage produced NaNs and intermittent pooler failures on the installed macOS stack, on both automatic device selection and CPU. Materializing identical parameters into owned contiguous storage resolved the controlled comparison. The delivered adapter includes this fix, finite-score validation and startup warmup. Inference defaults to CPU; other accelerators require validation.
- **Offline evaluation:** four fixture cases passed all configured gates: three answered and one abstained. Faithfulness/relevance are explicitly exact-extract/lexical proxies in demo mode. The result file includes timings and mode labels; its tiny corpus and zero paid model calls cannot establish production quality, cost or latency. See `demo-eval-report.json`.
- **Actual HTTP service:** a Uvicorn process served readiness, ingested three documents and returned a cited answer over localhost HTTP. Header and answer trace IDs matched and were nonzero. The process was stopped after verification. See `api-smoke.json`.
- **OpenTelemetry:** in-memory SDK export contained pipeline/stage spans and request/latency/cost instruments. Assertions checked that source text was absent from span attributes. See `telemetry-smoke.json`.
- **Configuration:** YAML files parse; `uv lock --check` passes.

## Initial validation boundaries

During initial delivery, no real generator or judge endpoint was called: no API credentials were provided. Later live regression checks are recorded below. HTTP contracts, retry behavior and the live orchestration path were exercised with controlled HTTP transports. At initial delivery, Docker was unavailable and the Compose stack and external OTLP export were not tested. The later monitoring validation below supersedes that limitation for the local observation stack. Application Linux container behavior, accelerator behavior, production-scale load, backup restoration and enterprise-corpus quality calibration remain deployment acceptance work.

## Reproduce

```bash
uv sync --frozen --extra dev --extra neural
uv run ruff check .
uv run ruff format --check rag tests examples
uv run pytest -q
cp .env.example .env
uv run python examples/seed.py
uv run rag-eval examples/eval.jsonl --output demo-eval-report.json
uv run python examples/neural_smoke.py --output neural-smoke.json
uv run python examples/telemetry_smoke.py
```

Initial model downloads require network access. Use a prefetched cache and `RAG_LOCAL_MODELS_ONLY=true` for reproducible offline inference checks. Evaluate actual deployment hardware and protected datasets before accepting production SLOs.


## Live resume regression, 2026-09-26

The reported live resume query exposed missing document titles in reranking and PDF whitespace differences in quoted evidence. Reranking now includes the title without changing evidence text. Quote matching permits whitespace-only differences and maps the result back to exact original source offsets. The generation prompt prevents adding uncited subjects and discourages document-meta claims that cause spurious NLI contradictions across excerpts.

Validation: 37 backend tests passed and Ruff passed. A local live pipeline test using the configured KodeKloud Responses endpoint returned `answered`, six retrieved contexts, two cited claims, and no review reasons for the reported programming-languages question. Thresholds were unchanged. This is one real integration case, not a corpus-wide quality benchmark; generation and NLI remain probabilistic. Provider rates in the user's configuration were not independently validated, so recorded cost is a configured estimate.


## Conflict-resolution regression, 2026-09-26

A repeated user query exposed an NLI false positive: one resume project that omits Python was treated as contradicting a different project that uses Python. Prompt wording alone did not solve this reliably. Live orchestration now adjudicates NLI conflict suspicions using a structured relationship check, only after citation authenticity and claim entailment pass. Every suspect pair must be covered exactly once. Real contradictions require an authentic counter-quote; contradictory, uncertain, invalid and unavailable assessments retain review. The original guard deadline and per-trace cost budget bound the additional request. Other guard failures and high-risk-topic triggers cannot be overridden by this check.

47 backend tests and Ruff checks pass in the consolidated project. Real integration verification: one fixed-claim reproduction, two live runs of the reported question, and a live paraphrase all returned answered with citations. A separate real-provider control distinguished a different project's JavaScript usage from an explicit denial of Python experience. See `live-conflict-validation.json`.

This adds a semantic check, not a proof of factual correctness. The conflict assessor uses the configured generation endpoint, so its errors may correlate with generation. It adds latency and token usage, recorded under the `conflict_check` stage. Provider timeouts or unsupported claims can still require human review; evaluation on a broader labeled corpus remains necessary.


## File-upload integration, 2026-09-28

- 68 backend tests pass (21 upload tests added), including all six real parser formats through authenticated multipart, vector/token persistence and cited queries.
- 14 frontend tests pass, including multipart payloads, auth, progress, validation, cancellation and error handling. TypeScript and the Vite production build pass. Ruff lint and formatting checks pass.
- Browser test at temporary port 5175 against isolated demo backend 8012: six files selected with the native file chooser, real upload progress followed by server processing, 6/6 indexed. Query `support available hours` returned a grounded answer, six contexts and one citation. PDF table/page and Excel sheet/row provenance were visible in the evidence inspector.
- Invalid/corrupt/empty uploads, encoding and expansion limits, unauthorized groups, parser deadline cleanup, embedding failure and post-delete transaction rollback are covered.
- Browser failure checks also confirmed unsupported-file validation before upload and a server error for a corrupt PDF, while the six successful files remained indexed.
- The existing user live database and `.env` were not changed. This validation uses synthetic fixtures and demo generation, and makes no new claim about live LLM quality. A running old backend needs restarting to load the routes/dependencies.

See `FILE_UPLOADS.md` for the implementation flow, full operational limits and unsupported OCR/header/image extraction boundaries.


## Token-aware ingestion regression

73 backend tests and Ruff checks pass. Added regressions cover tokenizer special tokens, dense Unicode/table inputs in all three chunking modes, exact source-offset coverage, bounded semantic-splitting inputs, and safe actionable embedding-limit errors. A user-supplied PDF was reproduced locally: parsing and content validation succeeded, but one original chunk used 268 tokens against the embedding model's 256-token limit. After the fix, the actual multipart endpoint with the real cached semantic encoder returned HTTP 200 and indexed 15 chunks (8,600 extracted characters, maximum 256 tokens, 384-dimensional embeddings). A private temporary index was removed after verification; no external LLM calls or writes to the user's live database were made. The private PDF is not included in fixtures or the project archive.


## Factual-answer review regression, 2026-09-29

86 backend tests pass, plus Ruff lint/format checks. Recorded failures showed unsupported claims with short evidence, invalid date quotes and a medical-topic false positive for a factual insurance-premium lookup. Tests now cover contextual verification with expanded exact citations, refusal to use uncited sources, a single bounded correction followed by re-verification, continued rejection of invalid/unsafe drafts, and preservation of high-risk advice review.

The actual offer PDF also exposed missing spaces in default PDF extraction: the first page had 81 whitespace-separated words, versus 374 with font-relative word-gap detection. A synthetic PDF regression covers small word gaps. Existing indexed documents require re-upload to get this extraction improvement.

Live checks use a synthetic offer letter and the configured provider with real local embedding, reranker and NLI models, in disposable databases. Base-salary and benefits queries returned cited answers; an insurance-premium query returned a cited answer on repeat checks after one earlier unavailable conflict assessment. Provider/NLI judgments remain probabilistic. No private offer content was sent during these synthetic provider tests.

The final live date check also returned answered with an authentic date quote, phrased as the date shown on the letter rather than asserting an unstated issue event.


## Latency regression, 2026-09-29

- 98 backend tests pass; added coverage includes fallback rewriting, cache TTL/eviction/disable behavior, fresh trace and usage data, tenant/group/subject/role/policy isolation, update/delete invalidation, shared-store revision visibility and rollback, and deduplicated NLI score mapping. Ruff lint and formatting pass.
- 14 frontend tests, TypeScript checking and the Vite production build pass. Execution inspection distinguishes cached reuse from a fresh inference run.
- Warm CPU microbenchmark with 12 heterogeneous NLI pairs: median scoring time decreased from approximately 787 ms (batch 32) to 465 ms (batch 4). Tests of lower CPU thread counts were slower; the existing thread count is unchanged.
- Real-provider pipeline benchmark used a temporary SQLite backup of the current index, the reported job-responsibilities question and three alternating runs per profile. All runs returned answered with citations. Mandatory rewriting / batch 32 had median 1,482.45 ms; fallback rewriting / batch 4 had median 1,147.89 ms (22.6% lower). The comparison uses the updated adapters under both settings, not a checkout of the old release.
- Three repeated verified queries had median 1.46 ms (range 1.26–3.34 ms) and zero provider attempts. One uncached optimized run took 6,672.67 ms with a provider retry. These small samples demonstrate the mechanism, not production percentiles or a universal reduction from the screenshot's 9.50 seconds.
- Source content and credentials are omitted from `latency-benchmark.json`. Benchmarks did not mutate the user's live corpus. Existing running services require a restart to pick up the changes. Broader recall evaluation, concurrent load, browser timing and production tail-latency testing remain outstanding.


## Further latency regression, 2026-09-29

111 backend tests pass with Ruff lint and formatting checks. New contracts cover reversible source-ID aliases, exact span coverage, unknown source rejection, duplicate references, long-passage fallback without truncation, warmup on every worker, warmup failure cleanup, supported and unsupported claims through the full live orchestration path, and reasoning controls restricted to initial generation. Existing quote-contract tests remain exercised explicitly. No frontend code changed in this round; its prior 14-test/build validation remains applicable.

Live testing showed compact IDs alone were insufficient and full-passage reference citations caused extra repairs; that experiment was rejected. The delivered mode references exact sentence/line spans and retains complete retrieved passages for the independent guard. With the configured provider accepting generation effort `none`, two uncached question variants completed in 3,352.55 ms and 2,847.24 ms, both answered with grounding and citations. The exact reported question completed in 3,346.87 ms: retrieval 25.13 ms, reranking 340.16 ms, generation 2,472.71 ms, verification 506.65 ms; one provider attempt, 68 output tokens, no repair. See `latency-v2-benchmark.json` for both low/none comparisons and the final result.

Provider variability was substantial: an earlier span-mode run without an explicit effort setting spent 10.10 seconds in generation. Accordingly, these changes do not establish a p95 or an upper latency bound. The repeated-answer medians from the prior record should not be presented as first-answer performance. Tests used temporary SQLite backups and did not alter live documents. The existing backend process still needs restarting to load the final settings; process inspection/restart from this sandbox is restricted.


## Source-selection regression, 2026-09-29

Reproduced the reported abstention: the draft began with a document-meta claim ("The offer letter says...") and combined facts from references split at PDF line breaks. NLI returned unsupported_claim; the repair model abstained. This is a generation/verification mismatch, not missing retrieval.

The delivered document-Q&A profile selects complete source sentences, constructs exact claims server-side and keeps all guard checks. 117 backend tests pass, including authentic extraction, invented IDs, inconsistent abstention, preservation of PDF line wraps, rejection without a generative repair, preservation of the initial failure when synthesis repair abstains, and runtime revision reporting. Ruff checks pass. 14 frontend tests, TypeScript checks and the production build pass.

Final live regression: eight runs with the application answer cache disabled, covering three exact repetitions, two paraphrases, a designation lookup and two absent facts. All eight met their expected answer/abstention outcome. All released claims used exact source wording and authentic citations. No run needed answer repair or human review. Median pipeline latency was 3.07 seconds; observed range 1.46–3.68 seconds. Output was 19–29 provider tokens. See selection-regression.json for every sample, including slow ones. Provider-side caching cannot be ruled out for repeated prompts, so these are not independent fresh-prompt production percentiles.

The live corpus was copied using SQLite backup into a temporary database; no live documents were changed. The existing port-8000 service still returned the old health contract at the end of validation and must be restarted. Testing proves the reported path on these examples, not universal correctness, relevance, recall or a guaranteed latency bound. Broader labeled evaluation is still required for synthesized answers, calculations, complex multi-document questions and additional languages.


## Jaeger Monitor validation, 2026-09-30

Enabled spanmetrics in Collector 0.123.0 and configured Jaeger 1.66.0 to query Prometheus 3.2.1 with matching normalized metric names and millisecond histogram units. All three monitoring containers were started successfully. Compose configuration validation and the collector's own configuration validator passed.

Sent nine successful readiness requests through the existing host API. Prometheus reports the rag-otel scrape target UP; Jaeger's calls and p95 latency APIs return finite, positive points for evidence-rag, and its errors API returns finite points. See monitoring-smoke.json for the bounded validation summary. This verifies real API → OTLP collector → spanmetrics → Prometheus → Jaeger Monitor API delivery. Browser chart rendering was not separately inspected. Health traffic is not an LLM or RAG latency benchmark, and no paid model call was needed.

The previous Jaeger traces were saved locally before recreating its ephemeral container; that sensitive backup is excluded from the deliverable. Metrics begin with new traffic and are not reconstructed from historical traces. The API, indexed documents and frontend were not restarted or changed for this fix.


## Production hardening regression, 2026-09-30

134 backend tests and 20 frontend tests pass; Ruff checking/formatting, TypeScript checking and the Vite production build pass. Added cases cover raw ingestion group grants, same-tenant unauthorized overwrite/delete, partial-group mutation rejection, transactional rollback and unchanged revisions, authorized review visibility beyond 100 hidden records, startup/cleanup failures, redacted unexpected errors, endpoint URL/pricing validation, ranking equivalence, late browser responses after cancellation/timeout, XHR cleanup and review-note ownership. The shared test fixture ignores local .env files to reduce machine-dependent test behavior.

BM25 statistics/postings are built once per authorized request snapshot and reused across query variants; query tokenization and IDF work no longer repeat for every document. Candidate selection uses bounded top-K selection while preserving deterministic tie ordering. A five-repeat synthetic benchmark with 5,000 documents, 80 tokens/document and three query variants measured lexical scoring including index construction: baseline median 176.096 ms, optimized median 65.115 ms (63.0% reduction). See production-review-benchmark.json. This is not an end-to-end provider latency or concurrency benchmark.

Frontend changes reuse the health schema, memoize the heavy evidence inspector and derived review lists, skip unchanged upload progress updates, cancel scheduled citation scrolling, and clean up request handlers. No browser rendering or interaction benchmark was run for this round. Vite reports harmless upstream Zod annotation warnings; the build completes. No dependencies, live model requests, live documents or deployment settings were changed. Existing backend processes need restart to load the Python changes; frontend production deployments need a rebuild.
