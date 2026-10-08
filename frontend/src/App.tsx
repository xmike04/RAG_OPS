import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, Check, ChevronDown,
  CircleDot, Clock3, Database, FilePlus2, FileText, Gauge, HeartPulse, Layers3,
  LockKeyhole, Menu, Network, PanelLeftClose, Play, RefreshCw, Search, Server, Sparkles,
  TerminalSquare, TimerReset, X, Zap,
} from 'lucide-react'
import { api } from './api'
import { demoDocuments, demoHealth, demoQueryResponse, demoSearch, demoSummary, demoTraces } from './demo'
import type { DocumentRecord, OpsSummary, QueryResponse, SearchResult, ServiceHealth, SourceMode, StageTiming, TraceRecord } from './types'

type Page = 'overview' | 'playground' | 'documents' | 'traces' | 'retrieval' | 'health'

const nav: { id: Page; label: string; icon: typeof Gauge }[] = [
  { id: 'overview', label: 'Overview', icon: Gauge },
  { id: 'playground', label: 'Query playground', icon: TerminalSquare },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'traces', label: 'Trace explorer', icon: Network },
  { id: 'retrieval', label: 'Retrieval quality', icon: BarChart3 },
  { id: 'health', label: 'System health', icon: HeartPulse },
]

const pageMeta: Record<Page, { eyebrow: string; title: string; description: string }> = {
  overview: { eyebrow: 'Command center', title: 'Operational overview', description: 'Retrieval performance, demand, and system posture at a glance.' },
  playground: { eyebrow: 'Inspect a query', title: 'Query playground', description: 'Run grounded queries and examine every retrieval stage.' },
  documents: { eyebrow: 'Knowledge base', title: 'Documents', description: 'Ingest, monitor, and audit the source material behind your answers.' },
  traces: { eyebrow: 'Observability', title: 'Trace explorer', description: 'Follow queries through retrieval, reranking, and generation.' },
  retrieval: { eyebrow: 'Quality lab', title: 'Retrieval scores', description: 'Compare lexical, vector, fusion, and reranker signals.' },
  health: { eyebrow: 'Platform', title: 'System health', description: 'Live readiness and dependency status for the RAG pipeline.' },
}

const fmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const timeFmt = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' })

function Sparkline({ values, tone = 'cyan' }: { values: number[]; tone?: 'cyan' | 'lime' | 'orange' }) {
  const points = useMemo(() => {
    if (!values.length) return ''
    const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
    return values.map((value, i) => `${(i / Math.max(values.length - 1, 1)) * 100},${36 - ((value - min) / span) * 30}`).join(' ')
  }, [values])
  return <svg className={`sparkline ${tone}`} viewBox="0 0 100 40" role="img" aria-label="Metric trend"><polyline points={points} /><polyline className="spark-glow" points={points} /></svg>
}

function Waterfall({ stages, total }: { stages: StageTiming[]; total?: number }) {
  const max = Math.max(total ?? 0, stages.reduce((sum, item) => sum + item.durationMs, 0), 1)
  const offsets = stages.map((_, index) => stages.slice(0, index).reduce((sum, item) => sum + item.durationMs, 0))
  return <div className="waterfall" aria-label="Retrieval stage timing">
    {stages.map((stage, index) => {
      const left = (offsets[index] / max) * 100; const width = Math.max((stage.durationMs / max) * 100, 2)
      return <div className="waterfall-row" key={`${stage.name}-${index}`}>
        <span>{stage.name}</span><div className="waterfall-track"><i style={{ left: `${left}%`, width: `${width}%` }} /></div><b>{stage.durationMs} ms</b>
      </div>
    })}
    {!stages.length && <Empty compact title="No timing data" detail="Stage timing will appear after a query completes." />}
  </div>
}

function StatusPill({ status }: { status: string }) {
  return <span className={`status-pill ${status}`}><i />{status}</span>
}

function Empty({ title, detail, compact = false }: { title: string; detail: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'compact' : ''}`}><CircleDot size={compact ? 18 : 24} /><strong>{title}</strong><span>{detail}</span></div>
}

function LoadingRows() {
  return <div className="loading-rows" aria-label="Loading"><i /><i /><i /></div>
}

function MetricCard({ label, value, suffix, detail, values, tone, icon: Icon }: { label: string; value: string; suffix?: string; detail: string; values: number[]; tone: 'cyan' | 'lime' | 'orange'; icon: typeof Gauge }) {
  return <article className="metric-card">
    <div className="metric-top"><span>{label}</span><Icon size={17} /></div>
    <div className="metric-value">{value}<small>{suffix}</small></div>
    <div className="metric-foot"><span>{detail}</span><Sparkline values={values} tone={tone} /></div>
  </article>
}

function SectionHeader({ title, aside }: { title: string; aside?: React.ReactNode }) {
  return <div className="section-header"><div><span className="section-kicker">LIVE SIGNAL</span><h2>{title}</h2></div>{aside}</div>
}

function Overview({ summary, traces, health, loading, onNavigate }: { summary: OpsSummary; traces: TraceRecord[]; health: ServiceHealth[]; loading: boolean; onNavigate: (page: Page) => void }) {
  const healthy = health.filter((item) => item.status === 'healthy').length
  return <>
    <div className="metric-grid">
      <MetricCard label="P50 latency" value={summary.latencyP50Ms.toLocaleString()} suffix="ms" detail="median end-to-end" values={summary.latencyTrend} tone="cyan" icon={Zap} />
      <MetricCard label="P95 latency" value={summary.latencyP95Ms.toLocaleString()} suffix="ms" detail="tail performance" values={[720, 780, 744, 810, 759, 742]} tone="orange" icon={TimerReset} />
      <MetricCard label="Queries" value={fmt.format(summary.queries)} detail="last 24 hours" values={summary.queryTrend} tone="lime" icon={Activity} />
      <MetricCard label="Cache hit" value={(summary.cacheHitRate * 100).toFixed(1)} suffix="%" detail={`${fmt.format(summary.tokens)} tokens used`} values={[52, 58, 57, 61, 64, summary.cacheHitRate * 100]} tone="cyan" icon={Database} />
    </div>
    <div className="overview-grid">
      <section className="panel demand-panel">
        <SectionHeader title="Query demand" aside={<span className="delta up">↗ 12.8%</span>} />
        <div className="chart-area">
          <div className="chart-y"><span>120</span><span>80</span><span>40</span><span>0</span></div>
          <div className="bar-chart" aria-label="Hourly query volume">{summary.queryTrend.map((value, i) => <div key={i} className="bar-slot"><i style={{ height: `${Math.max(8, (value / Math.max(...summary.queryTrend, 1)) * 100)}%` }} /><span>{i % 3 === 0 ? `${i * 2}:00` : ''}</span></div>)}</div>
        </div>
      </section>
      <section className="panel health-snapshot">
        <SectionHeader title="System posture" aside={<button className="text-button" onClick={() => onNavigate('health')}>Inspect <ArrowRight size={14} /></button>} />
        <div className="posture-score"><div className="orb"><strong>{health.length ? Math.round((healthy / health.length) * 100) : 0}</strong><span>health</span></div><div><h3>{healthy === health.length ? 'All systems nominal' : 'Attention recommended'}</h3><p>{healthy} of {health.length} services operating normally.</p></div></div>
        <div className="service-dots">{health.slice(0, 4).map((item) => <div key={item.name}><StatusPill status={item.status} /><span>{item.name}</span><b>{item.latencyMs ? `${item.latencyMs}ms` : '—'}</b></div>)}</div>
      </section>
    </div>
    <section className="panel trace-preview">
      <SectionHeader title="Recent traces" aside={<button className="text-button" onClick={() => onNavigate('traces')}>Open explorer <ArrowRight size={14} /></button>} />
      {loading ? <LoadingRows /> : traces.length ? <div className="data-table"><div className="table-head"><span>Trace / query</span><span>Status</span><span>Duration</span><span>Tokens</span><span>Started</span></div>{traces.slice(0, 4).map((trace) => <div className="table-row" key={trace.id}><span className="primary-cell"><code>{trace.id}</code><small>{trace.query}</small></span><span><StatusPill status={trace.status} /></span><span>{trace.durationMs} ms</span><span>{trace.tokens.toLocaleString()}</span><span>{timeFmt.format(new Date(trace.startedAt))}</span></div>)}</div> : <Empty title="No traces yet" detail="Run a query to begin collecting traces." />}
    </section>
  </>
}

function Playground({ mode, readOnly }: { mode: SourceMode; readOnly: boolean }) {
  const [question, setQuestion] = useState('How do I safely roll back a production deployment?')
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const run = async (event: FormEvent) => {
    event.preventDefault(); if (!question.trim()) return
    setPending(true); setError(''); setResult(null)
    if (readOnly) { setResult(demoQueryResponse); setPending(false); return }
    try { setResult(await api.query(question.trim(), 'default')) }
    catch (caught) {
      if (mode === 'demo') setResult(demoQueryResponse)
      else setError(caught instanceof Error ? caught.message : 'Query failed')
    } finally { setPending(false) }
  }
  return <div className="playground-grid">
    <section className="panel query-composer">
      <SectionHeader title="Compose query" aside={<span className="key-hint">⌘ ↵ to run</span>} />
      <form onSubmit={run}>
        <label htmlFor="question">Question</label>
        <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask your knowledge base…" rows={7} />
        <div className="form-row"><label>Workspace<select aria-label="Workspace"><option>default</option></select></label><label>Top K<select aria-label="Top K"><option>8 chunks</option><option>12 chunks</option></select></label></div>
        <button className="primary-button" disabled={pending || !question.trim()}>{pending ? <><RefreshCw className="spin" size={17} /> Running pipeline…</> : <><Play size={17} fill="currentColor" /> {readOnly ? 'Run demo query' : 'Run query'}</>}</button>
      </form>
      <div className="query-options"><span><Check size={13} /> Hybrid search</span><span><Check size={13} /> Reranking</span><span><Check size={13} /> Citations</span></div>
    </section>
    <section className="panel answer-panel">
      <SectionHeader title="Grounded answer" aside={result && <span className="mono-label">{result.totalMs} ms · {result.traceId}</span>} />
      {pending ? <div className="answer-loading"><Sparkles size={24} /><div><i /><i /><i /></div></div> : error ? <div className="inline-error"><AlertTriangle size={20} /><div><strong>Query failed</strong><span>{error}</span></div></div> : result ? <>
        <div className="answer-copy"><Sparkles size={18} /><p>{result.answer}</p></div>
        <h3 className="subheading">Citations <span>{result.citations.length}</span></h3>
        <div className="citations">{result.citations.map((citation, index) => <article key={citation.id}><b>{index + 1}</b><div><strong>{citation.title}</strong><p>{citation.excerpt}</p></div><span>{citation.score.toFixed(2)}</span></article>)}</div>
        <h3 className="subheading">Stage waterfall</h3><Waterfall stages={result.stages} total={result.totalMs} />
      </> : <Empty title="Ready for a query" detail="Your grounded answer, citations, and stage timings will appear here." />}
    </section>
  </div>
}

function Documents({ documents, setDocuments, loading, mode, readOnly }: { documents: DocumentRecord[]; setDocuments: React.Dispatch<React.SetStateAction<DocumentRecord[]>>; loading: boolean; mode: SourceMode; readOnly: boolean }) {
  const [showIngest, setShowIngest] = useState(false); const [title, setTitle] = useState(''); const [content, setContent] = useState(''); const [pending, setPending] = useState(false); const [error, setError] = useState(''); const [search, setSearch] = useState('')
  const pendingJobs = documents.filter((doc) => doc.jobId && ['queued', 'processing'].includes(doc.status)).map((doc) => doc.jobId).join(',')
  useEffect(() => {
    if (mode !== 'live' || !pendingJobs) return
    const poll = async () => {
      const jobs = await Promise.allSettled(pendingJobs.split(',').map((jobId) => api.getIngestion(jobId, 'default')))
      setDocuments((current) => current.map((doc) => {
        const result = jobs.find((candidate) => candidate.status === 'fulfilled' && candidate.value.id === doc.jobId)
        if (!result || result.status !== 'fulfilled') return doc
        const status = ['complete', 'completed', 'succeeded', 'ready'].includes(result.value.status) ? 'ready' : result.value.status === 'failed' ? 'failed' : 'processing'
        return { ...doc, status, error: result.value.error, updatedAt: result.value.updatedAt }
      }))
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 4_000)
    return () => window.clearInterval(timer)
  }, [mode, pendingJobs, setDocuments])
  const visible = documents.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase()))
  const ingest = async (event: FormEvent) => { event.preventDefault(); setPending(true); setError(''); try { const created = await api.createDocument({ title, content, workspaceId: 'default' }); setDocuments((current) => [created, ...current]); setTitle(''); setContent(''); setShowIngest(false) } catch (caught) { if (mode === 'demo') { setDocuments((current) => [{ id: `demo_${Date.now()}`, title, status: 'queued', chunks: 0, sizeBytes: new Blob([content]).size, updatedAt: new Date().toISOString() }, ...current]); setTitle(''); setContent(''); setShowIngest(false) } else setError(caught instanceof Error ? caught.message : 'Ingestion failed') } finally { setPending(false) } }
  return <>
    <div className="toolbar"><div className="search-box"><Search size={17} /><input aria-label="Search documents" placeholder="Search documents…" value={search} onChange={(event) => setSearch(event.target.value)} /></div><button className={`primary-button compact ${readOnly ? 'read-only-action' : ''}`} disabled={readOnly} title={readOnly ? 'Document ingestion is disabled in the public demo' : undefined} onClick={() => setShowIngest(!showIngest)}>{readOnly ? <LockKeyhole size={16} /> : showIngest ? <X size={17} /> : <FilePlus2 size={17} />}{readOnly ? 'Read-only demo' : showIngest ? 'Close' : 'Ingest document'}</button></div>
    {showIngest && <section className="panel ingest-panel"><div><span className="section-kicker">NEW SOURCE</span><h2>Ingest plain text or Markdown</h2><p>The worker will chunk, embed, and index this content asynchronously.</p></div><form onSubmit={ingest}><input aria-label="Document title" required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Document title" /><textarea aria-label="Document content" required value={content} onChange={(e) => setContent(e.target.value)} rows={5} placeholder="Paste text or Markdown…" />{error && <span className="error-text">{error}</span>}<button className="primary-button compact" disabled={pending}>{pending ? 'Submitting…' : 'Start ingestion'}<ArrowRight size={16} /></button></form></section>}
    <section className="panel">
      <SectionHeader title={`${documents.length} documents`} aside={<span className="muted">Workspace: default</span>} />
      {loading ? <LoadingRows /> : visible.length ? <div className="document-list">{visible.map((doc) => <article key={doc.id}><div className="file-icon"><FileText size={19} /></div><div className="document-main"><strong>{doc.title}</strong><span><code>{doc.id}</code> · Updated {timeFmt.format(new Date(doc.updatedAt))}</span>{doc.error && <small className="error-text">{doc.error}</small>}</div><div className="document-stat"><span>CHUNKS</span><b>{doc.chunks || '—'}</b></div><div className="document-stat"><span>SIZE</span><b>{doc.sizeBytes ? `${(doc.sizeBytes / 1024).toFixed(0)} KB` : '—'}</b></div><StatusPill status={doc.status} /></article>)}</div> : <Empty title={search ? 'No matching documents' : 'No documents yet'} detail={search ? 'Try a broader search.' : 'Ingest your first document to build the knowledge base.'} />}
    </section>
  </>
}

function Traces({ traces, loading }: { traces: TraceRecord[]; loading: boolean }) {
  const [selected, setSelected] = useState<TraceRecord | null>(null); const [search, setSearch] = useState(''); const [status, setStatus] = useState('all')
  const visible = traces.filter((trace) => (status === 'all' || trace.status === status) && `${trace.id} ${trace.query}`.toLowerCase().includes(search.toLowerCase()))
  return <div className="trace-layout">
    <section className="panel trace-list-panel"><div className="toolbar inset"><div className="search-box"><Search size={17} /><input aria-label="Search traces" placeholder="Search trace or query…" value={search} onChange={(e) => setSearch(e.target.value)} /></div><select aria-label="Trace status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">All statuses</option><option value="ok">Successful</option><option value="error">Error</option><option value="running">Running</option></select></div>
      {loading ? <LoadingRows /> : visible.length ? <div className="trace-cards">{visible.map((trace) => <button className={selected?.id === trace.id ? 'selected' : ''} key={trace.id} onClick={() => setSelected(trace)}><span className="trace-id"><StatusPill status={trace.status} /><code>{trace.id}</code></span><strong>{trace.query}</strong><span className="trace-meta"><span><Clock3 size={13} />{trace.durationMs} ms</span><span><Layers3 size={13} />{trace.chunks} chunks</span><span>{trace.cacheHit ? 'CACHE HIT' : 'LIVE'}</span></span></button>)}</div> : <Empty title="No matching traces" detail="Adjust the search or status filter." />}
    </section>
    <aside className="panel trace-detail">{selected ? <><SectionHeader title="Trace detail" aside={<button className="icon-button" aria-label="Close trace detail" onClick={() => setSelected(null)}><X size={16} /></button>} /><div className="trace-detail-head"><StatusPill status={selected.status} /><code>{selected.id}</code><h3>{selected.query}</h3><p>{new Date(selected.startedAt).toLocaleString()}</p></div><div className="detail-stats"><div><span>DURATION</span><b>{selected.durationMs} ms</b></div><div><span>TOKENS</span><b>{selected.tokens.toLocaleString()}</b></div><div><span>CHUNKS</span><b>{selected.chunks}</b></div></div><h3 className="subheading">Pipeline timing</h3><Waterfall stages={selected.stages} total={selected.durationMs} /></> : <Empty title="Select a trace" detail="Choose a trace to inspect its pipeline timings and metadata." />}</aside>
  </div>
}

function ScoreBar({ label, value, tone }: { label: string; value: number; tone: string }) { return <div className="score-bar"><span>{label}</span><div><i className={tone} style={{ width: `${Math.min(value * 100, 100)}%` }} /></div><b>{value.toFixed(2)}</b></div> }

function Retrieval({ mode, readOnly }: { mode: SourceMode; readOnly: boolean }) {
  const [query, setQuery] = useState('production rollback procedure'); const [results, setResults] = useState<SearchResult[]>(mode === 'demo' ? demoSearch : []); const [pending, setPending] = useState(false); const [error, setError] = useState('')
  const run = async (event: FormEvent) => { event.preventDefault(); if (!query.trim()) return; setPending(true); setError(''); if (readOnly) { setResults(demoSearch); setPending(false); return } try { setResults(await api.search(query, 'default')) } catch (caught) { if (mode === 'demo') setResults(demoSearch); else setError(caught instanceof Error ? caught.message : 'Search failed') } finally { setPending(false) } }
  return <>
    <section className="panel retrieval-query"><form onSubmit={run}><div className="search-box"><Search size={18} /><input aria-label="Retrieval query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Test a retrieval query…" /></div><button className="primary-button compact" disabled={pending}>{pending ? <RefreshCw size={17} className="spin" /> : <Play size={17} fill="currentColor" />}{readOnly ? 'Analyze demo retrieval' : 'Analyze retrieval'}</button></form>{error && <span className="error-text">{error}</span>}<div className="legend"><span><i className="lexical" />Lexical</span><span><i className="vector" />Vector</span><span><i className="fusion" />RRF fusion</span><span><i className="rerank" />Rerank</span></div></section>
    <section className="panel"><SectionHeader title="Ranked candidates" aside={<span className="muted">{results.length} results · higher is better</span>} />{pending ? <LoadingRows /> : results.length ? <div className="result-list">{results.map((result, index) => <article key={result.id}><div className="result-rank">{String(index + 1).padStart(2, '0')}</div><div className="result-copy"><div><strong>{result.title}</strong><code>{result.id}</code></div><p>{result.excerpt}</p></div><div className="scores"><ScoreBar label="Lex" value={result.lexicalScore} tone="lexical" /><ScoreBar label="Vec" value={result.vectorScore} tone="vector" /><ScoreBar label="RRF" value={result.fusedScore} tone="fusion" /><ScoreBar label="Rank" value={result.rerankScore} tone="rerank" /></div></article>)}</div> : <Empty title="No results to score" detail="Run a search to compare retrieval signals." />}</section>
  </>
}

function Health({ health, loading, onRefresh, readOnly }: { health: ServiceHealth[]; loading: boolean; onRefresh: () => void; readOnly: boolean }) {
  const healthy = health.filter((service) => service.status === 'healthy').length
  return <><section className="panel health-hero"><div className="health-mark"><Activity size={30} /></div><div><span className="section-kicker">{readOnly ? 'DEMO SNAPSHOT' : 'CURRENT STATUS'}</span><h2>{healthy === health.length ? 'All systems operational' : 'Some systems need attention'}</h2><p>{healthy} of {health.length} platform services are healthy.</p></div><button className="secondary-button" disabled={readOnly} title={readOnly ? 'Health checks are disabled in the public demo' : undefined} onClick={onRefresh}>{readOnly ? <LockKeyhole size={16} /> : <RefreshCw size={16} />}{readOnly ? 'Demo snapshot' : 'Refresh checks'}</button></section>
    <section className="service-grid">{loading ? <LoadingRows /> : health.map((service) => <article className="panel service-card" key={service.name}><div className="service-icon">{service.name.toLowerCase().includes('database') || service.name.toLowerCase().includes('postgres') ? <Database /> : service.name === 'API' ? <Server /> : <Activity />}</div><div><div className="service-title"><h3>{service.name}</h3><StatusPill status={service.status} /></div><p>{service.detail}</p></div><div className="latency-reading"><span>LATENCY</span><b>{service.latencyMs ? `${service.latencyMs} ms` : '—'}</b></div></article>)}</section>
    <section className="panel environment-card"><SectionHeader title="Environment" /><div className="environment-grid"><div><span>API VERSION</span><code>v1</code></div><div><span>WORKSPACE</span><code>default</code></div><div><span>DEPLOYMENT</span><code>local</code></div><div><span>LAST CHECK</span><code>{timeFmt.format(new Date())}</code></div></div></section></>
}

export default function App({ demoMode = import.meta.env.VITE_DEMO_MODE === 'true' }: { demoMode?: boolean }) {
  const [page, setPage] = useState<Page>('overview'); const [menuOpen, setMenuOpen] = useState(false); const [sidebarOpen, setSidebarOpen] = useState(true)
  const [summary, setSummary] = useState(demoSummary); const [documents, setDocuments] = useState<DocumentRecord[]>(demoMode ? demoDocuments : []); const [traces, setTraces] = useState<TraceRecord[]>(demoMode ? demoTraces : []); const [health, setHealth] = useState<ServiceHealth[]>(demoMode ? demoHealth : [])
  const [mode, setMode] = useState<SourceMode>(demoMode ? 'demo' : 'live'); const [loading, setLoading] = useState(!demoMode); const [failure, setFailure] = useState('')
  const load = useCallback(async () => {
    if (demoMode) { setSummary(demoSummary); setDocuments(demoDocuments); setTraces(demoTraces); setHealth(demoHealth); setMode('demo'); setLoading(false); setFailure(''); return }
    setLoading(true); setFailure('')
    const [summaryResult, documentsResult, tracesResult, healthResult] = await Promise.allSettled([api.getSummary(), api.listDocuments(), api.listTraces(), api.health()])
    const failed = [summaryResult, documentsResult, tracesResult, healthResult].some((result) => result.status === 'rejected')
    if (summaryResult.status === 'fulfilled') {
      const liveSummary = summaryResult.value
      if (tracesResult.status === 'fulfilled' && tracesResult.value.length) {
        const values = tracesResult.value.map((trace) => trace.durationMs).sort((a, b) => a - b)
        const center = Math.floor(values.length / 2)
        liveSummary.latencyP50Ms = values.length % 2 ? values[center] : (values[center - 1] + values[center]) / 2
      }
      setSummary(liveSummary)
    } else setSummary(demoSummary)
    if (documentsResult.status === 'fulfilled') setDocuments(documentsResult.value); else setDocuments(demoDocuments)
    if (tracesResult.status === 'fulfilled') setTraces(tracesResult.value); else setTraces(demoTraces)
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value); else setHealth(demoHealth)
    setMode(failed ? 'demo' : 'live'); if (failed) setFailure('The API is unavailable. Showing clearly marked demonstration data until the connection recovers.')
    setLoading(false)
  }, [demoMode])
  useEffect(() => { void load() }, [load])
  const navigate = (next: Page) => { setPage(next); setMenuOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  const meta = pageMeta[page]
  return <div className={`app-shell ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
    <aside className={`sidebar ${menuOpen ? 'mobile-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><span /><span /><span /></div><div><strong>RAG<span>OPS</span></strong><small>CONTROL PLANE</small></div><button className="icon-button desktop-only" aria-label="Collapse sidebar" onClick={() => setSidebarOpen(!sidebarOpen)}><PanelLeftClose size={17} /></button></div>
      <nav aria-label="Main navigation">{nav.map(({ id, label, icon: Icon }) => <button key={id} className={page === id ? 'active' : ''} onClick={() => navigate(id)} title={label}><Icon size={18} /><span>{label}</span>{page === id && <i />}</button>)}</nav>
      <div className="sidebar-bottom"><div className="environment"><span className={mode} /><div><small>ENVIRONMENT</small><strong>{mode === 'live' ? 'API connected' : demoMode ? 'Public demo' : 'Demo fallback'}</strong></div></div><div className="workspace"><div>DW</div><span><small>WORKSPACE</small><strong>default</strong></span><ChevronDown size={15} /></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMenuOpen(!menuOpen)}><Menu size={20} /></button><div className="breadcrumb"><span>RAGOPS</span><b>/</b><strong>{meta.title}</strong></div><div className="top-actions"><span className={`connection ${mode}`}><i />{mode === 'live' ? 'Connected' : demoMode ? 'Public demo' : 'Demo data'}</span><button className="icon-button" aria-label="Refresh data" disabled={demoMode} title={demoMode ? 'Live refresh is disabled in the public demo' : undefined} onClick={() => void load()}>{demoMode ? <LockKeyhole size={16} /> : <RefreshCw size={17} className={loading ? 'spin' : ''} />}</button></div></header>
      <main>
        {demoMode && <div className="demo-banner public-demo" role="status"><LockKeyhole size={17} /><span><strong>Public demo · Read-only.</strong> This is a deterministic product preview; no requests are sent and no data is changed.</span></div>}
        {failure && <div className="demo-banner" role="status"><AlertTriangle size={17} /><span><strong>Demo fallback active.</strong> {failure}</span><button aria-label="Retry API" onClick={() => void load()}>Retry</button></div>}
        <div className="page-heading"><div><span>{meta.eyebrow}</span><h1>{meta.title}</h1><p>{meta.description}</p></div><div className="period-control"><Clock3 size={16} /><span>Last 24 hours</span><ChevronDown size={14} /></div></div>
        {page === 'overview' && <Overview summary={summary} traces={traces} health={health} loading={loading} onNavigate={navigate} />}
        {page === 'playground' && <Playground mode={mode} readOnly={demoMode} />}
        {page === 'documents' && <Documents documents={documents} setDocuments={setDocuments} loading={loading} mode={mode} readOnly={demoMode} />}
        {page === 'traces' && <Traces traces={traces} loading={loading} />}
        {page === 'retrieval' && <Retrieval mode={mode} readOnly={demoMode} />}
        {page === 'health' && <Health health={health} loading={loading} readOnly={demoMode} onRefresh={() => void load()} />}
      </main>
    </div>
    {menuOpen && <button className="menu-backdrop" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
  </div>
}
