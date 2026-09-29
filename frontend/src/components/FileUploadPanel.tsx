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
