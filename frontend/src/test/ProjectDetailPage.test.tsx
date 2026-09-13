import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import React from 'react'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  episodesApi: { get: vi.fn(), update: vi.fn() },
  workflowApi: {
    start: vi.fn(), resume: vi.fn(), status: vi.fn(),
    reviseEpisode: vi.fn(), editEpisode: vi.fn(), revertEpisode: vi.fn(),
  },
  filesApi: {
    uploadImage: vi.fn(),
    copyFromAsset: vi.fn(),
    updateReferences: vi.fn(() => Promise.resolve([])),
    getReferences: vi.fn(() => Promise.resolve([])),
    exportUrl: (id: string) => `/api/episodes/${id}/export`,
    downloadUrl: (id: string, f: string) => `/api/episodes/${id}/files/${f}`,
  },
  assetsApi: { list: vi.fn(() => Promise.resolve([])), generate: vi.fn(), saveGenerated: vi.fn() },
  promptApi: { extract: vi.fn(), optimize: vi.fn() },
  storyTextApi: { revise: vi.fn() },
  configApi: { listImageModels: vi.fn(() => Promise.resolve({ models: [], default: null })) },
  artifactsApi: {
    listByShot: vi.fn(() => Promise.resolve([])),
    listActions: vi.fn(() => Promise.resolve([])),
    runAction: vi.fn(),
  },
  charactersApi: {
    list: vi.fn(() => Promise.resolve([])),
    listLooks: vi.fn(() => Promise.resolve([])),
  },
  scriptsApi: { saveFromEpisode: vi.fn() },
  storiesApi: { get: vi.fn(), update: vi.fn() },
  createWebSocket: vi.fn(),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectDetailPage from '../pages/ProjectDetailPage'
import { episodesApi, workflowApi, charactersApi, scriptsApi, storiesApi, promptApi, filesApi, assetsApi, configApi, createWebSocket } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const PROJECT_ID = 'proj-123'
const EPISODE_ID = 'ep-123'

const baseEpisode = {
  id: EPISODE_ID,
  project_id: PROJECT_ID,
  episode_number: 1,
  title: '测试短剧',
  status: 'created',
  story_id: 'st-1',
  script_id: 'sc-1',
  llm_model: 'kimi-k2-0711-preview',
  video_provider: 'seedance',
  video_model: '',
  resolution: '768P',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const baseStory = {
  id: 'st-1', project_id: PROJECT_ID, title: '原文', genre: 'drama',
  content: '', story_analysis: null, cast: {},
}

const baseStatus = {
  episode_id: EPISODE_ID,
  project_id: PROJECT_ID,
  db_status: 'created',
  current_stage: 'created',
  paused_at: null,
  pipeline: {
    steps: [
      { key: 'analysis', label: '故事分析' },
      { key: 'screenplay', label: '剧本' },
      { key: 'storyboard', label: '分镜' },
      { key: 'looks', label: '审核造型' },
      { key: 'prompts', label: 'Prompt' },
      { key: 'video', label: '生成视频' },
      { key: 'done', label: '完成' },
    ],
    current: null,
  },
}

const keyframePipeline = {
  // 真实后端:开了 use_keyframes 才会暂停在 keyframes_review,流水线里也就必然有这一步
  steps: [
    ...baseStatus.pipeline.steps.slice(0, 6),
    { key: 'keyframes', label: '关键帧' },
    ...baseStatus.pipeline.steps.slice(6),
  ],
  current: 'keyframes',
}

function makeWsMock() {
  const ws: any = { onmessage: null, onclose: null, close: vi.fn() }
  return ws
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/episodes/${EPISODE_ID}`]}>
      <Routes>
        <Route path="/episodes/:episodeId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>
  )

/**
 * 内容按步骤分页:要断言某一步的内容,先点左栏对应的 Step。
 * 点击即"钉"在该步,不会被后台推进抢走(点回当前步则恢复自动跟随)。
 */
const gotoStep = async (label: string) => {
  const step = await waitFor(() => {
    const el = screen.getAllByTestId('step').find(e => e.textContent === label)
    if (!el) throw new Error(`未找到步骤: ${label}`)
    return el
  })
  fireEvent.click(step)
}

describe('ProjectDetailPage', () => {
  let wsMock: ReturnType<typeof makeWsMock>

  beforeEach(() => {
    vi.clearAllMocks()
    wsMock = makeWsMock()
    vi.mocked(createWebSocket).mockReturnValue(wsMock)
    vi.mocked(episodesApi.get).mockResolvedValue(baseEpisode)
    vi.mocked(storiesApi.get).mockResolvedValue(baseStory as any)
    vi.mocked(workflowApi.status).mockResolvedValue(baseStatus)
  })

  // ── Loading & not-found ───────────────────────────────────────────────────

  it('shows loading spinner on initial load', () => {
    vi.mocked(episodesApi.get).mockReturnValue(new Promise(() => {}))
    vi.mocked(workflowApi.status).mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('spin')).toBeInTheDocument()
  })

  it('shows not-found state when project returns null', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('项目未找到')).toBeInTheDocument())
    expect(screen.getByText('返回列表')).toBeInTheDocument()
  })

  it('navigates home when "返回列表" clicked on not-found', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => screen.getByText('返回列表'))
    fireEvent.click(screen.getByText('返回列表'))
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })

  // ── Created state ─────────────────────────────────────────────────────────

  it('renders episode title and meta tags', async () => {
    renderPage()
    // title appears twice: breadcrumb leaf + page title
    await waitFor(() => expect(screen.getAllByText('测试短剧').length).toBeGreaterThan(0))
    expect(screen.getByText('第 1 集')).toBeInTheDocument()
    expect(screen.getByText('Seedance 2.0')).toBeInTheDocument()
  })

  it('shows 开始制作 CTA in created state', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('开始制作')).toBeInTheDocument())
  })

  it('renders progress steps', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    expect(screen.getByText('故事分析')).toBeInTheDocument()
    expect(screen.getByText('剧本')).toBeInTheDocument()
    expect(screen.getByText('完成')).toBeInTheDocument()
  })

  it('shows breadcrumb 作品列表 › ... › {episode title}', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('作品列表')).toBeInTheDocument())
    expect(screen.getByText('作品')).toBeInTheDocument()
  })

  // 回源头的路径:原文恒有(集的锚点),方案可空。两个链接各自按自己的 id 出现。
  it('有原文与起始方案时,两个回溯链接都在', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('源剧本 →')).toBeInTheDocument())
    expect(screen.getByText('故事 →')).toBeInTheDocument()
  })

  // 从故事开跑的集没有起始方案。若只挂方案链接,这类集完全没有回源头的入口 ——
  // 而它恰恰是最需要回去看原文的那种(剧本还没产出)。
  it('从故事开跑的集(无 script_id)仍有回原文的链接', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(
      { ...baseEpisode, script_id: null } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('故事 →')).toBeInTheDocument())
    expect(screen.queryByText('源剧本 →')).not.toBeInTheDocument()
  })

  // ── Start workflow ────────────────────────────────────────────────────────

  it('calls workflowApi.start and shows toast on success', async () => {
    vi.mocked(workflowApi.start).mockResolvedValue({})
    // first call: created (shows 开始制作), second: after start
    vi.mocked(episodesApi.get)
      .mockResolvedValueOnce(baseEpisode)
      .mockResolvedValue({ ...baseEpisode, status: 'analyzing' })
    vi.mocked(workflowApi.status)
      .mockResolvedValueOnce(baseStatus)
      .mockResolvedValue({ ...baseStatus, current_stage: 'analyzing' })
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(workflowApi.start).toHaveBeenCalledWith(EPISODE_ID))
    expect(Toast.info).toHaveBeenCalledWith('制作流程已启动')
  })

  it('shows error toast when start fails', async () => {
    vi.mocked(workflowApi.start).mockRejectedValue({ message: 'network error' })
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
  })

  // ── Story analysis ────────────────────────────────────────────────────────

  it('renders story analysis section when available', async () => {
    const storyStatus = {
      ...baseStatus,
      current_stage: 'story_analyzed',
      story_analysis: {
        title: '测试', genre: '现代剧', tone: '轻松', themes: ['友情', '成长'],
        plot_summary: '这是一个故事梗概',
        characters: [{ name: '小明', appearance: '高个子', personality: '开朗' }],
        setting: '都市',
      },
    }
    vi.mocked(workflowApi.status).mockResolvedValue(storyStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'story_analyzed' })
    renderPage()
    await waitFor(() => expect(screen.getByText('这是一个故事梗概')).toBeInTheDocument())
    expect(screen.getAllByText('小明').length).toBeGreaterThan(0)
    expect(screen.getAllByText('故事分析').length).toBeGreaterThan(0)
  })

  // ── Screenplay review ─────────────────────────────────────────────────────

  it('shows screenplay and review buttons when at screenplay_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '第一幕\n故事开始...',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    renderPage()
    await gotoStep('剧本')
    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    expect(screen.getByText('修改')).toBeInTheDocument()
    expect(screen.getByText('等待您审核剧本，确认内容后点击「通过」，或提交修改意见')).toBeInTheDocument()
    // screenplay content rendered inside <pre>
    expect(screen.getByText(/第一幕/)).toBeInTheDocument()
  })

  it('calls workflowApi.resume with approved=true on 通过 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '剧本内容',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await gotoStep('剧本')
    await waitFor(() => screen.getByText('通过'))
    fireEvent.click(screen.getByText('通过'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(EPISODE_ID, expect.objectContaining({ approved: true })))
    expect(Toast.success).toHaveBeenCalledWith('剧本已通过')
  })

  it('剧本审核面板展示 AI 改写入口与版本树', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '旧正文',
      screenplay_versions: [{ screenplay: '旧正文', label: '初稿', created_at: null }],
      screenplay_version_current: 0,
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    renderPage()
    await gotoStep('剧本')
    await waitFor(() => expect(screen.getByText('AI 改写助手')).toBeInTheDocument())
    // 版本树:后端 status 下发的 screenplay_versions 渲染成版本下拉
    expect(screen.getByText('版本1·初稿')).toBeInTheDocument()
  })

  it('AI 改写发送 → 调 reviseEpisode;apply 后刷新 status', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '旧正文',
      screenplay_versions: [{ screenplay: '旧正文', label: '初稿', created_at: null }],
      screenplay_version_current: 0,
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    vi.mocked(workflowApi.reviseEpisode).mockResolvedValue({
      action: 'apply', reply: '改好了', screenplay: '新正文', version_index: 1, versions_len: 2,
    })
    renderPage()
    await gotoStep('剧本')
    const input = await screen.findByPlaceholderText('和编剧助手说说想怎么改…')
    fireEvent.change(input, { target: { value: '改活泼点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(workflowApi.reviseEpisode).toHaveBeenCalledWith(
      EPISODE_ID, [{ role: 'user', content: '改活泼点' }]))
    // apply → 面板回调 onApplied → 父页 refreshStatus → status 再拉一次
    await waitFor(() => expect(workflowApi.status).toHaveBeenCalledTimes(2))
  })

  // ── Storyboard ────────────────────────────────────────────────────────────

  it('renders storyboard table when shots are available', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      current_stage: 'storyboard_ready',
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '第一个镜头描述', characters: ['小明'], dialogue: '', action: '', location: '室内',
      }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('分镜脚本 · 1 个镜头')).toBeInTheDocument())
    expect(screen.getByText('第一个镜头描述')).toBeInTheDocument()
    expect(screen.getByText('5s')).toBeInTheDocument()
  })

  // ── Prompts review ────────────────────────────────────────────────────────

  it('renders prompts section and confirm button at prompts_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.getByText('全部确认，开始生成视频')).toBeInTheDocument()
    expect(screen.getByDisplayValue('a cinematic shot')).toBeInTheDocument()
  })

  it('calls resume with edited prompts on 全部确认 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'original prompt', negative_prompt: '', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => screen.getByDisplayValue('original prompt'))
    fireEvent.change(screen.getByDisplayValue('original prompt'), { target: { value: 'edited prompt' } })
    fireEvent.click(screen.getByText('全部确认，开始生成视频'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: true, edited_prompts: { s1: 'edited prompt' } })
    ))
  })

  // ── Look review ───────────────────────────────────────────────────────────

  it('renders look review card seeded from status.look_assignments', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'looks' },
      current_stage: 'look_review',
      db_status: 'paused',
      paused_at: 'look_review',
      look_assignments: { '1': { 小明: 'look-a' } },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'look_review' })
    vi.mocked(charactersApi.list).mockResolvedValue([{ id: 'c1', project_id: PROJECT_ID, name: '小明' }])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([
      { id: 'look-a', character_id: 'c1', name: '休闲装', is_default: true },
      { id: 'look-b', character_id: 'c1', name: '西装', is_default: false },
    ])
    renderPage()
    await gotoStep('审核造型')
    await waitFor(() => expect(screen.getByText('审核服装造型（场景 → 角色 → 造型）')).toBeInTheDocument())
    expect(screen.getByText('场景 1')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('西装')).toBeInTheDocument())
  })

  it('calls resume with edited assignments on 确认造型 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'looks' },
      current_stage: 'look_review',
      db_status: 'paused',
      paused_at: 'look_review',
      look_assignments: { '1': { 小明: 'look-a' } },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'look_review' })
    vi.mocked(charactersApi.list).mockResolvedValue([{ id: 'c1', project_id: PROJECT_ID, name: '小明' }])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([
      { id: 'look-a', character_id: 'c1', name: '休闲装', is_default: true },
      { id: 'look-b', character_id: 'c1', name: '西装', is_default: false },
    ])
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await gotoStep('审核造型')
    await waitFor(() => screen.getByText('西装'))
    fireEvent.change(screen.getByDisplayValue('休闲装'), { target: { value: 'look-b' } })
    fireEvent.click(screen.getByText('确认造型'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: true, assignments: { '1': { 小明: 'look-b' } } })
    ))
  })

  it('keeps in-progress look edits across a status refresh', async () => {
    // Each HTTP response is a fresh object in production — model that, otherwise
    // the seeding effect's identity-based dependency never re-fires.
    const lookStatus = () => ({
      ...baseStatus,
      current_stage: 'look_review',
      db_status: 'paused',
      paused_at: 'look_review',
      pipeline: { ...baseStatus.pipeline, current: 'looks' },
      look_assignments: { '1': { 小明: 'look-a' } },
    })
    vi.mocked(workflowApi.status).mockImplementation(() => Promise.resolve(lookStatus()))
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'look_review' })
    vi.mocked(charactersApi.list).mockResolvedValue([{ id: 'c1', project_id: PROJECT_ID, name: '小明' }])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([
      { id: 'look-a', character_id: 'c1', name: '休闲装', is_default: true },
      { id: 'look-b', character_id: 'c1', name: '西装', is_default: false },
    ])
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await gotoStep('审核造型')
    await waitFor(() => screen.getByText('西装'))
    fireEvent.change(screen.getByDisplayValue('休闲装'), { target: { value: 'look-b' } })
    // A WebSocket-driven refresh must not reset the user's pending selection
    const [[, onMessage]] = vi.mocked(createWebSocket).mock.calls
    onMessage({ type: 'stage_change', data: { payload_json: { current_stage: 'look_review' } }, seq: 1 })
    await waitFor(() => expect(workflowApi.status).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByText('确认造型'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ assignments: { '1': { 小明: 'look-b' } } })
    ))
  })

  // ── Keyframes review ──────────────────────────────────────────────────────

  it('renders keyframe thumbnails at keyframes_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'keyframes_review',
      db_status: 'paused',
      paused_at: 'keyframes_review',
      pipeline: keyframePipeline,
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false, keyframe_url: '/u.png' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'keyframes_review' })
    renderPage()
    await gotoStep('关键帧')
    await waitFor(() => expect(screen.getByText('审核关键帧（勾选要重生成的镜头）')).toBeInTheDocument())
    expect(screen.getByAltText('s1')).toHaveAttribute('src', '/u.png')
    expect(screen.getByText('确认，生成视频')).toBeInTheDocument()
  })

  it('calls resume with regenerate_shot_ids for checked shots', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'keyframes_review',
      db_status: 'paused',
      paused_at: 'keyframes_review',
      pipeline: keyframePipeline,
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false, keyframe_url: '/u.png' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'keyframes_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await gotoStep('关键帧')
    await waitFor(() => screen.getByText('重生成所选'))
    fireEvent.click(screen.getByText('重生成').closest('label')!.querySelector('input')!)
    fireEvent.click(screen.getByText('重生成所选'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: false, regenerate_shot_ids: ['s1'] })
    ))
  })

  // ── Video generation ──────────────────────────────────────────────────────

  it('shows video generation progress section', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'video' },
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'running' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await gotoStep('生成视频')
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getByText('生成中')).toBeInTheDocument()
  })

  it('shows completed video status', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'video' },
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'succeeded', local_path: '/some/path.mp4' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await gotoStep('生成视频')
    // "完成" tag — distinguish from "完成" step by checking for the videos section
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getAllByText('完成').length).toBeGreaterThan(0)
  })

  it('shows failed video status with error', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'video' },
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'failed', error: '生成超时' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await gotoStep('生成视频')
    await waitFor(() => expect(screen.getByText('错误: 生成超时')).toBeInTheDocument())
  })

  // ── Completed / final video ───────────────────────────────────────────────

  it('shows final video section and download button when completed', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'done' },
      current_stage: 'completed',
      assembled_video_path: '/data/outputs/final.mp4',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'completed' })
    renderPage()
    await gotoStep('完成')
    await waitFor(() => expect(screen.getByText('✦ 最终成片')).toBeInTheDocument())
    expect(screen.getByText('下载完整视频')).toBeInTheDocument()
  })

  // ── Error state ───────────────────────────────────────────────────────────

  it('shows error message section when project has error_message', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'failed', error_message: '工作流执行失败' })
    renderPage()
    await waitFor(() => expect(screen.getByText('工作流执行失败')).toBeInTheDocument())
  })

  // ── Cost ──────────────────────────────────────────────────────────────────

  it('renders cost breakdown with ¥ amounts when priced', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'video' },
      current_stage: 'videos_generated',
      cost_total: 12.5,
      cost_unpriced: false,
      cost_tokens_total: 34567,
      cost_by_kind: { llm: 2.5, video: 10 },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('成本（估算）')).toBeInTheDocument())
    expect(screen.getByText('¥12.50（估算）')).toBeInTheDocument()
    expect(screen.getByText('¥2.50（估算）')).toBeInTheDocument()
    expect(screen.getByText('¥10.00（估算）')).toBeInTheDocument()
    // kinds absent from cost_by_kind fall back to a placeholder, not ¥0.00
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getByText('34567')).toBeInTheDocument()
  })

  it('renders 未定价 instead of an amount when cost_unpriced', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'video' },
      current_stage: 'videos_generated',
      cost_total: 0,
      cost_unpriced: true,
      cost_tokens_total: 100,
      cost_by_kind: { llm: 0 },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('成本（估算）')).toBeInTheDocument())
    expect(screen.getAllByText('未定价').length).toBeGreaterThan(0)
    expect(screen.queryByText(/¥/)).not.toBeInTheDocument()
  })

  it('hides the cost card when the projection carries no cost', async () => {
    renderPage()
    await waitFor(() => expect(screen.getAllByText('测试短剧').length).toBeGreaterThan(0))
    expect(screen.queryByText('成本（估算）')).not.toBeInTheDocument()
  })

  // ── WebSocket events ──────────────────────────────────────────────────────

  it('creates websocket on mount and closes on unmount', async () => {
    const { unmount } = renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalledWith(EPISODE_ID, expect.any(Function), expect.any(Number)))
    unmount()
    expect(wsMock.close).toHaveBeenCalled()
  })

  it('refreshes status on stage_change WebSocket event', async () => {
    vi.mocked(workflowApi.status)
      .mockResolvedValueOnce(baseStatus)
      .mockResolvedValue({ ...baseStatus, current_stage: 'story_analyzed' })
    vi.mocked(episodesApi.get)
      .mockResolvedValueOnce(baseEpisode)
      .mockResolvedValue({ ...baseEpisode, status: 'story_analyzed' })
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    // Trigger stage_change event
    const [[, onMessage]] = vi.mocked(createWebSocket).mock.calls
    onMessage({ type: 'stage_change', data: { payload_json: { current_stage: 'story_analyzed' } }, seq: 1 })
    await waitFor(() => expect(workflowApi.status).toHaveBeenCalledTimes(2))
  })

  it('shows error toast on WebSocket error event', async () => {
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    const [[, onMessage]] = vi.mocked(createWebSocket).mock.calls
    onMessage({ type: 'error', data: { payload_json: { message: 'node failed' } }, seq: 2 })
    expect(Toast.error).toHaveBeenCalledWith('工作流错误: node failed')
  })

  it('shows disconnect warning toast for active project on dirty close', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'analyzing' })
    vi.mocked(workflowApi.status).mockResolvedValue({ ...baseStatus, current_stage: 'analyzing' })
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    wsMock.onclose?.({ wasClean: false })
    expect(Toast.warning).toHaveBeenCalled()
  })

  it('does NOT show disconnect warning for inactive project on dirty close', async () => {
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    wsMock.onclose?.({ wasClean: false })
    expect(Toast.warning).not.toHaveBeenCalled()
  })

  // ── Steps 状态色 ──────────────────────────────────────────────────────────

  it('created 态(pipeline.current 为 null)时所有步都不带高亮状态', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const stepEls = screen.getAllByTestId('step')
    stepEls.forEach(el => expect(el).toHaveAttribute('data-status', 'wait'))
  })

  it('running 态时当前步标记为 process', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'story_analyzed',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'analysis' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'analyzing' })
    renderPage()
    await waitFor(() => expect(screen.getByText('故事分析')).toBeInTheDocument())
    const analysisStep = screen.getAllByTestId('step').find(el => el.textContent === '故事分析')
    expect(analysisStep).toHaveAttribute('data-status', 'process')
  })

  it('暂停在 prompts_review 时当前步标记为 warning', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const promptsStep = screen.getAllByTestId('step').find(el => el.textContent === 'Prompt')
    expect(promptsStep).toHaveAttribute('data-status', 'warning')
  })

  it('failed 态时当前步标记为 error', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_ready',
      db_status: 'failed',
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'failed', error_message: '生成失败' })
    renderPage()
    await waitFor(() => expect(screen.getByText('生成失败')).toBeInTheDocument())
    const promptsStep = screen.getAllByTestId('step').find(el => el.textContent === 'Prompt')
    expect(promptsStep).toHaveAttribute('data-status', 'error')
  })

  it('已完成的前置步标记为 finish', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const analysisStep = screen.getAllByTestId('step').find(el => el.textContent === '故事分析')
    const screenplayStep = screen.getAllByTestId('step').find(el => el.textContent === '剧本')
    expect(analysisStep).toHaveAttribute('data-status', 'finish')
    expect(screenplayStep).toHaveAttribute('data-status', 'finish')
  })

  it('completed 态时最后一步标记为 finish,而非 process', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'completed',
      db_status: 'completed',
      pipeline: { ...baseStatus.pipeline, current: 'done' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'completed' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const doneStep = screen.getAllByTestId('step').find(el => el.textContent === '完成')
    expect(doneStep).toHaveAttribute('data-status', 'finish')
  })

  it('未推进到的步不带可点样式 —— 看起来能点必须与真的能点一致', async () => {
    // Semi 会把 Steps 的 onChange 注入每一个 Step,那样未达步也会带 clickable/hover
    // (手型 + 悬停反馈)却点不动。这条删掉就放走那个"可点错觉"的回归。
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'story_analyzed',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'analysis' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'analyzing' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const byLabel = (label: string) =>
      screen.getAllByTestId('step').find(el => el.textContent === label)
    expect(byLabel('故事分析')).toHaveAttribute('data-clickable', 'true')   // 当前步
    expect(byLabel('剧本')).toHaveAttribute('data-clickable', 'false')  // 未推进到
    expect(byLabel('完成')).toHaveAttribute('data-clickable', 'false')
  })

  it('点击未推进到的步不切换面板(那边没内容,切过去只会得到空面板)', async () => {
    // 锚点必须选**步骤专属**的内容:故事分析折叠摘要是跨步骤常驻的,参考图在
    // storyboard~video 各步都在 —— 拿它们断言的话在这个场景下无论守卫在不在都恒真
    // (切换与否它们都在屏幕上),测试会变成永远通过的假绿。
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '分镜步专属内容', characters: [], dialogue: '', action: '', location: '',
      }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    // 当前步(分镜)的专属内容已在右栏
    await waitFor(() => expect(screen.getByText('分镜步专属内容')).toBeInTheDocument())
    const later = screen.getAllByTestId('step').find(el => el.textContent === '生成视频')!
    fireEvent.click(later)
    // 仍停在当前步,没有跳到"该步骤尚未开始"的空面板
    await waitFor(() => expect(screen.getByText('分镜步专属内容')).toBeInTheDocument())
    expect(screen.queryByText('该步骤尚未开始')).not.toBeInTheDocument()
  })

  // ── 跨步骤常驻上下文 ──────────────────────────────────────────────────────

  it('流程推进过第一步后,故事分析折叠摘要仍在屏幕上;参考图不再跨步常驻', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
      screenplay: '剧本正文',
      story_analysis: {
        title: '测试', genre: '现代剧', tone: '轻松', themes: [],
        plot_summary: '这是一个故事梗概', characters: [], setting: '都市',
      },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    renderPage()
    // 当前步是审核剧本,但故事分析折叠摘要作为常驻上下文仍须可见
    await waitFor(() => expect(screen.getByText('剧本正文')).toBeInTheDocument())
    expect(screen.getByText('这是一个故事梗概')).toBeInTheDocument()
    // 参考图已收紧为只在 storyboard~video 展示,screenplay 步不再展示
    expect(screen.queryByText('参考图片')).not.toBeInTheDocument()
  })

  // ── 故事内容(用户输入的源头) ──────────────────────────────────────────────

  // 原"流程推进后仍可见"的断言已被 2026-09-12 的收紧改动取代 ——
  // 原文现在只在 analysis 步展示,验证见下方"故事原文归属整治"分组的两个用例。

  // 原文只有 Story 一个家:改它必须落到 PATCH /stories/{id}。
  // 落到 Script 的话,同一段原文的多个方案各持一份并逐渐漂移;落到集上则同一段故事两份。
  it('created 态编辑故事内容,保存落到原文', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode })
    vi.mocked(storiesApi.get).mockResolvedValue({
      ...baseStory, content: '原始故事',
    } as any)
    vi.mocked(storiesApi.update).mockResolvedValue({
      ...baseStory, content: '改过的故事',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('原始故事')).toBeInTheDocument())
    fireEvent.click(screen.getByText('编辑'))
    const area = await screen.findByDisplayValue('原始故事')
    fireEvent.change(area, { target: { value: '改过的故事' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(storiesApi.update).toHaveBeenCalledWith(
      baseEpisode.story_id, { content: '改过的故事' }))
    expect(episodesApi.update).not.toHaveBeenCalled()   // 内容不写在集上
    expect(Toast.success).toHaveBeenCalledWith('已保存')
    await waitFor(() => expect(screen.getByText('改过的故事')).toBeInTheDocument())
  })

  it('已开拍后不给编辑入口 —— 改原文会让已生成的剧本与源头不符', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'story_analyzed',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'analysis' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({
      ...baseEpisode, status: 'story_analyzed',
    })
    vi.mocked(storiesApi.get).mockResolvedValue({
      ...baseStory, content: '原始故事',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('原始故事')).toBeInTheDocument())
    expect(screen.queryByText('编辑')).not.toBeInTheDocument()
    expect(screen.getByText('已开拍，如需调整请在剧本审核阶段改写')).toBeInTheDocument()
  })

  // ── 确认角色(身份对齐) ────────────────────────────────────────────────────

  const castPipeline = {
    steps: [
      { key: 'analysis', label: '故事分析' },
      { key: 'cast', label: '确认角色' },
      ...baseStatus.pipeline.steps.slice(1),
    ],
    current: 'cast',
  }

  it('停在确认角色步时列出待确认人物与候选角色', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast_pending: [
        { name: '李明', appearance: '中年男子', suggestions: [{ character_id: 'c1', name: '路人甲-女1' }] },
      ],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('李明')).toBeInTheDocument())
    expect(screen.getByText('中年男子')).toBeInTheDocument()
    // 候选来自后端下发的 suggestions,前端不自己拉角色列表
    expect(screen.getByText('关联到「路人甲-女1」')).toBeInTheDocument()
    expect(screen.getByText('新建为新角色')).toBeInTheDocument()
  })

  it('确认角色:选了关联则 resume 带 link + character_id', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast_pending: [
        { name: '李明', appearance: '', suggestions: [{ character_id: 'c1', name: '路人甲-女1' }] },
      ],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await waitFor(() => screen.getByText('确认，继续写剧本'))
    const select = screen.getByText('关联到「路人甲-女1」').closest('select')!
    fireEvent.change(select, { target: { value: 'c1' } })
    fireEvent.click(screen.getByText('确认，继续写剧本'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: true, cast: { 李明: { action: 'link', character_id: 'c1' } } })
    ))
  })

  it('确认角色:未选则按新建提交 —— 剧本里出场的角色不能被悄悄丢掉', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast_pending: [{ name: '李明', appearance: '', suggestions: [] }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await waitFor(() => screen.getByText('确认，继续写剧本'))
    fireEvent.click(screen.getByText('确认，继续写剧本'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ cast: { 李明: { action: 'create' } } })
    ))
  })

  it('确认角色:身份未定时「生成形象」不可用,并说明原因', async () => {
    // 生成的形象要落成 Look,而 Look 挂在 Character 上 —— 选"新建"时实体还没建出来,
    // 此时可点就会生成一张无处安放的图。禁用之外必须给出原因,否则用户只看到一个死按钮。
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast_pending: [
        { name: '李明', appearance: '', suggestions: [{ character_id: 'c1', name: '路人甲' }] },
      ],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    renderPage()
    await waitFor(() => screen.getByText('生成形象'))
    expect(screen.getByText('生成形象').closest('button')).toBeDisabled()
    expect(screen.getByTitle(/先关联到已有角色/)).toBeInTheDocument()
  })

  it('确认角色:选了关联后「生成形象」可用,打开弹窗即自动提炼', async () => {
    // 用户点开就是为了拿到描述,让他对着空框再点一次「提炼」是多余的一步
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast_pending: [
        { name: '李明', appearance: '', suggestions: [{ character_id: 'c1', name: '路人甲' }] },
      ],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    vi.mocked(promptApi.extract).mockResolvedValue({ prompt: '一位中年男子，短发' })
    renderPage()
    await waitFor(() => screen.getByText('生成形象'))
    fireEvent.change(screen.getByText('关联到「路人甲」').closest('select')!,
      { target: { value: 'c1' } })
    fireEvent.click(screen.getByText('生成形象'))
    await waitFor(() => expect(promptApi.extract).toHaveBeenCalledWith(
      expect.objectContaining({ subject: 'character', key: '李明', episode_id: EPISODE_ID })))
  })

  it('后端已匹配上的角色(cast 带 id)无需再选即可生成', async () => {
    // 名字与角色库同名时后端已在 cast 里给了 id;要求用户再手选一遍是多余的一步
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'cast_review',
      db_status: 'paused',
      paused_at: 'cast_review',
      pipeline: castPipeline,
      cast: { 李明: 'c-existing' },
      cast_pending: [{ name: '李明', appearance: '', suggestions: [] }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'cast_review' })
    renderPage()
    await waitFor(() => screen.getByText('生成形象'))
    expect(screen.getByText('生成形象').closest('button')).not.toBeDisabled()
  })

  it('背景参考图:未上传的场景可从分镜提炼并生成', async () => {
    // 缺图的场景以空占位列出;此处的入口让用户不必先去素材库手建一张
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    })
    vi.mocked(filesApi.getReferences).mockResolvedValue([
      { key: '内景 咖啡馆 - 日', ref_type: 'background', image_url: '', removable: false },
    ] as any)
    renderPage()
    await waitFor(() => screen.getByText('内景 咖啡馆 - 日'))
    vi.mocked(promptApi.extract).mockResolvedValue({ prompt: '一间空咖啡馆' })
    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(promptApi.extract).toHaveBeenCalledWith(
      expect.objectContaining({ subject: 'background', key: '内景 咖啡馆 - 日' })))
  })

  it('背景参考图生成时附带 project_id 以便后端注入作品视觉风格', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    })
    vi.mocked(filesApi.getReferences).mockResolvedValue([
      { key: '内景 咖啡馆 - 日', ref_type: 'background', image_url: '', removable: false },
    ] as any)
    vi.mocked(promptApi.extract).mockResolvedValue({ prompt: '一间空咖啡馆' })
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'doubao-seedream-3-0-t2i', label: '豆包', provider: 'p',
        resolutions: ['1024x1024'], default_resolution: '1024x1024' }],
      default: 'doubao-seedream-3-0-t2i',
    })
    vi.mocked(assetsApi.generate).mockResolvedValue({ images: ['QUJD'] })
    renderPage()
    await waitFor(() => screen.getByText('内景 咖啡馆 - 日'))
    fireEvent.click(screen.getByText('生成'))
    // 弹窗内还有一个同名「生成」按钮,真正触发 onGenerate 的是它
    await waitFor(() => expect(screen.getAllByText('生成').length).toBeGreaterThan(1))
    fireEvent.click(screen.getAllByText('生成')[screen.getAllByText('生成').length - 1])
    await waitFor(() => expect(assetsApi.generate).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: PROJECT_ID })))
  })

  it('背景参考图:已存 prompt 的条目重新生成时不重新提炼,直接给用户改', async () => {
    // 背景图很少一次满意;重新提炼出的措辞每次都不同,用户改过的版本会被抹掉
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    })
    vi.mocked(filesApi.getReferences).mockResolvedValue([
      { key: '咖啡馆', ref_type: 'background', image_url: '/img/a.png',
        prompt: '我改过的描述', removable: true },
    ] as any)
    vi.mocked(promptApi.extract).mockClear()
    renderPage()
    await waitFor(() => screen.getByText('咖啡馆'))
    fireEvent.click(screen.getByText('重新生成'))
    await waitFor(() => expect(screen.getByDisplayValue('我改过的描述')).toBeInTheDocument())
    expect(promptApi.extract).not.toHaveBeenCalled()
  })

  it('背景参考图整表提交时必须带上 prompt —— 漏掉它用户改过的描述刷新即丢', async () => {
    // prompt 存在参考图条目上,只有整表提交时一并送出才落库。挑字段提交时最易漏这个,
    // 而漏了的症状(下次打开又变回自动提炼的措辞)要到刷新后才显现。
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    })
    vi.mocked(filesApi.getReferences).mockResolvedValue([
      { key: '咖啡馆', ref_type: 'background', image_url: '/img/a.png',
        prompt: '我改过的描述', removable: true },
    ] as any)
    vi.mocked(filesApi.updateReferences).mockResolvedValue([] as any)
    renderPage()
    await waitFor(() => screen.getByText('咖啡馆'))
    fireEvent.click(screen.getByText('清除图片'))   // 任一落库动作都走同一条整表提交
    await waitFor(() => expect(filesApi.updateReferences).toHaveBeenCalledWith(
      EPISODE_ID,
      [expect.objectContaining({ key: '咖啡馆', prompt: '我改过的描述' })]))
  })

  // ── 存为改编方案 ──────────────────────────────────────────────────────────

  it('剧本审核通过后(非审核态)仍可存为方案 —— 故事页承诺的正是"通过后可存入"', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      screenplay: '已通过的剧本正文',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    vi.mocked(scriptsApi.saveFromEpisode).mockResolvedValue({ id: 'sc-new' } as any)
    renderPage()
    await gotoStep('剧本')
    await waitFor(() => expect(screen.getByText('存为改编方案')).toBeInTheDocument())
    // 通过后审核按钮已消失,但存入入口必须还在
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('存为改编方案'))
    await waitFor(() => expect(scriptsApi.saveFromEpisode).toHaveBeenCalledWith(EPISODE_ID))
    expect(Toast.success).toHaveBeenCalledWith('已存为改编方案')
  })

  it('存为方案失败时展示后端 detail(如正文为空 → 409)', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      screenplay: '正文',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    vi.mocked(scriptsApi.saveFromEpisode).mockRejectedValue({
      response: { data: { detail: '该集剧本尚未通过或正文为空' } },
    })
    renderPage()
    await gotoStep('剧本')
    await waitFor(() => screen.getByText('存为改编方案'))
    fireEvent.click(screen.getByText('存为改编方案'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith('存入失败: 该集剧本尚未通过或正文为空'))
  })

  it('合成失败(assembly_failed)时当前步标记为 error', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'assembly_failed',
      db_status: 'completed',
      pipeline: { ...baseStatus.pipeline, current: 'video' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'completed' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const videoStep = screen.getAllByTestId('step').find(el => el.textContent === '生成视频')
    expect(videoStep).toHaveAttribute('data-status', 'error')
  })

  // ── 分镜表格展开行 ────────────────────────────────────────────────────────

  it('点击分镜行展开,显示地点/动作/台词真实值', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      current_stage: 'storyboard_ready',
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '第一个镜头描述', characters: ['小明'],
        dialogue: '你好吗？', action: '小明挥手', location: 'INT. 客厅 - 日',
      }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('分镜脚本 · 1 个镜头')).toBeInTheDocument())
    // location 同时会出现在「参考图」区(每个地点一条参考项),故把断言限定在分镜表格内
    const table = screen.getByText('第一个镜头描述').closest('table')!
    expect(within(table).queryByText('INT. 客厅 - 日')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('第一个镜头描述').closest('tr')!)
    await waitFor(() => expect(within(table).getByText('INT. 客厅 - 日')).toBeInTheDocument())
    expect(within(table).getByText('小明挥手')).toBeInTheDocument()
    expect(within(table).getByText('你好吗？')).toBeInTheDocument()
    // 标签与值须成对出现在同一容器内,防止 动作/台词 接错线(字段名相近、最易犯的复制错误)
    expect(within(table).getByText('地点：').parentElement).toHaveTextContent('INT. 客厅 - 日')
    expect(within(table).getByText('动作：').parentElement).toHaveTextContent('小明挥手')
    expect(within(table).getByText('台词：').parentElement).toHaveTextContent('你好吗？')
  })

  it('台词为空时展开区显示占位文案而非空白', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
      current_stage: 'storyboard_ready',
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '空镜头', characters: [],
        dialogue: '', action: '', location: '',
      }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('分镜脚本 · 1 个镜头')).toBeInTheDocument())
    fireEvent.click(screen.getByText('空镜头').closest('tr')!)
    await waitFor(() => expect(screen.getByText('（无台词）')).toBeInTheDocument())
  })

  // ── Prompt 审核退回 ───────────────────────────────────────────────────────

  const promptsReviewStatus = {
    ...baseStatus,
    current_stage: 'prompts_review',
    db_status: 'paused',
    paused_at: 'prompts_review',
    pipeline: { ...baseStatus.pipeline, current: 'prompts' },
    shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
    prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false }],
  }

  it('prompts_review 阶段同时渲染「全部确认」与「退回重新生成」', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByText('全部确认，开始生成视频')).toBeInTheDocument())
    expect(screen.getByText('退回重新生成')).toBeInTheDocument()
  })

  it('点击退回重新生成,填写意见后 resume 携带 approved=false 与真实 notes', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => screen.getByText('退回重新生成'))
    fireEvent.click(screen.getByText('退回重新生成'))
    expect(Modal.confirm).toHaveBeenCalledOnce()
    const opts = (Modal as any)._lastConfirm.current
    // Modal.confirm 的 mock 不把 content 渲染进 DOM(本文件其它页面对 Modal.confirm 的测试
    // 都是这个模式,见 CharactersPage.test.tsx/AssetsPage.test.tsx/ProjectListPage.test.tsx)——
    // content 是一段 JSX(<TextArea onChange=.../>),直接调它的 onChange prop 模拟用户输入,
    // 再调 opts.onOk() 模拟点击确定,不去找渲染出的输入框或按钮。
    opts.content.props.onChange('光线太暗')
    await opts.onOk()
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: false, notes: '光线太暗' })
    ))
  })

  it('全部确认时 notes 为空字符串(未经过退回弹窗)', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => screen.getByText('全部确认，开始生成视频'))
    fireEvent.click(screen.getByText('全部确认，开始生成视频'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: true, notes: '' })
    ))
  })

  it('取消退回弹窗后点击全部确认,notes 不带上取消前打的字(ref 必须被清空)', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => screen.getByText('退回重新生成'))
    fireEvent.click(screen.getByText('退回重新生成'))
    const opts = (Modal as any)._lastConfirm.current
    opts.content.props.onChange('脏数据')
    opts.onCancel()
    fireEvent.click(screen.getByText('全部确认，开始生成视频'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ approved: true, notes: '' })
    ))
  })

  // ── negative_prompt 可编辑 ────────────────────────────────────────────────

  it('prompts_review 阶段 negative_prompt 渲染为可编辑文本域', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry, watermark', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByDisplayValue('a shot')).toBeInTheDocument())
    expect(screen.getByDisplayValue('blurry, watermark')).toBeInTheDocument()
  })

  it('修改 negative_prompt 后点击全部确认,resume 携带 edited_negative_prompts', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => screen.getByDisplayValue('blurry'))
    fireEvent.change(screen.getByDisplayValue('blurry'), { target: { value: 'blurry, low res' } })
    fireEvent.click(screen.getByText('全部确认，开始生成视频'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID,
      expect.objectContaining({ edited_negative_prompts: { s1: 'blurry, low res' } })
    ))
  })

  it('非审核态时 negative_prompt 只读展示', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', edited_negative_prompt: 'blurry, low res', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.getByText('负向：blurry, low res')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('blurry')).not.toBeInTheDocument()
  })

  it('只读展示时 edited_negative_prompt 为空串代表用户主动清空,不回落到原始 negative_prompt', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', edited_negative_prompt: '', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.queryByText('负向：blurry')).not.toBeInTheDocument()
    expect(screen.queryByText(/负向/)).not.toBeInTheDocument()
  })

  it('只读展示时 negative_prompt 为空则整行不渲染', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'prompts' },
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: '', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await gotoStep('Prompt')
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.queryByText(/负向/)).not.toBeInTheDocument()
  })

  // ── 未启动态(pipeline.current == null) ───────────────────────────────────

  // current == null 是"尚未启动",不是"所有步都到过"。此前守卫写成
  // `current == null || i <= progressIndex`,于是未启动时整条流水线都可点,
  // 点进去却是空面板。这条删掉就放走那个回归。
  it('未启动时只有第一步可点', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      db_status: 'created',
      pipeline: { ...baseStatus.pipeline, current: null },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'created' })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    const byLabel = (l: string) =>
      screen.getAllByTestId('step').find(el => el.textContent === l)
    expect(byLabel('故事分析')).toHaveAttribute('data-clickable', 'true')
    expect(byLabel('剧本')).toHaveAttribute('data-clickable', 'false')
    expect(byLabel('完成')).toHaveAttribute('data-clickable', 'false')
  })

  // 复用剧本的集直达分镜,流水线里没有 analysis 步。启动卡只挂 analysis 的话,
  // 这类集打开后没有任何启动入口 —— 用户无法开拍(实测反馈"没有启动按钮")。
  it('复用剧本的集(无 analysis 步)仍有「开始制作」入口', async () => {
    const fromScript = [
      { key: 'storyboard', label: '分镜' },
      { key: 'looks', label: '审核造型' },
      { key: 'prompts', label: 'Prompt' },
      { key: 'video', label: '生成视频' },
      { key: 'done', label: '完成' },
    ]
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      db_status: 'created',
      pipeline: { steps: fromScript, current: null },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'created' })
    renderPage()
    await waitFor(() => expect(screen.getByText('开始制作')).toBeInTheDocument())
  })

  // 一点「开始制作」,启动卡就随 status 变更整块卸载,而首个节点产出前右栏没有别的内容
  // —— 用户看到一片空白,像是操作失败了。改为保留卡片并显示进度。
  it('启动后卡片不消失,改为显示当前步进度', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      db_status: 'running',
      current_stage: 'analyzing',
      pipeline: { ...baseStatus.pipeline, current: 'analysis' },
      story_analysis: undefined,      // 首个产出尚未到位
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'running' })
    renderPage()
    await waitFor(() => expect(screen.getByText('制作已启动')).toBeInTheDocument())
    // 页头也有阶段标签,故限定在卡片内断言进度文案
    expect(screen.getByText(/首个产出完成后会自动显示在这里/)).toBeInTheDocument()
    expect(screen.getByTestId('spin')).toBeInTheDocument()
  })

  it('首个产出到位后,进度卡让位给内容', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      db_status: 'running',
      current_stage: 'story_analyzed',
      pipeline: { ...baseStatus.pipeline, current: 'analysis' },
      story_analysis: {
        title: 'T', genre: '现代剧', tone: '轻松', themes: [],
        plot_summary: '梗概在此', characters: [], setting: '都市',
      },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'running' })
    renderPage()
    await waitFor(() => expect(screen.getByText('梗概在此')).toBeInTheDocument())
    expect(screen.queryByText('制作已启动')).not.toBeInTheDocument()
  })

  // ── 分镜审核 ──────────────────────────────────────────────────────────────

  const storyboardReviewStatus = {
    ...baseStatus,
    current_stage: 'storyboard_ready',
    db_status: 'paused',
    paused_at: 'storyboard_review',
    pipeline: { ...baseStatus.pipeline, current: 'storyboard' },
    duration_over_target: true,
    shots: [{
      shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'ELS',
      camera_movement: 'static', duration_seconds: 5, description: '分镜内容',
      characters: [], dialogue: '', action: '', location: '',
    }],
  }

  // 分镜是人工卡点(storyboard_review)。只提示"建议退回"却不给按钮,
  // 用户无从操作、整集卡在这里(实测反馈:"没有回退按钮")。
  it('停在分镜审核时给出通过与退回入口', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(storyboardReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'paused' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('通过，继续造型')).toBeInTheDocument())
    expect(screen.getByText('退回重新生成')).toBeInTheDocument()
    expect(screen.getByText('总时长超出目标，建议退回重新生成')).toBeInTheDocument()
  })

  it('分镜通过时 resume 携带 approved=true', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(storyboardReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'paused' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => screen.getByText('通过，继续造型'))
    fireEvent.click(screen.getByText('通过，继续造型'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      EPISODE_ID, { approved: true, notes: '' }))
  })

  it('非审核态不给分镜的通过/退回按钮', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...storyboardReviewStatus, db_status: 'running', paused_at: null,
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'running' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('分镜内容')).toBeInTheDocument())
    expect(screen.queryByText('通过，继续造型')).not.toBeInTheDocument()
  })

  // 故事分析是写剧本的依据,分镜之后看的是剧本与镜头 —— 收成一行,但**不移除**:
  // 它仍是判断产出跑偏的参照,且规范要求跨步常驻。
  it('分镜步的故事分析收成折叠形态,仍可展开', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...storyboardReviewStatus,
      story_analysis: {
        title: 'T', genre: '现代剧', tone: '压抑', themes: ['孤独'],
        plot_summary: '梗概一句话', characters: [], setting: '办公室',
      },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'paused' })
    renderPage()
    await gotoStep('分镜')
    await waitFor(() => expect(screen.getByText('梗概一句话')).toBeInTheDocument())
    expect(screen.getByText('展开')).toBeInTheDocument()
    // 收起态不展开完整的类型/基调
    expect(screen.queryByText('压抑')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('展开'))
    await waitFor(() => expect(screen.getByText('压抑')).toBeInTheDocument())
  })

  // ── 故事原文归属整治(2026-09-12)────────────────────────────────────────

  // 流水线停在剧本步:只有推进到的步才可点(stepReached),故要在两步间来回切换,
  // 进度必须至少到 screenplay —— 停在 analysis 时剧本步没有 onClick,点了不动。
  it('from_story 模式:analysis 步展示故事原文,screenplay 步不展示', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'screenplay_written',
      db_status: 'running',
      pipeline: { ...baseStatus.pipeline, current: 'screenplay' },
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_written' })
    vi.mocked(storiesApi.get).mockResolvedValue({
      ...baseStory, content: '仅在分析步可见的原文',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    expect(screen.queryByText('仅在分析步可见的原文')).not.toBeInTheDocument()

    await gotoStep('故事分析')
    await waitFor(() => expect(screen.getByText('仅在分析步可见的原文')).toBeInTheDocument())

    await gotoStep('剧本')
    await waitFor(() => expect(screen.queryByText('仅在分析步可见的原文')).not.toBeInTheDocument())
  })

  it('from_script 模式(无 analysis 步):任何步都不展示故事原文卡', async () => {
    const fromScriptPipeline = {
      steps: [
        { key: 'storyboard', label: '分镜' },
        { key: 'looks', label: '审核造型' },
        { key: 'prompts', label: 'Prompt' },
        { key: 'video', label: '生成视频' },
        { key: 'done', label: '完成' },
      ],
      current: 'storyboard',
    }
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      db_status: 'running',
      pipeline: fromScriptPipeline,
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    vi.mocked(storiesApi.get).mockResolvedValue({
      ...baseStory, content: '不该出现的原文',
    } as any)
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    expect(screen.queryByText('不该出现的原文')).not.toBeInTheDocument()
    // 回原文的入口仍靠页头链接,不是本页内容区
    expect(screen.getByText('故事 →')).toBeInTheDocument()
  })

  // 参考图在 storyboard 步展示的正向覆盖已在下方"背景参考图"分组的三个用例里
  // (它们都以 pipeline.current: 'storyboard' 渲染,若参考图卡在那一步不出现,
  // 那三个用例会直接失败)。screenplay 步的反向覆盖见上方"流程推进过第一步后…"。

  it('参考图卡:done 步不展示', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      pipeline: { ...baseStatus.pipeline, current: 'done' },
      current_stage: 'completed',
      assembled_video_path: '/data/outputs/final.mp4',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'completed' })
    renderPage()
    await gotoStep('完成')
    await waitFor(() => expect(screen.getByText('✦ 最终成片')).toBeInTheDocument())
    expect(screen.queryByText('参考图片')).not.toBeInTheDocument()
  })
})
