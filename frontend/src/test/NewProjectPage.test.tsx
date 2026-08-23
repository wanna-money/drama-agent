import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { create: vi.fn() },
}))

const mockNavigate = vi.fn()
const mockBlocker = { state: 'unblocked', proceed: vi.fn(), reset: vi.fn() }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate, useBlocker: () => mockBlocker }
})

import NewProjectPage from '../pages/NewProjectPage'
import { projectsApi } from '../services/api'
import { Toast } from '@douyinfe/semi-ui'

const renderPage = () =>
  render(<MemoryRouter><NewProjectPage /></MemoryRouter>)

describe('NewProjectPage (slim: title + genre only)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders 剧名 field and 创建项目 button', async () => {
    renderPage()
    expect(screen.getByPlaceholderText('为你的短剧起一个名字')).toBeInTheDocument()
    expect(screen.getByText('创建项目')).toBeInTheDocument()
  })

  it('validates empty 剧名', async () => {
    renderPage()
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(screen.getByText('请输入剧名')).toBeInTheDocument())
    expect(projectsApi.create).not.toHaveBeenCalled()
  })

  it('creates project (title+genre) and navigates to its episode list', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({
      id: 'new-proj', title: '新项目', genre: 'drama', status: 'empty',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce())
    const callArg = vi.mocked(projectsApi.create).mock.calls[0][0]
    expect(callArg.title).toBe('新项目')
    expect(callArg).not.toHaveProperty('raw_input')  // raw_input 已挪到建集
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/projects/new-proj'))
  })

  it('shows error toast when creation fails', async () => {
    vi.mocked(projectsApi.create).mockRejectedValue({ message: 'Server error' })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
  })
})
