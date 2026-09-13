import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

// 故事库:文本入库产出的是原文(不是剧本)。页面负责 list/create/delete。
vi.mock('../services/api', () => ({
  storiesApi: { list: vi.fn(), create: vi.fn(), delete: vi.fn() },
  projectsApi: { list: vi.fn(() => Promise.resolve([])) },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import { Modal } from '@douyinfe/semi-ui'
import StoriesPage from '../pages/StoriesPage'
import { storiesApi, Story } from '../services/api'

const story = (over: Partial<Story> = {}): Story => ({
  id: 'st-1', project_id: null, title: '夏日重逢', genre: 'romance',
  content: '一个夏天的故事', project_title: null,
  script_count: 0, segment_count: 0, ...over,
})

const renderList = () =>
  render(
    <MemoryRouter initialEntries={['/stories']}>
      <Routes>
        <Route path="/stories" element={<StoriesPage />} />
        <Route path="/stories/group/:groupKey" element={<StoriesPage />} />
      </Routes>
    </MemoryRouter>
  )

const renderGroup = (key: string) =>
  render(
    <MemoryRouter initialEntries={[`/stories/group/${key}`]}>
      <Routes>
        <Route path="/stories" element={<StoriesPage />} />
        <Route path="/stories/group/:groupKey" element={<StoriesPage />} />
      </Routes>
    </MemoryRouter>
  )

describe('StoriesPage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  // 片段是父原文的内部结构:平铺进总览会把一本小说的 N 段与别的故事混在一起,
  // 用户分不出哪些是一组。故列表只请求顶层。
  it('总览只列顶层原文,不平铺切出来的片段', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([story()])
    renderList()
    await waitFor(() => expect(storiesApi.list).toHaveBeenCalled())
    expect(vi.mocked(storiesApi.list).mock.calls[0][0]).toMatchObject({ topLevelOnly: true })
  })

  // 用户点进去要做什么,取决于这段原文已经有什么产出:还没改编过的要去开拍,
  // 已有几个方案的是来对比取用。没有这两个数字就分不出来。
  it('列出已切段数与已有方案数', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'a1', title: '长篇', project_id: 'p1', project_title: '我的小说',
              segment_count: 12, script_count: 3 }),
    ])
    renderGroup('p1')
    await waitFor(() => expect(screen.getByText('12 段')).toBeInTheDocument())
    expect(screen.getByText('3 个方案')).toBeInTheDocument()
  })

  it('新建故事:归属留空即散稿,建完跳详情', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([])
    vi.mocked(storiesApi.create).mockResolvedValue({ ...story(), id: 'new-1' } as any)
    renderList()
    await waitFor(() => expect(screen.getByText('新建故事')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新建故事'))
    fireEvent.change(await screen.findByPlaceholderText('给这个故事起个名字'),
      { target: { value: '独立故事' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴故事/), { target: { value: '正文' } })
    fireEvent.click(screen.getByText('创建'))
    await waitFor(() => expect(storiesApi.create).toHaveBeenCalledOnce())
    const arg = vi.mocked(storiesApi.create).mock.calls[0][0]
    expect(arg).toMatchObject({ title: '独立故事', content: '正文', project_id: null })
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/stories/new-1'))
  })

  it('未填标题时不提交', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([])
    renderList()
    await waitFor(() => expect(screen.getByText('新建故事')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新建故事'))
    fireEvent.click(await screen.findByText('创建'))
    await waitFor(() => expect(storiesApi.create).not.toHaveBeenCalled())
  })

  // 后端挡住"还有方案在用"(409)时,它的说明要直达用户 —— 他据此知道先删那些剧本,
  // 而不是以为删除功能坏了。
  it('删除被挡住时展示后端 detail', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'a1', project_id: 'p1', project_title: '作品', script_count: 2 }),
    ])
    vi.mocked(storiesApi.delete).mockRejectedValue({
      response: { data: { detail: '还有 2 个改编方案挂在这个故事下' } },
    })
    const { Toast } = await import('@douyinfe/semi-ui')
    const { container } = renderGroup('p1')
    await waitFor(() => expect(screen.getByText('夏日重逢')).toBeInTheDocument())
    // 删除按钮只有图标(无可访问名),故按 DOM 取:列表项里的 danger 按钮
    const del = container.querySelectorAll('button')
    fireEvent.click(del[del.length - 1])
    await (Modal as any)._lastConfirm.current.onOk()
    expect(Toast.error).toHaveBeenCalledWith('还有 2 个改编方案挂在这个故事下')
  })

  it('空态给出去处', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([])
    renderList()
    await waitFor(() => expect(screen.getByText('还没有故事')).toBeInTheDocument())
  })
})
