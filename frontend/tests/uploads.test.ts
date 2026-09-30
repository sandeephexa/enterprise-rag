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

describe('upload cleanup', () => {
  it('detaches handlers after completion', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const signal = new AbortController().signal;
    const remove = vi.spyOn(signal, 'removeEventListener');
    const promise = new ApiClient('').uploadFile(new File(['text'], 'resume.txt'), ['staff'], '', vi.fn(), signal);
    const xhr = FakeXHR.latest;
    xhr.onload?.();
    await expect(promise).resolves.toEqual(result);
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(xhr.upload.onprogress).toBeNull();
    expect(xhr.onload).toBeNull();
  });
  it('cleans up a synchronous upload send failure', async () => {
    class FailingXHR extends FakeXHR { send() { throw new Error('transport detail'); } }
    vi.stubGlobal('XMLHttpRequest', FailingXHR);
    const signal = new AbortController().signal;
    const remove = vi.spyOn(signal, 'removeEventListener');
    await expect(new ApiClient('').uploadFile(new File(['text'], 'resume.txt'), ['staff'], '', vi.fn(), signal)).rejects.toThrow('Could not start');
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    expect(FakeXHR.latest.onerror).toBeNull();
  });
});
