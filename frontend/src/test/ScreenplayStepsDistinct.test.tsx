/**
 * 剧本的生成与审核是**同一步**(与 storyboard/looks/prompts 一致)。
 *
 * 曾拆成「生成剧本」「审核剧本」两步:审核的对象就是上一步的产出,两边右栏内容天然雷同,
 * 只能靠"有没有审核按钮"区分 —— 用户点这两步看到的东西一模一样(实测)。
 * 合并后这一步既展示正文,也在停卡点时承载审核控件。
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
  { key: 'done', label: '完成' },
]
const SCREENPLAY = 'INT. 卧室 - 傍晚\n父亲端着水走进来。'

const renderPage = () => render(
  <MemoryRouter initialEntries={[`/episodes/${EID}`]}>
    <Routes><Route path="/episodes/:episodeId" element={<ProjectDetailPage />} /></Routes>
  </MemoryRouter>,
)

const stepEl = (label: string) =>
  screen.getAllByTestId('step').find(e => e.textContent?.includes(label))

describe('剧本步:生成与审核合成一步', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createWebSocket).mockReturnValue(
      { onmessage: null, onclose: null, close: vi.fn() } as never)
    vi.mocked(storiesApi.get).mockResolvedValue({
      id: 'st-1', project_id: PID, title: '原文', genre: 'drama',
      content: '原文', story_analysis: null, cast: {},
    } as never)
    vi.mocked(episodesApi.get).mockResolvedValue({
      id: EID, project_id: PID, episode_number: 1, title: '第 1 集',
      status: 'paused', story_id: 'st-1', script_id: null,
      llm_model: 'm', video_provider: 'seedance', video_model: '', resolution: '720p',
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as never)
    // 停在剧本审核卡点 —— 正是两步内容雷同最明显的场景
    vi.mocked(workflowApi.status).mockResolvedValue({
      episode_id: EID, project_id: PID, db_status: 'paused',
      current_stage: 'screenplay_written', paused_at: 'screenplay_review',
      screenplay: SCREENPLAY,
      screenplay_versions: [{ screenplay: SCREENPLAY, label: '初稿', created_at: null }],
      screenplay_version_current: 0,
      pipeline: { steps: STEPS, current: 'screenplay' },
    } as never)
  })

  it('停在审核卡点时,剧本步带审核动作(通过/修改)', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    expect(screen.getByText('修改')).toBeInTheDocument()
  })

  it('剧本步同时展示正文 —— 审核要对着正文进行', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/INT\. 卧室/)).toBeInTheDocument())
  })

  it('流水线没停在剧本卡点时,该步不给审核动作(已通过的剧本不该还能"通过")', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      episode_id: EID, project_id: PID, db_status: 'running',
      current_stage: 'storyboard_ready', paused_at: 'storyboard_review',
      screenplay: SCREENPLAY,
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: 'MS',
                camera_movement: 'static', duration_seconds: 5, description: 'x',
                characters: [] }],
      pipeline: { steps: STEPS, current: 'storyboard' },
    } as never)
    renderPage()
    await waitFor(() => expect(stepEl('剧本')).toBeTruthy())
    fireEvent.click(stepEl('剧本')!)
    await waitFor(() => expect(screen.getByText(/INT\. 卧室/)).toBeInTheDocument())
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
  })

  it('左栏不再有独立的「审核剧本」步', async () => {
    renderPage()
    await waitFor(() => expect(stepEl('剧本')).toBeTruthy())
    expect(screen.queryByText('审核剧本')).not.toBeInTheDocument()
  })
})
