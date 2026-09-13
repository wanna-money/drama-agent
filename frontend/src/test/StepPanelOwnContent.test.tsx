/**
 * 每个步骤的面板只放**属于该步**的产出;左栏同时只高亮一处。
 *
 * 实测到的两个缺陷:
 *  1. 故事分析步的面板顶着「剧本」标题 —— 剧本是第 3 步的产出,被误挂到了第 1 步;
 *  2. 点某步后,左栏同时高亮"我在看的那步"与"流水线正在跑的那步",分不清自己在哪。
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

/** 一集跑到 Prompt 步、前面各步都有产出 —— 复现"点回前面某步"的场景。 */
const FULL_STATUS = {
  episode_id: EID, project_id: PID, db_status: 'running',
  current_stage: 'prompts_approved', paused_at: null,
  story_analysis: {
    title: '无限复活', genre: 'drama', tone: 'serious', themes: ['历史记忆'],
    plot_summary: '父子二人在游戏里体会战争', characters: [], setting: '卧室',
  },
  screenplay: 'INT. 卧室 - 傍晚\n父亲走进来。',
  shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'MS',
            camera_movement: 'static', duration_seconds: 5, description: '一个镜头',
            characters: [] }],
  prompts: [{ shot_id: 's1', prompt_text: '中景，父亲走进卧室', negative_prompt: '模糊' }],
  total_duration_seconds: 5,
  pipeline: { steps: STEPS, current: 'prompts' },
}

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

const stepEl = (label: string) =>
  screen.getAllByTestId('step').find(e => e.textContent?.replace('▸ ', '').trim() === label)
const clickStep = (label: string) => fireEvent.click(stepEl(label)!)
const waitReady = () => waitFor(() => expect(stepEl('Prompt')).toBeTruthy())

describe('步骤面板只放自己的内容', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '故事原文正文', story_analysis: null, cast: {},
    } as never)
    vi.mocked(episodesApi.get).mockResolvedValue({
      id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
      status: 'running', story_id: 'st-1', script_id: null,
      llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as never)
    vi.mocked(workflowApi.status).mockResolvedValue(FULL_STATUS as never)
  })

  it('故事分析步不展示剧本 —— 剧本是「生成剧本」步的产出', async () => {
    renderPage()
    await waitReady()
    clickStep('故事分析')
    await waitFor(() => {
      // 该步应显示自己的产出(梗概),不该出现剧本正文
      expect(screen.getByText('父子二人在游戏里体会战争')).toBeInTheDocument()
    })
    expect(screen.queryByText(/INT\. 卧室/)).not.toBeInTheDocument()
  })

  it('生成剧本步展示剧本正文', async () => {
    renderPage()
    await waitReady()
    clickStep('剧本')
    await waitFor(() => expect(screen.getByText(/INT\. 卧室/)).toBeInTheDocument())
  })

  it('分镜步展示分镜表,不展示剧本正文', async () => {
    renderPage()
    await waitReady()
    clickStep('分镜')
    await waitFor(() => expect(screen.getByText(/分镜脚本 ·/)).toBeInTheDocument())
    expect(screen.queryByText(/INT\. 卧室/)).not.toBeInTheDocument()
  })

  it('点某步后右栏换成该步内容(视觉焦点跟着走)', async () => {
    renderPage()
    await waitReady()
    // 流水线跑在 Prompt 步,右栏初始是 Prompt 列表
    await waitFor(() => expect(screen.getByText(/视频 Prompt ·/)).toBeInTheDocument())
    clickStep('分镜')
    await waitFor(() => expect(screen.getByText(/分镜脚本 ·/)).toBeInTheDocument())
    // 切过去后不再展示上一步的内容
    expect(screen.queryByText(/视频 Prompt ·/)).not.toBeInTheDocument()
  })
})
