import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import './mocks'

// 剧本库瘦身:剧本只由「剧集审核通过后存入」产生,页面只 list/delete,无新建表单。
vi.mock('../services/api', () => ({
  scriptsApi: {
    list: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ScriptsPage from '../pages/ScriptsPage'
import { scriptsApi } from '../services/api'
import { Script } from '../services/api'

const script = (over: Partial<Script> = {}): Script => ({
  id: 's-1',
  project_id: null,
  title: '夏日重逢',
  genre: 'romance',
  source_text: '一个夏天的故事',
  content: '正文',
  project_title: null,
  created_at: undefined,
  ...over,
})

describe('ScriptsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders every script returned by the list API', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([
      script(),
      script({ id: 's-2', title: '雪夜追凶' }),
    ])
    render(<ScriptsPage />)
    await waitFor(() => expect(screen.getByText('夏日重逢')).toBeInTheDocument())
    expect(screen.getByText('雪夜追凶')).toBeInTheDocument()
  })

  it('shows the empty state when there are no scripts', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    render(<ScriptsPage />)
    await waitFor(() => expect(screen.getByText('还没有剧本')).toBeInTheDocument())
  })

  it('剧本库不再有「新建剧本」入口(剧本只由剧集审核通过后存入)', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    render(<ScriptsPage />)
    await waitFor(() => screen.getByText('还没有剧本'))
    expect(screen.queryByText('新建剧本')).not.toBeInTheDocument()
  })
})
