/**
 * 启动卡只挂**流水线首步**,不写死在某个 key 上。
 *
 * 原实现把它同时挂在 analysis 与 storyboard 两处:因为复用剧本的集(from_script)
 * 流水线里没有 analysis 步,只挂那里的话这类集打开后没有任何启动入口。
 * 但硬编码两个 key 也意味着 storyboard 步夹带了不属于它的卡片 —— 判据该是
 * "这是不是第一步",而不是"这一步叫什么名字"。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
  charactersApi: { list: vi.fn(() => Promise.resolve([])), listLooks: vi.fn(() => Promise.resolve([])) },
  scriptsApi: { saveFromEpisode: vi.fn() },
  storiesApi: { get: vi.fn(), update: vi.fn() },
  createWebSocket: vi.fn(),
}))

import ProjectDetailPage from '../pages/ProjectDetailPage'
import { episodesApi, workflowApi, storiesApi, createWebSocket } from '../services/api'

const PID = 'proj-1'
const EID = 'ep-1'
const FROM_STORY = [
  { key: 'analysis', label: '故事分析' }, { key: 'cast', label: '确认角色' },
  { key: 'screenplay', label: '剧本' }, { key: 'storyboard', label: '分镜' },
  { key: 'done', label: '完成' },
]
/** 复用剧本的集:图直达分镜,流水线里没有剧本各步 */
const FROM_SCRIPT = [
  { key: 'storyboard', label: '分镜' }, { key: 'looks', label: '审核造型' },
  { key: 'done', label: '完成' },
]

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

const seed = (steps: typeof FROM_STORY, epStatus: string, extra = {}) => {
  vi.mocked(episodesApi.get).mockResolvedValue({
    id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
    status: epStatus, story_id: 'st-1', script_id: null,
    llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } as never)
  vi.mocked(workflowApi.status).mockResolvedValue({
    episode_id: EID, project_id: PID, db_status: epStatus,
    current_stage: 'created', paused_at: null,
    pipeline: { steps, current: null }, ...extra,
  } as never)
}

describe('启动卡只在流水线首步', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '原文', story_analysis: null, cast: {},
    } as never)
  })

  it('从故事开跑的未开拍集:首步(故事分析)有启动入口', async () => {
    seed(FROM_STORY, 'created')
    renderPage()
    await waitFor(() => expect(screen.getByText('项目准备就绪')).toBeInTheDocument())
  })

  it('复用剧本的未开拍集:首步是分镜,启动入口必须在那里', async () => {
    seed(FROM_SCRIPT, 'created')
    renderPage()
    await waitFor(() => expect(screen.getByText('项目准备就绪')).toBeInTheDocument())
  })

  it('已开拍后任何步都没有启动卡(没有启动动作可做)', async () => {
    seed(FROM_STORY, 'paused', {
      current_stage: 'storyboard_ready', paused_at: 'storyboard_review',
      db_status: 'paused',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'MS',
                camera_movement: 'static', duration_seconds: 5, description: 'x',
                characters: [] }],
      pipeline: { steps: FROM_STORY, current: 'storyboard' },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText(/分镜脚本 ·/)).toBeInTheDocument())
    expect(screen.queryByText('项目准备就绪')).not.toBeInTheDocument()
  })

  // 复用剧本的集(from_script)首步是分镜(不是故事分析),而它的 story_analysis
  // 继承自 Story、开拍那一刻就非空 —— 若进度占位卡仍按"story_analysis 还没来"判断,
  // 分镜生成中(耗时的 LLM 调用)这张卡永远不出现,右栏没有任何进度提示与按钮(实测)。
  it('复用剧本的集在分镜生成中,显示进度占位卡而非一片空白', async () => {
    seed(FROM_SCRIPT, 'running', {
      current_stage: 'storyboard_start', paused_at: null,
      db_status: 'running',
      shots: [],
      story_analysis: {
        title: 'T', genre: '现代剧', tone: '轻松', themes: [],
        plot_summary: '继承自故事的梗概', characters: [], setting: '都市',
      },
      pipeline: { steps: FROM_SCRIPT, current: 'storyboard' },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('制作已启动')).toBeInTheDocument())
    // 顶部标签与卡内文案都会出现该词,用 getAllByText 只断言"至少出现"(与
    // ProjectDetailPage.test.tsx 同例的多处命中场景一致)
    expect(screen.getAllByText(/分镜生成中/).length).toBeGreaterThan(0)
  })
})
