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
