import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import './mocks'

vi.mock('../services/api', () => ({
  adaptationApi: { start: vi.fn(), get: vi.fn(), commit: vi.fn(), confirmCast: vi.fn() },
  projectsApi: { update: vi.fn() },
  storyTextApi: { revise: vi.fn(), parseAttachment: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }))

import AdaptationPanel from '../components/AdaptationPanel'
import { adaptationApi, projectsApi } from '../services/api'

const PID = 'p-1'
const SCRIPTS = [
  { id: 'sc1', title: '第 1 集 · 启程', genre: 'drama', content: '第一集正文' },
  { id: 'sc2', title: '第 2 集 · 遇险', genre: 'drama', content: '第二集正文' },
]

describe('AdaptationPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('小说正文可见且未改编时可改 —— 它是这部作品所有产出的源头', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '一段小说',
    } as any)
    vi.mocked(projectsApi.update).mockResolvedValue({} as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('一段小说')).toBeInTheDocument())
    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(screen.getByPlaceholderText(/粘贴内容/), { target: { value: '改过的小说' } })
    fireEvent.click(screen.getAllByText('保存')[0])
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledWith(
      PID, { source_text: '改过的小说' }))
  })

  it('改编开跑后小说正文冻结 —— 切出的剧本不会随之更新', async () => {
    // 后端同样守着(409)。前端也要挡:让用户点了才发现失败是更差的体验,
    // 且他会以为是系统出错而不是这条规则。
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', scripts: SCRIPTS, source_text: '一段小说',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('一段小说')).toBeInTheDocument())
    expect(screen.queryByText('编辑')).not.toBeInTheDocument()
    expect(screen.getByText('已开始改编，如需修改请先重新改编')).toBeInTheDocument()
  })

  it('未改编时点「开始改编」调 start', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.start).mockResolvedValue({ job_id: 'j', adaptation_status: 'adapting' })
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
    fireEvent.click(screen.getByText('开始改编'))
    await waitFor(() => expect(adaptationApi.start).toHaveBeenCalledWith(PID))
  })

  it('done 时展示切出的剧本,并能建集', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', scripts: SCRIPTS, source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.commit).mockResolvedValue({
      episodes: [{}, {}], adaptation_status: 'done',
    } as any)
    const onCommitted = vi.fn()
    render(<AdaptationPanel projectId={PID} onCommitted={onCommitted} />)
    await waitFor(() => expect(screen.getByText('第 1 集 · 启程')).toBeInTheDocument())
    expect(screen.getByText('第 2 集 · 遇险')).toBeInTheDocument()
    fireEvent.click(screen.getByText('建出 2 集'))
    await waitFor(() => expect(adaptationApi.commit).toHaveBeenCalledWith(PID))
    await waitFor(() => expect(onCommitted).toHaveBeenCalled())
  })

  it('面板不提供正文编辑器 —— 内容的家在故事页,改正文去那里', async () => {
    // 面板内再放一套编辑器就与故事/方案详情页重复表达同一件事(两处各存一份的老毛病)。
    // 这条删掉就会放走"草稿编辑又回到面板里"的回归。
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', scripts: SCRIPTS, source_text: '小说正文',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('第 1 集 · 启程')).toBeInTheDocument())
    expect(screen.queryByDisplayValue('第一集正文')).not.toBeInTheDocument()
    expect(screen.queryByText('保存分集草稿')).not.toBeInTheDocument()
  })

  // 切分产出的是「片段原文 + 它的方案」两条。跳片段页能同时看到原文与它已有的方案;
  // 跳方案页只看得到其中一个,而用户在这一步要确认的正是「这段切得对不对」。
  it('点「查看 / 编辑」跳到片段原文,不是方案', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', source_text: '小说正文',
      scripts: [{ ...SCRIPTS[0], story_id: 'st1' }],
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => screen.getByText('第 1 集 · 启程'))
    fireEvent.click(screen.getAllByText('查看 / 编辑')[0])
    expect(mockNavigate).toHaveBeenCalledWith('/stories/st1')
  })

  // 未迁移的旧行没有片段归属。此时退回方案页 —— 总比按钮点了没反应强。
  it('方案没有片段归属时退回方案详情页', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', scripts: SCRIPTS, source_text: '小说正文',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => screen.getByText('第 1 集 · 启程'))
    fireEvent.click(screen.getAllByText('查看 / 编辑')[0])
    expect(mockNavigate).toHaveBeenCalledWith('/scripts/sc1')
  })

  it('没有剧本时不给建集入口 —— 建 0 集是无意义操作', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', scripts: [], source_text: '小说正文',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('还没有剧本')).toBeInTheDocument())
    expect(screen.getByText('建出 0 集')).toBeDisabled()
  })

  it('非小说作品(无 source_text)不渲染本面板', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '',
    } as any)
    const { container } = render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(adaptationApi.get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  // 加载失败 ≠ 非小说作品:前者必须有提示与重试入口,不能与"不渲染"混为一谈。
  it('首屏加载失败时给出错误提示与重试入口,重试成功后正常渲染', async () => {
    vi.mocked(adaptationApi.get).mockRejectedValueOnce(new Error('boom'))
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('改编信息加载失败,请检查网络或稍后重试')).toBeInTheDocument())

    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '小说正文',
    } as any)
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
  })

  it('cast_review 时展示角色确认面板 —— 切分前必须先定身份', async () => {
    // 没有这个卡点,各段会自行发明称呼(同一角色跨集变成不同名字),
    // 下游按 character_id 取造型必然落空。这条删掉就放走那个回归。
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'cast_review', scripts: [], source_text: '小说正文',
      cast_pending: [{ name: '李默', appearance: '二十多岁男性', suggestions: [] }],
    } as any)
    vi.mocked(adaptationApi.confirmCast).mockResolvedValue({
      adaptation_status: 'adapting', cast: { 李默: 'c1' }, job_id: 'j',
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('李默')).toBeInTheDocument())
    expect(screen.getByText('二十多岁男性')).toBeInTheDocument()
    fireEvent.click(screen.getByText('确认，继续写剧本'))
    await waitFor(() => expect(adaptationApi.confirmCast).toHaveBeenCalledWith(
      PID, { 李默: { action: 'create' } }))
  })

  it('failed 态给出重新改编入口', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'failed', scripts: [], source_text: '小说正文',
    } as any)
    vi.mocked(adaptationApi.start).mockResolvedValue({ job_id: 'j', adaptation_status: 'adapting' })
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('重新改编')).toBeInTheDocument())
    fireEvent.click(screen.getByText('重新改编'))
    await waitFor(() => expect(adaptationApi.start).toHaveBeenCalledWith(PID))
  })

  // 切片标题是 LLM 起的「第 N 集 · xxx」,读起来就是剧集。不标一下,用户会以为
  // 剧集已经存在(实测反馈:"这里已经有剧集了,前端仍然展示无剧集")。
  it('done 态每条剧本带「剧本」标签,与剧集区分开', async () => {
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', source_text: '小说正文',
      scripts: [{ id: 'sc1', title: '第 1 集 · 启程', genre: 'drama', content: '正文' }],
    } as any)
    render(<AdaptationPanel projectId={PID} onCommitted={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('第 1 集 · 启程')).toBeInTheDocument())
    expect(screen.getByText('剧本')).toBeInTheDocument()
  })
})
