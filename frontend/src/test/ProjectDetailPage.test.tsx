import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import React from 'react'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  episodesApi: { get: vi.fn() },
  workflowApi: { start: vi.fn(), resume: vi.fn(), status: vi.fn() },
  filesApi: {
    uploadImage: vi.fn(),
    updateReferences: vi.fn(),
    getReferences: vi.fn(() => Promise.resolve({})),
    exportUrl: (id: string) => `/api/episodes/${id}/export`,
    downloadUrl: (id: string, f: string) => `/api/episodes/${id}/files/${f}`,
  },
  artifactsApi: {
    listByShot: vi.fn(() => Promise.resolve([])),
    listActions: vi.fn(() => Promise.resolve([])),
    runAction: vi.fn(),
  },
  charactersApi: {
    list: vi.fn(() => Promise.resolve([])),
    listLooks: vi.fn(() => Promise.resolve([])),
  },
  createWebSocket: vi.fn(),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectDetailPage from '../pages/ProjectDetailPage'
import { episodesApi, workflowApi, charactersApi, createWebSocket } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const PROJECT_ID = 'proj-123'
const EPISODE_ID = 'ep-123'

const baseEpisode = {
  id: EPISODE_ID,
  project_id: PROJECT_ID,
  episode_number: 1,
  title: '测试短剧',
  status: 'created',
  script_id: 'sc-1',
  llm_model: 'kimi-k2-0711-preview',
  video_provider: 'seedance',
  video_model: '',
  resolution: '768P',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
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
      { key: 'screenplay', label: '生成剧本' },
      { key: 'screenplay_review', label: '审核剧本' },
      { key: 'storyboard', label: '分镜' },
      { key: 'looks', label: '审核造型' },
      { key: 'prompts', label: 'Prompt' },
      { key: 'video', label: '生成视频' },
      { key: 'done', label: '完成' },
    ],
    current: null,
  },
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

describe('ProjectDetailPage', () => {
  let wsMock: ReturnType<typeof makeWsMock>

  beforeEach(() => {
    vi.clearAllMocks()
    wsMock = makeWsMock()
    vi.mocked(createWebSocket).mockReturnValue(wsMock)
    vi.mocked(episodesApi.get).mockResolvedValue(baseEpisode)
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
    expect(screen.getByText('生成剧本')).toBeInTheDocument()
    expect(screen.getByText('完成')).toBeInTheDocument()
  })

  it('shows breadcrumb 作品列表 › ... › {episode title}', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('作品列表')).toBeInTheDocument())
    expect(screen.getByText('作品')).toBeInTheDocument()
  })

  it('renders a source-script link when episode has script_id', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('源剧本 →')).toBeInTheDocument())
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
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '第一幕\n故事开始...',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    expect(screen.getByText('修改')).toBeInTheDocument()
    expect(screen.getByText('等待您审核剧本，确认内容后点击「通过」，或提交修改意见')).toBeInTheDocument()
    // screenplay content rendered inside <pre>
    expect(screen.getByText(/第一幕/)).toBeInTheDocument()
  })

  it('calls workflowApi.resume with approved=true on 通过 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'screenplay_review',
      db_status: 'paused',
      paused_at: 'screenplay_review',
      screenplay: '剧本内容',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'screenplay_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await waitFor(() => screen.getByText('通过'))
    fireEvent.click(screen.getByText('通过'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(EPISODE_ID, expect.objectContaining({ approved: true })))
    expect(Toast.success).toHaveBeenCalledWith('剧本已通过')
  })

  // ── Storyboard ────────────────────────────────────────────────────────────

  it('renders storyboard table when shots are available', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '第一个镜头描述', characters: ['小明'], dialogue: '', action: '', location: '室内',
      }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'storyboard_ready' })
    renderPage()
    await waitFor(() => expect(screen.getByText('分镜脚本 · 1 个镜头')).toBeInTheDocument())
    expect(screen.getByText('第一个镜头描述')).toBeInTheDocument()
    expect(screen.getByText('5s')).toBeInTheDocument()
  })

  // ── Prompts review ────────────────────────────────────────────────────────

  it('renders prompts section and confirm button at prompts_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.getByText('全部确认，开始生成视频')).toBeInTheDocument()
    expect(screen.getByDisplayValue('a cinematic shot')).toBeInTheDocument()
  })

  it('calls resume with edited prompts on 全部确认 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'original prompt', negative_prompt: '', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
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
    await waitFor(() => expect(screen.getByText('审核服装造型（场景 → 角色 → 造型）')).toBeInTheDocument())
    expect(screen.getByText('场景 1')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('西装')).toBeInTheDocument())
  })

  it('calls resume with edited assignments on 确认造型 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
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
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false, keyframe_url: '/u.png' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'keyframes_review' })
    renderPage()
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
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false, keyframe_url: '/u.png' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'keyframes_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
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
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'running' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getByText('生成中')).toBeInTheDocument()
  })

  it('shows completed video status', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'succeeded', local_path: '/some/path.mp4' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    // "完成" tag — distinguish from "完成" step by checking for the videos section
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getAllByText('完成').length).toBeGreaterThan(0)
  })

  it('shows failed video status with error', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'failed', error: '生成超时' }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('错误: 生成超时')).toBeInTheDocument())
  })

  // ── Completed / final video ───────────────────────────────────────────────

  it('shows final video section and download button when completed', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'completed',
      assembled_video_path: '/data/outputs/final.mp4',
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'completed' })
    renderPage()
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
    const screenplayStep = screen.getAllByTestId('step').find(el => el.textContent === '生成剧本')
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
    shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
    prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false }],
  }

  it('prompts_review 阶段同时渲染「全部确认」与「退回重新生成」', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('全部确认，开始生成视频')).toBeInTheDocument())
    expect(screen.getByText('退回重新生成')).toBeInTheDocument()
  })

  it('点击退回重新生成,填写意见后 resume 携带 approved=false 与真实 notes', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue(promptsReviewStatus)
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
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
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry, watermark', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    renderPage()
    await waitFor(() => expect(screen.getByDisplayValue('a shot')).toBeInTheDocument())
    expect(screen.getByDisplayValue('blurry, watermark')).toBeInTheDocument()
  })

  it('修改 negative_prompt 后点击全部确认,resume 携带 edited_negative_prompts', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      db_status: 'paused',
      paused_at: 'prompts_review',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', approved: false }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({} as any)
    renderPage()
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
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', edited_negative_prompt: 'blurry, low res', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.getByText('负向：blurry, low res')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('blurry')).not.toBeInTheDocument()
  })

  it('只读展示时 edited_negative_prompt 为空串代表用户主动清空,不回落到原始 negative_prompt', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: 'blurry', edited_negative_prompt: '', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.queryByText('负向：blurry')).not.toBeInTheDocument()
    expect(screen.queryByText(/负向/)).not.toBeInTheDocument()
  })

  it('只读展示时 negative_prompt 为空则整行不渲染', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_approved',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a shot', negative_prompt: '', approved: true }],
    })
    vi.mocked(episodesApi.get).mockResolvedValue({ ...baseEpisode, status: 'prompts_approved' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.queryByText(/负向/)).not.toBeInTheDocument()
  })
})
