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

## Not executed

No real generator or judge endpoint was called: no API credentials were provided. HTTP contracts, retry behavior and the live orchestration path were exercised with controlled HTTP transports. The Docker/Compose stack was not launched because Docker is unavailable in this environment. External OTLP collector export, Linux container behavior, accelerator behavior, production-scale load, backup restoration and enterprise-corpus quality calibration remain deployment acceptance work.

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
