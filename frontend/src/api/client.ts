import { z } from 'zod';
import { UploadLimitsSchema, UploadResultSchema, type UploadResult } from './uploads';
import { AnswerSchema, ReviewSchema, IngestSchema, HealthSchema, type IngestBatch } from './schemas';

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
    if (options.signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
    const controller = new AbortController();
    const abort = () => controller.abort();
    options.signal?.addEventListener('abort', abort, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, options.timeout ?? 35000);
    try {
      const response = await fetch(`${this.base}${path}`, {
        method: options.method ?? 'GET', signal: controller.signal, credentials: 'omit',
        headers: { ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
          ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      });
      if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
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
      if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
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
    return this.request('/health/ready', HealthSchema, { signal, timeout: 5000 });
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
        xhr.onload = xhr.onerror = xhr.onabort = xhr.ontimeout = null;
        xhr.upload.onprogress = xhr.upload.onload = null;
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
      try { xhr.send(body); }
      catch { finish(undefined, new ApiError('Could not start the upload. Check the API URL and connection.')); }
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
