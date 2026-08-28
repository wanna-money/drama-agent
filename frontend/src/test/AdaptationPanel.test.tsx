import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import './mocks'

vi.mock('../services/api', () => ({
  adaptationApi: { start: vi.fn(), get: vi.fn(), saveDraft: vi.fn(), commit: vi.fn() },
}))

import AdaptationPanel from '../components/AdaptationPanel'
import { adaptationApi } from '../services/api'

const PID = 'p-1'
const DRAFT = [
  { index: 1, title: '第 1 集 · 启程', screenplay: '第一集正文' },
  { index: 2, title: '第 2 集 · 遇险', screenplay: '第二集正文' },
]

describe('AdaptationPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('未改编时点「开始改编」调 start', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', adapted_draft: [], source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.start).mockResolvedValue({ job_id: 'j', adaptation_status: 'adapting' })
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
    fireEvent.click(screen.getByText('开始改编'))
    await waitFor(() => expect(adaptationApi.start).toHaveBeenCalledWith(PID))
  })

  it('draft_ready 时展示每一集,并能确认建集', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'draft_ready', adapted_draft: DRAFT, source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.commit).mockResolvedValue({
      episodes: [{}, {}], adaptation_status: 'committed',
    } as any)
    const onCommitted = vi.fn()
    render(<AdaptationPanel projectId={PID} onCommitted={onCommitted} />)
    await waitFor(() => expect(screen.getByText('第 1 集')).toBeInTheDocument())
    expect(screen.getByDisplayValue('第一集正文')).toBeInTheDocument()
    fireEvent.click(screen.getByText('确认,建出 2 集'))
    await waitFor(() => expect(adaptationApi.commit).toHaveBeenCalledWith(PID))
    await waitFor(() => expect(onCommitted).toHaveBeenCalled())
  })

  it('编辑某集正文后保存,提交的是改后的草稿', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'draft_ready', adapted_draft: DRAFT, source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.saveDraft).mockResolvedValue({
      adaptation_status: 'draft_ready', adapted_draft: DRAFT, source_text: '小说正文',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => screen.getByDisplayValue('第一集正文'))
    fireEvent.change(screen.getByDisplayValue('第一集正文'), { target: { value: '改过的正文' } })
    fireEvent.click(screen.getByText('保存分集草稿'))
    await waitFor(() => expect(adaptationApi.saveDraft).toHaveBeenCalledWith(
      PID, [expect.objectContaining({ index: 1, screenplay: '改过的正文' }),
            expect.objectContaining({ index: 2 })]))
  })

  it('非小说作品(无 source_text)不渲染本面板', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', adapted_draft: [], source_text: '',
    } as any)
    const { container } = render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(adaptationApi.get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  // 回归网:PUT /adaptation/draft 必须回与 GET 同形状(含 source_text)。
  // 后端若哪天少返字段,保存后 state.source_text 变空 → 面板整个消失(用户以为草稿没了)。
  // 断言"保存成功后分集仍在 DOM"能把这类回归拦住。
  it('保存草稿后面板仍在(PUT 返回缺字段会让面板消失)', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'draft_ready', adapted_draft: DRAFT, source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.saveDraft).mockResolvedValue({
      adaptation_status: 'draft_ready', adapted_draft: DRAFT, source_text: '小说正文',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('第 1 集')).toBeInTheDocument())
    fireEvent.click(screen.getByText('保存分集草稿'))
    await waitFor(() => expect(adaptationApi.saveDraft).toHaveBeenCalled())
    expect(screen.getByText('第 1 集')).toBeInTheDocument()
    expect(screen.getByDisplayValue('第一集正文')).toBeInTheDocument()
  })

  // 加载失败 ≠ 非小说作品:前者必须有提示与重试入口,不能与"不渲染"混为一谈。
  it('首屏加载失败时给出错误提示与重试入口,重试成功后正常渲染', async () => {
    vi.mocked(adaptationApi.get).mockRejectedValueOnce(new Error('boom'))
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('改编信息加载失败,请检查网络或稍后重试')).toBeInTheDocument())

    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', adapted_draft: [], source_text: '小说正文',
    } as any)
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
  })

  it('failed 态给出重新改编入口', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'failed', adapted_draft: [], source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.start).mockResolvedValue({ job_id: 'j', adaptation_status: 'adapting' })
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('重新改编')).toBeInTheDocument())
    fireEvent.click(screen.getByText('重新改编'))
    await waitFor(() => expect(adaptationApi.start).toHaveBeenCalledWith(PID))
  })
})
