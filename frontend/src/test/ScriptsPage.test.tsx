import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import './mocks'

vi.mock('../services/api', () => ({
  scriptsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    start: vi.fn(),
    resume: vi.fn(),
    status: vi.fn(),
  },
  configApi: {
    listModels: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ScriptsPage from '../pages/ScriptsPage'
import { scriptsApi, configApi } from '../services/api'

const script = (over: Partial<{ id: string; title: string; status: string }> = {}) => ({
  id: 's-1',
  project_id: null,
  episode_index: null,
  title: '夏日重逢',
  genre: 'romance',
  source_text: '一个夏天的故事',
  content: null,
  status: 'completed',
  error_message: null,
  ...over,
})

describe('ScriptsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.listModels).mockResolvedValue({ models: [], default: null })
  })

  it('renders every script returned by the list API', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([
      script(),
      script({ id: 's-2', title: '雪夜追凶', status: 'created' }),
    ])
    render(<ScriptsPage />)
    await waitFor(() => expect(screen.getByText('夏日重逢')).toBeInTheDocument())
    expect(screen.getByText('雪夜追凶')).toBeInTheDocument()
    // 状态映射:completed → 已完成,created → 草稿
    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('草稿')).toBeInTheDocument()
  })

  it('shows the empty state when there are no scripts', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    render(<ScriptsPage />)
    await waitFor(() => expect(screen.getByText('还没有剧本')).toBeInTheDocument())
  })

  it('creates a script with the entered title and source text', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    vi.mocked(scriptsApi.create).mockResolvedValue(script({ id: 's-new' }))
    render(<ScriptsPage />)
    await waitFor(() => screen.getByText('还没有剧本'))

    fireEvent.click(screen.getByText('新建剧本'))
    fireEvent.change(screen.getByPlaceholderText('如 夏日重逢'), { target: { value: '雪夜追凶' } })
    fireEvent.change(
      screen.getByPlaceholderText(/粘贴或输入故事文本/),
      { target: { value: '一个雪夜的故事' } },
    )
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => expect(scriptsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ title: '雪夜追凶', source_text: '一个雪夜的故事' })
    ))
    // 建完跳详情页看生成进度
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scripts/s-new'))
  })

  it('does not call create when required fields are blank', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    render(<ScriptsPage />)
    await waitFor(() => screen.getByText('还没有剧本'))

    fireEvent.click(screen.getByText('新建剧本'))
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => expect(scriptsApi.create).not.toHaveBeenCalled())
  })

  it('submits the backend-provided default llm on create', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listModels).mockResolvedValue({
      models: [
        { value: 'a', label: 'A', provider: 'P' },
        { value: 'b', label: 'B', provider: 'P', is_default: true },
      ],
      default: 'b',
    })
    vi.mocked(scriptsApi.create).mockResolvedValue(script({ id: 's1' }))
    render(<ScriptsPage />)
    await waitFor(() => screen.getByText('新建剧本'))

    fireEvent.click(screen.getByText('新建剧本'))
    fireEvent.change(screen.getByPlaceholderText('如 夏日重逢'), { target: { value: 'My' } })
    fireEvent.change(
      screen.getByPlaceholderText(/粘贴或输入故事文本/),
      { target: { value: 'body text' } },
    )
    fireEvent.click(screen.getByText('创建'))

    await waitFor(() => expect(scriptsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ llm_model: 'b' })
    ))
  })
})
