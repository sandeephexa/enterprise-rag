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
