import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json', 'x-request-id': 'req_test' } })
}

describe('typed API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('normalizes summary variants from the v1 API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({
      latency_ms: { p50: 112, p95: 508 }, queries_total: 42,
      cache_hit_rate: 0.75, tokens_total: 9001,
      query_trend: [1, 3, 5], latency_trend: [120, 115, 112],
    })))
    await expect(api.getSummary()).resolves.toEqual({
      latencyP50Ms: 112, latencyP95Ms: 508, queries: 42,
      cacheHitRate: 0.75, tokens: 9001,
      queryTrend: [1, 3, 5], latencyTrend: [120, 115, 112],
    })
  })

  it('normalizes a grounded answer with citations and timings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({
      answer: 'Grounded answer', trace_id: 'trace_1', latency_ms: 20,
      citations: [{ chunk_id: 'chunk_1', document_title: 'Runbook', text: 'Evidence', rerank_score: 0.91 }],
      stage_latency_ms: { search: 8, generate: 12 },
    })))
    const result = await api.query('question', 'default')
    expect(result.answer).toBe('Grounded answer')
    expect(result.citations[0]).toMatchObject({ id: 'chunk_1', title: 'Runbook', score: 0.91 })
    expect(result.stages).toEqual([{ name: 'search', durationMs: 8 }, { name: 'generate', durationMs: 12 }])
  })

  it('surfaces API errors with request IDs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Bad query' }, 422)))
    await expect(api.query('', 'default')).rejects.toEqual(expect.objectContaining({ name: 'ApiError', message: 'Bad query', status: 422, requestId: 'req_test' } as ApiError))
  })

  it('scopes ingestion status polling to the workspace', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ id: 'job_1', document_id: 'doc_1', status: 'running', updated_at: '2026-10-08T10:00:00Z' }))
    vi.stubGlobal('fetch', fetchMock)
    await api.getIngestion('job_1', 'default')
    expect(fetchMock).toHaveBeenCalledWith('/v1/ingestions/job_1?workspace_id=00000000-0000-0000-0000-000000000001', expect.any(Object))
  })
})
