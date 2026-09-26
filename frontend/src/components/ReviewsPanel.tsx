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
