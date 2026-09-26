import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, FlaskConical, FolderInput, KeyRound, Moon, ShieldCheck, Sun, Terminal, Unplug } from 'lucide-react';
import { ApiClient } from './api/client';
import type { Citation, Health } from './api/schemas';
import { usePlayground } from './hooks/usePlayground';
import { useRequest } from './hooks/useRequest';
import { Playground } from './components/Playground';
import { Inspector } from './components/Inspector';
import { IngestionPanel } from './components/IngestionPanel';
import { ReviewsPanel } from './components/ReviewsPanel';
import { ConnectionDialog } from './components/ConnectionDialog';
import { Badge, Button } from './components/ui';

type View = 'playground' | 'documents' | 'reviews';
const VIEWS = [{ id: 'playground', label: 'Playground', icon: FlaskConical }, { id: 'documents', label: 'Documents', icon: FolderInput }, { id: 'reviews', label: 'Human review', icon: ShieldCheck }] as const;

function Workspace({ token, onConnect, theme, toggleTheme }: { token: string; onConnect: () => void; theme: string; toggleTheme: () => void }) {
  const [view, setView] = useState<View>('playground');
  const api = useMemo(() => new ApiClient(token), [token]);
  const health = useRequest<Health>();
  const playground = usePlayground(api);
  const [citation, setCitation] = useState<{ runId: string; citation: Citation } | null>(null);
  useEffect(() => { void health.execute(signal => api.health(signal)); }, [api, health.execute]);
  const selected = playground.runs.find(run => run.id === playground.selectedId);
  const title = VIEWS.find(item => item.id === view)!.label;
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="navigation"><div className="brand"><div className="brand-symbol">E<span /></div><div><span className="text-lg font-semibold tracking-tight">evidence</span><span className="block text-xs muted">RAG workbench</span></div></div>
      <div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{VIEWS.map(item => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)} aria-current={view === item.id ? 'page' : undefined}><item.icon size={18} /><span>{item.label}</span>{view === item.id && <span className="nav-active-marker" />}</button>)}</nav>
      <div className="nav-bottom"><div className="rounded-xl border border-line p-4"><Terminal size={17} className="mb-3 text-accent" /><p className="text-sm font-medium">Your pipeline. In focus.</p><p className="mt-2 text-xs leading-5 muted">Inspect retrieval, trace claims, and review what needs a human.</p></div><button className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}<span>{theme === 'dark' ? 'Light appearance' : 'Dark appearance'}</span></button></div>
    </aside>
    <div className="workspace-main"><header className="topbar"><div className="flex items-center gap-2 text-sm"><span className="muted hidden sm:inline">Workspace</span><ArrowRight size={12} className="muted hidden sm:inline" /><span>{title}</span></div><div className="flex items-center gap-3"><span className="hidden sm:inline-flex">{health.loading ? <Badge>Checking API…</Badge> : health.error ? <Badge tone="warning">API unavailable</Badge> : health.data ? <Badge tone="good">{health.data.mode === 'demo' ? 'Demo API ready' : 'Live API ready'}</Badge> : null}</span><Button onClick={onConnect}><KeyRound size={14} />{token ? 'Connection' : 'Set API token'}</Button><button className="mobile-theme" onClick={toggleTheme} aria-label="Toggle appearance">{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button></div></header>
      {health.error && <div className="connection-banner"><Unplug size={16} /><span>Backend unavailable. Start FastAPI or check your proxy target.</span><button onClick={() => void health.execute(signal => api.health(signal))} className="underline underline-offset-4 ml-auto">Retry</button></div>}
      <main id="main-content" tabIndex={-1} className={`main-content ${view === 'playground' ? 'playground-layout' : ''}`}>
        <div hidden={view !== 'playground'} className="min-w-0"><Playground state={playground} authenticated={!!token} onConnect={onConnect} onCitation={(id, selectedCitation) => { playground.select(id); setCitation({ runId: id, citation: selectedCitation }); }} /></div>
        {view === 'playground' && <Inspector key={selected?.id ?? 'empty'} answer={selected?.answer} pending={selected?.status === 'pending'} citation={citation?.runId === selected?.id ? citation?.citation : null} />}
        <div hidden={view !== 'documents'}><IngestionPanel api={api} authenticated={!!token} onConnect={onConnect} /></div>
        <div hidden={view !== 'reviews'}><ReviewsPanel api={api} active={view === 'reviews'} authenticated={!!token} onConnect={onConnect} /></div>
      </main>
      <footer className="footer"><span>Evidence workbench <span className="muted">/ v1.0</span></span><span className="muted">Session data stays in memory · Queries run independently</span></footer>
    </div>
  </div>;
}

export default function App() {
  const [token, setToken] = useState('');
  const [connection, setConnection] = useState(false);
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('evidence-theme') === 'light' ? 'light' : 'dark'; } catch { return 'dark'; } });
  useEffect(() => { document.documentElement.dataset.theme = theme; try { localStorage.setItem('evidence-theme', theme); } catch { /* Private browser modes may block storage. */ } }, [theme]);
  // Remount on identity changes to abort requests and remove prior tenant data.
  return <><Workspace key={token} token={token} onConnect={() => setConnection(true)} theme={theme} toggleTheme={() => setTheme(previous => previous === 'dark' ? 'light' : 'dark')} /><ConnectionDialog open={connection} token={token} onClose={() => setConnection(false)} onApply={setToken} /></>;
}
