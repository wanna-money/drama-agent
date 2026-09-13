/**
 * 选中的步骤必须在左栏高亮 —— 点了一步却看不出选中,就分不清自己在看哪。
 *
 * 实测:一集跑完后所有步的 status 都是 finish,选中的那步也一样,
 * Semi 加的 -active 类被 finish 样式盖住,视觉上毫无变化。
 * 修法用 Semi 原生的 status 表达选中(process 本身就是高亮态),不写自定义样式。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  episodesApi: { get: vi.fn(), update: vi.fn() },
  workflowApi: {
    start: vi.fn(), resume: vi.fn(), status: vi.fn(),
    reviseEpisode: vi.fn(), editEpisode: vi.fn(), revertEpisode: vi.fn(),
  },
  filesApi: {
    uploadImage: vi.fn(), copyFromAsset: vi.fn(),
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

import ProjectDetailPage from '../pages/ProjectDetailPage'
import { episodesApi, workflowApi, storiesApi, createWebSocket } from '../services/api'

const PID = 'proj-1'
const EID = 'ep-1'
const STEPS = [
  { key: 'analysis', label: '故事分析' },
  { key: 'cast', label: '确认角色' },
  { key: 'screenplay', label: '剧本' },
  { key: 'storyboard', label: '分镜' },
  { key: 'looks', label: '审核造型' },
  { key: 'prompts', label: 'Prompt' },
  { key: 'video', label: '生成视频' },
  { key: 'done', label: '完成' },
]

const SHOT = {
  shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'MS',
  camera_movement: 'static', duration_seconds: 5, description: '一个镜头', characters: [],
}

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

const stepEl = (label: string) =>
  screen.getAllByTestId('step').find(e => e.textContent?.includes(label))
const statusOf = (label: string) => stepEl(label)?.getAttribute('data-status')

describe('选中的步骤高亮', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '原文', story_analysis: null, cast: {},
    } as never)
  })

  /** 一集已跑完 —— 复现"所有步都是 finish、选中步看不出来"的场景。 */
  const seedCompleted = () => {
    vi.mocked(episodesApi.get).mockResolvedValue({
      id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
      status: 'completed', story_id: 'st-1', script_id: null,
      llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as never)
    vi.mocked(workflowApi.status).mockResolvedValue({
      episode_id: EID, project_id: PID, db_status: 'completed',
      current_stage: 'completed', paused_at: null,
      screenplay: 'INT. 卧室', shots: [SHOT],
      story_analysis: { title: 'x', genre: 'drama', tone: 's', themes: [],
                        plot_summary: '梗概', characters: [], setting: '卧室' },
      assembled_video_path: '/out/final.mp4',
      pipeline: { steps: STEPS, current: 'done' },
    } as never)
  }

  it('已完成的集里点某步,该步 status 变为 process(高亮),其余不是', async () => {
    seedCompleted()
    renderPage()
    await waitFor(() => expect(stepEl('分镜')).toBeTruthy())
    fireEvent.click(stepEl('分镜')!)
    await waitFor(() => expect(statusOf('分镜')).toBe('process'))
    // 全局只有一处 process —— 两处高亮同样分不清
    const marked = screen.getAllByTestId('step')
      .filter(e => e.getAttribute('data-status') === 'process')
    expect(marked.length).toBe(1)
  })

  it('切到另一步,高亮随之转移', async () => {
    seedCompleted()
    renderPage()
    await waitFor(() => expect(stepEl('分镜')).toBeTruthy())
    fireEvent.click(stepEl('分镜')!)
    await waitFor(() => expect(statusOf('分镜')).toBe('process'))
    fireEvent.click(stepEl('故事分析')!)
    await waitFor(() => expect(statusOf('故事分析')).toBe('process'))
    expect(statusOf('分镜')).not.toBe('process')
  })

  it('停在审核卡点时,选中该步仍显示 warning(卡点语义优先于"我在看这里")', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue({
      id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
      status: 'paused', story_id: 'st-1', script_id: null,
      llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as never)
    vi.mocked(workflowApi.status).mockResolvedValue({
      episode_id: EID, project_id: PID, db_status: 'paused',
      current_stage: 'storyboard_ready', paused_at: 'storyboard_review',
      shots: [SHOT], pipeline: { steps: STEPS, current: 'storyboard' },
    } as never)
    renderPage()
    // 默认就跟随当前步(分镜),它是卡点 → warning 而非 process
    await waitFor(() => expect(statusOf('分镜')).toBe('warning'))
  })
})
