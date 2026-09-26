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
