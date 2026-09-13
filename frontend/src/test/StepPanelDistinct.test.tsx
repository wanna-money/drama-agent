/**
 * 每一步的面板必须有属于自己的内容 —— 点两步看到同一张卡片是体验缺陷。
 *
 * 实测到的重复:screenplay 与 screenplay_review 渲染同一个 screenplayCard;
 * done 步把 video 步的视频清单又放一遍;storyboard 步夹带启动卡。
 * 加上跨步常驻的故事/参考图/故事分析,用户点来点去看到的东西差不多。
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

const episode = (over: Record<string, unknown> = {}) => ({
  id: EID, project_id: PID, episode_number: 1, title: '测试短剧',
  status: 'running', story_id: 'st-1', script_id: null,
  llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...over,
})

const status = (over: Record<string, unknown> = {}) => ({
  episode_id: EID, project_id: PID, db_status: 'running',
  current_stage: 'created', paused_at: null,
  pipeline: { steps: STEPS, current: null }, ...over,
})

const SHOT = {
  shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'MS',
  camera_movement: 'static', duration_seconds: 5, description: '一个镜头', characters: [],
}

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

describe('步骤面板内容互不重复', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '故事原文', story_analysis: null, cast: {},
    } as never)
  })

  it('分镜步不再夹带启动卡:已开拍的集在该步没有启动动作可做', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(episode({ status: 'paused' }) as never)
    vi.mocked(workflowApi.status).mockResolvedValue(status({
      db_status: 'paused', current_stage: 'storyboard_ready', paused_at: 'storyboard_review',
      shots: [SHOT], total_duration_seconds: 5,
      pipeline: { steps: STEPS, current: 'storyboard' },
    }) as never)
    renderPage()
    await waitFor(() => expect(screen.getByText(/分镜脚本 ·/)).toBeInTheDocument())
    expect(screen.queryByText('项目准备就绪')).not.toBeInTheDocument()
  })

  it('未开拍的集在首步仍有启动入口(守卫不能把正常路径也挡掉)', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(episode({ status: 'created' }) as never)
    vi.mocked(workflowApi.status).mockResolvedValue(status({
      db_status: 'created', pipeline: { steps: STEPS, current: null },
    }) as never)
    renderPage()
    await waitFor(() => expect(screen.getByText('项目准备就绪')).toBeInTheDocument())
  })

  it('完成步聚焦成片,不整段重放生成视频步的分镜清单', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(episode({ status: 'completed' }) as never)
    vi.mocked(workflowApi.status).mockResolvedValue(status({
      db_status: 'completed', current_stage: 'completed',
      assembled_video_path: '/out/final.mp4',
      videos: [{ shot_id: 's1', status: 'succeeded', video_url: 'http://x/1.mp4',
                 task_id: 't1', local_path: null, last_frame_url: null, error: null }],
      shots: [SHOT],
      pipeline: { steps: STEPS, current: 'done' },
    }) as never)
    renderPage()
    await waitFor(() => expect(screen.getByText("✦ 最终成片")).toBeInTheDocument())
    expect(screen.queryByText("视频生成进度")).not.toBeInTheDocument()
  })

  it('生成视频步展示分镜视频清单(那是它自己的内容)', async () => {
    vi.mocked(episodesApi.get).mockResolvedValue(episode() as never)
    vi.mocked(workflowApi.status).mockResolvedValue(status({
      current_stage: 'videos_generating',
      videos: [{ shot_id: 's1', status: 'succeeded', video_url: 'http://x/1.mp4',
                 task_id: 't1', local_path: null, last_frame_url: null, error: null }],
      shots: [SHOT],
      pipeline: { steps: STEPS, current: 'video' },
    }) as never)
    renderPage()
    await waitFor(() => expect(screen.getByText("视频生成进度")).toBeInTheDocument())
  })
})
