import { useRef, useState } from 'react';
import { CheckCircle2, FileJson2, FilePlus2, Upload } from 'lucide-react';
import type { ApiClient } from '../api/client';
import { IngestSchema } from '../api/schemas';
import { useRequest } from '../hooks/useRequest';
import { SAMPLE_DOCUMENTS } from '../samples';
import { Badge, Button, ErrorNotice } from './ui';

export function IngestionPanel({ api, authenticated, onConnect }: { api: ApiClient; authenticated: boolean; onConnect: () => void }) {
  const [mode, setMode] = useState<'form' | 'json'>('form');
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
    <div className="section-heading"><div><div className="eyebrow">BUILD YOUR TEST CORPUS</div><h1>Document ingestion</h1><p className="muted mt-2">Give your next query something to work with.</p></div><Badge tone="accent">POST /ingest</Badge></div>
    <div className="panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-5"><div className="segmented" aria-label="Input mode">{(['form', 'json'] as const).map(value => <button key={value} aria-pressed={mode === value} className={mode === value ? 'active' : ''} onClick={() => { setMode(value); setValidation(null); setResult(null); }}>{value === 'form' ? 'Single document' : 'JSON batch'}</button>)}</div><Button onClick={() => { setMode('json'); setJson(JSON.stringify(SAMPLE_DOCUMENTS, null, 2)); setValidation(null); setResult(null); }}><FileJson2 size={15} /> Load sample corpus</Button></div>
      <form className="space-y-5 p-5 sm:p-7" onSubmit={event => { event.preventDefault(); void submit(); }}>
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
