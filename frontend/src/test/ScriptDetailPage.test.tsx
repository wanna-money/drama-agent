import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

// 剧本库是内容的家:正文在此编辑。制作流程的审核/AI 改写在剧集页(那条路有版本树)。
vi.mock('../services/api', () => ({
  scriptsApi: { get: vi.fn(), update: vi.fn(), delete: vi.fn() },
  projectsApi: { list: vi.fn(() => Promise.resolve([])) },
  storyTextApi: { revise: vi.fn(), parseAttachment: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ScriptDetailPage from '../pages/ScriptDetailPage'
import { scriptsApi, projectsApi } from '../services/api'
import { Modal, Toast } from '@douyinfe/semi-ui'

const SCRIPT_ID = 's-1'
const baseScript = {
  id: SCRIPT_ID, project_id: null, story_id: 'st-1', title: '夏日重逢', genre: 'romance',
  source_text: '一个夏天的故事', content: '第一场 海边', story_analysis: null,
  story_title: '夏日的原文', project_title: null, created_at: null,
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/scripts/${SCRIPT_ID}`]}>
      <Routes>
        <Route path="/scripts/:id" element={<ScriptDetailPage />} />
      </Routes>
    </MemoryRouter>
  )

describe('ScriptDetailPage(内容的家)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('原文与剧本各有一张卡 —— 方案正文还空时也看得到它改编自什么', async () => {
    // 方案可以先只有原文、正文待产出(从故事开跑的那条路)。若本页只认 content,
    // 用户点进来会看到一片空白,不知道这个方案是从哪段原文来的。
    vi.mocked(scriptsApi.get).mockResolvedValue(
      { ...baseScript, content: null } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('一个夏天的故事')).toBeInTheDocument())
    expect(screen.getByText('改编自《夏日的原文》')).toBeInTheDocument()
  })

  // 原文住在 Story 上,可能被同一段原文的多个方案共用 —— 在方案页改它会让别的方案
  // 跟着变,而用户以为只动了眼前这一个。故此处**只读**,改原文去故事页。
  it('原文只读:方案页不给编辑入口,并说明去哪改', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('一个夏天的故事')).toBeInTheDocument())
    expect(screen.getByText(/原文由故事页维护/)).toBeInTheDocument()
    // 只有剧本正文那张卡可编辑
    expect(screen.getAllByText('编辑')).toHaveLength(1)
  })

  it('原文卡标出改编自哪段原文 —— 同名方案多了要能认出源头', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(
      { ...baseScript, story_title: '深夜来客' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('改编自《深夜来客》')).toBeInTheDocument())
  })

  it('展示剧本正文,但不承载制作流程的生成/审核', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('第一场 海边')).toBeInTheDocument())
    // 审核与 AI 改写在剧集页(有版本树);剧本库不重复表达同一件事
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
    expect(screen.queryByText('生成正文')).not.toBeInTheDocument()
  })

  // 改编面板把用户导到这里改正文("点开任一剧本可修改正文")。这条删掉,
  // 那句引导就会落空,而后端 PATCH /scripts/{id} 也再无调用方。
  it('编辑正文并保存,调 PATCH 并展示新正文', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    vi.mocked(scriptsApi.update).mockResolvedValue(
      { ...baseScript, content: '改过的正文' } as any)
    renderPage()
    await waitFor(() => expect(screen.getAllByText('编辑')).toHaveLength(1))
    fireEvent.click(screen.getAllByText('编辑')[0])
    fireEvent.change(screen.getByDisplayValue('第一场 海边'), { target: { value: '改过的正文' } })
    fireEvent.click(screen.getAllByText('保存')[0])
    await waitFor(() => expect(scriptsApi.update).toHaveBeenCalledWith(
      SCRIPT_ID, { content: '改过的正文' }))
    await waitFor(() => expect(screen.getByText('改过的正文')).toBeInTheDocument())
  })

  it('正文清空后不提交 —— 空剧本会让下游分镜无从下手', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getAllByText('编辑')).toHaveLength(1))
    fireEvent.click(screen.getAllByText('编辑')[0])
    fireEvent.change(screen.getByDisplayValue('第一场 海边'), { target: { value: '   ' } })
    fireEvent.click(screen.getAllByText('保存')[0])
    await waitFor(() => expect(scriptsApi.update).not.toHaveBeenCalled())
  })

  it('取消编辑后正文回到原样,不落库', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    renderPage()
    await waitFor(() => expect(screen.getAllByText('编辑')).toHaveLength(1))
    fireEvent.click(screen.getAllByText('编辑')[0])
    fireEvent.change(screen.getByDisplayValue('第一场 海边'), { target: { value: '弃稿' } })
    fireEvent.click(screen.getAllByText('取消')[0])
    await waitFor(() => expect(screen.getByText('第一场 海边')).toBeInTheDocument())
    expect(scriptsApi.update).not.toHaveBeenCalled()
  })

  it('可删除方案，确认后回到它所属的原文', async () => {
    // 方案没有列表页可回 —— 回原文是唯一说得通的去处:那里列着它的兄弟方案
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    vi.mocked(scriptsApi.delete).mockResolvedValue({ ok: true } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('删除')).toBeInTheDocument())
    fireEvent.click(screen.getByText('删除'))
    await (Modal as any)._lastConfirm.current.onOk()
    expect(scriptsApi.delete).toHaveBeenCalledWith(SCRIPT_ID)
    expect(mockNavigate).toHaveBeenCalledWith('/stories/st-1')
  })

  it('删除被后端挡住时展示 detail（还有集在用 → 409）', async () => {
    // 后端守卫的说明要直达用户:他据此知道先删剧集,而不是以为删除功能坏了
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    vi.mocked(scriptsApi.delete).mockRejectedValue(
      { response: { data: { detail: '还有 2 集在用这个剧本' } } })
    renderPage()
    await waitFor(() => expect(screen.getByText('删除')).toBeInTheDocument())
    fireEvent.click(screen.getByText('删除'))
    await (Modal as any)._lastConfirm.current.onOk()
    expect(Toast.error).toHaveBeenCalledWith(expect.stringContaining('还有 2 集'))
  })

  // 方案在原文的上下文里读:面包屑要能回到它改编自的那段原文。
  // 只给"故事库"的话,用户回去还得在一堆故事里重新找是哪一段。
  it('面包屑 故事库 › 《原文》 › {标题}', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(
      { ...baseScript, story_title: '深夜来客' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('故事库')).toBeInTheDocument())
    expect(screen.getByText('深夜来客')).toBeInTheDocument()
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

  // ── 归属 ──────────────────────────────────────────────────────────────────

  // 剧本是全局可复用内容,归属只是"产生于哪个作品",应当可改(移走 / 解绑成散稿)。
  it('可改归属:选作品后调 PATCH', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(baseScript as any)
    vi.mocked(projectsApi.list).mockResolvedValue([
      { id: 'p-a', title: '作品甲' },
    ] as any)
    vi.mocked(scriptsApi.update).mockResolvedValue(
      { ...baseScript, project_id: 'p-a', project_title: '作品甲' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('改归属')).toBeInTheDocument())
    fireEvent.click(screen.getByText('改归属'))
    const sel = await waitFor(() => screen.getAllByRole('combobox')[0] as HTMLSelectElement)
    fireEvent.change(sel, { target: { value: 'p-a' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(scriptsApi.update).toHaveBeenCalledWith(
      SCRIPT_ID, { project_id: 'p-a' }))
  })

  // 空串是"解绑"的显式表达 —— 后端据此区分"不改归属"(不传)与"改成散稿"。
  it('归属留空即解绑成散稿,传的是空串而非 undefined', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(
      { ...baseScript, project_id: 'p-a', project_title: '作品甲' } as any)
    vi.mocked(projectsApi.list).mockResolvedValue([{ id: 'p-a', title: '作品甲' }] as any)
    vi.mocked(scriptsApi.update).mockResolvedValue(
      { ...baseScript, project_id: null, project_title: null } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('改归属')).toBeInTheDocument())
    fireEvent.click(screen.getByText('改归属'))
    const sel = await waitFor(() => screen.getAllByRole('combobox')[0] as HTMLSelectElement)
    fireEvent.change(sel, { target: { value: '' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(scriptsApi.update).toHaveBeenCalledWith(
      SCRIPT_ID, { project_id: '' }))
  })

  it('无归属时展示「未归属」而非空白', async () => {
    vi.mocked(scriptsApi.get).mockResolvedValue(
      { ...baseScript, project_id: null, project_title: null } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('未归属')).toBeInTheDocument())
  })
})
