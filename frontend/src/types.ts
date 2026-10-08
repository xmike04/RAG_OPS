export type SourceMode = 'live' | 'demo'

export interface OpsSummary {
  latencyP50Ms: number
  latencyP95Ms: number
  queries: number
  cacheHitRate: number
  tokens: number
  queryTrend: number[]
  latencyTrend: number[]
}

export type DocumentStatus = 'ready' | 'processing' | 'failed' | 'queued'

export interface DocumentRecord {
  id: string
  title: string
  status: DocumentStatus
  chunks: number
  sizeBytes: number
  updatedAt: string
  jobId?: string
  error?: string
}

export interface IngestionJob {
  id: string
  documentId: string
  status: string
  error?: string
  updatedAt: string
}

export interface StageTiming {
  name: string
  durationMs: number
}

export interface Citation {
  id: string
  title: string
  excerpt: string
  score: number
  chunkId?: string
}

export interface QueryResponse {
  answer: string
  citations: Citation[]
  stages: StageTiming[]
  requestId?: string
  traceId?: string
  totalMs: number
  cacheHit?: boolean
}

export type TraceStatus = 'ok' | 'error' | 'running'

export interface TraceRecord {
  id: string
  query: string
  status: TraceStatus
  startedAt: string
  durationMs: number
  chunks: number
  tokens: number
  cacheHit: boolean
  stages: StageTiming[]
}

export interface SearchResult {
  id: string
  title: string
  excerpt: string
  lexicalScore: number
  vectorScore: number
  fusedScore: number
  rerankScore: number
}

export interface ServiceHealth {
  name: string
  status: 'healthy' | 'degraded' | 'offline' | 'checking'
  latencyMs?: number
  detail: string
}
