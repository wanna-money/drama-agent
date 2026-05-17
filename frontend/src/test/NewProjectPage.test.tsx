import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: {
    create: vi.fn(),
  },
  configApi: {
    listModels: vi.fn(),
    listVideoModels: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
const mockBlocker = { state: 'unblocked', proceed: vi.fn(), reset: vi.fn() }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate, useBlocker: () => mockBlocker }
})

import NewProjectPage from '../pages/NewProjectPage'
import { projectsApi, configApi } from '../services/api'
import { Toast } from '@douyinfe/semi-ui'

const llmModels = [{ value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'DeepSeek' }]
const videoModels = [{ value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动' }]

const renderPage = () =>
  render(
    <MemoryRouter>
      <NewProjectPage />
    </MemoryRouter>
  )

describe('NewProjectPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.listModels).mockResolvedValue(llmModels)
    vi.mocked(configApi.listVideoModels).mockResolvedValue(videoModels)
  })

  it('renders form fields', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByPlaceholderText('为您的短剧起一个名字')).toBeInTheDocument())
    expect(screen.getByPlaceholderText(/粘贴您的故事/)).toBeInTheDocument()
    expect(screen.getByText('开始创作')).toBeInTheDocument()
  })

  it('shows validation errors when submitting empty form', async () => {
    renderPage()
    await waitFor(() => screen.getByText('开始创作'))
    fireEvent.click(screen.getByText('开始创作'))
    await waitFor(() => expect(screen.getByText('请输入项目标题')).toBeInTheDocument())
    expect(screen.getByText('请输入故事内容')).toBeInTheDocument()
    expect(projectsApi.create).not.toHaveBeenCalled()
  })

  it('clears validation errors when user types in field', async () => {
    renderPage()
    await waitFor(() => screen.getByText('开始创作'))
    // Trigger validation errors
    fireEvent.click(screen.getByText('开始创作'))
    await waitFor(() => screen.getByText('请输入项目标题'))
    // Type in title field
    fireEvent.change(screen.getByPlaceholderText('为您的短剧起一个名字'), { target: { value: '新项目' } })
    await waitFor(() => expect(screen.queryByText('请输入项目标题')).not.toBeInTheDocument())
  })

  it('calls api.create with form data and navigates on success', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({
      id: 'new-proj', title: '新项目', status: 'created', genre: 'drama',
      llm_model: 'deepseek-v4-pro', video_provider: 'seedance',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    })
    renderPage()
    await waitFor(() => screen.getByPlaceholderText('为您的短剧起一个名字'))
    fireEvent.change(screen.getByPlaceholderText('为您的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴您的故事/), { target: { value: '这是一个故事内容，测试用的内容' } })
    fireEvent.click(screen.getByText('开始创作'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce())
    const callArg = vi.mocked(projectsApi.create).mock.calls[0][0]
    expect(callArg.title).toBe('新项目')
    expect(callArg.raw_input).toBe('这是一个故事内容，测试用的内容')
    expect(callArg.video_provider).toBe('seedance')
    expect(callArg.llm_model).toBe('deepseek-v4-pro')
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/projects/new-proj'))
  })

  it('shows error toast when creation fails', async () => {
    vi.mocked(projectsApi.create).mockRejectedValue({ message: 'Server error' })
    renderPage()
    await waitFor(() => screen.getByPlaceholderText('为您的短剧起一个名字'))
    fireEvent.change(screen.getByPlaceholderText('为您的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴您的故事/), { target: { value: '故事内容' } })
    fireEvent.click(screen.getByText('开始创作'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
  })

  it('does not submit when only title is filled', async () => {
    renderPage()
    await waitFor(() => screen.getByPlaceholderText('为您的短剧起一个名字'))
    fireEvent.change(screen.getByPlaceholderText('为您的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.click(screen.getByText('开始创作'))
    await waitFor(() => expect(screen.getByText('请输入故事内容')).toBeInTheDocument())
    expect(projectsApi.create).not.toHaveBeenCalled()
  })
})
