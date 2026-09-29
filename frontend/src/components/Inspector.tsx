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
