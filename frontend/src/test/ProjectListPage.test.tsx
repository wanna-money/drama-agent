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
  },
}))

import ProjectListPage from '../pages/ProjectListPage'
import { projectsApi } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const mockProject = {
  id: 'proj-1',
  title: '测试项目',
  genre: 'drama',
  status: 'created',
  video_provider: 'seedance',
  llm_model: 'deepseek-v4-pro',
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

  it('maps video_provider to display label', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([mockProject])
    renderPage()
    await waitFor(() => expect(screen.getByText('Seedance 2.0')).toBeInTheDocument())
    expect(screen.queryByText('seedance')).not.toBeInTheDocument()
  })

  it('maps bailian provider to display label', async () => {
    vi.mocked(projectsApi.list).mockResolvedValue([{ ...mockProject, video_provider: 'bailian' }])
    renderPage()
    await waitFor(() => expect(screen.getByText('万相 2.7')).toBeInTheDocument())
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
})
