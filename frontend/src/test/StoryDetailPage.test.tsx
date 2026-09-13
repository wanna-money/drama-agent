import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

// 故事详情:原文正文在此编辑,并列出由它派生的片段与改编方案(1:N 唯一完整呈现处)。
vi.mock('../services/api', () => ({
  storiesApi: { get: vi.fn(), list: vi.fn(), update: vi.fn(), delete: vi.fn() },
  scriptsApi: { list: vi.fn() },
  projectsApi: { list: vi.fn(() => Promise.resolve([])) },
  storyTextApi: { revise: vi.fn(), parseAttachment: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import StoryDetailPage from '../pages/StoryDetailPage'
import { storiesApi, scriptsApi, Story } from '../services/api'

const STORY_ID = 'st-1'
const baseStory: Story = {
  id: STORY_ID, project_id: null, title: '夏日重逢', genre: 'romance',
  content: '一个夏天的故事', story_analysis: null, project_title: null,
  script_count: 0, segment_count: 0,
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/stories/${STORY_ID}`]}>
      <Routes><Route path="/stories/:id" element={<StoryDetailPage />} /></Routes>
    </MemoryRouter>
  )

describe('StoryDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(storiesApi.get).mockResolvedValue(baseStory as any)
    vi.mocked(storiesApi.list).mockResolvedValue([])
    vi.mocked(scriptsApi.list).mockResolvedValue([])
  })

  // 改原文写 Story —— 写 Script 会让同一段原文的多个方案各持一份并逐渐漂移。
  it('编辑原文保存落到 PATCH /stories/{id}', async () => {
    vi.mocked(storiesApi.update).mockResolvedValue(
      { ...baseStory, content: '改过的故事' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('一个夏天的故事')).toBeInTheDocument())
    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(await screen.findByDisplayValue('一个夏天的故事'),
      { target: { value: '改过的故事' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(storiesApi.update).toHaveBeenCalledWith(
      STORY_ID, { content: '改过的故事' }))
    await waitFor(() => expect(screen.getByText('改过的故事')).toBeInTheDocument())
  })

  // 这是 1:N 的全部意义:同一段原文并列多个方案。只列一个(或不列)就退回了 1:1 的表达,
  // 用户看不到"我已经试过哪几个方向"。
  it('列出这段原文的全部改编方案,按 story_id 取', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([
      { id: 'sc-a', title: '悬疑版', genre: 'thriller', content: '正文A' },
      { id: 'sc-b', title: '温情版', genre: 'romance', content: '正文B' },
    ] as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('悬疑版')).toBeInTheDocument())
    expect(screen.getByText('温情版')).toBeInTheDocument()
    expect(screen.getByText('改编方案（2）')).toBeInTheDocument()
    expect(vi.mocked(scriptsApi.list).mock.calls[0][0]).toMatchObject({ storyId: STORY_ID })
  })

  // 改原文不会自动更新已有方案(那些剧本是独立产出)。不说这句,用户会以为改了原文
  // 剧本就同步了,拿着旧方案继续开拍。
  it('方案区说明改原文不会自动更新已有方案', async () => {
    renderPage()
    await waitFor(() => expect(
      screen.getByText(/改原文不会自动更新已有方案/)).toBeInTheDocument())
  })

  it('没有方案时给出下一步,而不是空白', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/还没有方案/)).toBeInTheDocument())
  })

  // 片段是这段原文的内部结构(切分产出),故列在详情页;按 parent_id 取。
  it('列出切出的片段,按 parent_id 取', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      { ...baseStory, id: 'seg-1', title: '第 1 段', parent_id: STORY_ID, script_count: 1 },
    ] as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('第 1 段')).toBeInTheDocument())
    expect(screen.getByText('片段（1）')).toBeInTheDocument()
    expect(vi.mocked(storiesApi.list).mock.calls[0][0]).toMatchObject({ parentId: STORY_ID })
  })

  it('故事不存在时给错误态', async () => {
    vi.mocked(storiesApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('故事不存在')).toBeInTheDocument())
  })
})
