import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('RAGOps console', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('API offline')))
  })

  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('labels demo fallback data when the API is unavailable', async () => {
    render(<App />)
    expect(await screen.findByText('Demo fallback active.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Operational overview' })).toBeInTheDocument()
    expect(screen.getByText('12.8K')).toBeInTheDocument()
    expect(screen.getByText('Demo data')).toBeInTheDocument()
  })

  it('navigates to the playground and renders a fallback answer', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Demo fallback active.')
    await user.click(screen.getByRole('button', { name: 'Query playground' }))
    expect(screen.getByRole('heading', { name: 'Query playground' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run query' }))
    expect(await screen.findByText(/A safe rollback starts/)).toBeInTheDocument()
    expect(screen.getByText('Incident response playbook')).toBeInTheDocument()
    expect(screen.getByLabelText('Retrieval stage timing')).toBeInTheDocument()
  })

  it('filters the demo document list', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Demo fallback active.')
    await user.click(screen.getByRole('button', { name: 'Documents' }))
    await user.type(screen.getByLabelText('Search documents'), 'incident')
    expect(screen.getByText('Incident response playbook')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Platform operations handbook')).not.toBeInTheDocument())
  })
})
