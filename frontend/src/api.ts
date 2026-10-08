import type { Citation, DocumentRecord, IngestionJob, OpsSummary, QueryResponse, SearchResult, ServiceHealth, StageTiming, TraceRecord } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''
export const WORKSPACE_ID = (import.meta.env.VITE_WORKSPACE_ID as string | undefined) ?? '00000000-0000-0000-0000-000000000001'
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined

export class ApiError extends Error {
  constructor(message: string, public status: number, public requestId?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit, acceptError = false): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(API_KEY ? { 'x-api-key': API_KEY } : {}), ...init?.headers },
  })
  const requestId = response.headers.get('x-request-id') ?? undefined
  if (!response.ok && !acceptError) {
    let message = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json() as { detail?: string; message?: string }
      message = payload.detail ?? payload.message ?? message
    } catch { /* use HTTP status */ }
    throw new ApiError(message, response.status, requestId)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const n = (value: unknown, fallback = 0) => typeof value === 'number' ? value : fallback
const s = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback
const workspace = (value: string) => /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(value) ? value : WORKSPACE_ID
const list = (payload: unknown): Record<string, unknown>[] => {
  if (Array.isArray(payload)) return payload as Record<string, unknown>[]
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>
    for (const key of ['items', 'documents', 'traces', 'results', 'data']) if (Array.isArray(record[key])) return record[key] as Record<string, unknown>[]
  }
  return []
}

function normalizeStages(value: unknown): StageTiming[] {
  if (Array.isArray(value)) return value.map((stage, index) => {
    const item = stage as Record<string, unknown>
    return { name: s(item.name ?? item.stage, `Stage ${index + 1}`), durationMs: n(item.duration_ms ?? item.durationMs ?? item.latency_ms) }
  })
  if (value && typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([name, duration]) => ({ name, durationMs: n(duration) }))
  return []
}

export const api = {
  async getSummary(): Promise<OpsSummary> {
    const p = await request<Record<string, unknown>>(`/v1/ops/summary?workspace_id=${WORKSPACE_ID}`)
    const latency = (p.latency_ms ?? p.latency) as Record<string, unknown> | undefined
    return {
      latencyP50Ms: n(p.latency_p50_ms ?? p.p50_latency_ms ?? p.average_latency_ms ?? latency?.p50),
      latencyP95Ms: n(p.latency_p95_ms ?? p.p95_latency_ms ?? latency?.p95),
      queries: n(p.queries ?? p.query_count ?? p.queries_total),
      cacheHitRate: n(p.cache_hit_rate ?? p.cache_rate),
      tokens: n(p.tokens ?? p.token_count ?? p.tokens_total, n(p.prompt_tokens) + n(p.completion_tokens)),
      queryTrend: Array.isArray(p.query_trend) ? p.query_trend.map((v) => n(v)) : [],
      latencyTrend: Array.isArray(p.latency_trend) ? p.latency_trend.map((v) => n(v)) : [],
    }
  },

  async listDocuments(): Promise<DocumentRecord[]> {
    return list(await request<unknown>(`/v1/documents?workspace_id=${WORKSPACE_ID}`)).map((item) => ({
      id: s(item.id ?? item.document_id), title: s(item.title ?? item.name, 'Untitled document'),
      status: s(item.status, 'queued') as DocumentRecord['status'], chunks: n(item.chunks ?? item.chunk_count),
      sizeBytes: n(item.size_bytes ?? item.size), updatedAt: s(item.updated_at ?? item.created_at, new Date().toISOString()),
      jobId: s(item.job_id) || undefined, error: s(item.error ?? item.error_message) || undefined,
    }))
  },

  async createDocument(input: { title: string; content: string; workspaceId: string }): Promise<DocumentRecord> {
    const payload = await request<Record<string, unknown>>('/v1/documents', { method: 'POST', body: JSON.stringify({ title: input.title, content: input.content, workspace_id: workspace(input.workspaceId) }) })
    const item = payload.document && typeof payload.document === 'object' ? payload.document as Record<string, unknown> : payload
    return { id: s(item.id ?? item.document_id), title: s(item.title, input.title), status: s(item.status, 'queued') as DocumentRecord['status'], chunks: n(item.chunks ?? item.chunk_count), sizeBytes: new Blob([input.content]).size, updatedAt: s(item.updated_at ?? item.created_at, new Date().toISOString()), jobId: s(payload.ingestion_job_id ?? payload.job_id) || undefined }
  },

  async getIngestion(jobId: string, workspaceId: string): Promise<IngestionJob> {
    const item = await request<Record<string, unknown>>(`/v1/ingestions/${encodeURIComponent(jobId)}?workspace_id=${workspace(workspaceId)}`)
    return { id: s(item.id), documentId: s(item.document_id), status: s(item.status), error: s(item.error) || undefined, updatedAt: s(item.updated_at, new Date().toISOString()) }
  },

  async query(question: string, workspaceId: string): Promise<QueryResponse> {
    const p = await request<Record<string, unknown>>('/v1/query', { method: 'POST', body: JSON.stringify({ query: question, workspace_id: workspace(workspaceId), top_k: 8, rerank: true }) })
    const citations = list(p.citations ?? p.sources).map((item, index): Citation => ({ id: s(item.id ?? item.chunk_id, `citation-${index}`), title: s(item.title ?? item.document_title, `Source ${index + 1}`), excerpt: s(item.excerpt ?? item.quote ?? item.text ?? item.content), score: n(item.score ?? item.rerank_score, 1 / (index + 1)), chunkId: s(item.chunk_id) || undefined }))
    const stages = normalizeStages(p.stages ?? p.timings ?? p.stage_latency_ms ?? p.latency_ms)
    return { answer: s(p.answer), citations, stages, requestId: s(p.request_id) || undefined, traceId: s(p.trace_id) || undefined, totalMs: n(p.total_ms, stages.reduce((sum, stage) => sum + stage.durationMs, 0)), cacheHit: Boolean(p.cache_hit) }
  },

  async listTraces(): Promise<TraceRecord[]> {
    return list(await request<unknown>(`/v1/traces?workspace_id=${WORKSPACE_ID}`)).map((item) => ({
      id: s(item.id ?? item.trace_id), query: s(item.query ?? item.question), status: s(item.status, 'ok') as TraceRecord['status'], startedAt: s(item.started_at ?? item.created_at, new Date().toISOString()), durationMs: n(item.duration_ms ?? item.total_latency_ms ?? item.latency_ms), chunks: n(item.chunks ?? item.retrieved_chunks ?? item.retrieval_count), tokens: n(item.tokens ?? item.token_count, n(item.prompt_tokens) + n(item.completion_tokens)), cacheHit: Boolean(item.cache_hit), stages: normalizeStages(item.stages ?? item.timings ?? item.stage_latency_ms),
    }))
  },

  async search(query: string, workspaceId: string): Promise<SearchResult[]> {
    return list(await request<unknown>('/v1/search', { method: 'POST', body: JSON.stringify({ query, workspace_id: workspace(workspaceId), top_k: 8, rerank: true }) })).map((item) => { const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata as Record<string, unknown> : {}; return { id: s(item.id ?? item.chunk_id), title: s(item.title ?? item.document_title ?? metadata.title, 'Untitled'), excerpt: s(item.excerpt ?? item.text ?? item.content), lexicalScore: n(item.lexical_score), vectorScore: n(item.vector_score ?? item.similarity), fusedScore: n(item.fused_score ?? item.rrf_score), rerankScore: n(item.rerank_score ?? item.final_score ?? item.score) } })
  },

  async health(): Promise<ServiceHealth[]> {
    const [live, ready] = await Promise.all([request<Record<string, unknown>>('/health'), request<Record<string, unknown>>('/ready', undefined, true)])
    const services: ServiceHealth[] = [{ name: 'API', status: s(live.status, 'ok') === 'ok' || s(live.status) === 'healthy' ? 'healthy' : 'degraded', detail: s(live.detail, 'Liveness check passed') }]
    const dependencies = ready.dependencies ?? ready.checks
    if (dependencies && typeof dependencies === 'object') Object.entries(dependencies as Record<string, unknown>).forEach(([name, value]) => {
      const detail = typeof value === 'object' && value ? value as Record<string, unknown> : {}
      const state = typeof value === 'string' ? value : s(detail.status, 'healthy')
      services.push({ name, status: state === 'ok' || state === 'healthy' || value === true ? 'healthy' : 'degraded', latencyMs: n(detail.latency_ms) || undefined, detail: s(detail.detail, state) })
    })
    if (services.length === 1) services.push({ name: 'Dependencies', status: s(ready.status, 'ready') === 'ready' ? 'healthy' : 'degraded', detail: s(ready.status, 'Ready') })
    return services
  },
}
