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
      id: 'new-proj', title: '新项目', genre: 'drama', visual_style: 'realistic', status: 'empty',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce())
    const callArg = vi.mocked(projectsApi.create).mock.calls[0][0]
    expect(callArg.title).toBe('新项目')
    // 故事正文不属于作品:它的家是剧本(作品只管小说原文 source_text)
    expect(callArg).not.toHaveProperty('raw_input')
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/projects/new-proj'))
  })

  it('要求选择视觉风格才能提交', async () => {
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(screen.getByText('请选择视觉风格')).toBeInTheDocument())
    expect(projectsApi.create).not.toHaveBeenCalled()
  })

  it('提交时带上选中的视觉风格', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({
      id: 'new-proj', title: '新项目', genre: 'drama', visual_style: 'cyberpunk',
      status: 'empty', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'cyberpunk' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ visual_style: 'cyberpunk' })))
  })

  it('shows error toast when creation fails', async () => {
    vi.mocked(projectsApi.create).mockRejectedValue({ message: 'Server error' })
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: '新项目' } })
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
  })
})

describe('NewProjectPage 小说模式', () => {
  beforeEach(() => vi.clearAllMocks())

  const fillTitle = (v: string) =>
    fireEvent.change(screen.getByPlaceholderText('为你的短剧起一个名字'), { target: { value: v } })

  it('提交 source_text 与切分依据(按集数)', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({ id: 'p-new' } as any)
    renderPage()
    fillTitle('我的小说')
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴小说全文/), { target: { value: '很长的正文' } })
    fireEvent.change(screen.getByPlaceholderText(/期望集数/), { target: { value: '6' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ title: '我的小说', source_text: '很长的正文', target_episodes: 6 })))
  })

  it('提交 source_text 与切分依据(按每集时长)', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({ id: 'p-new' } as any)
    renderPage()
    fillTitle('我的小说')
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴小说全文/), { target: { value: '很长的正文' } })
    fireEvent.change(screen.getByPlaceholderText(/与集数二选一/), { target: { value: '90' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ source_text: '很长的正文', target_seconds_per_episode: 90 })))
    expect(vi.mocked(projectsApi.create).mock.calls[0][0]).not.toHaveProperty('target_episodes')
  })

  // 空字段不能变成 ''/0 传给后端:后端「有正文时切分依据恰好二选一」会因此误判 → 422。
  it('短故事模式:三个小说字段留空时一个都不传', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({ id: 'p-new' } as any)
    renderPage()
    fillTitle('短故事作品')
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce())
    const arg = vi.mocked(projectsApi.create).mock.calls[0][0]
    expect(arg).not.toHaveProperty('source_text')
    expect(arg).not.toHaveProperty('target_episodes')
    expect(arg).not.toHaveProperty('target_seconds_per_episode')
  })

  // 清空 InputNumber 时真实 Semi 回调的是 ''(见 semi-foundation notifyChange),不是 undefined。
  // 生产代码若把真值判断改成 `!== undefined`,清空后就会把 '' 发给后端 → 有正文时误判为
  // 「两个切分依据都给了」而 422。这条锁住"填了又清空 = 不传"。
  it('清空切分依据后不把空值传给后端', async () => {
    vi.mocked(projectsApi.create).mockResolvedValue({ id: 'p-new' } as any)
    renderPage()
    fillTitle('我的小说')
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴小说全文/), { target: { value: '很长的正文' } })
    const episodes = screen.getByPlaceholderText(/期望集数/)
    fireEvent.change(episodes, { target: { value: '6' } })
    fireEvent.change(episodes, { target: { value: '' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce())
    expect(vi.mocked(projectsApi.create).mock.calls[0][0]).not.toHaveProperty('target_episodes')
  })

  // 「切分依据恰好二选一」的唯一权威在后端(规范 4),前端不复刻规则;
  // 那么后端 422 的中文 detail 就是用户唯一能看到原因的途径,必须原样透出。
  it('后端 422 的 detail 原样提示给用户', async () => {
    vi.mocked(projectsApi.create).mockRejectedValue({
      response: { data: { detail: '有小说正文时,期望集数与每集时长必须恰好二选一' } },
    })
    renderPage()
    fillTitle('我的小说')
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'realistic' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴小说全文/), { target: { value: '很长的正文' } })
    fireEvent.click(screen.getByText('创建项目'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith(
      expect.stringContaining('有小说正文时,期望集数与每集时长必须恰好二选一')))
  })
})
