import type { DocumentRecord, OpsSummary, QueryResponse, SearchResult, ServiceHealth, TraceRecord } from './types'

export const demoSummary: OpsSummary = {
  latencyP50Ms: 184,
  latencyP95Ms: 742,
  queries: 12842,
  cacheHitRate: 0.684,
  tokens: 2_480_610,
  queryTrend: [48, 54, 49, 68, 72, 67, 88, 91, 86, 109, 113, 126],
  latencyTrend: [220, 198, 205, 192, 180, 178, 194, 171, 187, 176, 184, 181],
}

export const demoDocuments: DocumentRecord[] = [
  { id: 'doc_2f8c', title: 'Platform operations handbook', status: 'ready', chunks: 148, sizeBytes: 842_240, updatedAt: '2026-10-08T13:46:00Z' },
  { id: 'doc_76aa', title: 'Incident response playbook', status: 'ready', chunks: 84, sizeBytes: 491_520, updatedAt: '2026-10-08T12:18:00Z' },
  { id: 'doc_c193', title: 'Q4 product specification', status: 'processing', chunks: 36, sizeBytes: 1_348_812, updatedAt: '2026-10-08T14:02:00Z', jobId: 'job_37d1' },
  { id: 'doc_0b4e', title: 'API migration notes', status: 'failed', chunks: 0, sizeBytes: 76_800, updatedAt: '2026-10-08T11:21:00Z', error: 'Unsupported document encoding' },
]

export const demoTraces: TraceRecord[] = [
  { id: 'tr_92da1f', query: 'How do we rotate provider credentials?', status: 'ok', startedAt: '2026-10-08T14:08:41Z', durationMs: 621, chunks: 8, tokens: 1238, cacheHit: false, stages: [{ name: 'Lexical', durationMs: 42 }, { name: 'Vector', durationMs: 67 }, { name: 'Fusion', durationMs: 8 }, { name: 'Rerank', durationMs: 96 }, { name: 'Generate', durationMs: 408 }] },
  { id: 'tr_691ae0', query: 'What is the rollback procedure?', status: 'ok', startedAt: '2026-10-08T14:07:12Z', durationMs: 94, chunks: 6, tokens: 816, cacheHit: true, stages: [{ name: 'Cache lookup', durationMs: 9 }, { name: 'Hydrate', durationMs: 85 }] },
  { id: 'tr_61f48c', query: 'Summarize the Q4 roadmap risks', status: 'running', startedAt: '2026-10-08T14:06:39Z', durationMs: 318, chunks: 10, tokens: 0, cacheHit: false, stages: [{ name: 'Lexical', durationMs: 48 }, { name: 'Vector', durationMs: 73 }, { name: 'Fusion', durationMs: 9 }, { name: 'Rerank', durationMs: 112 }] },
  { id: 'tr_e873c1', query: 'List deprecated API endpoints', status: 'error', startedAt: '2026-10-08T13:58:02Z', durationMs: 1203, chunks: 0, tokens: 0, cacheHit: false, stages: [{ name: 'Lexical', durationMs: 47 }, { name: 'Vector', durationMs: 1156 }] },
]

export const demoSearch: SearchResult[] = [
  { id: 'chunk_801', title: 'Incident response playbook', excerpt: 'Initiate rollback after confirming the error budget threshold and assigning an incident commander…', lexicalScore: 0.91, vectorScore: 0.83, fusedScore: 0.87, rerankScore: 0.94 },
  { id: 'chunk_24d', title: 'Platform operations handbook', excerpt: 'Production rollback uses the previous immutable image and requires a readiness verification…', lexicalScore: 0.74, vectorScore: 0.88, fusedScore: 0.81, rerankScore: 0.86 },
  { id: 'chunk_c18', title: 'API migration notes', excerpt: 'Consumers should retain the prior route mapping for one release window to enable rapid rollback…', lexicalScore: 0.62, vectorScore: 0.76, fusedScore: 0.69, rerankScore: 0.71 },
  { id: 'chunk_4aa', title: 'Release checklist', excerpt: 'The release owner records deployment and rollback markers in the operations timeline…', lexicalScore: 0.54, vectorScore: 0.68, fusedScore: 0.61, rerankScore: 0.58 },
]

export const demoHealth: ServiceHealth[] = [
  { name: 'API', status: 'healthy', latencyMs: 18, detail: 'Serving requests' },
  { name: 'PostgreSQL', status: 'healthy', latencyMs: 7, detail: 'Pool 12 / 30' },
  { name: 'Redis', status: 'healthy', latencyMs: 3, detail: 'Memory 42%' },
  { name: 'Ingestion worker', status: 'healthy', latencyMs: 31, detail: 'Queue depth 3' },
  { name: 'Generation provider', status: 'degraded', latencyMs: 684, detail: 'Elevated latency' },
  { name: 'Embedding provider', status: 'healthy', latencyMs: 82, detail: 'Local deterministic' },
]

export const demoQueryResponse: QueryResponse = {
  answer: 'A safe rollback starts by declaring the incident owner, confirming the last known-good immutable image, and pausing concurrent deploys. Roll back one region first, verify readiness and error-rate guardrails, then complete the rollout and record deployment markers.',
  citations: [
    { id: 'c1', title: 'Incident response playbook', excerpt: 'Initiate rollback after confirming the error budget threshold and assigning an incident commander.', score: 0.94 },
    { id: 'c2', title: 'Platform operations handbook', excerpt: 'Production rollback uses the previous immutable image and requires readiness verification.', score: 0.86 },
  ],
  stages: demoTraces[0].stages,
  totalMs: 621,
  traceId: 'demo_trace_92da1f',
}
