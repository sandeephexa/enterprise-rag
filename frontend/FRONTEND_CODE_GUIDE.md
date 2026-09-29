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


# Complete implementation code

The source files are authoritative. This snapshot accompanies the downloadable project.

## `src/api/schemas.ts`

```typescript
import { z } from 'zod';

const number = z.number().finite();
export const EvidenceSchema = z.object({ chunk_id: z.string(), quote: z.string() });
export const ClaimSchema = z.object({ text: z.string(), evidence: z.array(EvidenceSchema) });
export const CitationSchema = z.object({
  number: number, claim_index: number, chunk_id: z.string(), document_id: z.string(),
  version: z.string(), source: z.string(), title: z.string(), quote: z.string(), start: number, end: number,
});
export const HitSchema = z.object({
  chunk: z.object({ id: z.string(), document_id: z.string(), version: z.string(), source: z.string(),
    title: z.string(), text: z.string(), start: number, end: number, groups: z.array(z.string()) }),
  fusion_score: number, rerank_score: number.nullable(),
});
export const AnswerSchema = z.object({
  cache_hit: z.boolean().optional(),
  answer_style: z.enum(['extractive', 'synthesis']).optional(),
  initial_verification_reasons: z.array(z.string()).optional(),
  request_id: z.string(), trace_id: z.string(), status: z.enum(['answered', 'abstained', 'review']),
  answer: z.string(), claims: z.array(ClaimSchema), citations: z.array(CitationSchema),
  contexts: z.array(HitSchema), review_reasons: z.array(z.string()), faithfulness: number.nullable(),
  usage: z.object({ input_tokens: number, output_tokens: number, known_cost_usd: number,
    reserved_cost_usd: number, uncertain_attempts: number, attempts: number }),
  latency_ms: number, stage_ms: z.record(z.string(), number), mode: z.enum(['live', 'demo']),
});
export const ReviewSchema = z.object({
  request_id: z.string(),
  answer: z.object({ question: z.string(), answer: AnswerSchema,
    verified_draft: z.object({ claims: z.array(ClaimSchema), abstain: z.boolean() }).nullable(),
    submitted_by: z.string() }),
  state: z.enum(['pending', 'approve', 'reject']),
  decision: z.object({ decision: z.enum(['approve', 'reject']), note: z.string(),
    reviewed_by: z.string(), reviewed_at: z.string() }).nullable(),
});
export const DocumentSchema = z.object({
  id: z.string().regex(/^[A-Za-z0-9_.-]{1,100}$/, 'Use 1–100 letters, numbers, dots, underscores or hyphens.'),
  title: z.string().min(1).max(200), source: z.string().min(1).max(500).refine(s => /^(https:\/\/|urn:)/.test(s), 'Use an HTTPS source or URN.'),
  text: z.string().min(1).max(200000), groups: z.array(z.string().min(1)).min(1).max(50),
}).strict();
export const IngestSchema = z.object({ documents: z.array(DocumentSchema).min(1).max(20) }).strict()
  .refine(batch => new Set(batch.documents.map(d => d.id)).size === batch.documents.length, 'Document IDs must be unique.');

export type Answer = z.infer<typeof AnswerSchema>;
export type Citation = z.infer<typeof CitationSchema>;
export type Hit = z.infer<typeof HitSchema>;
export type Review = z.infer<typeof ReviewSchema>;
export type IngestBatch = z.infer<typeof IngestSchema>;
export const PIPELINE_REVISION = 'source-selection-v1';
export type Health = { status: string; mode: 'live' | 'demo'; pipeline_revision?: string; answer_style?: 'extractive' | 'synthesis' };

```

## `src/api/uploads.ts`

```typescript
import { z } from 'zod';

export const UploadLimitsSchema = z.object({
  extensions: z.array(z.string()), max_file_bytes: z.number().positive(),
  max_extracted_chars: z.number().positive(), max_pdf_pages: z.number().positive(),
  max_excel_sheets: z.number().positive(), parse_timeout_s: z.number().positive(),
});
export const UploadResultSchema = z.object({
  document_id: z.string(), source: z.string(), indexed_chunks: z.number().int().nonnegative(),
  extracted_characters: z.number().int().nonnegative(), warnings: z.array(z.string()),
});
export type UploadLimits = z.infer<typeof UploadLimitsSchema>;
export type UploadResult = z.infer<typeof UploadResultSchema>;

export function validateFile(file: Pick<File, 'name' | 'size'>, limits: UploadLimits): string | null {
  const extension = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!limits.extensions.includes(extension)) return `Unsupported format. Choose ${limits.extensions.join(', ')}.`;
  if (!file.size) return 'The file is empty.';
  if (file.size > limits.max_file_bytes) return `File exceeds ${(limits.max_file_bytes / 1048576).toFixed(0)} MiB.`;
  if (file.name.length > 255 || /[\u0000-\u001f]/.test(file.name)) return 'File name is invalid or too long.';
  return null;
}

```

## `src/api/client.ts`

```typescript
import { z } from 'zod';
import { UploadLimitsSchema, UploadResultSchema, type UploadResult } from './uploads';
import { AnswerSchema, ReviewSchema, IngestSchema, type IngestBatch } from './schemas';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status = 0, public requestId?: string) {
    super(message); this.name = 'ApiError';
  }
}

/** Immutable per-session client. Credentials are never persisted or logged. */
export class ApiClient {
  constructor(private token: string, private base = API_BASE) {}

  private async request<T>(path: string, schema: z.ZodType<T>, options: {
    method?: string; body?: unknown; signal?: AbortSignal; timeout?: number;
  } = {}): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    options.signal?.addEventListener('abort', abort, { once: true });
    if (options.signal?.aborted) controller.abort();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, options.timeout ?? 35000);
    try {
      const response = await fetch(`${this.base}${path}`, {
        method: options.method ?? 'GET', signal: controller.signal, credentials: 'omit',
        headers: { ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
          ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      });
      if (!response.ok) {
        const retry = response.headers.get('retry-after');
        const messages: Record<number, string> = {
          400: 'The content was rejected by the safety policy.',
          401: 'Authentication failed. Update the API token in Connection.',
          403: 'This identity does not have permission for this action.',
          404: 'This record is no longer pending or is unavailable. Refresh the list.',
          413: 'The request exceeds the server’s body limit (default: 1 MB).',
          422: 'The server rejected the request schema. Check the input fields.',
          429: `Rate limit reached.${retry ? ` Retry after ${retry} seconds.` : ' Try again later.'}`,
          503: 'The service is busy or a dependency is unavailable. Try again shortly.',
        };
        throw new ApiError(messages[response.status] ?? `API request failed (${response.status}).`, response.status, response.headers.get('x-request-id') ?? undefined);
      }
      let data: unknown;
      try { data = await response.json(); }
      catch { throw new ApiError('The API returned a non-JSON response. Check the API URL and proxy.'); }
      const parsed = schema.safeParse(data);
      if (!parsed.success) throw new ApiError('The API response does not match this workbench’s contract. Check backend versions.');
      return parsed.data;
    } catch (error) {
      if (options.signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
      if (timedOut) throw new ApiError('Request timed out. The server may still be processing it.');
      if (error instanceof ApiError) throw error;
      throw new ApiError('Cannot reach the API. Check the backend, proxy and network connection.');
    } finally {
      clearTimeout(timer); options.signal?.removeEventListener('abort', abort);
    }
  }

  query(text: string, signal?: AbortSignal) {
    // The backend forbids additional request fields; do not send UI-only controls.
    return this.request('/query', AnswerSchema, { method: 'POST', body: { text }, signal });
  }
  health(signal?: AbortSignal) {
    return this.request('/health/ready', z.object({ status: z.string(), mode: z.enum(['live', 'demo']), pipeline_revision: z.string().optional(), answer_style: z.enum(['extractive', 'synthesis']).optional() }), { signal, timeout: 5000 });
  }
  ingest(batch: IngestBatch, signal?: AbortSignal) {
    const body = IngestSchema.parse(batch);
    if (new TextEncoder().encode(JSON.stringify(body)).byteLength > 1_000_000) throw new ApiError('Batch exceeds the default 1 MB body limit.');
    return this.request('/ingest', z.object({ indexed_chunks: z.number().int().nonnegative() }), { method: 'POST', body, signal, timeout: 130000 });
  }
  uploadLimits(signal?: AbortSignal) {
    return this.request('/ingest/formats', UploadLimitsSchema, { signal, timeout: 5000 });
  }

  /** XHR supplies real byte progress; 100% means server processing, not indexed. */
  uploadFile(file: File, groups: string[], documentId: string, onProgress: (percent: number) => void, signal: AbortSignal): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      let settled = false;
      const finish = (result?: UploadResult, error?: Error) => {
        if (settled) return;
        settled = true;
        signal.removeEventListener('abort', abort);
        if (error) reject(error); else resolve(result!);
      };
      xhr.open('POST', `${this.base}/ingest/file`);
      xhr.timeout = 190000;
      if (this.token) xhr.setRequestHeader('Authorization', `Bearer ${this.token}`);
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) onProgress(Math.min(100, Math.round(event.loaded / event.total * 100)));
      };
      xhr.upload.onload = () => onProgress(100);
      xhr.onerror = () => finish(undefined, new ApiError('Upload connection failed. Check the backend and proxy.'));
      xhr.onabort = () => finish(undefined, new DOMException('Upload cancelled. Indexing may already have completed; retrying the same document ID safely replaces it.', 'AbortError'));
      xhr.ontimeout = () => finish(undefined, new ApiError('Upload timed out. Indexing may still finish; retry with the same document ID.'));
      xhr.onload = () => {
        let data: unknown;
        try { data = JSON.parse(xhr.responseText); } catch { finish(undefined, new ApiError('The upload API returned an invalid response. Restart the updated backend.')); return; }
        if (xhr.status < 200 || xhr.status >= 300) {
          const detail = z.object({ detail: z.object({ code: z.string(), message: z.string().max(500) }) }).safeParse(data);
          const messages: Record<number, string> = {
            400: 'Malformed upload or content rejected by the safety policy.',
            401: 'Authentication failed. Update your API token.',
            403: 'Your identity cannot ingest files into these groups.',
            404: 'File uploads are unavailable. Restart the updated backend.',
            408: 'Upload or parsing timed out. Split or simplify the file.',
            413: 'The file or its extracted contents exceed the server limits.',
            415: 'Unsupported file format. Use PDF, MD, XLSX, DOCX, CSV or TXT.',
            422: 'The file or metadata could not be processed.',
            429: 'Rate limit reached. Wait a minute before retrying.',
            503: 'The service is busy or indexing failed. Retry shortly.',
          };
          // React renders this as text, never as HTML.
          finish(undefined, new ApiError(detail.success ? detail.data.detail.message : messages[xhr.status] ?? `Upload failed (${xhr.status}).`, xhr.status));
          return;
        }
        const parsed = UploadResultSchema.safeParse(data);
        if (!parsed.success) finish(undefined, new ApiError('Upload response does not match this workbench version.'));
        else finish(parsed.data);
      };
      if (signal.aborted) { finish(undefined, new DOMException('Cancelled', 'AbortError')); return; }
      signal.addEventListener('abort', abort, { once: true });
      const body = new FormData();
      body.append('file', file);
      body.append('groups', JSON.stringify(groups));
      if (documentId.trim()) body.append('document_id', documentId.trim());
      // The browser supplies the multipart boundary; do not set Content-Type.
      xhr.send(body);
    });
  }
  reviews(signal?: AbortSignal) { return this.request('/reviews', z.array(ReviewSchema), { signal }); }
  decide(id: string, decision: 'approve' | 'reject', note: string, signal?: AbortSignal) {
    return this.request(`/reviews/${encodeURIComponent(id)}/decision`, z.object({ recorded: z.literal(true) }), {
      method: 'POST', body: { decision, note }, signal,
    });
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'An unexpected error occurred.';
}

```

## `src/hooks/usePlayground.ts`

```typescript
import { useCallback, useEffect, useReducer, useRef } from 'react';
import { ApiClient, errorMessage } from '../api/client';
import type { Answer } from '../api/schemas';

export type Run = { id: string; question: string; started: string;
  status: 'pending' | 'complete' | 'error' | 'cancelled'; answer?: Answer; error?: string };
export type RunState = { runs: Run[]; selectedId: string | null };
export type RunAction = { type: 'start'; run: Run } | { type: 'success'; id: string; answer: Answer }
  | { type: 'error'; id: string; error: string } | { type: 'cancel'; id: string }
  | { type: 'select'; id: string } | { type: 'clear' };

export function runReducer(state: RunState, action: RunAction): RunState {
  if (action.type === 'clear') return { runs: [], selectedId: null };
  if (action.type === 'select') return { ...state, selectedId: action.id };
  if (action.type === 'start') return { runs: [...state.runs.slice(-29), action.run], selectedId: action.run.id };
  return { ...state, runs: state.runs.map(run => {
    if (run.id !== action.id || run.status !== 'pending') return run;
    if (action.type === 'success') return { ...run, status: 'complete', answer: action.answer };
    if (action.type === 'error') return { ...run, status: 'error', error: action.error };
    return { ...run, status: 'cancelled' };
  }) };
}

/** Independent query runs, not a conversational API; at most 30 are kept in memory. */
export function usePlayground(api: ApiClient) {
  const [state, dispatch] = useReducer(runReducer, { runs: [], selectedId: null });
  const active = useRef<{ id: string; controller: AbortController } | null>(null);
  useEffect(() => () => active.current?.controller.abort(), []);
  const cancel = useCallback(() => {
    if (active.current) { active.current.controller.abort(); dispatch({ type: 'cancel', id: active.current.id }); active.current = null; }
  }, []);
  const submit = async (question: string) => {
    if (active.current || question.trim().length < 3 || question.length > 2000) return;
    const id = crypto.randomUUID();
    const controller = new AbortController(); active.current = { id, controller };
    dispatch({ type: 'start', run: { id, question: question.trim(), started: new Date().toISOString(), status: 'pending' } });
    try {
      const answer = await api.query(question.trim(), controller.signal);
      if (!controller.signal.aborted) dispatch({ type: 'success', id, answer });
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'error', id, error: errorMessage(error) });
    } finally { if (active.current?.id === id) active.current = null; }
  };
  return { ...state, submit, cancel, busy: state.runs.some(run => run.status === 'pending'),
    select: (id: string) => dispatch({ type: 'select', id }),
    clear: () => { cancel(); dispatch({ type: 'clear' }); } };
}

```

## `src/hooks/useRequest.ts`

```typescript
import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../api/client';

/** Cancels obsolete work and prevents late results from replacing newer state. */
export function useRequest<T>() {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({ data: null, loading: false, error: null });
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const execute = useCallback(async (task: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> => {
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setState(previous => ({ ...previous, loading: true, error: null }));
    try {
      const data = await task(controller.signal);
      if (!controller.signal.aborted) { setState({ data, loading: false, error: null }); return data; }
    } catch (error) {
      if (!controller.signal.aborted) setState(previous => ({ ...previous, loading: false, error: errorMessage(error) }));
    }
  }, []);
  return { ...state, execute };
}

```

## `src/App.tsx`

```tsx
import { PIPELINE_REVISION } from './api/schemas';
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, FlaskConical, FolderInput, KeyRound, Moon, ShieldCheck, Sun, Terminal, Unplug } from 'lucide-react';
import { ApiClient } from './api/client';
import type { Citation, Health } from './api/schemas';
import { usePlayground } from './hooks/usePlayground';
import { useRequest } from './hooks/useRequest';
import { Playground } from './components/Playground';
import { Inspector } from './components/Inspector';
import { IngestionPanel } from './components/IngestionPanel';
import { ReviewsPanel } from './components/ReviewsPanel';
import { ConnectionDialog } from './components/ConnectionDialog';
import { Badge, Button } from './components/ui';

type View = 'playground' | 'documents' | 'reviews';
const VIEWS = [{ id: 'playground', label: 'Playground', icon: FlaskConical }, { id: 'documents', label: 'Documents', icon: FolderInput }, { id: 'reviews', label: 'Human review', icon: ShieldCheck }] as const;

function Workspace({ token, onConnect, theme, toggleTheme }: { token: string; onConnect: () => void; theme: string; toggleTheme: () => void }) {
  const [view, setView] = useState<View>('playground');
  const api = useMemo(() => new ApiClient(token), [token]);
  const health = useRequest<Health>();
  const playground = usePlayground(api);
  const [citation, setCitation] = useState<{ runId: string; citation: Citation } | null>(null);
  useEffect(() => { void health.execute(signal => api.health(signal)); }, [api, health.execute]);
  const selected = playground.runs.find(run => run.id === playground.selectedId);
  const title = VIEWS.find(item => item.id === view)!.label;
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="navigation"><div className="brand"><div className="brand-symbol">E<span /></div><div><span className="text-lg font-semibold tracking-tight">evidence</span><span className="block text-xs muted">RAG workbench</span></div></div>
      <div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{VIEWS.map(item => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)} aria-current={view === item.id ? 'page' : undefined}><item.icon size={18} /><span>{item.label}</span>{view === item.id && <span className="nav-active-marker" />}</button>)}</nav>
      <div className="nav-bottom"><div className="rounded-xl border border-line p-4"><Terminal size={17} className="mb-3 text-accent" /><p className="text-sm font-medium">Your pipeline. In focus.</p><p className="mt-2 text-xs leading-5 muted">Inspect retrieval, trace claims, and review what needs a human.</p></div><button className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}<span>{theme === 'dark' ? 'Light appearance' : 'Dark appearance'}</span></button></div>
    </aside>
    <div className="workspace-main"><header className="topbar"><div className="flex items-center gap-2 text-sm"><span className="muted hidden sm:inline">Workspace</span><ArrowRight size={12} className="muted hidden sm:inline" /><span>{title}</span></div><div className="flex items-center gap-3"><span className="hidden sm:inline-flex">{health.loading ? <Badge>Checking API…</Badge> : health.error ? <Badge tone="warning">API unavailable</Badge> : health.data ? <Badge tone="good">{health.data.mode === 'demo' ? 'Demo API ready' : 'Live API ready'}</Badge> : null}</span><Button onClick={onConnect}><KeyRound size={14} />{token ? 'Connection' : 'Set API token'}</Button><button className="mobile-theme" onClick={toggleTheme} aria-label="Toggle appearance">{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button></div></header>
      {health.data && health.data.pipeline_revision !== PIPELINE_REVISION && <div className="connection-banner" role="status"><Unplug size={16} /><span>The backend is running an older answer pipeline. Restart FastAPI to load the update, then check again.</span><button onClick={() => void health.execute(signal => api.health(signal))} className="underline underline-offset-4 ml-auto">Check again</button></div>}
      {health.error && <div className="connection-banner"><Unplug size={16} /><span>Backend unavailable. Start FastAPI or check your proxy target.</span><button onClick={() => void health.execute(signal => api.health(signal))} className="underline underline-offset-4 ml-auto">Retry</button></div>}
      <main id="main-content" tabIndex={-1} className={`main-content ${view === 'playground' ? 'playground-layout' : ''}`}>
        <div hidden={view !== 'playground'} className="min-w-0"><Playground state={playground} authenticated={!!token} onConnect={onConnect} onCitation={(id, selectedCitation) => { playground.select(id); setCitation({ runId: id, citation: selectedCitation }); }} /></div>
        {view === 'playground' && <Inspector key={selected?.id ?? 'empty'} answer={selected?.answer} pending={selected?.status === 'pending'} citation={citation?.runId === selected?.id ? citation?.citation : null} />}
        <div hidden={view !== 'documents'}><IngestionPanel api={api} authenticated={!!token} onConnect={onConnect} /></div>
        <div hidden={view !== 'reviews'}><ReviewsPanel api={api} active={view === 'reviews'} authenticated={!!token} onConnect={onConnect} /></div>
      </main>
      <footer className="footer"><span>Evidence workbench <span className="muted">/ v1.0</span></span><span className="muted">Session data stays in memory · Queries run independently</span></footer>
    </div>
  </div>;
}

export default function App() {
  const [token, setToken] = useState('');
  const [connection, setConnection] = useState(false);
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('evidence-theme') === 'light' ? 'light' : 'dark'; } catch { return 'dark'; } });
  useEffect(() => { document.documentElement.dataset.theme = theme; try { localStorage.setItem('evidence-theme', theme); } catch { /* Private browser modes may block storage. */ } }, [theme]);
  // Remount on identity changes to abort requests and remove prior tenant data.
  return <><Workspace key={token} token={token} onConnect={() => setConnection(true)} theme={theme} toggleTheme={() => setTheme(previous => previous === 'dark' ? 'light' : 'dark')} /><ConnectionDialog open={connection} token={token} onClose={() => setConnection(false)} onApply={setToken} /></>;
}

```

## `src/components/Playground.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Braces, CheckCheck, ChevronRight, Clock3, Layers3, SlidersHorizontal, Square, Trash2, UserRound } from 'lucide-react';
import type { Citation } from '../api/schemas';
import type { usePlayground } from '../hooks/usePlayground';
import { Badge, Button, duration, ErrorNotice, Skeleton } from './ui';

const EXAMPLES = ['Enterprise support available hours', 'Billing disputes submitted days', 'medical support available hours'];

export function Playground({ state, authenticated, onConnect, onCitation }: {
  state: ReturnType<typeof usePlayground>; authenticated: boolean; onConnect: () => void;
  onCitation: (runId: string, citation: Citation) => void;
}) {
  const [query, setQuery] = useState('');
  const [settings, setSettings] = useState(false);
  const latest = useRef<HTMLDivElement>(null);
  useEffect(() => { latest.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [state.runs.length]);
  const submit = () => { if (!authenticated) { onConnect(); return; } void state.submit(query); };
  return <section aria-label="Query playground" className="min-w-0">
    <div className="section-heading"><div><div className="eyebrow">EXPERIMENT / INSPECT / VERIFY</div><h1>Query playground</h1><p className="muted mt-2">Follow every answer back to its evidence.</p></div><Badge tone="accent"><Braces size={13} /> POST /query</Badge></div>
    <form className="query-box" onSubmit={event => { event.preventDefault(); submit(); }}>
      <label className="label flex items-center gap-2" htmlFor="query"><Layers3 size={16} /> Your question</label>
      <textarea id="query" value={query} onChange={event => setQuery(event.target.value)} maxLength={2000} rows={3}
        placeholder="Ask a question about your documents…" onKeyDown={event => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); if (!state.busy) submit(); }
        }} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
        <div className="flex items-center gap-3"><Button variant="ghost" aria-expanded={settings} onClick={() => setSettings(!settings)}><SlidersHorizontal size={15} /> Parameters</Button><span className="text-xs muted tabular-nums">{query.length}/2,000</span></div>
        {state.busy ? <Button onClick={state.cancel}><Square size={14} /> Stop waiting</Button> : <Button variant="primary" type="submit" disabled={query.trim().length < 3}><span>{authenticated ? 'Run query' : 'Connect to run'}</span><ArrowUp size={17} /></Button>}
      </div>
      {settings && <div className="settings-note"><span className="label">Server-managed parameters</span><div className="mt-3 grid gap-3 sm:grid-cols-3">
        {['Top-K: dynamic', 'Reranking: server policy', 'Temperature: not exposed'].map(label => <div key={label} className="rounded-lg border border-line p-3 text-sm muted">{label}</div>)}
      </div><p className="mt-3 text-xs muted">This API accepts only query text. Change retrieval settings in the backend configuration and restart it. Requests are independent; previous messages are not sent.</p></div>}
    </form>
    <div className="mt-3 flex flex-wrap gap-2" aria-label="Example queries">{EXAMPLES.map((example, i) => <button className="example-chip" key={example} onClick={() => setQuery(example)}>{['Support hours', 'Billing policy', 'Review trigger'][i]}<ChevronRight size={12} /></button>)}</div>
    <div className="my-7 flex items-center justify-between"><h2 className="label">SESSION RUNS <span className="ml-2 muted">{state.runs.length.toString().padStart(2, '0')}</span></h2>{state.runs.length > 0 && <Button variant="ghost" onClick={state.clear}><Trash2 size={14} /> Clear session</Button>}</div>
    {!state.runs.length && <div className="welcome-state"><div className="inline-flex rounded-xl border border-line p-3 text-accent"><CheckCheck size={25} /></div><h2 className="mt-5 text-xl font-medium">A good answer leaves a trail.</h2><p className="mt-2 max-w-md text-sm leading-6 muted">Ingest a document, ask a question, then inspect the claims, source passages and execution metrics side by side.</p><div className="mt-8 flex flex-wrap items-center gap-3 text-xs font-mono muted"><span>01 RETRIEVE</span><ChevronRight size={13} /><span>02 GENERATE</span><ChevronRight size={13} /><span>03 VERIFY</span></div></div>}
    <div className="space-y-5" aria-live="polite" aria-relevant="additions text">{state.runs.map((run, index) => <article key={run.id} className={`run-card ${state.selectedId === run.id ? 'run-selected' : ''}`}>
      <div className="run-question"><UserRound size={17} className="shrink-0 text-accent" /><p className="min-w-0 flex-1 whitespace-pre-wrap break-words">{run.question}</p><span className="font-mono text-xs muted">{String(index + 1).padStart(2, '0')}</span></div>
      <div className="p-5 sm:p-6">
        {run.status === 'pending' ? <div role="status"><div className="mb-4 flex items-center gap-2 text-sm muted"><span className="loading-dot" />Retrieving evidence and verifying the answer…</div><Skeleton className="mb-2 h-3 w-full" /><Skeleton className="mb-2 h-3 w-11/12" /><Skeleton className="h-3 w-2/3" /></div> : run.status === 'error' ? <ErrorNotice message={run.error} /> : run.status === 'cancelled' ? <p className="text-sm muted">Stopped waiting. The backend may still finish this request.</p> : run.answer && <>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold">Evidence</span><Badge tone={run.answer.status === 'answered' ? 'good' : 'warning'}>{run.answer.status === 'answered' ? 'Grounding passed' : run.answer.status === 'review' ? 'Human review' : 'Abstained'}</Badge>{run.answer.mode === 'live' && run.answer.answer_style === 'extractive' && <Badge>Source sentences</Badge>}{run.answer.mode === 'demo' && <Badge>Demo · exact extract</Badge>}</div><span className="flex items-center gap-1 text-xs muted"><Clock3 size={12} />{duration(run.answer.latency_ms)}</span></div>
          {run.answer.claims.length ? <div className="space-y-4">{run.answer.claims.map((claim, claimIndex) => <div key={claimIndex} className="claim"><span className="claim-number" title={`Claim ${claimIndex + 1}`}>C{claimIndex + 1}</span><p className="min-w-0 whitespace-pre-wrap leading-7 break-words">{claim.text}{' '}{run.answer!.citations.filter(c => c.claim_index === claimIndex).map(citation => <button key={citation.number} className="citation" aria-label={`Inspect citation ${citation.number} for claim ${claimIndex + 1}`} onClick={() => onCitation(run.id, citation)}>[{citation.number}]</button>)}</p></div>)}</div> : <p className="leading-7">{run.answer.answer}</p>}
          {run.answer.review_reasons.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{run.answer.review_reasons.map(reason => <Badge key={reason} tone="warning">{reason.replaceAll('_', ' ')}</Badge>)}</div>}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4"><span className="text-xs muted">{run.answer.contexts.length} contexts · {run.answer.claims.length} claims · {run.answer.citations.length} citations</span><Button variant="ghost" onClick={() => state.select(run.id)}>Inspect run <ChevronRight size={14} /></Button></div>
        </>}
      </div>
    </article>)}</div><div ref={latest} />
  </section>;
}

```

## `src/components/Inspector.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, FileText, ScanSearch, Timer, Fingerprint } from 'lucide-react';
import type { Answer, Citation } from '../api/schemas';
import { Badge, CopyButton, duration, safeSource, Skeleton, usd } from './ui';

function Highlight({ text, quote }: { text: string; quote?: string }) {
  const start = quote ? text.indexOf(quote) : -1;
  return <p className="whitespace-pre-wrap break-words leading-7">{start < 0 || !quote ? text : <>{text.slice(0, start)}<mark>{quote}</mark>{text.slice(start + quote.length)}</>}</p>;
}

export function Inspector({ answer, pending, citation }: { answer?: Answer; pending?: boolean; citation?: Citation | null }) {
  const [tab, setTab] = useState<'evidence' | 'metrics'>('evidence');
  const focused = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (citation) { setTab('evidence'); requestAnimationFrame(() => focused.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })); }
  }, [citation]);
  const stages = Object.entries(answer?.stage_ms ?? {});
  const totalStages = Math.max(1, stages.reduce((sum, [, ms]) => sum + ms, 0));
  return <aside className="inspector" aria-label="Evidence inspector">
    <div className="flex items-center justify-between p-5"><h2 className="flex items-center gap-2 font-semibold"><ScanSearch size={18} className="text-accent" /> Run inspector</h2>{answer && <Badge>{answer.contexts.length} chunks</Badge>}</div>
    <div className="tab-strip" role="group" aria-label="Inspector views"><button aria-pressed={tab === 'evidence'} onClick={() => setTab('evidence')} className={tab === 'evidence' ? 'active' : ''}><FileText size={15} /> Evidence</button><button aria-pressed={tab === 'metrics'} onClick={() => setTab('metrics')} className={tab === 'metrics' ? 'active' : ''}><Timer size={15} /> Execution</button></div>
    {pending ? <div className="space-y-4 p-5" role="status" aria-label="Waiting for run results"><Skeleton className="h-20 w-full" /><Skeleton className="h-36 w-full" /><Skeleton className="h-20 w-full" /></div> : !answer ? <div className="inspector-empty"><ScanSearch size={32} strokeWidth={1.3} /><p className="mt-4 font-medium">Evidence belongs here</p><p className="mt-2 text-sm leading-6 muted">Run a query or select a completed run to explore its source passages and execution.</p></div> : tab === 'evidence' ? <div className="p-4 space-y-4" role="region" aria-label="Retrieved evidence">
      <p className="text-xs leading-5 muted">Ordered by retrieval rank. A rerank score is not a calibrated probability.</p>
      {!answer.contexts.length && <p className="py-6 text-sm muted">No context was selected for this run.</p>}
      {answer.contexts.map((hit, index) => {
        const selected = citation?.chunk_id === hit.chunk.id;
        const citations = answer.citations.filter(c => c.chunk_id === hit.chunk.id);
        const href = safeSource(hit.chunk.source);
        return <div key={hit.chunk.id} ref={selected ? focused : null} className={`context-card ${selected ? 'context-selected' : ''}`}>
          <div className="mb-3 flex gap-3"><div className="context-index">{String(index + 1).padStart(2, '0')}</div><div className="min-w-0"><h3 className="text-sm font-semibold break-words">{hit.chunk.title}</h3><span className="text-xs muted">{hit.chunk.document_id}</span></div></div>
          <div className="mb-4 flex flex-wrap gap-2"><Badge>Fusion {hit.fusion_score.toFixed(4)}</Badge><Badge tone="accent">Rerank {hit.rerank_score === null ? 'unavailable' : hit.rerank_score.toFixed(3)}</Badge></div>
          <div className="text-sm"><Highlight text={hit.chunk.text} quote={selected ? citation?.quote : undefined} /></div>
          <div className="mt-4 flex flex-wrap gap-2">{citations.map(c => <Badge key={c.number} tone={selected && citation?.number === c.number ? 'good' : 'neutral'}>[{c.number}] Claim {c.claim_index + 1}</Badge>)}</div>
          {selected && <div className="mt-3 text-xs text-accent">Quoted characters {citation.start}–{citation.end} in source</div>}
          <details className="mt-4 border-t border-line pt-3"><summary className="text-xs muted cursor-pointer">Source & provenance</summary><dl className="mt-3 space-y-3 text-xs"><div><dt className="muted">Source</dt><dd className="mt-1 break-all">{href ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent">{hit.chunk.source}<ArrowUpRight size={12} className="ml-1 inline" /></a> : hit.chunk.source}</dd></div><div><dt className="muted">Chunk ID</dt><dd className="mt-1 font-mono break-all">{hit.chunk.id}</dd></div><div><dt className="muted">Content version</dt><dd className="mt-1 font-mono break-all">{hit.chunk.version}</dd></div><div><dt className="muted">Character offsets</dt><dd>{hit.chunk.start}–{hit.chunk.end} (Python character indices)</dd></div></dl></details>
        </div>;
      })}
    </div> : <div className="p-5 space-y-6" role="region" aria-label="Execution metrics">
      <div className="grid grid-cols-2 gap-3"><div className="metric"><span>Latency</span><strong>{duration(answer.latency_ms)}</strong></div><div className="metric"><span>Faithfulness</span><strong>{answer.faithfulness === null ? 'Not scored' : answer.faithfulness.toFixed(2)}</strong></div></div>
      {answer.cache_hit && <p className="text-xs leading-5 text-accent">Verified answer reused from cache. Latency and usage describe this request; no model calls were made. Citations refer to the unchanged indexed sources.</p>}
      {answer.answer_style === 'extractive' && <p className="text-xs leading-5 muted">The model selected relevant source sentences. Answer wording comes directly from the document; citations and grounding checks still apply.</p>}
      {!!answer.initial_verification_reasons?.length && <p className="text-xs leading-5 muted">Initial verification: {answer.initial_verification_reasons.map(reason => reason.replaceAll('_', ' ')).join(', ')}. See the final outcome for the result after recovery.</p>}
      {answer.mode === 'demo'   && <p className="text-xs leading-5 muted">Demo faithfulness checks exact extracts. These results do not measure live model quality.</p>}
      <section><h3 className="label mb-4">STAGE LATENCY</h3><div className="space-y-4">{stages.map(([name, ms]) => <div key={name}><div className="mb-2 flex justify-between text-xs"><span className="capitalize">{name.replaceAll('_', ' ')}</span><span className="muted tabular-nums">{duration(ms)}</span></div><div className="stage-track"><div style={{ width: `${Math.max(1, ms / totalStages * 100)}%` }} /></div></div>)}</div><p className="mt-3 text-xs muted">Share of measured stage time; excludes other overhead.</p></section>
      <section><h3 className="label mb-3">USAGE & COST</h3><dl className="metric-list"><div><dt>Input tokens</dt><dd>{answer.usage.input_tokens.toLocaleString()}</dd></div><div><dt>Output tokens</dt><dd>{answer.usage.output_tokens.toLocaleString()}</dd></div><div><dt>Provider attempts</dt><dd>{answer.usage.attempts}</dd></div><div><dt>Known model cost</dt><dd>{usd(answer.usage.known_cost_usd)}</dd></div><div><dt>Reserved uncertain cost</dt><dd>{usd(answer.usage.reserved_cost_usd)}</dd></div><div><dt>Uncertain attempts</dt><dd>{answer.usage.uncertain_attempts}</dd></div></dl><p className="mt-3 text-xs leading-5 muted">Known cost excludes local compute. Reservations are estimates, not confirmed charges.</p></section>
      <section className="border-t border-line pt-4"><h3 className="label mb-3 flex items-center gap-2"><Fingerprint size={15} /> TRACE</h3>{[['Trace ID', answer.trace_id], ['Request ID', answer.request_id]].map(([label, value]) => <div className="mb-3" key={label}><div className="flex items-center justify-between text-xs muted"><span>{label}</span><CopyButton value={value} label={`Copy ${label}`} /></div><p className="font-mono text-xs break-all">{value}</p></div>)}</section>
    </div>}
  </aside>;
}

```

## `src/components/IngestionPanel.tsx`

```tsx
import { FileUploadPanel } from './FileUploadPanel';
import { useRef, useState } from 'react';
import { CheckCircle2, FileJson2, FilePlus2, Upload } from 'lucide-react';
import type { ApiClient } from '../api/client';
import { IngestSchema } from '../api/schemas';
import { useRequest } from '../hooks/useRequest';
import { SAMPLE_DOCUMENTS } from '../samples';
import { Badge, Button, ErrorNotice } from './ui';

export function IngestionPanel({ api, authenticated, onConnect }: { api: ApiClient; authenticated: boolean; onConnect: () => void }) {
  const [mode, setMode] = useState<'form' | 'json' | 'files'>('files');
  const [filesBusy, setFilesBusy] = useState(false);
  const [fields, setFields] = useState({ id: '', title: '', source: '', groups: 'staff', text: '' });
  const [json, setJson] = useState('');
  const [validation, setValidation] = useState<string | null>(null);
  const [result, setResult] = useState<{ indexed_chunks: number } | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const request = useRequest<{ indexed_chunks: number }>();
  const update = (field: keyof typeof fields, value: string) => { setFields(previous => ({ ...previous, [field]: value })); setResult(null); };
  const submit = async () => {
    if (!authenticated) { onConnect(); return; }
    setValidation(null); setResult(null);
    try {
      const raw: unknown = mode === 'json' ? JSON.parse(json) : { documents: [{ ...fields,
        id: fields.id.trim(), title: fields.title.trim(), source: fields.source.trim(),
        groups: fields.groups.split(',').map(group => group.trim()).filter(Boolean) }] };
      const parsed = IngestSchema.safeParse(raw);
      if (!parsed.success) { setValidation(parsed.error.issues.map(issue => `${issue.path.join('.') || 'Batch'}: ${issue.message}`).slice(0, 4).join(' · ')); return; }
      const response = await request.execute(signal => api.ingest(parsed.data, signal));
      if (response) setResult(response);
    } catch { setValidation('Invalid JSON. Provide an object containing a documents array.'); }
  };
  return <section className="max-w-4xl">
    <div className="section-heading"><div><div className="eyebrow">BUILD YOUR TEST CORPUS</div><h1>Document ingestion</h1><p className="muted mt-2">Give your next query something to work with.</p></div><Badge tone="accent">{mode === 'files' ? 'POST /ingest/file' : 'POST /ingest'}</Badge></div>
    <div className="panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-5"><div className="segmented" aria-label="Input mode">{(['files', 'form', 'json'] as const).map(value => <button key={value} disabled={filesBusy} aria-pressed={mode === value} className={mode === value ? 'active' : ''} onClick={() => { setMode(value); setValidation(null); setResult(null); }}>{value === 'files' ? 'File upload' : value === 'form' ? 'Paste text' : 'JSON batch'}</button>)}</div><Button disabled={filesBusy} onClick={() => { setMode('json'); setJson(JSON.stringify(SAMPLE_DOCUMENTS, null, 2)); setValidation(null); setResult(null); }}><FileJson2 size={15} /> Load sample corpus</Button></div>
      <div hidden={mode !== 'files'}><FileUploadPanel api={api} authenticated={authenticated} onConnect={onConnect} onBusy={setFilesBusy} /></div>
      <form hidden={mode === 'files'} className="space-y-5 p-5 sm:p-7" onSubmit={event => { event.preventDefault(); void submit(); }}>
        {mode === 'form' ? <><div className="grid gap-5 sm:grid-cols-2"><label className="field">Document ID<input value={fields.id} onChange={e => update('id', e.target.value)} placeholder="support-policy" maxLength={100} required /><span>Stable ID; reusing it replaces the document.</span></label><label className="field">Title<input value={fields.title} onChange={e => update('title', e.target.value)} placeholder="Enterprise support policy" maxLength={200} required /></label></div><label className="field">Source<input value={fields.source} onChange={e => update('source', e.target.value)} placeholder="https://docs.example.com/support or urn:acme:support" maxLength={500} required /></label><label className="field">Access groups<input value={fields.groups} onChange={e => update('groups', e.target.value)} placeholder="staff, support" required /><span>Comma-separated. Only matching groups can retrieve this document.</span></label><label className="field">Document text<textarea value={fields.text} onChange={e => update('text', e.target.value)} rows={9} maxLength={200000} placeholder="Paste the source text here. Paragraphs and exact wording are preserved." required /></label></> : <><div className="flex items-center justify-between"><label htmlFor="batch-json" className="label">DOCUMENTS PAYLOAD</label><Button onClick={() => upload.current?.click()}><Upload size={14} /> Import JSON</Button></div><input ref={upload} type="file" accept=".json,application/json" className="hidden" aria-label="Import JSON file" onChange={async e => {
          const file = e.target.files?.[0]; e.target.value = '';
          if (!file) return;
          if (file.size > 1_000_000) { setValidation('File exceeds the default 1 MB body limit.'); return; }
          try { setJson(await file.text()); setResult(null); setValidation(null); } catch { setValidation('Could not read this file.'); }
        }} /><textarea id="batch-json" className="font-mono text-sm" value={json} rows={17} placeholder={'{\n  "documents": [\n    { "id": "support", "title": "Support", "source": "urn:acme:support",\n      "groups": ["staff"], "text": "Your source text." }\n  ]\n}'} onChange={e => { setJson(e.target.value); setResult(null); }} /></>}
        <ErrorNotice message={validation ?? request.error} />
        {result && <div className="success-notice" role="status"><CheckCircle2 size={18} /><span>Indexed {result.indexed_chunks} {result.indexed_chunks === 1 ? 'chunk' : 'chunks'} in this batch. Your documents are ready to query.</span></div>}
        <div className="flex flex-wrap justify-between items-center gap-4 border-t border-line pt-5"><p className="text-xs leading-5 muted max-w-sm">Up to 20 documents / 1 MB per request. Chunking uses the server configuration. Existing document IDs are replaced atomically.</p><Button type="submit" variant="primary" disabled={request.loading}>{request.loading ? <><span className="loading-dot" /> Indexing documents…</> : <><FilePlus2 size={16} />{authenticated ? 'Ingest documents' : 'Connect to ingest'}</>}</Button></div>
      </form>
    </div>
  </section>;
}

```

## `src/components/FileUploadPanel.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, FileUp, Trash2, Upload } from 'lucide-react';
import { type ApiClient, errorMessage } from '../api/client';
import { validateFile, type UploadLimits, type UploadResult } from '../api/uploads';
import { Button, ErrorNotice } from './ui';

type Entry = { id: string; file: File; documentId: string; progress: number;
  status: 'queued' | 'uploading' | 'processing' | 'indexed' | 'error' | 'cancelled';
  error?: string; result?: UploadResult; invalid?: boolean };

export function FileUploadPanel({ api, authenticated, onConnect, onBusy }: {
  api: ApiClient; authenticated: boolean; onConnect: () => void; onBusy: (busy: boolean) => void;
}) {
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [limitsError, setLimitsError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [groups, setGroups] = useState('staff');
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    setLimitsError(null);
    void api.uploadLimits(abort.signal).then(setLimits).catch(error => {
      if (!abort.signal.aborted) setLimitsError(`${errorMessage(error)} Restart the backend after installing the upload dependencies.`);
    });
    return () => abort.abort();
  }, [api, reload]);
  useEffect(() => () => controller.current?.abort(), []);

  const update = (id: string, changes: Partial<Entry>) => setEntries(previous => previous.map(entry => entry.id === id ? { ...entry, ...changes } : entry));
  const addFiles = (files: FileList | File[]) => {
    if (!limits || busy) return;
    const selected = Array.from(files);
    if (entries.length + selected.length > 20) { setValidation('Queue up to 20 files at a time. Remove completed files to add more.'); return; }
    const names = new Set(entries.map(entry => entry.file.name));
    const next: Entry[] = [];
    for (const file of selected) {
      if (names.has(file.name)) { setValidation('A file with this name is already in the queue. Remove it before adding a replacement.'); continue; }
      names.add(file.name);
      const error = validateFile(file, limits);
      next.push({ id: crypto.randomUUID(), file, documentId: '', status: error ? 'error' : 'queued', progress: 0, error: error ?? undefined, invalid: !!error });
    }
    setEntries(previous => [...previous, ...next]);
  };
  const submit = async () => {
    if (!authenticated) { onConnect(); return; }
    if (controller.current || !limits) return;
    const accessGroups = groups.split(',').map(group => group.trim()).filter(Boolean);
    if (!accessGroups.length || accessGroups.length > 50) { setValidation('Provide between 1 and 50 access groups.'); return; }
    const pending = entries.filter(entry => !entry.invalid && entry.status !== 'indexed');
    if (!pending.length) return;
    if (pending.some(entry => entry.documentId && !/^[A-Za-z0-9_.-]{1,100}$/.test(entry.documentId))) {
      setValidation('Document IDs can contain only letters, numbers, dots, underscores and hyphens (up to 100 characters).'); return;
    }
    const customIds = pending.map(entry => entry.documentId).filter(Boolean);
    if (new Set(customIds).size !== customIds.length) { setValidation('Use distinct document IDs for files in this queue.'); return; }
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); onBusy(true); setValidation(null);
    try {
      for (const entry of pending) {
        if (abort.signal.aborted) break;
        update(entry.id, { status: 'uploading', progress: 0, error: undefined });
        try {
          const result = await api.uploadFile(entry.file, accessGroups, entry.documentId, progress => {
            update(entry.id, { progress, status: progress === 100 ? 'processing' : 'uploading' });
          }, abort.signal);
          update(entry.id, { status: 'indexed', result, progress: 100 });
        } catch (error) {
          update(entry.id, { status: abort.signal.aborted ? 'cancelled' : 'error', error: errorMessage(error) });
        }
      }
    } finally {
      controller.current = null; setBusy(false); onBusy(false);
    }
  };
  return <div className="space-y-5 p-5 sm:p-7">
    <div><h2 className="font-semibold">Upload source files</h2><p className="muted mt-1 text-sm">Extract text, create chunks and index your documents in one step.</p></div>
    <ErrorNotice message={limitsError} />
    {limitsError && <Button onClick={() => setReload(value => value + 1)}>Reload upload settings</Button>}
    {!limits && !limitsError && <div className="skeleton h-24 rounded-xl" aria-label="Loading upload settings" />}
    {limits && <>
      <input ref={input} type="file" multiple accept={limits.extensions.join(',')} className="sr-only" aria-label="Choose source files" disabled={busy} onChange={event => { if (event.target.files) addFiles(event.target.files); event.target.value = ''; }} />
      <button type="button" disabled={busy} className={`upload-dropzone ${dragging ? 'dragging' : ''}`} onClick={() => input.current?.click()}
        onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={event => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}>
        <FileUp size={30} className="text-accent" /><span className="font-semibold">Drop files here, or click to browse</span>
        <span className="muted text-xs">{limits.extensions.join(' · ')} · {(limits.max_file_bytes / 1048576).toFixed(0)} MiB per file</span>
      </button>
      <label className="field">Access groups<input value={groups} onChange={event => setGroups(event.target.value)} disabled={busy} placeholder="staff" /><span>Comma-separated. Groups must belong to your connected identity.</span></label>
      <p className="muted text-xs leading-5">Each file is indexed independently. Its filename supplies the title and a stable source ID. Uploading the same filename replaces its previous document; set a custom ID to keep versions. PDFs need selectable text; OCR is not included.</p>
      <ErrorNotice message={validation} />
      <ul className="space-y-3" aria-label="Selected files">
        {entries.map(entry => <li key={entry.id} className="upload-file">
          <div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="font-medium break-all">{entry.file.name}</div><div className="muted text-xs mt-1">{(entry.file.size / 1024).toFixed(1)} KiB</div></div>
            <Button disabled={busy} onClick={() => setEntries(previous => previous.filter(item => item.id !== entry.id))} aria-label={`Remove ${entry.file.name}`}><Trash2 size={15} /></Button></div>
          <label className="field mt-3 text-xs">Document ID (optional)<input value={entry.documentId} disabled={busy || entry.status === 'indexed'} maxLength={100} placeholder="Automatic stable ID from filename" onChange={event => update(entry.id, { documentId: event.target.value })} /></label>
          {(entry.status === 'uploading' || entry.status === 'processing') && <div className="mt-3"><progress className="upload-progress" value={entry.progress} max={100} aria-label={`Upload progress for ${entry.file.name}`} /><p className="muted text-xs mt-1" role="status">{entry.status === 'processing' ? 'Upload complete · Parsing and indexing…' : `Uploading ${entry.progress}%`}</p></div>}
          {entry.status === 'queued' && <p className="muted mt-3 text-xs">Ready to upload</p>}
          {entry.result && <div className="success-notice mt-3" role="status"><CheckCircle2 size={18} /><div><p>Indexed {entry.result.indexed_chunks} chunks · {entry.result.extracted_characters.toLocaleString()} characters</p><p className="text-xs mt-1 break-all">{entry.result.document_id}</p></div></div>}
          {entry.result?.warnings.map((warning, index) => <p key={index} className="muted text-xs mt-2">{warning}</p>)}
          {entry.error && <div className="mt-3"><ErrorNotice message={entry.error} /></div>}
        </li>)}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5"><p className="muted text-xs">{entries.filter(entry => entry.status === 'indexed').length} of {entries.length} files indexed</p><div className="flex gap-2">{busy && <Button onClick={() => controller.current?.abort()}>Cancel upload queue</Button>}<Button variant="primary" disabled={busy || !entries.some(entry => !entry.invalid && entry.status !== 'indexed')} onClick={() => void submit()}>{busy ? <><span className="loading-dot" /> Processing files…</> : <><Upload size={16} />{authenticated ? 'Upload / retry pending files' : 'Connect to upload'}</>}</Button></div></div>
      <p className="muted text-xs leading-5">Up to {limits.max_extracted_chars.toLocaleString()} extracted characters, {limits.max_pdf_pages} PDF pages or {limits.max_excel_sheets} Excel sheets. Cancel stops this browser request and queued files; server indexing may already have completed.</p>
    </>}
  </div>;
}

```

## `src/components/ReviewsPanel.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { Check, CheckCheck, RefreshCw, X, ShieldCheck } from 'lucide-react';
import type { ApiClient } from '../api/client';
import type { Review } from '../api/schemas';
import { useRequest } from '../hooks/useRequest';
import { Badge, Button, ErrorNotice, Skeleton } from './ui';
import { Inspector } from './Inspector';

export function ReviewsPanel({ api, active, authenticated, onConnect }: { api: ApiClient; active: boolean; authenticated: boolean; onConnect: () => void }) {
  const list = useRequest<Review[]>();
  const decision = useRequest<{ recorded: true }>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [note, setNote] = useState('');
  const [recorded, setRecorded] = useState<string | null>(null);
  const [localDecisions, setLocalDecisions] = useState<Record<string, 'approve' | 'reject'>>({});
  const deciding = useRef(false);
  const refresh = () => list.execute(signal => api.reviews(signal));
  useEffect(() => { if (active && authenticated) void list.execute(signal => api.reviews(signal)); }, [active, authenticated, api, list.execute]);
  const allRows = (list.data ?? []).map(row => localDecisions[row.request_id] ? { ...row, state: localDecisions[row.request_id] } : row);
  const rows = allRows.filter(row => showAll || row.state === 'pending');
  const selected = rows.find(row => row.request_id === selectedId) ?? rows[0];
  const changeSelection = (id: string) => { if (deciding.current) return; setSelectedId(id); setNote(''); setRecorded(null); };
  const submit = async (value: 'approve' | 'reject') => {
    if (!selected || !note.trim() || deciding.current) return;
    deciding.current = true; setRecorded(null);
    try {
      const id = selected.request_id;
      const response = await decision.execute(signal => api.decide(id, value, note.trim(), signal));
      if (response) {
        setLocalDecisions(previous => ({ ...previous, [id]: value }));
        setRecorded(`Decision recorded: ${value === 'approve' ? 'approved' : 'rejected'}. No answer was automatically published.`);
        setNote(''); await refresh();
      }
    } finally { deciding.current = false; }
  };
  return <section>
    <div className="section-heading"><div><div className="eyebrow">HUMAN OVERSIGHT</div><h1>Review queue</h1><p className="muted mt-2">Resolve flagged questions with the evidence in view.</p></div><Button onClick={() => { if (authenticated) void refresh(); else onConnect(); }} disabled={list.loading || decision.loading}><RefreshCw size={15} className={list.loading ? 'animate-spin' : ''} /> Refresh</Button></div>
    {!authenticated ? <div className="panel p-8"><ShieldCheck className="text-accent mb-4" /><h2 className="text-lg font-medium">Connect a reviewer identity</h2><p className="muted my-3">Your token needs the review role to view and resolve records.</p><Button variant="primary" onClick={onConnect}>Set API token</Button></div> : <>
      <ErrorNotice message={list.error} /><ErrorNotice message={decision.error} />
      {recorded && <div className="success-notice mb-5" role="status"><CheckCheck size={18} />{recorded}</div>}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div className="segmented">{[false, true].map(value => <button key={String(value)} aria-pressed={showAll === value} disabled={decision.loading} className={showAll === value ? 'active' : ''} onClick={() => { setShowAll(value); setNote(''); }}>{value ? 'All records' : `Pending (${allRows.filter(row => row.state === 'pending').length})`}</button>)}</div><span className="text-xs muted">Latest 100 records available to this identity</span></div>
      {list.loading && !list.data ? <div className="grid gap-5 md:grid-cols-2" role="status" aria-label="Loading reviews"><Skeleton className="h-56" /><Skeleton className="h-56" /></div> : !rows.length && !list.error ? <div className="welcome-state"><ShieldCheck size={32} className="text-accent" /><h2 className="mt-4 text-xl font-medium">{showAll ? 'No review records yet' : 'Nothing awaiting review'}</h2><p className="muted mt-2 text-sm">Flagged queries will appear here after the backend queues them.</p></div> : <div className="review-grid">
        <div className="space-y-3">{rows.map(row => <button key={row.request_id} className={`review-row ${row.request_id === selected?.request_id ? 'selected' : ''}`} disabled={decision.loading} onClick={() => changeSelection(row.request_id)}><div className="mb-3 flex items-center justify-between gap-2"><Badge tone={row.state === 'pending' ? 'warning' : 'neutral'}>{row.state === 'approve' ? 'Approved' : row.state === 'reject' ? 'Rejected' : 'Pending'}</Badge><span className="font-mono text-xs muted">{row.request_id.slice(0, 8)}</span></div><p className="font-medium break-words leading-6">{row.answer.question}</p><p className="mt-3 text-xs muted">{row.answer.answer.review_reasons.join(' · ').replaceAll('_', ' ')}</p></button>)}</div>
        {selected && <div className="min-w-0 space-y-5"><div className="panel p-5 sm:p-6"><h2 className="text-lg font-medium break-words">{selected.answer.question}</h2><div className="mt-3 flex flex-wrap gap-2">{selected.answer.answer.review_reasons.map(reason => <Badge tone="warning" key={reason}>{reason.replaceAll('_', ' ')}</Badge>)}</div>
          <h3 className="label mt-6 mb-3">VERIFIED DRAFT</h3>{selected.answer.verified_draft ? <div className="space-y-3">{selected.answer.verified_draft.claims.map((claim, i) => <div className="rounded-lg bg-surface-raised p-4" key={i}><p className="whitespace-pre-wrap leading-7">{claim.text}</p>{claim.evidence.map((evidence, j) => <blockquote key={j} className="mt-3 border-l-2 border-accent pl-3 text-sm muted">{evidence.quote}</blockquote>)}</div>)}</div> : <p className="text-sm leading-6 muted">No draft passed verification. Review the source context before deciding.</p>}
          {selected.state === 'pending' ? <div className="mt-6 border-t border-line pt-5"><label className="field">Decision note<textarea aria-label="Decision note" value={note} onChange={e => setNote(e.target.value)} maxLength={2000} rows={3} placeholder="Record your reasoning or the correction needed…" disabled={decision.loading} /></label><p className="mt-2 text-xs muted">A decision records reviewer judgment. It does not publish an answer.</p><div className="mt-4 flex flex-wrap gap-3"><Button variant="primary" disabled={!note.trim() || decision.loading} onClick={() => void submit('approve')}><Check size={16} />Approve</Button><Button variant="danger" disabled={!note.trim() || decision.loading} onClick={() => void submit('reject')}><X size={16} />Reject</Button>{decision.loading && <span role="status" className="text-sm muted self-center">Recording decision…</span>}</div></div> : <div className="mt-5 border-t border-line pt-4 text-sm"><p className="font-medium">Decision: {selected.state === 'approve' ? 'approved' : 'rejected'}</p>{selected.decision && <><p className="mt-2 whitespace-pre-wrap muted">{selected.decision.note}</p><p className="mt-3 text-xs muted">{selected.decision.reviewed_by} · {new Date(selected.decision.reviewed_at).toLocaleString()}</p></>}</div>}
        </div><Inspector key={selected.request_id} answer={selected.answer.answer} /></div>}
      </div>}
    </>}
  </section>;
}

```

## `src/components/ConnectionDialog.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { KeyRound, X } from 'lucide-react';
import { API_BASE } from '../api/client';
import { LOCAL_TEST_TOKEN } from '../samples';
import { Button } from './ui';

export function ConnectionDialog({ open, token, onClose, onApply }: { open: boolean; token: string; onClose: () => void; onApply: (token: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState(token);
  useEffect(() => { if (open) { setDraft(token); dialog.current?.showModal(); } else dialog.current?.close(); }, [open, token]);
  return <dialog ref={dialog} className="connection-dialog" onCancel={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <form onSubmit={event => { event.preventDefault(); onApply(draft.trim()); onClose(); }} className="p-6 sm:p-8">
      <div className="flex items-start justify-between gap-4"><div><KeyRound size={22} className="text-accent mb-4" /><h2 className="text-xl font-semibold">API connection</h2></div><Button variant="ghost" aria-label="Close connection settings" onClick={onClose}><X size={18} /></Button></div>
      <p className="my-4 text-sm leading-6 muted">Use a backend access token. Changing identity clears this browser session’s runs and documents.</p>
      <label className="field">API base URL<input readOnly value={API_BASE} /><span>Configured with VITE_API_BASE_URL. Default /api uses the local proxy.</span></label>
      <label className="field mt-5">Bearer token<input type="password" autoComplete="off" value={draft} onChange={event => setDraft(event.target.value)} placeholder="Paste your RAG access token" autoFocus /><span>Kept in memory only. Never stored in browser storage.</span></label>
      <button type="button" className="mt-3 text-sm text-accent underline underline-offset-4" onClick={() => setDraft(LOCAL_TEST_TOKEN)}>Use local test identity</button><p className="mt-2 text-xs muted">Matches testing/demo.env. Use only with your local test backend.</p>
      <div className="mt-7 flex flex-wrap justify-end gap-3">{token && <Button variant="danger" onClick={() => { onApply(''); onClose(); }}>Disconnect & clear</Button>}<Button type="submit" variant="primary" disabled={!draft.trim()}>Apply connection</Button></div>
    </form>
  </dialog>;
}

```

## `src/components/ui.tsx`

```tsx
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { AlertCircle, Copy, Check } from 'lucide-react';
import { useState } from 'react';

export function Button({ children, className = '', variant = 'secondary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button type="button" className={`button button-${variant} ${className}`} {...props}>{children}</button>;
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warning' | 'accent' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function ErrorNotice({ message }: { message?: string | null }) {
  return message ? <div role="alert" className="error-notice"><AlertCircle size={17} className="shrink-0" /><span>{message}</span></div> : null;
}
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />;
}
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  return <Button variant="ghost" className="!px-2" aria-label={label} onClick={async () => {
    try { await navigator.clipboard.writeText(value); setState('copied'); }
    catch { setState('failed'); }
  }}>{state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
    <span className={state === 'idle' ? 'sr-only' : 'text-xs'} role="status">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy unavailable' : label}</span>
  </Button>;
}
export const usd = (value: number) => `$${value.toFixed(6)}`;
export const duration = (ms: number) => ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(2)} s`;
export function safeSource(source: string): string | null {
  try { const url = new URL(source); return url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
}

```

## `src/samples.ts`

```typescript
import type { IngestBatch } from './api/schemas';
export const SAMPLE_DOCUMENTS: IngestBatch = { documents: [
  { id: 'support', title: 'Enterprise support policy', source: 'urn:acme:support:v1', groups: ['staff'], text: 'Enterprise support is available 24 hours a day. Tickets receive a response within 2 hours.' },
  { id: 'billing', title: 'Billing policy', source: 'urn:acme:billing:v1', groups: ['staff'], text: 'Annual subscriptions are billed in advance. Billing disputes must be submitted within 30 days.' },
  { id: 'onboarding', title: 'Onboarding policy', source: 'urn:acme:onboarding:v1', groups: ['staff'], text: 'New employees complete security training within 7 days. Managers approve access requests.' },
] };
export const LOCAL_TEST_TOKEN = 'test-admin-acme-000000000000000001';

```

## `src/styles.css`

```css
@import "tailwindcss";

@theme inline {
  --color-canvas: var(--canvas);
  --color-surface: var(--surface);
  --color-surface-raised: var(--raised);
  --color-line: var(--line);
  --color-accent: var(--accent);
  --color-ink: var(--ink);
  --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}

:root { color-scheme: dark; --canvas:#101216; --surface:#17191f; --raised:#20232b; --line:#2b2e38; --ink:#ecedf2; --muted:#9b9ead; --accent:#9ba8ff; --accent-solid:#667cf1; --accent-soft:#212b49; --good:#8ad3b7; --good-bg:#18322a; --warning:#e3bd7d; --warning-bg:#352c1e; --bad:#f0a1a7; --bad-bg:#352127; }
:root[data-theme="light"] { color-scheme: light; --canvas:#f6f7fb; --surface:#ffffff; --raised:#eef0f5; --line:#dfe2eb; --ink:#202431; --muted:#636b7c; --accent:#435aca; --accent-solid:#4f65da; --accent-soft:#e9edff; --good:#236548; --good-bg:#e8f5ed; --warning:#885a16; --warning-bg:#fcf1dc; --bad:#a73444; --bad-bg:#fcebef; }
* { box-sizing: border-box; }
body { margin:0; background:var(--canvas); color:var(--ink); font-family:var(--font-sans); font-size:14px; line-height:1.5; -webkit-font-smoothing:antialiased; }
button, input, textarea { font:inherit; }
button, a, summary { -webkit-tap-highlight-color:transparent; }
button { cursor:pointer; }
button:disabled { opacity:.5; cursor:not-allowed; }
button, a, input, textarea, summary { outline-offset:4px; }
:focus-visible { outline:2px solid var(--accent); }
textarea, input:not([type="file"]) { width:100%; border:1px solid var(--line); border-radius:8px; background:var(--canvas); padding:11px 13px; color:var(--ink); font-size:14px; }
textarea { resize:vertical; min-height:90px; }
input::placeholder, textarea::placeholder { color:var(--muted); opacity:.75; }
textarea:focus, input:focus { border-color:var(--accent); outline:none; box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 15%, transparent); }
mark { background:var(--accent-soft); color:var(--ink); border-bottom:1px solid var(--accent); padding:2px 0; }
[hidden] { display:none !important; }
.muted { color:var(--muted); }
.label { font-size:12px; font-weight:600; letter-spacing:.045em; }
.eyebrow { font-family:var(--font-mono); color:var(--accent); font-size:11px; letter-spacing:.13em; margin-bottom:10px; }
.app-shell { min-height:100dvh; display:grid; grid-template-columns:220px minmax(0,1fr); }
.navigation { border-right:1px solid var(--line); background:var(--surface); padding:30px 17px 17px; display:flex; flex-direction:column; position:sticky; top:0; height:100dvh; }
.brand { display:flex; align-items:center; gap:12px; padding:0 11px 39px; }
.brand-symbol { position:relative; display:grid; place-items:center; font-size:22px; font-weight:700; width:36px; height:38px; color:white; background:var(--accent-solid); border-radius:9px; }
.brand-symbol span { position:absolute; width:5px; height:5px; border-radius:2px; background:var(--surface); right:6px; top:9px; }
.nav-label { font-size:10px; letter-spacing:.13em; color:var(--muted); padding:0 12px 12px; }
.nav-item { display:flex; align-items:center; gap:11px; width:100%; padding:12px; border-radius:8px; color:var(--muted); margin:3px 0; text-align:left; transition:background .15s,color .15s; }
.nav-item:hover { background:var(--raised); color:var(--ink); }
.nav-item.active { background:var(--accent-soft); color:var(--accent); }
.nav-active-marker { width:4px; height:15px; border-radius:3px; background:var(--accent); margin-left:auto; }
.nav-bottom { margin-top:auto; padding:20px 4px 0; }
.theme-toggle { width:100%; display:flex; align-items:center; gap:10px; padding:18px 8px 4px; color:var(--muted); font-size:12px; }
.workspace-main { min-width:0; display:flex; flex-direction:column; }
.topbar { min-height:76px; border-bottom:1px solid var(--line); padding:16px 32px; display:flex; align-items:center; justify-content:space-between; gap:12px; background:var(--canvas); }
.mobile-theme { display:none; }
.main-content { flex:1; padding:34px 32px 40px; min-width:0; }
.playground-layout { display:grid; grid-template-columns:minmax(0,1fr) 350px; gap:28px; align-items:start; }
.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-bottom:28px; }
.section-heading h1 { font-size:27px; font-weight:600; line-height:1.25; letter-spacing:-.035em; }
.section-heading>.badge { margin-top:29px; white-space:nowrap; }
.button { display:inline-flex; align-items:center; justify-content:center; gap:8px; padding:9px 13px; border:1px solid transparent; border-radius:7px; font-size:12px; font-weight:500; line-height:1.5; transition:background .15s,border-color .15s; }
.button-secondary { background:var(--surface); border-color:var(--line); color:var(--ink); }
.button-secondary:hover:not(:disabled) { background:var(--raised); border-color:var(--muted); }
.button-primary { background:var(--accent-solid); color:white; border-color:var(--accent-solid); }
.button-primary:hover:not(:disabled) { filter:brightness(1.1); }
.button-ghost { color:var(--muted); padding:6px 4px; }
.button-ghost:hover:not(:disabled) { color:var(--ink); }
.button-danger { color:var(--bad); background:var(--bad-bg); }
.badge { display:inline-flex; align-items:center; gap:6px; border-radius:5px; padding:3px 7px; font-size:10px; line-height:1.6; font-weight:500; background:var(--raised); color:var(--muted); }
.badge-good { color:var(--good); background:var(--good-bg); }
.badge-warning { color:var(--warning); background:var(--warning-bg); }
.badge-accent { color:var(--accent); background:var(--accent-soft); }
.query-box { padding:20px; border:1px solid var(--line); background:var(--surface); border-radius:12px; }
.query-box:focus-within { border-color:color-mix(in srgb,var(--accent) 60%,var(--line)); }
.query-box>textarea { padding:17px 0; background:transparent; border:0; font-size:16px; min-height:118px; outline:none; box-shadow:none; }
.settings-note { margin-top:16px; padding-top:16px; border-top:1px solid var(--line); }
.example-chip { display:flex; gap:8px; align-items:center; border:1px solid var(--line); border-radius:20px; padding:5px 10px; font-size:11px; color:var(--muted); }
.example-chip:hover { color:var(--ink); background:var(--surface); }
.welcome-state { border:1px dashed var(--line); border-radius:12px; padding:42px 30px; }
.run-card { border:1px solid var(--line); border-radius:12px; overflow:hidden; background:var(--surface); animation:enter .2s ease-out; }
.run-selected { border-color:color-mix(in srgb,var(--accent) 50%,var(--line)); }
.run-question { display:flex; align-items:flex-start; gap:12px; padding:19px 22px; background:var(--raised); border-bottom:1px solid var(--line); }
.claim { display:flex; align-items:flex-start; gap:12px; font-size:15px; }
.claim-number { flex-shrink:0; font-family:var(--font-mono); color:var(--muted); font-size:10px; margin-top:7px; border:1px solid var(--line); border-radius:4px; padding:0 4px; }
.citation { display:inline; padding:0 4px; margin-left:3px; background:var(--accent-soft); color:var(--accent); border-radius:4px; font-size:12px; font-weight:600; vertical-align:baseline; }
.citation:hover { text-decoration:underline; }
.inspector { border:1px solid var(--line); background:var(--surface); border-radius:12px; min-width:0; overflow:hidden; }
.playground-layout>.inspector { position:sticky; top:20px; max-height:calc(100dvh - 40px); overflow:auto; scrollbar-width:thin; }
.tab-strip { display:flex; border-bottom:1px solid var(--line); padding:0 16px; }
.tab-strip>button { display:flex; flex:1; align-items:center; justify-content:center; gap:7px; padding:12px 4px; color:var(--muted); font-size:12px; border-bottom:2px solid transparent; }
.tab-strip>button.active { color:var(--accent); border-bottom-color:var(--accent); }
.inspector-empty { padding:65px 24px; text-align:center; display:flex; align-items:center; flex-direction:column; color:var(--muted); }
.context-card { padding:16px; border:1px solid var(--line); border-radius:8px; background:var(--canvas); scroll-margin:20px; }
.context-selected { border-color:var(--accent); }
.context-index { display:grid; place-items:center; height:32px; width:30px; flex-shrink:0; border:1px solid var(--line); border-radius:6px; font-family:var(--font-mono); font-size:11px; color:var(--muted); }
.metric { background:var(--canvas); border:1px solid var(--line); padding:14px 12px; border-radius:8px; }
.metric>span { display:block; font-size:11px; color:var(--muted); }
.metric>strong { display:block; margin-top:5px; font-family:var(--font-mono); font-size:18px; font-weight:500; }
.stage-track { height:5px; background:var(--raised); border-radius:5px; overflow:hidden; }
.stage-track>div { height:100%; background:var(--accent-solid); border-radius:5px; }
.metric-list>div { display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-bottom:1px solid var(--line); font-size:12px; }
.metric-list dt { color:var(--muted); }
.metric-list dd { font-family:var(--font-mono); }
.panel { background:var(--surface); border:1px solid var(--line); border-radius:12px; }
.field { display:flex; flex-direction:column; gap:8px; font-size:13px; font-weight:500; }
.field>span { font-size:11px; font-weight:400; color:var(--muted); }
.segmented { display:flex; padding:3px; border:1px solid var(--line); border-radius:8px; background:var(--canvas); }
.segmented>button { padding:6px 12px; font-size:12px; color:var(--muted); border-radius:5px; }
.segmented>button.active { color:var(--ink); background:var(--raised); }
.error-notice,.success-notice { padding:12px 14px; display:flex; align-items:flex-start; gap:9px; border-radius:8px; font-size:13px; line-height:1.6; }
.error-notice { background:var(--bad-bg); color:var(--bad); margin:12px 0; }
.success-notice { background:var(--good-bg); color:var(--good); }
.review-grid { display:grid; grid-template-columns:310px minmax(0,1fr); gap:24px; max-width:1100px; }
.review-row { width:100%; text-align:left; padding:18px; background:var(--surface); border:1px solid var(--line); border-radius:10px; }
.review-row.selected { border-color:var(--accent); }
.connection-dialog { max-width:500px; width:calc(100% - 32px); margin:auto; color:var(--ink); background:var(--surface); border:1px solid var(--line); border-radius:16px; }
.connection-dialog::backdrop { background:#0009; backdrop-filter:blur(3px); }
.connection-banner { display:flex; align-items:center; gap:10px; background:var(--warning-bg); color:var(--warning); padding:12px 32px; font-size:12px; }
.footer { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; border-top:1px solid var(--line); padding:15px 32px; font-size:10px; }
.skeleton { background:var(--raised); border-radius:6px; animation:pulse 1.6s ease-in-out infinite; }
.loading-dot { width:7px; height:7px; border-radius:50%; background:currentColor; display:inline-block; animation:pulse 1.2s ease-in-out infinite; }
.skip-link { position:fixed; top:-80px; left:20px; z-index:100; padding:12px; background:var(--accent-solid); color:white; border-radius:8px; }
.skip-link:focus { top:10px; }
@keyframes pulse { 50% { opacity:.35; } }
@keyframes enter { from { opacity:0; transform:translateY(5px); } to { opacity:1; transform:translateY(0); } }
@media (min-width:1600px) { .playground-layout { grid-template-columns:minmax(0,900px) minmax(350px,420px); justify-content:center; gap:36px; } .main-content { padding:42px; } }
@media (max-width:1200px) { .app-shell { grid-template-columns:190px minmax(0,1fr); } .playground-layout { grid-template-columns:minmax(0,1fr) 305px; gap:20px; } .main-content { padding:25px 22px; } .topbar { padding:16px 22px; } .section-heading { flex-wrap:wrap; gap:8px; } .section-heading>.badge { margin-top:0; } .review-grid { grid-template-columns:250px minmax(0,1fr); } }
@media (max-width:1000px) { .playground-layout { grid-template-columns:1fr; } .playground-layout>.inspector { position:static; max-height:none; } .review-grid { grid-template-columns:1fr; } }
@media (max-width:640px) { .app-shell { display:block; } .navigation { position:static; height:auto; padding:14px 16px 0; border-right:0; border-bottom:1px solid var(--line); } .brand { padding:0 0 16px; gap:10px; } .brand-symbol { height:32px; width:30px; font-size:19px; } .brand>div:last-child { display:flex; align-items:baseline; gap:10px; } .nav-label,.nav-bottom { display:none; } .navigation nav { display:flex; gap:4px; } .nav-item { justify-content:center; gap:7px; font-size:12px; padding:10px 7px; margin:0 0 10px; } .nav-item svg { width:15px; } .nav-active-marker { display:none; } .topbar { padding:12px 16px; min-height:61px; } .mobile-theme { display:block; padding:6px; color:var(--muted); } .main-content { padding:26px 16px; } .section-heading h1 { font-size:25px; } .section-heading { margin-bottom:23px; } .query-box { padding:16px; } .welcome-state { padding:28px 20px; } .connection-banner { padding:12px 16px; align-items:flex-start; } .footer { padding:16px; } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation:none !important; transition:none !important; scroll-behavior:auto !important; } }

/* File upload controls inherit the workbench light/dark tokens. */
.upload-dropzone { width: 100%; display: flex; flex-direction: column; align-items: center; gap: .65rem; padding: 2rem 1rem; border: 2px dashed var(--line); border-radius: 1rem; background: var(--surface); transition: border-color .2s, background .2s; cursor: pointer; }
.upload-dropzone:hover, .upload-dropzone.dragging { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 7%, transparent); }
.upload-dropzone:disabled { opacity: .6; cursor: wait; }
.upload-file { border: 1px solid var(--line); border-radius: .85rem; padding: 1rem; }
.upload-progress { display: block; width: 100%; height: .4rem; accent-color: var(--accent); border-radius: 1rem; }
.upload-progress::-webkit-progress-bar { background: var(--line); border-radius: 1rem; }
.upload-progress::-webkit-progress-value { background: var(--accent); border-radius: 1rem; transition: width .2s; }

```

## `vite.config.ts`

```typescript
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxy = {
    '/api': {
      target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api(?=\/|$)/, ''),
      timeout: 195_000,
      proxyTimeout: 195_000,
    },
  };
  return {
    plugins: [react(), tailwindcss()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, strictPort: true, proxy },
  };
});

```

## `tests/client.test.ts`

```typescript
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../src/api/client';
import { IngestSchema } from '../src/api/schemas';
import { runReducer, type RunState } from '../src/hooks/usePlayground';
import { safeSource } from '../src/components/ui';
import { SAMPLE_DOCUMENTS } from '../src/samples';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('API boundary', () => {
  it('sends only supported query fields, and attaches authorization', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 422 }));
    vi.stubGlobal('fetch', fetch);
    await expect(new ApiClient('secret', '/api').query('support hours')).rejects.toBeInstanceOf(ApiError);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe('/api/query');
    expect(JSON.parse(init.body)).toEqual({ text: 'support hours' });
    expect(init.headers.Authorization).toBe('Bearer secret');
    expect(init.credentials).toBe('omit');
  });
  it('reports authorization errors without rendering response HTML', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<script>secret</script>', { status: 403 })));
    await expect(new ApiClient('key').reviews()).rejects.toThrow('permission');
  });
  it('validates the backend contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ready', mode: 'invented' }))));
    await expect(new ApiClient('').health()).rejects.toThrow('contract');
  });
  it('distinguishes cancellation from network failure', async () => {
    const controller = new AbortController(); controller.abort();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')));
    await expect(new ApiClient('key').query('support', controller.signal)).rejects.toHaveProperty('name', 'AbortError');
  });
  it('never retries mutation requests automatically', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 503 }));
    vi.stubGlobal('fetch', fetch);
    await expect(new ApiClient('key').decide('id', 'approve', 'reviewed')).rejects.toThrow('unavailable');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('rejects oversized ingestion before network transmission', () => {
    const document = SAMPLE_DOCUMENTS.documents[0];
    const documents = Array.from({ length: 6 }, (_, i) => ({ ...document, id: `doc-${i}`, text: 'a'.repeat(200000) }));
    expect(() => new ApiClient('key').ingest({ documents })).toThrow('1 MB');
  });
});

describe('state and content safety', () => {
  it('ignores a late error after cancellation', () => {
    const state: RunState = { runs: [{ id: '1', question: 'test', started: '', status: 'pending' }], selectedId: '1' };
    const cancelled = runReducer(state, { type: 'cancel', id: '1' });
    expect(runReducer(cancelled, { type: 'error', id: '1', error: 'late' }).runs[0].status).toBe('cancelled');
  });
  it('bounds history to 30 runs', () => {
    let state: RunState = { runs: [], selectedId: null };
    for (let i = 0; i < 35; i++) state = runReducer(state, { type: 'start', run: { id: String(i), question: 'test', started: '', status: 'pending' } });
    expect(state.runs).toHaveLength(30); expect(state.runs[0].id).toBe('5');
  });
  it('does not permit executable source links', () => {
    expect(safeSource('javascript:alert(1)')).toBeNull();
    expect(safeSource('urn:acme:test')).toBeNull();
    expect(safeSource('https://example.com/source')).toBe('https://example.com/source');
  });
  it('rejects duplicate document ids and client-side tenant overrides', () => {
    expect(IngestSchema.safeParse({ documents: [SAMPLE_DOCUMENTS.documents[0], SAMPLE_DOCUMENTS.documents[0]] }).success).toBe(false);
    expect(IngestSchema.safeParse({ ...SAMPLE_DOCUMENTS, tenant: 'other' }).success).toBe(false);
  });
});

```

## `tests/uploads.test.ts`

```typescript
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { validateFile, type UploadLimits } from '../src/api/uploads';

const limits: UploadLimits = { extensions: ['.pdf', '.txt'], max_file_bytes: 1000, max_extracted_chars: 200000, max_pdf_pages: 100, max_excel_sheets: 50, parse_timeout_s: 30 };
const result = { document_id: 'file-test', source: 'urn:upload:test', indexed_chunks: 2, extracted_characters: 500, warnings: [] };
class FakeXHR {
  static latest: FakeXHR;
  headers: Record<string, string> = {};
  upload: { onprogress?: (event: { lengthComputable: boolean; loaded: number; total: number }) => void; onload?: () => void } = {};
  onload?: () => void; onabort?: () => void; onerror?: () => void; ontimeout?: () => void;
  status = 200; responseText = JSON.stringify(result); timeout = 0;
  body?: FormData; method = ''; url = '';
  constructor() { FakeXHR.latest = this; }
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: FormData) { this.body = body; }
  abort() { this.onabort?.(); }
}
afterEach(() => vi.unstubAllGlobals());
describe('upload validation and multipart client', () => {
  it('validates extension, empty files, size and filename', () => {
    expect(validateFile({ name: 'resume.PDF', size: 1000 }, limits)).toBeNull();
    expect(validateFile({ name: 'resume.pdf', size: 1001 }, limits)).toContain('exceeds');
    expect(validateFile({ name: 'resume.exe', size: 10 }, limits)).toContain('Unsupported');
    expect(validateFile({ name: 'resume.txt', size: 0 }, limits)).toContain('empty');
  });
  it('sends authenticated multipart and measures bytes before awaiting indexing', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const progress = vi.fn();
    const promise = new ApiClient('test-token', '/api').uploadFile(new File(['content'], 'resume.txt'), ['staff'], 'resume-v1', progress, new AbortController().signal);
    const xhr = FakeXHR.latest;
    expect(xhr.url).toBe('/api/ingest/file');
    expect(xhr.headers).toEqual({ Authorization: 'Bearer test-token' });
    expect(xhr.body?.get('groups')).toBe('["staff"]');
    expect(xhr.body?.get('document_id')).toBe('resume-v1');
    expect((xhr.body?.get('file') as File).name).toBe('resume.txt');
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    expect(progress).toHaveBeenLastCalledWith(50);
    xhr.upload.onload?.();
    expect(progress).toHaveBeenLastCalledWith(100);
    xhr.onload?.();
    await expect(promise).resolves.toEqual(result);
  });
  it('surfaces safe parsing failures and cancellation', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const api = new ApiClient('');
    const file = new File(['bad'], 'resume.pdf');
    const failed = api.uploadFile(file, ['staff'], '', vi.fn(), new AbortController().signal);
    FakeXHR.latest.status = 422;
    FakeXHR.latest.responseText = JSON.stringify({ detail: { code: 'corrupt_file', message: 'Invalid PDF.' } });
    FakeXHR.latest.onload?.();
    await expect(failed).rejects.toThrow('Invalid PDF.');
    const abort = new AbortController();
    const cancelled = api.uploadFile(file, ['staff'], '', vi.fn(), abort.signal);
    abort.abort();
    await expect(cancelled).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('rejects invalid success contracts and pre-aborted requests', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const api = new ApiClient('');
    const file = new File(['text'], 'resume.txt');
    const invalid = api.uploadFile(file, ['staff'], '', vi.fn(), new AbortController().signal);
    FakeXHR.latest.responseText = '{}'; FakeXHR.latest.onload?.();
    await expect(invalid).rejects.toThrow('does not match');
    const abort = new AbortController(); abort.abort();
    await expect(api.uploadFile(file, ['staff'], '', vi.fn(), abort.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(FakeXHR.latest.body).toBeUndefined();
  });
});

```
