import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import './mocks'

// Mock the api module before importing the component
vi.mock('../services/api', () => ({
  projectsApi: {
    list: vi.fn(),
    delete: vi.fn(),
    create: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectListPage from '../pages/ProjectListPage'
import { projectsApi } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const mockProject = {
  id: 'proj-1',
  title: '测试项目',
  genre: 'drama',
  visual_style: 'realistic',
  status: 'running',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <ProjectListPage />
    </MemoryRouter>
  )

describe('ProjectListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    vi.mocked(projectsApi.list).mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('spin')).toBeInTheDocument()
  })

  it('shows project list after loading', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([mockProject])
    renderPage()
    await waitFor(() => expect(screen.getByText('测试项目')).toBeInTheDocument())
  })

  it('shows error state when API fails', async () => {
    vi.mocked(projectsApi.list).mockRejectedValue(new Error('Network error'))
    renderPage()
    await waitFor(() => expect(screen.getByText('加载失败')).toBeInTheDocument())
  })

  it('shows empty state when no projects', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => expect(screen.getByText('还没有作品')).toBeInTheDocument())
  })

  it('shows delete confirmation dialog on delete click', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([mockProject])
    renderPage()
    await waitFor(() => screen.getByText('删除'))
    fireEvent.click(screen.getByText('删除'))
    expect(Modal.confirm).toHaveBeenCalledOnce()
    const call = vi.mocked(Modal.confirm).mock.calls[0][0] as any
    expect(call.title).toBe('确认删除')
    expect(call.content).toContain('测试项目')
  })

  it('removes project from list after successful delete', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([mockProject])
    vi.mocked(projectsApi.delete).mockResolvedValue(undefined)
    renderPage()
    await waitFor(() => screen.getByText('删除'))
    fireEvent.click(screen.getByText('删除'))
    const opts = (Modal as any)._lastConfirm.current
    await opts.onOk()
    expect(Toast.success).toHaveBeenCalledWith('已删除')
    await waitFor(() => expect(screen.queryByText('测试项目')).not.toBeInTheDocument())
  })

  it('shows error toast when delete fails', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([mockProject])
    vi.mocked(projectsApi.delete).mockRejectedValue(new Error('Server error'))
    renderPage()
    await waitFor(() => screen.getByText('删除'))
    fireEvent.click(screen.getByText('删除'))
    const opts = (Modal as any)._lastConfirm.current
    await opts.onOk()
    expect(Toast.error).toHaveBeenCalledWith('删除失败，请重试')
  })

  it('shows stronger warning when deleting an active project', async () => {
    const activeProject = { ...mockProject, status: 'analyzing' }
    vi.mocked(projectsApi.list).mockResolvedValue([activeProject])
    renderPage()
    await waitFor(() => screen.getByText('删除'))
    fireEvent.click(screen.getByText('删除'))
    const opts = (Modal as any)._lastConfirm.current
    expect(opts.content).toContain('正在制作中')
  })

  it('shows normal warning when deleting a completed project', async () => {
    const completedProject = { ...mockProject, status: 'completed' }
    vi.mocked(projectsApi.list).mockResolvedValue([completedProject])
    renderPage()
    await waitFor(() => screen.getByText('删除'))
    fireEvent.click(screen.getByText('删除'))
    const opts = (Modal as any)._lastConfirm.current
    expect(opts.content).not.toContain('正在制作中')
    expect(opts.content).toContain('无法恢复')
  })

  it('creates a project via the modal and navigates to it', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([])
    vi.mocked(projectsApi.create).mockResolvedValue({ ...mockProject, id: 'new-1', title: '新剧' })
    renderPage()
    await waitFor(() => screen.getByText('还没有作品'))
    // 空态下顶部「新建项目」按钮常驻,点它打开弹窗
    fireEvent.click(screen.getByText('新建项目'))
    // 填剧名(genre 有默认 drama)
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '  新剧  ' } })
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    // 点确定 → submitForm → onSubmit → create
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() =>
      expect(projectsApi.create).toHaveBeenCalledWith(
        { title: '新剧', genre: 'drama', visual_style: 'realistic' })
    )
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/projects/new-1'))
  })

  it('does not create when title is empty (validation blocks submit)', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => screen.getByText('还没有作品'))
    fireEvent.click(screen.getByText('新建项目'))
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(screen.getByText('请输入剧名')).toBeInTheDocument())
    expect(projectsApi.create).not.toHaveBeenCalled()
  })

  it('创建项目时要求选择视觉风格', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => screen.getByText('还没有作品'))
    fireEvent.click(screen.getByText('新建项目'))
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新剧' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(screen.getByText('请选择视觉风格')).toBeInTheDocument())
    expect(projectsApi.create).not.toHaveBeenCalled()
  })

  // 列表里给用户看的是中文;drama/romance 是后端枚举值,漏译就把内部取值漏给了用户。
  it('类型列展示中文而非枚举原值', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([
      { id: 'p1', title: '作品甲', genre: 'romance', status: 'empty',
        episodes: [], created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ] as any)
    render(<ProjectListPage />)
    await waitFor(() => expect(screen.getByText('作品甲')).toBeInTheDocument())
    expect(screen.getByText('爱情')).toBeInTheDocument()
    expect(screen.queryByText('romance')).not.toBeInTheDocument()
  })
})
