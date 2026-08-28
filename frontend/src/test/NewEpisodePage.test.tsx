import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  episodesApi: { create: vi.fn() },
  scriptsApi: { list: vi.fn() },
  projectsApi: { get: vi.fn() },
  configApi: {
    listModels: vi.fn().mockResolvedValue({
      models: [{ value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'DeepSeek' }],
      default: 'deepseek-v4-pro',
    }),
    listVideoModels: vi.fn().mockResolvedValue({
      models: [
        { value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动', resolutions: ['768P', '1080p'], default_resolution: '1080p' },
      ],
      default: 'seedance',
    }),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import NewEpisodePage from '../pages/NewEpisodePage'
import { episodesApi, scriptsApi, configApi, projectsApi } from '../services/api'

const PROJECT_ID = 'proj-1'
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/episodes/new`]}>
      <Routes>
        <Route path="/projects/:id/episodes/new" element={<NewEpisodePage />} />
      </Routes>
    </MemoryRouter>
  )

const completedScript = {
  id: 'sc-1', project_id: PROJECT_ID, title: '深夜来客', genre: 'drama',
  content: '# 深夜来客\n\n第一场...', status: 'completed',
  // story_analysis.genre 特意与顶层 genre 取不同值,防止预览误读 s.genre 时测试仍误判通过
  story_analysis: {
    title: '深夜来客', genre: 'thriller', setting: '城市公寓', tone: 'tense',
    themes: ['信任', '孤独'], plot_summary: '一个深夜来客打破了主角的平静生活。',
    scene_count_estimate: 5, characters: [],
  },
}

describe('NewEpisodePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(projectsApi.get).mockResolvedValue({ id: PROJECT_ID, title: '测试作品' } as any)
    vi.mocked(scriptsApi.list).mockResolvedValue([completedScript as any])
  })

  it('从剧本库选:用选中的 completed 剧本建集,跳视频详情', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({
      id: 'ep-new', project_id: PROJECT_ID, episode_number: 1, title: '第1集',
      script_id: 'sc-1', status: 'created', llm_model: 'deepseek-v4-pro',
      video_provider: 'seedance', video_model: '', resolution: '1080p',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [pid, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(pid).toBe(PROJECT_ID)
    expect(data.title).toBe('第1集')
    expect(data.script_id).toBe('sc-1')
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/episodes/ep-new'))
  })

  it('剧本列表不按作品过滤,散稿也能选到并标注归属', async () => {
    // 剧本库是全局的:散稿(project_id=null)不属于任何作品。若按 projectId 过滤,
    // 它对每个作品的「新建一集」都不可见 —— 这条就是那个回归的拦截。
    vi.mocked(scriptsApi.list).mockResolvedValue([
      { ...completedScript, id: 'loose', title: '散稿剧本', project_title: null },
      { ...completedScript, id: 'owned', title: '归属剧本', project_title: '作品甲' },
    ] as any)
    renderPage()
    await waitFor(() => expect(scriptsApi.list).toHaveBeenCalled())
    expect(vi.mocked(scriptsApi.list).mock.calls[0][0]).toBeUndefined()
    await waitFor(() => expect(screen.getByText('散稿剧本（未归属）')).toBeInTheDocument())
    expect(screen.getByText('归属剧本（作品甲）')).toBeInTheDocument()
  })

  it('无剧本时,从剧本库选显示空态、不建集', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => expect(screen.getByText(/剧本库还没有剧本/)).toBeInTheDocument())
    expect(screen.queryByText('创建视频')).not.toBeInTheDocument()
  })

  it('输入故事:直接建集(带 raw_input),跳剧集详情', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({
      id: 'ep-2', project_id: PROJECT_ID, episode_number: 1, title: '新集',
      script_id: '', status: 'created', llm_model: 'deepseek-v4-pro',
      video_provider: 'seedance', video_model: '', resolution: '1080p',
    } as any)
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.change(screen.getByPlaceholderText('给这一集起个名字'), { target: { value: '新集' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴故事/), { target: { value: '这是一个故事' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [pid, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(pid).toBe(PROJECT_ID)
    expect(data.title).toBe('新集')
    expect(data.raw_input).toBe('这是一个故事')
    // 从故事开始不带 script_id(否则会被图当成复用剧本、跳过故事分析)
    expect(data.script_id).toBeUndefined()
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/episodes/ep-2'))
  })

  it('输入故事 tab 提交后端默认 llm', async () => {
    vi.mocked(configApi.listModels).mockResolvedValue({
      models: [
        { value: 'a', label: 'A', provider: 'P' },
        { value: 'b', label: 'B', provider: 'P', is_default: true },
      ],
      default: 'b',
    })
    vi.mocked(configApi.listVideoModels).mockResolvedValue({ models: [], default: null })
    vi.mocked(scriptsApi.list).mockResolvedValue([])
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-x' } as any)
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.change(screen.getByPlaceholderText('给这一集起个名字'), { target: { value: 'My' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴故事/), { target: { value: 'text body' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledWith(
      PROJECT_ID, expect.objectContaining({ llm_model: 'b' })
    ))
  })

  // ── 源剧本预览 ────────────────────────────────────────────────────────────

  it('选中剧本后点击预览,SideSheet 展示该剧本的类型/基调/主题/正文', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.click(screen.getByText('预览'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    // 剧本标题同时是 script_id <select> 的 option 文本,断言须限定在 SideSheet 内
    const sheet = within(screen.getByTestId('side-sheet'))
    expect(sheet.getByText('深夜来客')).toBeInTheDocument()
    expect(sheet.getByText('thriller')).toBeInTheDocument()
    expect(sheet.getByText('tense')).toBeInTheDocument()
    expect(sheet.getByText('信任、孤独')).toBeInTheDocument()
    expect(sheet.getByText(/第一场/)).toBeInTheDocument()
  })

  it('关闭 SideSheet 后表单已填字段不变', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({
      id: 'ep-new', project_id: PROJECT_ID, episode_number: 1, title: '第1集标题',
      script_id: 'sc-1', status: 'created', llm_model: 'deepseek-v4-pro',
      video_provider: 'seedance', video_model: '', resolution: '1080p',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/第 1 集/), { target: { value: '第1集标题' } })
    fireEvent.click(screen.getByText('预览'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('关闭预览'))
    await waitFor(() => expect(screen.queryByTestId('side-sheet')).not.toBeInTheDocument())
    expect(screen.getByPlaceholderText(/第 1 集/)).toHaveValue('第1集标题')
    // DOM 值断言在非受控 mock Form.Input 下可能出现假阳性(store 已清空但 DOM 未回写也会通过)——
    // 用真实提交结果交叉验证 store 里的字段确实还在:store 若被清空,required 校验会拦截提交,
    // episodesApi.create 就不会被调用。
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.title).toBe('第1集标题')
  })

  it('切换到另一条剧本后再次预览,展示内容更新为新选中记录', async () => {
    const secondScript = {
      id: 'sc-2', project_id: PROJECT_ID, title: '清晨的信', genre: 'romance',
      content: '# 清晨的信\n\n开场...', status: 'completed',
      story_analysis: {
        title: '清晨的信', genre: 'slice-of-life', setting: '乡村小镇', tone: 'warm',
        themes: ['爱情'], plot_summary: '一封信改变了两个人的命运。',
        scene_count_estimate: 3, characters: [],
      },
    }
    vi.mocked(scriptsApi.list).mockResolvedValue([completedScript, secondScript] as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.click(screen.getByText('预览'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    expect(within(screen.getByTestId('side-sheet')).getByText('深夜来客')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('关闭预览'))
    await waitFor(() => expect(screen.queryByTestId('side-sheet')).not.toBeInTheDocument())

    // Semi Select mock 是原生 <select>,按 field="script_id" 的 value 切换
    const scriptSelect = screen.getAllByRole('combobox').find(
      el => (el as HTMLSelectElement).querySelector('option[value="sc-2"]')
    ) as HTMLSelectElement
    fireEvent.change(scriptSelect, { target: { value: 'sc-2' } })
    fireEvent.click(screen.getByText('预览'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    const sheet = within(screen.getByTestId('side-sheet'))
    expect(sheet.getByText('清晨的信')).toBeInTheDocument()
    expect(sheet.getByText('slice-of-life')).toBeInTheDocument()
    expect(sheet.queryByText('深夜来客')).not.toBeInTheDocument()
  })
})
