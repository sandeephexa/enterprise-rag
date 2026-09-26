import { z } from 'zod';
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
    return this.request('/health/ready', z.object({ status: z.string(), mode: z.enum(['live', 'demo']) }), { signal, timeout: 5000 });
  }
  ingest(batch: IngestBatch, signal?: AbortSignal) {
    const body = IngestSchema.parse(batch);
    if (new TextEncoder().encode(JSON.stringify(body)).byteLength > 1_000_000) throw new ApiError('Batch exceeds the default 1 MB body limit.');
    return this.request('/ingest', z.object({ indexed_chunks: z.number().int().nonnegative() }), { method: 'POST', body, signal, timeout: 130000 });
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
