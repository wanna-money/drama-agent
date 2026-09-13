import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  episodesApi: { create: vi.fn() },
  scriptsApi: { list: vi.fn() },
  storiesApi: { analyze: vi.fn(), create: vi.fn(), list: vi.fn() },
  projectsApi: { get: vi.fn() },
  clipsApi: { create: vi.fn(), list: vi.fn(), get: vi.fn(), delete: vi.fn() },
  filesApi: { uploadImage: vi.fn(), copyFromAsset: vi.fn(), listImages: vi.fn(), uploadVideo: vi.fn() },
  assetsApi: { list: vi.fn() },
  configApi: {
    listModels: vi.fn().mockResolvedValue({
      models: [{ value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'DeepSeek' }],
      default: 'deepseek-v4-pro',
    }),
    listVideoModels: vi.fn().mockResolvedValue({
      models: [
        { value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动',
          provider_id: 'seedance', model_id: 'seedance',
          resolutions: ['768P', '1080p'], default_resolution: '1080p',
          aspect_ratios: ['16:9', '9:16', '1:1'], default_aspect_ratio: '9:16' },
      ],
      default: 'seedance',
    }),
    storageStatus: vi.fn().mockResolvedValue({ available: true }),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import NewCreationPage from '../pages/NewCreationPage'
import {
  episodesApi, scriptsApi, storiesApi, configApi, projectsApi,
  clipsApi, assetsApi, filesApi,
} from '../services/api'

const VIDEO_MODELS = {
  models: [
    { value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动',
      provider_id: 'seedance', model_id: 'seedance',
      resolutions: ['768P', '1080p'], default_resolution: '1080p',
      aspect_ratios: ['16:9', '9:16', '1:1'], default_aspect_ratio: '9:16' },
  ],
  default: 'seedance',
}

const PROJECT_ID = 'proj-1'

const story = (over: any = {}) => ({
  id: 'st-1', project_id: PROJECT_ID, title: '深夜来客', genre: 'drama',
  content: '一个深夜的故事', project_title: '测试作品',
  script_count: 1, segment_count: 0, ...over,
})

/** 两个 tab 的作用域。mock 同时渲染两个 pane(免得测试先点 tab),
 *  而两边都有「拍哪段原文」字段 —— 不限定范围的查询会命中两个。 */
const storyTab = () => within(screen.getByTestId('tabpane-story'))
const reuseTab = () => within(screen.getByTestId('tabpane-pick'))

/** 「拍一个已有方案」tab:选故事 → 触发拉方案 → 选方案。 */
const pickStoryThenScript = async (storyId: string, scriptId: string) => {
  fireEvent.change(reuseTab().getByLabelText('拍哪段原文'), { target: { value: storyId } })
  await waitFor(() => expect(scriptsApi.list).toHaveBeenCalledWith({ storyId }))
  await waitFor(() => expect(
    reuseTab().getByLabelText('用哪一版改编')).not.toBeDisabled())
  fireEvent.change(reuseTab().getByLabelText('用哪一版改编'), { target: { value: scriptId } })
}
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/create`]}>
      <Routes>
        <Route path="/projects/:id/create" element={<NewCreationPage />} />
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

describe('NewCreationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(projectsApi.get).mockResolvedValue({ id: PROJECT_ID, title: '测试作品' } as any)
    vi.mocked(storiesApi.list).mockResolvedValue([story() as any])
    vi.mocked(scriptsApi.list).mockResolvedValue([completedScript as any])
    vi.mocked(configApi.listVideoModels).mockResolvedValue(VIDEO_MODELS as any)
    vi.mocked(storiesApi.analyze).mockResolvedValue({
      story_analysis: { title: '新集', characters: [] }, cast: {}, pending: [],
    } as any)
    vi.mocked(storiesApi.create).mockResolvedValue(
      { id: 'st-new', title: '新集', genre: 'drama', content: '这是一个故事',
        script_id: null } as any)
    vi.mocked(clipsApi.list).mockResolvedValue([])
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(filesApi.listImages).mockResolvedValue([])
  })

  it('复用已有方案:选原文 → 选方案 → 建集,跳视频详情', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({
      id: 'ep-new', project_id: PROJECT_ID, episode_number: 1, title: '第1集',
      script_id: 'sc-1', status: 'created', llm_model: 'deepseek-v4-pro',
      video_provider: 'seedance', video_model: '', resolution: '1080p',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    await pickStoryThenScript('st-1', 'sc-1')
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [pid, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(pid).toBe(PROJECT_ID)
    expect(data.title).toBe('第1集')
    // 只传 script_id:原文由后端经该方案的 story_id 解析(前端不搬运两个 id)
    expect(data.script_id).toBe('sc-1')
    expect(data.story_id).toBeUndefined()
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/episodes/ep-new'))
  })

  it('故事列表不按作品过滤,散稿也能选到并标出归属', async () => {
    // 故事是全局可复用的:散稿(project_id=null)不属于任何作品。若按 projectId 过滤,
    // 它对每个作品的「新建一集」都不可见 —— 这条就是那个回归的拦截。
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'loose', title: '散稿故事', project_id: null, project_title: null }),
      story({ id: 'owned', title: '归属故事', project_id: 'p-a', project_title: '作品甲' }),
    ] as any)
    renderPage()
    await waitFor(() => expect(storiesApi.list).toHaveBeenCalled())
    // 只列顶层原文:片段是父原文的内部结构,平铺会把一本小说的 N 段与别的故事混在一起
    expect(vi.mocked(storiesApi.list).mock.calls[0][0]).toMatchObject({ topLevelOnly: true })
    await waitFor(() => expect(reuseTab().getByText(/散稿故事/)).toBeInTheDocument())
    // 归属标在选项里(而非靠分组),散稿显示「未归属作品」
    expect(reuseTab().getByText(/散稿故事 · 未归属作品/)).toBeInTheDocument()
    expect(reuseTab().getByText(/归属故事 · 作品甲/)).toBeInTheDocument()
  })

  // 同名故事很常见(「第 1 集」这类标题),而"有没有方案"决定选它之后第二个下拉是不是空的。
  // 不提前标出来,用户要选完才发现无从继续。
  it('故事选项标出已有几个方案', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'a', title: '有方案的', script_count: 3 }),
      story({ id: 'b', title: '没方案的', script_count: 0 }),
    ] as any)
    renderPage()
    // 「拍一个已有方案」tab 只列有方案的 —— 没方案的在这里选出来也走不通
    await waitFor(() => expect(
      reuseTab().getByText(/有方案的 · 测试作品 · 3 个方案/)).toBeInTheDocument())
    expect(reuseTab().queryByText(/没方案的/)).not.toBeInTheDocument()
    // 但它在「拍一段故事」tab 里必须可选(那条路不需要方案)
    expect(storyTab().getByText(/没方案的 · 测试作品 · 暂无方案/)).toBeInTheDocument()
  })

  // 方案只按需拉:一次性取回所有故事的方案既拿不到正文摘要(响应过大),
  // 也无从按故事分组展示。
  it('未选原文前不拉方案,且方案下拉禁用', async () => {
    renderPage()
    await waitFor(() => expect(reuseTab().getByLabelText('拍哪段原文')).toBeInTheDocument())
    expect(scriptsApi.list).not.toHaveBeenCalled()
    expect(reuseTab().getByLabelText('用哪一版改编')).toBeDisabled()
  })

  // 方案之间的差别全在正文里 —— 只给标题的话「悬疑版」「温情版」在下拉里长得一模一样。
  it('方案选项带正文摘要', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([
      { ...completedScript, id: 'sc-a', title: '悬疑版', content: '雨夜，门铃响了三声。' },
      { ...completedScript, id: 'sc-b', title: '温情版', content: '午后，她端来一杯热茶。' },
    ] as any)
    renderPage()
    await waitFor(() => expect(reuseTab().getByLabelText('拍哪段原文')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByLabelText('拍哪段原文'), { target: { value: 'st-1' } })
    await waitFor(() => expect(
      reuseTab().getByText(/悬疑版 — 雨夜，门铃响了三声。/)).toBeInTheDocument())
    expect(reuseTab().getByText(/温情版 — 午后，她端来一杯热茶。/)).toBeInTheDocument()
  })

  // 换故事必须清掉已选方案:留着会提交上一段原文的方案,而两个字段看起来一致、校验也过,
  // 错到成片才发现。
  it('换原文后清掉已选方案', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'st-1' }), story({ id: 'st-2', title: '另一段' }),
    ] as any)
    renderPage()
    await waitFor(() => expect(reuseTab().getByLabelText('拍哪段原文')).toBeInTheDocument())
    await pickStoryThenScript('st-1', 'sc-1')
    expect((reuseTab().getByLabelText('用哪一版改编') as HTMLSelectElement).value).toBe('sc-1')
    fireEvent.change(reuseTab().getByLabelText('拍哪段原文'), { target: { value: 'st-2' } })
    await waitFor(() => expect(
      (reuseTab().getByLabelText('用哪一版改编') as HTMLSelectElement).value).toBe(''))
  })

  // 本轮修的缺陷:有故事、但它还没有方案时,用户在「拍一个已有方案」tab 里选到它
  // 就走进死路(第二个下拉永远是空的),而当时的引导竟是"去另一个 tab 重新粘一遍原文"。
  // 现在无方案的故事不进这个 tab,而在「拍一段故事」tab 里可直接选它开拍。
  it('无方案的故事不进「已有方案」tab,但在「拍一段故事」tab 里可直接开拍', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([
      story({ id: 'st-bare', title: '还没改编的', script_count: 0 }),
    ] as any)
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-s' } as any)
    renderPage()
    await waitFor(() => expect(
      reuseTab().getByText(/还没有可复用的改编方案/)).toBeInTheDocument())
    fireEvent.change(storyTab().getByPlaceholderText('给这一集起个名字'),
      { target: { value: '第1集' } })
    fireEvent.change(storyTab().getByLabelText('拍哪段原文'), { target: { value: 'st-bare' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.story_id).toBe('st-bare')
    expect(data.script_id).toBeUndefined()
    // 选了已有原文就不走"分析新文本"那条路 —— 它的角色在入库时已确认过,不重复问
    expect(storiesApi.analyze).not.toHaveBeenCalled()
    expect(storiesApi.create).not.toHaveBeenCalled()
  })

  // 选了已有故事时粘贴框要消失:两者同时有值时"到底拍哪一段"没有答案,而提交只能取一个。
  it('选了已有原文后隐藏粘贴框', async () => {
    renderPage()
    await waitFor(() => expect(
      storyTab().getByPlaceholderText(/粘贴故事/)).toBeInTheDocument())
    fireEvent.change(storyTab().getByLabelText('拍哪段原文'), { target: { value: 'st-1' } })
    await waitFor(() => expect(
      storyTab().queryByPlaceholderText(/粘贴故事/)).not.toBeInTheDocument())
  })

  // 没有任何带方案的故事时,「拍一个已有方案」tab 无从下手(方案总挂在故事下)。
  it('没有可复用方案时该 tab 显示空态、不给建集入口', async () => {
    vi.mocked(storiesApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => expect(
      reuseTab().getByText(/还没有可复用的改编方案/)).toBeInTheDocument())
    expect(screen.queryByText('创建视频')).not.toBeInTheDocument()
  })

  // 一段故事必须先落成**原文**、再建拍它的集:原文是内容的源头。
  // 若退回"故事直接挂在集上",同一段原文无法复用(日后改编不出别的方案),
  // 故事库对这条入口永远是空的。
  it('输入故事:先把故事落成原文,再建拍它的集', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({
      id: 'ep-2', project_id: PROJECT_ID, episode_number: 1, title: '新集',
      story_id: 'st-new', script_id: null, status: 'created', llm_model: 'deepseek-v4-pro',
      video_provider: 'seedance', video_model: '', resolution: '1080p',
    } as any)
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.change(screen.getByPlaceholderText('给这一集起个名字'), { target: { value: '新集' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴故事/), { target: { value: '这是一个故事' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(storiesApi.create).toHaveBeenCalledOnce())
    expect(storiesApi.analyze).toHaveBeenCalledWith(PROJECT_ID, '这是一个故事', 'deepseek-v4-pro')
    const draft = vi.mocked(storiesApi.create).mock.calls[0][0]
    expect(draft).toMatchObject({
      project_id: PROJECT_ID, title: '新集', content: '这是一个故事',
    })
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [pid, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(pid).toBe(PROJECT_ID)
    expect(data.title).toBe('新集')
    // 集拍这段原文(story_id 是锚点);此时还没有改编方案,故不带 script_id ——
    // 提前造一个空方案会让剧本库长满没有正文的行
    expect(data.story_id).toBe('st-new')
    expect(data.script_id).toBeUndefined()
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/episodes/ep-2'))
  })

  // 名单外角色必须在落原文**之前**定身份:原文带着 cast 落库,下游才按 character_id
  // 取得到造型与外貌(阵容的权威在 Story)。这条删掉就放走"未确认就落库、
  // 角色形象逐镜漂移"的回归。
  it('输入故事:有待确认角色时先停在确认面板,确认后才落原文建集', async () => {
    vi.mocked(configApi.listVideoModels).mockResolvedValue(VIDEO_MODELS as any)
    vi.mocked(storiesApi.analyze).mockResolvedValue({
      story_analysis: { title: '新集', characters: [] }, cast: {},
      pending: [{ name: '林夏', appearance: '长发白裙', suggestions: [] }],
    } as any)
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-3' } as any)
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.change(screen.getByPlaceholderText('给这一集起个名字'), { target: { value: '新集' } })
    fireEvent.change(screen.getByPlaceholderText(/粘贴故事/), { target: { value: '这是一个故事' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(screen.getByText('林夏')).toBeInTheDocument())
    expect(storiesApi.create).not.toHaveBeenCalled()
    expect(episodesApi.create).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('确认，继续写剧本'))
    await waitFor(() => expect(storiesApi.create).toHaveBeenCalledOnce())
    expect(vi.mocked(storiesApi.create).mock.calls[0][0].cast)
      .toEqual({ 林夏: { action: 'create' } })
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
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
    // 分析用的也必须是这个默认模型:两处取不同模型会让分析与建集口径分叉
    expect(storiesApi.analyze).toHaveBeenCalledWith(PROJECT_ID, 'text body', 'b')
  })

  // ── 源剧本预览 ────────────────────────────────────────────────────────────

  it('选中方案后点击预览,SideSheet 展示它的来源/类型/基调/主题/正文', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    await pickStoryThenScript('st-1', 'sc-1')
    fireEvent.click(screen.getByText('预览这个方案'))
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
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集标题' } })
    await pickStoryThenScript('st-1', 'sc-1')
    fireEvent.click(screen.getByText('预览这个方案'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('关闭预览'))
    await waitFor(() => expect(screen.queryByTestId('side-sheet')).not.toBeInTheDocument())
    expect(reuseTab().getByPlaceholderText(/第 1 集/)).toHaveValue('第1集标题')
    // DOM 值断言在非受控 mock Form.Input 下可能出现假阳性(store 已清空但 DOM 未回写也会通过)——
    // 用真实提交结果交叉验证 store 里的字段确实还在:store 若被清空,required 校验会拦截提交,
    // episodesApi.create 就不会被调用。
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.title).toBe('第1集标题')
  })

  it('切换到另一个方案后再次预览,展示内容更新为新选中记录', async () => {
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
    await pickStoryThenScript('st-1', 'sc-1')
    fireEvent.click(screen.getByText('预览这个方案'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    expect(within(screen.getByTestId('side-sheet')).getByText('深夜来客')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('关闭预览'))
    await waitFor(() => expect(screen.queryByTestId('side-sheet')).not.toBeInTheDocument())

    fireEvent.change(reuseTab().getByLabelText('用哪一版改编'), { target: { value: 'sc-2' } })
    fireEvent.click(screen.getByText('预览这个方案'))
    await waitFor(() => expect(screen.getByTestId('side-sheet')).toBeInTheDocument())
    const sheet = within(screen.getByTestId('side-sheet'))
    expect(sheet.getByText('清晨的信')).toBeInTheDocument()
    expect(sheet.getByText('slice-of-life')).toBeInTheDocument()
    expect(sheet.queryByText('深夜来客')).not.toBeInTheDocument()
  })

  // ── 画面比例 ──────────────────────────────────────────────────────────────

  // 短剧多为竖屏。此前比例写死在后端 video_generator 里,所有集只能出 16:9;
  // 选项与默认值都必须来自后端下发(前端自带一份写死清单迟早与后端分叉)。
  it('比例默认取后端下发的 default_aspect_ratio,并随建集提交', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-r' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    await pickStoryThenScript('st-1', 'sc-1')
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.aspect_ratio).toBe('9:16')
  })

  it('比例下拉的选项来自所选模型的 aspect_ratios', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    const sel = screen.getAllByRole('combobox').find(
      el => (el as HTMLSelectElement).querySelector('option[value="9:16"]')
    ) as HTMLSelectElement
    expect(sel).toBeTruthy()
    const opts = [...sel.querySelectorAll('option')].map(o => o.getAttribute('value'))
    expect(opts).toEqual(['16:9', '9:16', '1:1'])
  })

  // 自定义 provider 常见:用户只填了模型名,能力清单是空数组。
  // 空数组不是 nullish,`?? 兜底` 不会触发 → 下拉渲染成「暂无数据」,
  // 值显示着 768P 却一个选项都选不了。这条删掉就放走那个回归。
  it('模型未声明能力(空数组)时,分辨率与比例仍有可选项', async () => {
    vi.mocked(configApi.listVideoModels).mockResolvedValue({
      models: [{ value: 'custom', label: '自定义模型', provider: '云',
                 resolutions: [], aspect_ratios: [] }],
      default: 'custom',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    const optsOf = (v: string) => {
      const sel = screen.getAllByRole('combobox').find(
        el => (el as HTMLSelectElement).querySelector(`option[value="${v}"]`)
      ) as HTMLSelectElement | undefined
      return sel ? [...sel.querySelectorAll('option')].map(o => o.getAttribute('value')) : []
    }
    expect(optsOf('768P').length).toBeGreaterThan(0)
    expect(optsOf('9:16').length).toBeGreaterThan(0)
  })

  // 未配凭证的模型选中后要等整条流水线跑完全部失败,才看到一条与
  // "没配 key" 无关的 "Connection error."。禁用该选项,而不是等报错才发现。
  it('未配凭证的视频模型在下拉里禁用', async () => {
    vi.mocked(configApi.listVideoModels).mockResolvedValue({
      models: [
        { value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动',
          provider_id: 'seedance', model_id: 'seedance',
          resolutions: ['768P', '1080p'], default_resolution: '1080p',
          aspect_ratios: ['16:9', '9:16', '1:1'], default_aspect_ratio: '9:16',
          credential_configured: false },
        { value: 'minimax', label: 'MiniMax H3', provider: 'MiniMax',
          provider_id: 'minimax', model_id: 'minimax',
          resolutions: ['768P'], default_resolution: '768P',
          aspect_ratios: ['9:16'], default_aspect_ratio: '9:16',
          credential_configured: true },
      ],
      default: 'minimax',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    const sel = screen.getAllByRole('combobox').find(
      el => (el as HTMLSelectElement).querySelector('option[value="seedance"]')
    ) as HTMLSelectElement
    const opt = sel.querySelector('option[value="seedance"]') as HTMLOptionElement
    expect(opt.disabled).toBe(true)
    expect(opt.textContent).toContain('未配置凭证')
    const okOpt = sel.querySelector('option[value="minimax"]') as HTMLOptionElement
    expect(okOpt.disabled).toBe(false)
  })

  // 级联的值是**整条路径**(['作品','剧本']),而建集接口要的是单个 script_id。
  // 不取末位就会把路径数组原样发给后端 → 422。这条删掉就放走那个回归。
  it('提交的是第二个下拉选中的那个方案', async () => {
    vi.mocked(scriptsApi.list).mockResolvedValue([
      { ...completedScript, id: 'sc-1' },
      { ...completedScript, id: 'sc-2', title: '第二版' },
    ] as any)
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-c' } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    await pickStoryThenScript('st-1', 'sc-2')
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.script_id).toBe('sc-2')
  })

  // 两个字段都必填:只选原文不构成一次有效选择(这条入口拍的是**某个方案**,
  // 从原文起跑要走「输入故事」页)。
  it('只选了原文、没选方案时不提交', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    fireEvent.change(reuseTab().getByLabelText('拍哪段原文'), { target: { value: 'st-1' } })
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).not.toHaveBeenCalled())
  })

  it('两个都没选时不提交', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    fireEvent.change(reuseTab().getByPlaceholderText(/第 1 集/), { target: { value: '第1集' } })
    fireEvent.click(screen.getByText('创建视频'))
    await waitFor(() => expect(episodesApi.create).not.toHaveBeenCalled())
  })

  it('目标时长含 30 秒选项', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('创建视频')).toBeInTheDocument())
    const sel = screen.getAllByRole('combobox').find(
      el => (el as HTMLSelectElement).querySelector('option[value="120"]')
    ) as HTMLSelectElement
    const opts = [...sel.querySelectorAll('option')].map(o => o.getAttribute('value'))
    expect(opts).toEqual(['30', '60', '90', '120', '180'])
  })

  // ── 二选一的字段级校验 ────────────────────────────────────────────────────

  // 「点了开始制作毫无反应」是最难自查的一类失败:用户不知道是自己漏填、还是系统坏了。
  // 校验必须挂在字段上 —— 全局 toast 一闪而过、离输入框很远,而且不留痕。
  it('两个都空时不提交,并在字段上给出可读错误', async () => {
    renderPage()
    await waitFor(() => expect(
      storyTab().getByPlaceholderText(/粘贴故事/)).toBeInTheDocument())
    fireEvent.change(storyTab().getByPlaceholderText('给这一集起个名字'),
      { target: { value: '第1集' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(
      storyTab().getByText(/请选择一段已有故事，或在此粘一段新的/)).toBeInTheDocument())
    expect(storiesApi.analyze).not.toHaveBeenCalled()
    expect(episodesApi.create).not.toHaveBeenCalled()
  })

  // 选了已有故事时粘贴框是隐藏的,此时不得因为它为空而拦住提交 ——
  // 否则"复用已入库的故事"这条路会被自己的校验堵死。
  it('选了已有原文时,空粘贴框不拦提交', async () => {
    vi.mocked(episodesApi.create).mockResolvedValue({ id: 'ep-ok' } as any)
    renderPage()
    await waitFor(() => expect(storyTab().getByLabelText('拍哪段原文')).toBeInTheDocument())
    fireEvent.change(storyTab().getByPlaceholderText('给这一集起个名字'),
      { target: { value: '第1集' } })
    fireEvent.change(storyTab().getByLabelText('拍哪段原文'), { target: { value: 'st-1' } })
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(episodesApi.create).toHaveBeenCalledOnce())
    const [, data] = vi.mocked(episodesApi.create).mock.calls[0]
    expect(data.story_id).toBe('st-1')
  })

  // ── 简单模式:直接生成散片 ────────────────────────────────────────────────

  const switchToClip = () =>
    fireEvent.click(screen.getByLabelText('直接生成'))

  it('默认是完整剧集模式,渲染剧集表单', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('tabpane-story')).toBeInTheDocument())
    // 与下一条的正向断言对称:那条断"切过去就该有输入区",这条断"没切就不该有"。
    // 必须按 placeholder 找 —— 散片表单里没有任何 label,按 label 查会恒为 null,
    // 两套表单同时渲染时也照样通过。
    expect(screen.queryByPlaceholderText(/描述/)).toBeNull()
  })

  it('切到直接生成:渲染 prompt 输入区,不再渲染建集表单', async () => {
    // 两套表单同时渲染会让"选了简单模式却提交建集请求"这类错走得通
    renderPage()
    await waitFor(() => expect(screen.getByTestId('tabpane-story')).toBeInTheDocument())
    switchToClip()
    await waitFor(() => expect(screen.getByPlaceholderText(/描述/)).toBeInTheDocument())
    expect(screen.queryByTestId('tabpane-story')).toBeNull()
  })

  it('提交散片:请求体带正确拆分的 video_provider / video_model', async () => {
    // 把 model id 或 "provider/model" 填进 video_provider 会被网关拒,
    // 而报错指向权限、极难排查 —— 拆分只有一处权威(splitVideoModel)
    vi.mocked(clipsApi.create).mockResolvedValue({
      id: 'c-1', project_id: PROJECT_ID, prompt: '一只猫跳上桌子', duration: 5,
      resolution: '1080p', aspect_ratio: '9:16', video_provider: 'seedance',
      video_model: 'seedance', status: 'queued', task_id: '',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByTestId('tabpane-story')).toBeInTheDocument())
    switchToClip()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.type(screen.getByPlaceholderText(/描述/), '一只猫跳上桌子{Enter}')
    await waitFor(() => expect(clipsApi.create).toHaveBeenCalledWith(
      PROJECT_ID, expect.objectContaining({
        prompt: '一只猫跳上桌子',
        video_provider: 'seedance',   // provider_id(协议名)
        video_model: 'seedance',      // model_id
      })))
  })

  it('提示词为空时不提交', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('tabpane-story')).toBeInTheDocument())
    switchToClip()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.type(screen.getByPlaceholderText(/描述/), '{Enter}')
    expect(clipsApi.create).not.toHaveBeenCalled()
  })

  it('提交成功后不跳转,新散片出现在下方', async () => {
    // 留在页面才能接着改 prompt 再提一条;跳转会打断这个节奏
    vi.mocked(clipsApi.create).mockResolvedValue({
      id: 'c-1', project_id: PROJECT_ID, prompt: '一只猫', duration: 5,
      resolution: '1080p', aspect_ratio: '9:16', video_provider: 'seedance',
      video_model: 'seedance', status: 'queued', task_id: '',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByTestId('tabpane-story')).toBeInTheDocument())
    switchToClip()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.type(screen.getByPlaceholderText(/描述/), '一只猫{Enter}')
    await waitFor(() => expect(screen.getByText('排队中')).toBeInTheDocument())
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
