# Evidence — RAG workbench

A responsive React 19 + TypeScript + Tailwind CSS 4 application that calls the Python service in this repository. Vite handles development and builds. Fetch handles JSON requests; XMLHttpRequest measures file upload progress; Zod validates API responses at runtime. Nothing in the interface fabricates answers, scores, costs or review records.

## Start the application

Use Python 3.12+ with `uv`, and Node.js 22.18+ with npm. Run the backend from the repository root in one terminal:

```bash
uv sync --frozen --extra dev
set -a
. testing/demo.env
set +a
uv run uvicorn rag.app:app --host 127.0.0.1 --port 8000
```

This uses the isolated synthetic test identities and database configured in `testing/demo.env`. These credentials are public test fixtures, never production credentials. Follow the root README to configure live models instead.

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open **http://127.0.0.1:5173**. Choose **Set API token → Use local test identity → Apply connection**. This token matches the admin identity in `testing/demo.env`.

1. Open **Documents → Load sample corpus → Ingest documents**. Expect three indexed chunks with the default test configuration.
2. Open **Playground → Support hours → Run query**. Expect the 24-hour support policy and a citation.
3. Click **[1]** to highlight its exact source passage. Open **Source & provenance** to inspect source IDs, versions and offsets.
4. Choose **Execution** to inspect stage latency, usage, cost and trace IDs.
5. Choose **Review trigger → Run query**, then **Human review**. Select the flagged request, enter a reason and approve or reject. Decisions are persisted by the API; they do not automatically publish an answer.
6. Switch between light and dark modes. Use browser responsive mode to exercise the mobile navigation and stacked inspector.

The test corpus and credentials are bundled for convenience; requests go to the real backend. Demo responses are exact extracts, with zero provider token costs, and are labeled accordingly.

## Configuration and API contract

`.env.local`:

```dotenv
VITE_API_BASE_URL=/api
API_PROXY_TARGET=http://127.0.0.1:8000
```

Vite proxies `/api/query` to `http://127.0.0.1:8000/query`, with the same mapping for ingestion, reviews and health. This avoids requiring backend CORS changes for local use. Restart Vite after changing environment settings. `VITE_*` values are public build-time configuration: never put bearer credentials or model API keys there.

The browser accepts a backend bearer token through the Connection dialog and holds it only in memory. Refreshing clears it. Switching identity remounts the workspace, aborts active reads and clears previous results, ingestion text and review data. Only the appearance preference is stored in localStorage. The server remains responsible for authentication, roles, tenant isolation and document access.

Supported endpoints:

- `POST /query`: `{ "text": "Enterprise support available hours" }`
- `POST /ingest`: `{ "documents": [{ "id": "support", "title": "Support", "source": "urn:acme:support", "groups": ["staff"], "text": "Enterprise support is available 24 hours a day." }] }`
- `GET /reviews`: returns the latest 100 accessible records, including status, nested request payload and optional verified draft.
- `POST /reviews/{request_id}/decision`: `{ "decision": "reject", "note": "The evidence does not address the question." }`
- `GET /health/ready`: reports backend readiness and demo/live mode. Readiness does not verify the entered identity.

**Runtime query tuning is not exposed by this backend.** Its strict query schema permits only `text`; sending `top_k`, `rerank` or `temperature` would return 422. The Parameters disclosure explains the server-controlled policy. To add live controls later, extend the backend schema and pipeline first, then update the API client and controls together. Queries are independent requests; the chat-style history is not multi-turn model memory.

## Component structure and state management

`src/App.tsx` composes navigation, appearance, connection settings, three workspace views and readiness status. `src/api/client.ts` owns URL construction, headers, request deadlines, cancellation and error mapping. `src/api/schemas.ts` supplies the runtime contracts and inferred TypeScript types.

- `Playground.tsx`: query form, examples, cancellation, bounded session history, claims and citations.
- `Inspector.tsx`: source highlighting, retrieval scores, provenance, stage timings, token costs and trace identifiers.
- `IngestionPanel.tsx`: single-document form, JSON batches, JSON-file import and bundled corpus.
- `ReviewsPanel.tsx`: pending/all filters, verified drafts, required decision notes and confirmed mutation results.
- `ConnectionDialog.tsx`: in-memory credentials and identity changes.
- `ui.tsx`: shared buttons, status badges, skeletons, errors and formatting.

`usePlayground` uses a typed reducer. A run moves from `pending` to `complete`, `error` or `cancelled`. A late result cannot overwrite a cancelled run. An AbortController ref prevents duplicate active queries. History is capped at 30 runs. `useRequest` provides latest-request-wins cancellation for other API reads and explicit loading/error state. Mutations are not automatically retried: a timeout may occur after the server commits, so inspect the queue or index before retrying.

Usage from the application:

```tsx
const api = useMemo(() => new ApiClient(token), [token]);
const playground = usePlayground(api);

// Form submission starts a typed run and updates loading/error state.
await playground.submit(question);

// Citation selection is separate UI state; no new generation request occurs.
setCitation(citation);

// Aborts the browser request and ignores any late response.
playground.cancel();
```

Cancellation stops browser waiting; it does not promise cancellation of work already accepted by a model provider. Ingestion and decision buttons disable during their requests. Decision submission also uses a synchronous lock to guard against repeated clicks.

See `FRONTEND_CODE_GUIDE.md` for the complete key-component and state-management code, or edit the source modules directly.

## Validation and error behavior

```bash
npm test
npm run build
```

Automated tests cover exact request payloads, bearer authorization, absence of cross-site cookies, schema failures, safe error text, cancellation, avoiding mutation retries, body limits, duplicate document IDs, unsafe source links and reducer transitions.

Browser checks executed against the real local FastAPI demo service:

- Three sample documents ingested; a support query produced a grounded answer and citation.
- Citation navigation and the execution metrics panel worked.
- A high-risk query appeared in the review queue; rejection persisted and removed it from Pending.
- Switching identity cleared session runs; an invalid token displayed a useful authentication error.
- Light/dark controls worked; the 390px mobile viewport had no horizontal document overflow. The 1440px desktop breakpoint was also exercised.

These checks do not validate live model quality, production identity infrastructure or high-concurrency performance. Use the root testing guide for backend evaluation and failure injection. Loading skeletons cover pending queries and review fetches; empty, abstained, review-required and failed states have distinct presentations.

## Deployment

`npm run build` writes static assets to `dist/`. Serve them over HTTPS and route `/api/` to the backend. A Vite development proxy is not included in the static build. Example reverse-proxy locations:

```nginx
location /api/ {
    proxy_pass http://rag:8000/;
    proxy_read_timeout 135s;
    client_max_body_size 1m;
}
location / {
    try_files $uri $uri/ /index.html;
}
```

If using a different API origin, configure its CORS allowlist deliberately and build with the intended `VITE_API_BASE_URL`. The UI renders model/source text as escaped React text, never raw HTML. External source links are limited to HTTPS. Review decisions still require server authorization; hiding controls is not an authorization mechanism.

Implementation references: [Tailwind's Vite integration](https://tailwindcss.com/docs/installation/using-vite), [Vite development proxy](https://vite.dev/config/server-options#server-proxy), and [React useReducer](https://react.dev/reference/react/useReducer).

## Direct file uploads

Documents now opens the File upload tab. Select or drop PDF, Markdown, XLSX, DOCX, CSV or TXT files, choose authorized access groups and upload. Each file has its own progress, parse/index state, errors, warnings and retry result. Paste text and JSON batch remain available. Default limits are fetched from the backend; restart an older backend to expose `/ingest/formats` and `/ingest/file`.

See [the complete upload guide](../FILE_UPLOADS.md) for server limits, format-specific extraction, identity/provenance, cancellation behavior, samples and tested rollback cases. The source client is `src/api/client.ts`, upload schemas are in `src/api/uploads.ts`, and the UI is `src/components/FileUploadPanel.tsx`.


Verified-answer reuse is reported in the Execution inspector when `cache_hit` is true. Timings and usage belong to the current request; cache hits show zero new model calls. Backend defaults and cache invalidation are documented in [the runbook](../RUNBOOK.md#latency-controls).


The Source sentences badge means the live model selected evidence and the server copied exact source wording into the answer. The inspector retains initial verification failure codes. The connection banner identifies an older backend using the readiness pipeline revision; restart FastAPI and click Check again to confirm the update is active.
