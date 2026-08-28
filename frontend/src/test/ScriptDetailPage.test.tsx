import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

// 剧本库瘦身后:剧本是只读复用素材,详情页只 get 展示,无生成/审核/编辑端点。
vi.mock('../services/api', () => ({
  scriptsApi: { get: vi.fn() },
}))

import ScriptDetailPage from '../pages/ScriptDetailPage'
import { scriptsApi } from '../services/api'

const SCRIPT_ID = 's-1'
const baseScript = {
  id: SCRIPT_ID, project_id: null, title: '夏日重逢', genre: 'romance',
  source_text: '一个夏天的故事', content: '第一场 海边', story_analysis: null,
  project_title: null, created_at: null,
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/scripts/${SCRIPT_ID}`]}>
      <Routes>
        <Route path="/scripts/:id" element={<ScriptDetailPage />} />
      </Routes>
    </MemoryRouter>
  )

describe('ScriptDetailPage(只读复用素材)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('展示剧本正文,且没有任何生成/审核/编辑入口', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('第一场 海边')).toBeInTheDocument())
    // 审核/编辑流程已搬到剧集页;剧本库这里必须是纯只读
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
    expect(screen.queryByText('编辑')).not.toBeInTheDocument()
    expect(screen.queryByText('生成正文')).not.toBeInTheDocument()
  })

  it('面包屑 剧本库 › {标题}', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('剧本库')).toBeInTheDocument())
  })

  it('有故事分析时展示类型/基调/主题/梗概', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue({
      ...baseScript,
      story_analysis: {
        title: 'x', genre: 'thriller', tone: 'tense', themes: ['信任', '孤独'],
        plot_summary: '梗概文本', setting: '', characters: [],
      },
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('梗概文本')).toBeInTheDocument())
    expect(screen.getByText('故事分析')).toBeInTheDocument()
  })

  it('剧本不存在时显示未找到', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('剧本未找到')).toBeInTheDocument())
  })
})
