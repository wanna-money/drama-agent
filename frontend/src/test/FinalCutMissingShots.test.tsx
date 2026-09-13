/**
 * 成片由**部分**镜头拼成时必须显式告知,并给出补齐入口。
 *
 * 实测:20 镜里 1 支超时失败,video_assembler 跳过它、用 19 支合成。
 * 成片能正常播、看起来完整 —— 用户不会知道少了一个镜头,更不会知道少的恰好是高潮戏
 * (苏寒扑向黑袍男人那镜)。上一集同样静默少了 2 镜(内容审核被拒)。
 *
 * "能播"不等于"完整":缺镜必须在成片卡上讲明白,否则用户拿着残片以为是成品。
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
const STEPS = [
  { key: 'analysis', label: '故事分析' }, { key: 'cast', label: '确认角色' },
  { key: 'screenplay', label: '剧本' }, { key: 'storyboard', label: '分镜' },
  { key: 'looks', label: '审核造型' }, { key: 'prompts', label: 'Prompt' },
  { key: 'video', label: '生成视频' }, { key: 'done', label: '完成' },
]

const shot = (n: number) => ({
  shot_id: `s${n}`, scene_number: 1, shot_number: n, shot_type: 'MS',
  camera_movement: 'static', duration_seconds: 5, description: `镜${n}`, characters: [],
})
const okVideo = (n: number) => ({
  shot_id: `s${n}`, status: 'succeeded', task_id: `t${n}`,
  video_url: `http://cdn/${n}.mp4`, local_path: `/out/${n}.mp4`,
  last_frame_url: null, error: null,
})
const badVideo = (n: number, error: string) => ({
  shot_id: `s${n}`, status: 'failed', task_id: `t${n}`,
  video_url: null, local_path: null, last_frame_url: null, error,
})

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

const seed = (videos: unknown[], shots: unknown[]) => {
  vi.mocked(episodesApi.get).mockResolvedValue({
    id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
    status: 'completed', story_id: 'st-1', script_id: null,
    llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } as never)
  vi.mocked(workflowApi.status).mockResolvedValue({
    episode_id: EID, project_id: PID, db_status: 'completed',
    current_stage: 'completed', paused_at: null,
    assembled_video_path: '/out/final.mp4',
    shots, videos,
    pipeline: { steps: STEPS, current: 'done' },
  } as never)
}

describe('成片缺镜必须显式告知', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '原文', story_analysis: null, cast: {},
    } as never)
  })

  it('全部镜头都成功时不显示缺镜提示', async () => {
    seed([okVideo(1), okVideo(2)], [shot(1), shot(2)])
    renderPage()
    await waitFor(() => expect(screen.getByText('✦ 最终成片')).toBeInTheDocument())
    expect(screen.queryByText(/未纳入/)).not.toBeInTheDocument()
  })

  it('有镜头失败时讲明缺了几个、缺的是哪几镜', async () => {
    seed([okVideo(1), badVideo(2, '超时'), okVideo(3)], [shot(1), shot(2), shot(3)])
    renderPage()
    await waitFor(() => expect(screen.getByText('✦ 最终成片')).toBeInTheDocument())
    // 数量与镜号都要有 —— 只说"不完整"用户不知道该补哪个
    const warn = screen.getByText(/未纳入/)
    expect(warn.textContent).toMatch(/1\s*个/)
    expect(warn.textContent).toMatch(/镜\s*2/)
  })

  it('多个失败时逐一列出镜号', async () => {
    seed([badVideo(1, 'e'), okVideo(2), badVideo(3, 'e')], [shot(1), shot(2), shot(3)])
    renderPage()
    await waitFor(() => expect(screen.getByText(/未纳入/)).toBeInTheDocument())
    const warn = screen.getByText(/未纳入/)
    expect(warn.textContent).toMatch(/镜\s*1/)
    expect(warn.textContent).toMatch(/镜\s*3/)
  })

  it('缺镜时给出去「生成视频」步补齐的入口', async () => {
    seed([okVideo(1), badVideo(2, '超时')], [shot(1), shot(2)])
    renderPage()
    await waitFor(() => expect(screen.getByText(/未纳入/)).toBeInTheDocument())
    expect(screen.getByText('去补齐这些镜头')).toBeInTheDocument()
  })
})
